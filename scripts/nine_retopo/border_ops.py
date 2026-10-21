"""ziRail-style operations on selected borders of retopo meshes.

A :class:`Segment` is a run of border vertices of one mesh, picked in the
viewport. Segments can be redrawn along a new stroke, extruded along a
stroke, bridged to another segment, or welded to it; single vertices can be
welded onto a target vertex.
"""

import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui
import maya.cmds as cmds

from nine_retopo import chain, display, geometry, mesh_utils, strip
from nine_retopo.surface import Projector

PICK_RADIUS = 20  # pixels


def _faces(mesh):
    fn = om.MFnMesh(mesh_utils.mesh_path(mesh))
    counts, connects = fn.getVertices()
    faces, k = [], 0
    for n in counts:
        faces.append(list(connects[k:k + n]))
        k += n
    return faces


class Segment(object):
    """Ordered border vertex ids of ``mesh``; ``closed`` for a whole loop."""

    def __init__(self, mesh, ids, closed):
        self.mesh = mesh
        self.ids = list(ids)
        self.closed = closed

    def points(self):
        pts = mesh_utils.get_points(self.mesh)
        return [pts[i] for i in self.ids]

    def valid(self):
        return (cmds.objExists(self.mesh)
                and max(self.ids) < cmds.polyEvaluate(self.mesh, vertex=True))

    def rail(self):
        return strip.Rail(self.points(), self.closed, self.mesh)


# Picking ------------------------------------------------------------------
def _to_screen(view, point):
    result = view.worldToView(om.MPoint(*point))
    return result[0], result[1]


def pick_vertex(x, y, meshes, border_only=False, exclude=None):
    """``(mesh, vertex_id)`` of the vertex drawn closest to screen ``x, y``."""
    view = omui.M3dView.active3dView()
    best, best_d = None, PICK_RADIUS * PICK_RADIUS
    for mesh in meshes:
        pts = mesh_utils.get_points(mesh)
        if border_only:
            ids = set(v for loop, _ in geometry.border_loops(_faces(mesh)) for v in loop)
        else:
            ids = range(len(pts))
        for vid in ids:
            if exclude == (mesh, vid):
                continue
            sx, sy = _to_screen(view, pts[vid])
            d = (sx - x) ** 2 + (sy - y) ** 2
            if d < best_d:
                best, best_d = (mesh, vid), d
    return best


def _loop_of(mesh, vid):
    for ids, closed in geometry.border_loops(_faces(mesh)):
        if vid in ids:
            return ids, closed
    raise RuntimeError("Vertex %d is not on an open border." % vid)


def segment_between(mesh, a, b):
    ids, closed = _loop_of(mesh, a)
    if b not in ids:
        raise RuntimeError("The two vertices are on different borders.")
    return Segment(mesh, geometry.border_path(ids, closed, a, b), False)


def whole_border(mesh, vid):
    ids, closed = _loop_of(mesh, vid)
    return Segment(mesh, ids, closed)


def ids_at(mesh, points):
    """Vertex ids of ``mesh`` closest to each of ``points``."""
    pts = mesh_utils.get_points(mesh)
    return [min(range(len(pts)), key=lambda i: geometry.distance(pts[i], p)) for p in points]


# Helpers ------------------------------------------------------------------
def _combine(mesh_a, mesh_b):
    """Put two meshes into one; returns ``(mesh, offset of mesh_b's ids)``."""
    if mesh_a == mesh_b:
        return mesh_a, 0
    offset = cmds.polyEvaluate(mesh_a, vertex=True)
    parent = cmds.listRelatives(mesh_a, parent=True, fullPath=True)
    name = mesh_a.split("|")[-1]
    result = cmds.polyUnite(mesh_a, mesh_b, constructionHistory=True, mergeUVSets=True)[0]
    cmds.delete(result, constructionHistory=True)
    for leftover in (mesh_a, mesh_b):
        if cmds.objExists(leftover) and not cmds.listRelatives(leftover, shapes=True):
            cmds.delete(leftover)
    if parent:
        result = cmds.parent(result, parent[0])[0]
    result = cmds.ls(cmds.rename(result, name), long=True)[0]
    display.style_retopo(result)
    return result, offset


def _edge_length(points, closed):
    segments = len(points) if closed else len(points) - 1
    return geometry.polyline_length(points, closed) / max(segments, 1)


def _stroke_points(stroke, count, closed, reference):
    """``count`` points along ``stroke`` ordered to match ``reference``."""
    pts = geometry.resample_polyline(stroke, count, closed)
    return geometry.align_rails(reference, pts, closed)


