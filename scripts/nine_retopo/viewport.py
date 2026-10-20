"""Viewport helpers: turning screen positions into hits on a mesh."""

import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui


def view_ray(x, y):
    """World space ``(source, direction)`` of the ray under screen ``x, y``."""
    view = omui.M3dView.active3dView()
    source, direction = om.MPoint(), om.MVector()
    view.viewToWorld(int(x), int(y), source, direction)
    return source, direction


class MeshRaycaster(object):
    """Fast repeated ray hits against one mesh (keeps an acceleration grid)."""

    def __init__(self, dag):
        self._fn = om.MFnMesh(dag)
        self._accel = om.MFnMesh.autoUniformGridParams()

    def hit(self, x, y):
        """World space point under screen ``x, y``, or None."""
        source, direction = view_ray(x, y)
        hit = self._fn.closestIntersection(
            om.MFloatPoint(source), om.MFloatVector(direction),
            om.MSpace.kWorld, 1e9, False, accelParams=self._accel)
        if not hit or hit[2] < 0:
            return None
        p = hit[0]
        return (p.x, p.y, p.z)
