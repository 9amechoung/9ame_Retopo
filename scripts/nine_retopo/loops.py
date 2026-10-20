"""Insert edge loops and snap the new vertices onto the live surface."""

import maya.cmds as cmds

from nine_retopo import mesh_utils
from nine_retopo.surface import Projector


def _edge_index(edge):
    return int(edge[edge.rindex("[") + 1:-1])


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
