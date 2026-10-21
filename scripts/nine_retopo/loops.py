"""Insert edge loops and snap the new vertices onto the live surface."""

import maya.api.OpenMaya as om
import maya.cmds as cmds

from nine_retopo import geometry, mesh_utils
from nine_retopo.surface import Projector


def _edge_index(edge):
    return int(edge[edge.rindex("[") + 1:-1])


def _faces(fn):
    counts, connects = fn.getVertices()
    faces, k = [], 0
    for n in counts:
        faces.append(list(connects[k:k + n]))
        k += n
    return faces


class Ring(object):
    """An edge ring picked under the cursor, split at parameter ``t``.

    ``edges`` are vertex pairs oriented so every new vertex sits at
    ``lerp(points[v0], points[v1], t)``.
    """

    def __init__(self, mesh, edges, closed, t, points):
        self.mesh = mesh
        self.edges = edges
        self.closed = closed
        self.t = t
        self.points = points

    def cut_points(self, projector=None):
        pts = [geometry.lerp(self.points[a], self.points[b], self.t) for a, b in self.edges]
        return [projector.project(p) for p in pts] if projector else pts


def ring_under(mesh, point, face):
    """The ring crossing the edge of ``face`` closest to ``point``."""
    fn = om.MFnMesh(mesh_utils.mesh_path(mesh))
    points = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]
    faces = _faces(fn)
    verts = faces[face]
    best = None
    for i in range(len(verts)):
        a, b = verts[i], verts[(i + 1) % len(verts)]
        t = geometry.closest_param_on_segment(point, points[a], points[b])
        d = geometry.distance(point, geometry.lerp(points[a], points[b], t))
        if best is None or d < best[0]:
            best = (d, a, b, t)
    _, a, b, t = best
    edges, closed = geometry.edge_ring(faces, a, b)
    # Keep the cut away from existing vertices.
    t = min(max(t, 0.05), 0.95)
    return Ring(mesh, edges, closed, t, points)


@mesh_utils.undoable
def split_ring(ring, snap=True):
    """Insert one edge loop across ``ring`` at its parameter ``t``.

    Returns ``(point_a, point_b, new_point)`` for every split edge.
    """
    mesh = ring.mesh
    fn = om.MFnMesh(mesh_utils.mesh_path(mesh))
    edge_ids = {}
    it = om.MItMeshEdge(mesh_utils.mesh_path(mesh))
    while not it.isDone():
        edge_ids[frozenset((it.vertexId(0), it.vertexId(1)))] = it.index()
        it.next()
    names = ["%s.e[%d]" % (mesh, edge_ids[frozenset(e)]) for e in ring.edges]
    oriented = {frozenset(e): e for e in ring.edges}

    before = fn.numVertices
    cmds.polySplitRing(names, splitType=2, divisions=1, constructionHistory=True)

    # polySplitRing cuts at the middle; move every new vertex to ``t`` along
    # its original edge so the loop runs where the user pointed.
    neighbors, _ = mesh_utils.topology(mesh)
    projector = Projector() if snap else None
    moves = {}
    inserted = []
    for vid in range(before, cmds.polyEvaluate(mesh, vertex=True)):
        old = frozenset(n for n in neighbors[vid] if n < before)
        edge = oriented.get(old)
        if edge is None:
            continue
        a, b = ring.points[edge[0]], ring.points[edge[1]]
        p = geometry.lerp(a, b, ring.t)
        moves[vid] = projector.project(p) if projector else p
        inserted.append((a, b, moves[vid]))
    mesh_utils.set_points(mesh, moves)
    return inserted


@mesh_utils.undoable
def insert_edge_loop(divisions=1, snap=True):
    """Split the ring of the selected edge into ``divisions`` new loops.

    With a single edge selected the whole edge ring is split; with several
    edges selected only those edges are split.
    """
    edges = cmds.filterExpand(selectionMask=32, fullPath=True, expand=True) or []
    if not edges:
        raise RuntimeError("Select an edge to insert a loop across.")
    mesh = edges[0].split(".", 1)[0]
    if cmds.nodeType(mesh) == "mesh":
        mesh = cmds.listRelatives(mesh, parent=True, fullPath=True)[0]

    if len(edges) == 1:
        ring = cmds.polySelect(mesh, edgeRing=_edge_index(edges[0]), noSelection=True) or []
        edges = ["%s.e[%d]" % (mesh, i) for i in ring]

    before = cmds.polyEvaluate(mesh, vertex=True)
    cmds.polySplitRing(edges, splitType=2, divisions=divisions,
                       constructionHistory=True)
    after = cmds.polyEvaluate(mesh, vertex=True)
    new_ids = list(range(before, after))

    projector = Projector() if snap else None
    if projector and new_ids:
        points = mesh_utils.get_points(mesh)
        mesh_utils.set_points(mesh, {i: projector.project(points[i]) for i in new_ids})
    cmds.select(["%s.vtx[%d]" % (mesh, i) for i in new_ids] or mesh)
    return new_ids
