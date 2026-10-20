"""Small Maya helpers shared by the retopo tools."""

import functools

import maya.api.OpenMaya as om
import maya.cmds as cmds


def undoable(func):
    """Run ``func`` inside a single undo chunk."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        cmds.undoInfo(openChunk=True, chunkName=func.__name__)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(closeChunk=True)
    return wrapper


def shape_path(name):
    """Return the MDagPath of the shape under ``name``."""
    sel = om.MSelectionList()
    sel.add(name)
    dag = sel.getDagPath(0)
    if dag.apiType() == om.MFn.kTransform and dag.numberOfShapesDirectlyBelow():
        dag.extendToShape()
    return dag


def transform_name(dag):
    """Full path of the transform owning ``dag``."""
    dag = om.MDagPath(dag)
    if dag.apiType() != om.MFn.kTransform:
        dag.pop()
    return dag.fullPathName()


def mesh_path(name):
    dag = shape_path(name)
    if not dag.hasFn(om.MFn.kMesh):
        raise RuntimeError("'%s' is not a polygon mesh." % name)
    return dag


def get_points(mesh):
    """World space vertex positions of ``mesh`` as a list of tuples."""
    points = om.MFnMesh(mesh_path(mesh)).getPoints(om.MSpace.kWorld)
    return [(p.x, p.y, p.z) for p in points]


def set_points(mesh, positions):
    """Move vertices (``{vertex_id: (x, y, z)}``) in world space, undoably."""
    for vid, p in positions.items():
        cmds.xform("%s.vtx[%d]" % (mesh, vid), translation=p, worldSpace=True)


def topology(mesh):
    """Return ``(neighbors, boundary)`` for ``mesh``.

    ``neighbors`` maps vertex id to connected vertex ids and ``boundary`` is
    the set of vertices on open borders.
    """
    it = om.MItMeshVertex(mesh_path(mesh))
    neighbors = {}
    boundary = set()
    while not it.isDone():
        vid = it.index()
        neighbors[vid] = list(it.getConnectedVertices())
        if it.onBoundary():
            boundary.add(vid)
        it.next()
    return neighbors, boundary


def selected_vertices():
    """Group the current selection as ``{mesh_transform: [vertex ids]}``.

    Components are converted to vertices; whole mesh objects contribute all
    of their vertices.
    """
    result = {}
    sel = cmds.ls(selection=True, long=True) or []
    components = [s for s in sel if "." in s]
    objects = [s for s in sel if "." not in s]

    if components:
        verts = cmds.polyListComponentConversion(components, toVertex=True) or []
        for v in cmds.ls(verts, flatten=True, long=True) or []:
            node, comp = v.split(".", 1)
            if cmds.nodeType(node) == "mesh":
                node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
            vid = int(comp[comp.index("[") + 1:-1])
            result.setdefault(node, []).append(vid)

    for obj in objects:
        try:
            dag = mesh_path(obj)
        except RuntimeError:
            continue
        name = transform_name(dag)
        result[name] = list(range(om.MFnMesh(dag).numVertices))
    return result
