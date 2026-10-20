"""Viewport relax brush: drag over a retopo mesh to relax it onto the surface."""

import maya.cmds as cmds

from nine_retopo import geometry, mesh_utils
from nine_retopo.surface import Projector
from nine_retopo.viewport import MeshRaycaster

CONTEXT = "nineRetopoRelaxBrushCtx"


class RelaxBrush(object):
    def __init__(self):
        self.radius = 1.0
        self.strength = 0.3
        self.keep_boundary = True
        self.mesh = None
        self._raycaster = None
        self._positions = None
        self._neighbors = None
        self._boundary = None
        self._projector = None

    def activate(self, mesh=None):
        """Make the brush the current tool, working on ``mesh`` or the selection."""
        if mesh is None:
            sel = cmds.ls(selection=True, objectsOnly=True, long=True) or []
            sel += cmds.ls(hilite=True, long=True) or []
            if not sel:
                raise RuntimeError("Select the retopo mesh to relax.")
            mesh = sel[0]
        dag = mesh_utils.mesh_path(mesh)
        self.mesh = mesh_utils.transform_name(dag)

        callbacks = dict(pressCommand=self._press, dragCommand=self._drag,
                         releaseCommand=self._release)
        if cmds.draggerContext(CONTEXT, exists=True):
            cmds.draggerContext(CONTEXT, edit=True, **callbacks)
        else:
            cmds.draggerContext(CONTEXT, cursor="crossHair", space="screen",
                                undoMode="all", name=CONTEXT, **callbacks)
        cmds.setToolTo(CONTEXT)

    def _press(self):
        if not self.mesh or not cmds.objExists(self.mesh):
            return
        self._raycaster = MeshRaycaster(mesh_utils.mesh_path(self.mesh))
        self._neighbors, self._boundary = mesh_utils.topology(self.mesh)
        self._positions = dict(enumerate(mesh_utils.get_points(self.mesh)))
        self._projector = Projector()
        if self._projector.name == self.mesh:
            self._projector = None
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, anchorPoint=True)
        self._stroke(x, y)

    def _drag(self):
        if self._raycaster is None:
            return
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, dragPoint=True)
        self._stroke(x, y)

    def _release(self):
        self._raycaster = None
        self._positions = None

    def _stroke(self, x, y):
        center = self._raycaster.hit(x, y)
        if center is None:
            return
        weights = {}
        for vid, p in self._positions.items():
            if self.keep_boundary and vid in self._boundary:
                continue
            w = geometry.falloff(geometry.distance(p, center), self.radius)
            if w > 0.0:
                weights[vid] = w * self.strength
        if not weights:
            return
        moved = geometry.relax_step(self._positions, self._neighbors, weights)
        if self._projector:
            moved = self._projector.project_dict(moved)
        self._positions.update(moved)
        mesh_utils.set_points(self.mesh, moved)
        cmds.refresh(currentView=True)


brush = RelaxBrush()


def activate(radius=None, strength=None, keep_boundary=None):
    if radius is not None:
        brush.radius = radius
    if strength is not None:
        brush.strength = strength
    if keep_boundary is not None:
        brush.keep_boundary = keep_boundary
    brush.activate()
