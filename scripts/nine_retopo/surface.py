"""The live (reference) surface that retopo geometry snaps onto."""

import maya.api.OpenMaya as om
import maya.cmds as cmds

from nine_retopo import mesh_utils

OPTION_VAR = "nineRetopo_liveSurface"


def set_live_surface(name=None, make_live=True):
    """Use ``name`` (or the selected mesh) as the snapping surface."""
    if name is None:
        sel = cmds.ls(selection=True, objectsOnly=True, long=True) or []
        if not sel:
            raise RuntimeError("Select the high poly mesh to use as live surface.")
        name = sel[0]
    dag = mesh_utils.mesh_path(name)
    name = mesh_utils.transform_name(dag)
    cmds.optionVar(stringValue=(OPTION_VAR, name))
    if make_live:
        # Lets Maya's own curve / quad draw tools snap to the surface too.
        cmds.makeLive(name)
    return name


def clear_live_surface():
    cmds.optionVar(remove=OPTION_VAR)
    cmds.makeLive(none=True)


def get_live_surface():
    if not cmds.optionVar(exists=OPTION_VAR):
        return None
    name = cmds.optionVar(query=OPTION_VAR)
    return name if name and cmds.objExists(name) else None


class Projector(object):
    """Projects points onto a mesh. Falsy when there is no mesh to use."""

    def __init__(self, name=None):
        name = name or get_live_surface()
        self.name = name
        self._fn = om.MFnMesh(mesh_utils.mesh_path(name)) if name else None

    def __bool__(self):
        return self._fn is not None

    __nonzero__ = __bool__

    def closest(self, point):
        """Return ``(point, normal)`` on the surface closest to ``point``."""
        hit, normal, _ = self._fn.getClosestPointAndNormal(
            om.MPoint(*point), om.MSpace.kWorld)
        return (hit.x, hit.y, hit.z), (normal.x, normal.y, normal.z)

    def project(self, point):
        if not self._fn:
            return tuple(point)
        return self.closest(point)[0]

    def project_dict(self, positions):
        return {k: self.project(p) for k, p in positions.items()}


@mesh_utils.undoable
def snap_selection():
    """Snap selected vertices (or whole meshes) onto the live surface."""
    projector = Projector()
    if not projector:
        raise RuntimeError("Set a live surface first.")
    count = 0
    for mesh, ids in mesh_utils.selected_vertices().items():
        if mesh == projector.name:
            continue
        points = mesh_utils.get_points(mesh)
        mesh_utils.set_points(mesh, {i: projector.project(points[i]) for i in ids})
        count += len(ids)
    return count
