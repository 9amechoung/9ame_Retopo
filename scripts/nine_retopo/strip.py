"""Build a quad strip between two rails (curves or mesh edge chains)."""

import maya.api.OpenMaya as om
import maya.cmds as cmds

from nine_retopo import geometry, mesh_utils
from nine_retopo.surface import Projector

CURVE_SAMPLES_PER_CV = 8


class Rail(object):
    """An ordered list of world space points.

    Rails taken from mesh edges remember their mesh so the new strip can be
    merged back into it.
    """

    def __init__(self, points, closed, mesh=None):
        self.points = points
        self.closed = closed
        self.mesh = mesh

    @property
    def segments(self):
        return len(self.points) if self.closed else len(self.points) - 1


def _curve_rail(dag):
    fn = om.MFnNurbsCurve(dag)
    closed = fn.form != om.MFnNurbsCurve.kOpen
    total = fn.length()
    samples = max(64, fn.numCVs * CURVE_SAMPLES_PER_CV)
    start, end = fn.knotDomain
    points = []
    count = samples if closed else samples + 1
    for k in range(count):
        if not closed and k == samples:
            param = end
        else:
            param = fn.findParamFromLength(total * k / float(samples))
        p = fn.getPointAtParam(param, om.MSpace.kWorld)
        points.append((p.x, p.y, p.z))
    return Rail(points, closed)


def _edge_rails(dag, component):
    it = om.MItMeshEdge(dag, component)
    edges = []
    while not it.isDone():
        edges.append((it.vertexId(0), it.vertexId(1)))
        it.next()
    points = om.MFnMesh(dag).getPoints(om.MSpace.kWorld)
    mesh = mesh_utils.transform_name(dag)
    rails = []
    for ids, closed in geometry.chains_from_edges(edges):
        rails.append(Rail([(points[i].x, points[i].y, points[i].z) for i in ids],
                          closed, mesh))
    return rails


def rails_from_selection():
    """Collect rails from selected NURBS curves and mesh edges."""
    sel = om.MGlobal.getActiveSelectionList()
    rails = []
    for i in range(sel.length()):
        try:
            dag, component = sel.getComponent(i)
        except (RuntimeError, TypeError):
            continue  # not a DAG node
        if dag.apiType() == om.MFn.kTransform and dag.numberOfShapesDirectlyBelow():
            dag.extendToShape()
        if component.isNull():
            if dag.hasFn(om.MFn.kNurbsCurve):
                rails.append(_curve_rail(dag))
        elif component.hasFn(om.MFn.kMeshEdgeComponent):
            rails.extend(_edge_rails(dag, component))
    return rails


def _resolve_spans(rail_a, rail_b, spans_along, spans_across):
    if spans_along > 0:
        return spans_along
    # Match an edge rail so its vertices can be merged with the strip.
    for rail in (rail_a, rail_b):
        if rail.mesh:
            return rail.segments
    return geometry.auto_spans(rail_a.points, rail_b.points, spans_across,
                               rail_a.closed)


def _rail_points(rail, spans):
    """Return ``(points, exact)``; ``exact`` when the rail's own points are kept."""
    if rail.mesh and rail.segments == spans:
        return list(rail.points), True
    count = spans if rail.closed else spans + 1
    return geometry.resample_polyline(rail.points, count, rail.closed), False


def _create_grid_mesh(vertices, columns, rows):
    """Create a polyPlane with ``columns`` x ``rows`` vertices placed at ``vertices``."""
    mesh = cmds.polyPlane(subdivisionsX=columns - 1, subdivisionsY=rows - 1,
                          constructionHistory=False, name="retopoStrip#")[0]
    mesh = cmds.ls(mesh, long=True)[0]
    # polyPlane vertices are row major: index = row * columns + column, which
    # is the same layout geometry.build_strip_grid uses.
    mesh_utils.set_points(mesh, dict(enumerate(vertices)))
    return mesh


