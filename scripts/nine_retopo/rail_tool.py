"""zRail-style rail drawing tool.

Drag on the live surface to draw a rail. The second rail builds a strip
between the two, and every following rail continues from the edge of the
previous strip, welded to it. Start with mesh edges selected to continue
from an existing retopo mesh. Shift-drag starts a new chain.
"""

import maya.api.OpenMaya as om
import maya.cmds as cmds

from nine_retopo import geometry, mesh_utils, strip
from nine_retopo.surface import Projector, get_live_surface
from nine_retopo.viewport import MeshRaycaster

CONTEXT = "nineRetopoRailCtx"
PREVIEW_COLOR = 17  # yellow


def _preview_curve(points, closed, curve=None):
    """Create or update a linear curve through ``points``."""
    pts = list(points) + ([points[0]] if closed else [])
    if curve and cmds.objExists(curve):
        cmds.curve(curve, replace=True, degree=1, point=pts)
        return curve
    curve = cmds.curve(degree=1, point=pts, name="retopoRail#")
    shape = cmds.listRelatives(curve, shapes=True, fullPath=True)[0]
    cmds.setAttr(shape + ".overrideEnabled", True)
    cmds.setAttr(shape + ".overrideColor", PREVIEW_COLOR)
    if cmds.attributeQuery("lineWidth", node=shape, exists=True):
        cmds.setAttr(shape + ".lineWidth", 2)
    return cmds.ls(curve, long=True)[0]


def _delete(node):
    if node and cmds.objExists(node):
        cmds.delete(node)


class RailTool(object):
    def __init__(self):
        self.spans_along = 0
        self.spans_across = 1
        self.smooth = 3
        self._rail = None
        self._rail_curve = None
        self._stroke = []
        self._stroke_curve = None
        self._last_xy = None
        self._raycaster = None

    def activate(self):
        if not get_live_surface():
            raise RuntimeError("Set a live surface first.")
        self.reset()
        # Continue from selected border edges of an existing retopo mesh.
        edge_rails = [r for r in strip.rails_from_selection() if r.mesh]
        if edge_rails:
            self._rail = edge_rails[0]

        callbacks = dict(pressCommand=self._press, dragCommand=self._drag,
                         releaseCommand=self._release)
        if cmds.draggerContext(CONTEXT, exists=True):
            cmds.draggerContext(CONTEXT, edit=True, **callbacks)
        else:
            cmds.draggerContext(CONTEXT, cursor="crossHair", space="screen",
                                undoMode="all", name=CONTEXT, **callbacks)
        cmds.setToolTo(CONTEXT)

    def reset(self):
        """Forget the pending rail so the next stroke starts a new chain."""
        _delete(self._rail_curve)
        self._rail = None
        self._rail_curve = None

    # Dragger callbacks ----------------------------------------------------
    def _press(self):
        surface = get_live_surface()
        if not surface:
            om.MGlobal.displayError("Set a live surface first.")
            return
        if cmds.draggerContext(CONTEXT, query=True, modifier=True) == "shift":
            self.reset()
        self._raycaster = MeshRaycaster(mesh_utils.mesh_path(surface))
        self._stroke = []
        self._stroke_curve = None
        self._last_xy = None
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, anchorPoint=True)
        self._add_point(x, y)

    def _drag(self):
        if self._raycaster is None:
            return
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, dragPoint=True)
        self._add_point(x, y)

    def _release(self):
        if self._raycaster is None:
            return
        self._raycaster = None
        _delete(self._stroke_curve)
        self._stroke_curve = None
        try:
            self._finish_stroke(self._stroke)
        except Exception as exc:  # keep the tool alive, report in the status line
            om.MGlobal.displayError(str(exc))

    # Stroke handling ------------------------------------------------------
    def _add_point(self, x, y):
        if self._last_xy == (int(x), int(y)):
            return
        self._last_xy = (int(x), int(y))
        p = self._raycaster.hit(x, y)
        if p is None:
            return
        if self._stroke and geometry.distance(p, self._stroke[-1]) < 1e-6:
            return
        self._stroke.append(p)
        if len(self._stroke) >= 2:
            self._stroke_curve = _preview_curve(self._stroke, False, self._stroke_curve)
            cmds.refresh(currentView=True)

    def _finish_stroke(self, points):
        if len(points) < 2:
            return
        closed = geometry.is_closed_stroke(points)
        points = geometry.smooth_polyline(points, self.smooth, closed)
        projector = Projector()
        points = [projector.project(p) for p in points]
        rail = strip.Rail(points, closed)

        pending = self._rail
        if pending is not None and pending.mesh and not cmds.objExists(pending.mesh):
            pending = strip.Rail(pending.points, pending.closed)  # mesh was undone
        if pending is None or pending.closed != closed:
            if pending is not None:
                om.MGlobal.displayWarning(
                    "Open and closed rails can't be bridged; starting a new chain.")
            self.reset()
            self._rail = rail
            self._rail_curve = _preview_curve(points, closed)
            return

        mesh, far_rail = strip.build_strip_from_rails(
            pending, rail, self.spans_along, self.spans_across, merge=True, snap=True)
        _delete(self._rail_curve)
        self._rail_curve = None
        self._rail = far_rail
        cmds.select(mesh)


tool = RailTool()


def activate(spans_along=None, spans_across=None, smooth=None):
    if spans_along is not None:
        tool.spans_along = spans_along
    if spans_across is not None:
        tool.spans_across = spans_across
    if smooth is not None:
        tool.smooth = smooth
    tool.activate()


def reset():
    tool.reset()