# Operations ---------------------------------------------------------------
@mesh_utils.undoable
def redraw(segment, stroke, smooth=0):
    """Move the segment's vertices onto ``stroke`` (spaced evenly)."""
    projector = Projector()
    current = segment.points()
    stroke = geometry.smooth_polyline(stroke, smooth, segment.closed)
    target = _stroke_points(stroke, len(current), segment.closed, current)
    if projector:
        target = [projector.project(p) for p in target]
    mesh_utils.set_points(segment.mesh, dict(zip(segment.ids, target)))
    chain.forget(segment.mesh)


def extrude_grid(segment_points, closed, stroke, spans=0, projector=None):
    """Rows of an extrusion of the segment along ``stroke``.

    ``spans`` of 0 keeps the new quads roughly square.
    """
    if spans <= 0:
        length = geometry.polyline_length(stroke)
        spans = max(1, int(round(length / max(_edge_length(segment_points, closed),
                                              geometry.EPSILON))))
    rows = geometry.sweep_rows(segment_points, stroke, spans)
    if projector:
        rows = [rows[0]] + [[projector.project(p) for p in row] for row in rows[1:]]
    if closed:
        rows = [row + [row[0]] for row in rows]
    return rows


@mesh_utils.undoable
def extrude(segment, stroke, spans=0):
    """Extrude ``segment`` along ``stroke``; returns the new far border segment."""
    projector = Projector()
    points = segment.points()
    rows = extrude_grid(points, segment.closed, stroke, spans, projector)
    vertices = [p for row in rows for p in row]
    tolerance = max(_edge_length(points, segment.closed) * 0.01, 1e-5)
    mesh = strip.mesh_from_grid(vertices, len(rows[0]), len(rows), segment.closed,
                                tolerance, [segment.mesh], projector)
    chain.forget(mesh)
    far = rows[-1][:-1] if segment.closed else rows[-1]
    return Segment(mesh, ids_at(mesh, far), segment.closed)


@mesh_utils.undoable
def bridge(seg_a, seg_b, spans_across=0):
    """Fill between two border segments with quads."""
    if seg_a.closed != seg_b.closed:
        raise RuntimeError("Bridge an open border with an open one, or two loops.")
    if len(seg_a.ids) != len(seg_b.ids):
        raise RuntimeError("Both borders need the same number of edges to bridge "
                           "(%d and %d)." % (len(seg_a.ids) - (0 if seg_a.closed else 1),
                                             len(seg_b.ids) - (0 if seg_b.closed else 1)))
    mesh, _ = strip.build_strip_from_rails(seg_a.rail(), seg_b.rail(), 0, spans_across,
                                           merge=True, snap=True)
    chain.forget(mesh)
    return mesh


@mesh_utils.undoable
def weld(seg_a, seg_b):
    """Zip two border segments together, vertex for vertex."""
    if len(seg_a.ids) != len(seg_b.ids) or seg_a.closed != seg_b.closed:
        raise RuntimeError("Both borders need the same number of vertices to weld.")
    pts_a, pts_b = seg_a.points(), seg_b.points()
    order = geometry.align_order(pts_a, pts_b, seg_a.closed)
    mesh, offset = _combine(seg_a.mesh, seg_b.mesh)
    ids_b = [i + offset for i in seg_b.ids]
    projector = Projector()
    moves = {}
    for i, j in enumerate(order):
        mid = geometry.lerp(pts_a[i], pts_b[j], 0.5)
        mid = projector.project(mid) if projector else mid
        moves[seg_a.ids[i]] = mid
        moves[ids_b[j]] = mid
    mesh_utils.set_points(mesh, moves)
    tolerance = max(_edge_length(pts_a, seg_a.closed) * 0.01, 1e-5)
    cmds.polyMergeVertex(["%s.vtx[%d]" % (mesh, v) for v in moves], distance=tolerance,
                         constructionHistory=False)
    chain.forget(mesh)
    return mesh


@mesh_utils.undoable
def target_weld(mesh_a, vid_a, mesh_b, vid_b):
    """Move vertex ``vid_a`` onto ``vid_b`` and merge them."""
    target = mesh_utils.get_points(mesh_b)[vid_b]
    mesh, offset = _combine(mesh_b, mesh_a)
    vid_a += offset
    mesh_utils.set_points(mesh, {vid_a: target})
    cmds.polyMergeVertex(["%s.vtx[%d]" % (mesh, vid_a), "%s.vtx[%d]" % (mesh, vid_b)],
                         distance=1e-3, alwaysMergeTwoVertices=True,
                         constructionHistory=False)
    chain.forget(mesh)
    return mesh