def _orient_to(mesh, reference):
    """Flip ``mesh`` normals if they point away from ``reference``."""
    if not reference:
        return
    fn = om.MFnMesh(mesh_utils.mesh_path(mesh))
    normal = fn.getPolygonNormal(0, om.MSpace.kWorld)
    center = geometry.average(
        (p.x, p.y, p.z) for p in
        (fn.getPoint(v, om.MSpace.kWorld) for v in fn.getPolygonVertices(0)))
    _, ref_normal = reference.closest(center)
    if geometry.dot((normal.x, normal.y, normal.z), ref_normal) < 0:
        cmds.polyNormal(mesh, normalMode=0, userNormalMode=0, constructionHistory=False)


def _merge_into(meshes, strip, tolerance):
    """Combine ``strip`` with ``meshes`` and weld coincident vertices."""
    target = meshes[0]
    parent = cmds.listRelatives(target, parent=True, fullPath=True)
    short_name = target.split("|")[-1]
    result = cmds.polyUnite(list(meshes) + [strip], constructionHistory=True,
                            mergeUVSets=True)[0]
    cmds.delete(result, constructionHistory=True)
    for leftover in list(meshes) + [strip]:
        if cmds.objExists(leftover) and not cmds.listRelatives(leftover, shapes=True):
            cmds.delete(leftover)
    cmds.polyMergeVertex(result, distance=tolerance, alwaysMergeTwoVertices=True,
                         constructionHistory=False)
    if parent:
        result = cmds.parent(result, parent[0])[0]
    result = cmds.rename(result, short_name)
    return cmds.ls(result, long=True)[0]


@mesh_utils.undoable
def build_strip(spans_along=0, spans_across=1, merge=True, snap=True):
    """Build a quad strip between the two selected rails.

    ``spans_along`` of 0 picks a count automatically: an edge rail's own
    segment count when there is one, otherwise roughly square quads.
    Returns the resulting mesh.
    """
    rails = rails_from_selection()
    if len(rails) != 2:
        raise RuntimeError("Select exactly two rails (curves or edge chains); "
                           "found %d." % len(rails))
    rail_a, rail_b = rails
    if rail_a.closed != rail_b.closed:
        raise RuntimeError("Both rails must be open or both closed.")
    closed = rail_a.closed

    spans = _resolve_spans(rail_a, rail_b, spans_along, spans_across)
    points_a, exact_a = _rail_points(rail_a, spans)
    points_b, exact_b = _rail_points(rail_b, spans)
    points_b = geometry.align_rails(points_a, points_b, closed)
    if closed:
        # Build open and weld the seam afterwards.
        points_a = points_a + [points_a[0]]
        points_b = points_b + [points_b[0]]

    columns = len(points_a)
    rows = spans_across + 1
    vertices, _ = geometry.build_strip_grid(points_a, points_b, spans_across)

    projector = Projector() if snap else None
    if projector:
        for j in range(rows):
            # Keep edge rail rows exactly in place so they weld cleanly.
            if (j == 0 and exact_a) or (j == rows - 1 and exact_b):
                continue
            for i in range(columns):
                k = j * columns + i
                vertices[k] = projector.project(vertices[k])

    seg_length = geometry.polyline_length(points_a) / max(spans, 1)
    tolerance = max(seg_length * 0.01, 1e-5)

    strip = _create_grid_mesh(vertices, columns, rows)

    targets = []
    for rail, exact in ((rail_a, exact_a), (rail_b, exact_b)):
        if exact and rail.mesh not in targets:
            targets.append(rail.mesh)
    reference = projector if projector else (Projector(targets[0]) if targets else None)
    _orient_to(strip, reference)

    if closed:
        seam = []
        for j in range(rows):
            seam.append("%s.vtx[%d]" % (strip, j * columns))
            seam.append("%s.vtx[%d]" % (strip, j * columns + columns - 1))
        cmds.polyMergeVertex(seam, distance=tolerance, constructionHistory=False)

    if merge and targets:
        strip = _merge_into(targets, strip, tolerance)
    cmds.select(strip)
    return strip
