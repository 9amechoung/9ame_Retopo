"""Dockable tool window."""

import maya.api.OpenMaya as om
import maya.cmds as cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

from nine_retopo import brush, display, loops, rail_tool, relax, strip, surface

WINDOW_NAME = "nineRetopoWindow"


def _run(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as exc:  # report every tool error in Maya's status line
        om.MGlobal.displayError(str(exc))


def _spin(value, minimum, maximum, tooltip=""):
    w = QtWidgets.QSpinBox()
    w.setRange(minimum, maximum)
    w.setValue(value)
    w.setToolTip(tooltip)
    return w


def _dspin(value, minimum, maximum, step):
    w = QtWidgets.QDoubleSpinBox()
    w.setRange(minimum, maximum)
    w.setSingleStep(step)
    w.setDecimals(3)
    w.setValue(value)
    return w


class RetopoWindow(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(RetopoWindow, self).__init__(parent)
        self.setObjectName(WINDOW_NAME)
        self.setWindowTitle("9ame Retopo")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._surface_group())
        layout.addWidget(self._strip_group())
        layout.addWidget(self._loop_group())
        layout.addWidget(self._relax_group())
        layout.addWidget(self._brush_group())
        layout.addStretch()
        self._refresh_surface_label()

    # Live surface -------------------------------------------------------
    def _surface_group(self):
        group = QtWidgets.QGroupBox("Live Surface")
        layout = QtWidgets.QVBoxLayout(group)
        self.surface_label = QtWidgets.QLabel()
        row = QtWidgets.QHBoxLayout()
        set_btn = QtWidgets.QPushButton("Set From Selection")
        clear_btn = QtWidgets.QPushButton("Clear")
        set_btn.clicked.connect(self._set_surface)
        clear_btn.clicked.connect(self._clear_surface)
        row.addWidget(set_btn)
        row.addWidget(clear_btn)
        layout.addWidget(self.surface_label)
        layout.addLayout(row)
        return group

    def _refresh_surface_label(self):
        name = surface.get_live_surface()
        self.surface_label.setText(name.split("|")[-1] if name else "(none)")

    def _set_surface(self):
        _run(surface.set_live_surface)
        self._refresh_surface_label()

    def _clear_surface(self):
        _run(surface.clear_live_surface)
        self._refresh_surface_label()

    # Strip --------------------------------------------------------------
    def _strip_group(self):
        group = QtWidgets.QGroupBox("Rail Strip")
        form = QtWidgets.QFormLayout(group)
        self.spans_along = _spin(0, 0, 1000, "0 = auto (match edge rail or square quads)")
        self.spans_across = _spin(1, 1, 1000)
        self.strip_merge = QtWidgets.QCheckBox("Merge into edge rail mesh")
        self.strip_merge.setChecked(True)
        self.strip_snap = QtWidgets.QCheckBox("Snap to live surface")
        self.strip_snap.setChecked(True)
        self.rail_smooth = _spin(3, 0, 50, "Smoothing passes for freehand strokes")
        draw_btn = QtWidgets.QPushButton("Draw Rails")
        draw_btn.setToolTip("Drag on the live surface. The strip is previewed while you "
                            "draw and built on release; each new rail continues from the "
                            "previous one. Shift-drag starts a new chain. Ctrl-drag over a "
                            "retopo mesh slides a new edge loop and inserts it on release.")
        draw_btn.clicked.connect(lambda: _run(
            rail_tool.activate, self.spans_along.value(), self.spans_across.value(),
            self.rail_smooth.value()))
        new_chain_btn = QtWidgets.QPushButton("New Chain")
        new_chain_btn.clicked.connect(lambda: _run(rail_tool.reset))
        look_btn = QtWidgets.QPushButton("Retopo Look")
        look_btn.setToolTip("Give the selected meshes the translucent retopo shader and "
                            "let Ctrl-drag cut them.")
        look_btn.clicked.connect(lambda: _run(self._style_selection))
        draw_row = QtWidgets.QHBoxLayout()
        draw_row.addWidget(draw_btn)
        draw_row.addWidget(new_chain_btn)
        draw_row.addWidget(look_btn)
        for spin in (self.spans_along, self.spans_across, self.rail_smooth):
            spin.valueChanged.connect(self._sync_rail_tool)

        btn = QtWidgets.QPushButton("Build Strip (select 2 rails)")
        btn.clicked.connect(lambda: _run(
            strip.build_strip, self.spans_along.value(), self.spans_across.value(),
            self.strip_merge.isChecked(), self.strip_snap.isChecked()))
        form.addRow("Spans along", self.spans_along)
        form.addRow("Spans across", self.spans_across)
        form.addRow("Stroke smoothing", self.rail_smooth)
        form.addRow(draw_row)
        form.addRow(self.strip_merge)
        form.addRow(self.strip_snap)
        form.addRow(btn)
        return group

    @staticmethod
    def _style_selection():
        meshes = cmds.ls(selection=True, objectsOnly=True, long=True) or []
        meshes = [m for m in meshes
                  if cmds.listRelatives(m, shapes=True, type="mesh", fullPath=True)]
        if not meshes:
            raise RuntimeError("Select the retopo meshes to style.")
        for mesh in meshes:
            display.style_retopo(mesh)

    def _sync_rail_tool(self, *_):
        rail_tool.tool.spans_along = self.spans_along.value()
        rail_tool.tool.spans_across = self.spans_across.value()
        rail_tool.tool.smooth = self.rail_smooth.value()

    # Edge loop ----------------------------------------------------------
    def _loop_group(self):
        group = QtWidgets.QGroupBox("Edge Loop")
        form = QtWidgets.QFormLayout(group)
        self.loop_divisions = _spin(1, 1, 50)
        btn = QtWidgets.QPushButton("Insert Loop (select edge)")
        btn.clicked.connect(lambda: _run(loops.insert_edge_loop,
                                         self.loop_divisions.value()))
        form.addRow("Loops", self.loop_divisions)
        form.addRow(btn)
        return group

    # Relax --------------------------------------------------------------
    def _relax_group(self):
        group = QtWidgets.QGroupBox("Relax")
        form = QtWidgets.QFormLayout(group)
        self.relax_iterations = _spin(5, 1, 200)
        self.relax_strength = _dspin(0.5, 0.0, 1.0, 0.05)
        self.relax_boundary = QtWidgets.QCheckBox("Keep border vertices")
        self.relax_boundary.setChecked(True)
        relax_btn = QtWidgets.QPushButton("Relax Selection")
        relax_btn.clicked.connect(lambda: _run(
            relax.relax_selection, self.relax_iterations.value(),
            self.relax_strength.value(), self.relax_boundary.isChecked()))
        snap_btn = QtWidgets.QPushButton("Snap Selection To Surface")
        snap_btn.clicked.connect(lambda: _run(surface.snap_selection))
        form.addRow("Iterations", self.relax_iterations)
        form.addRow("Strength", self.relax_strength)
        form.addRow(self.relax_boundary)
        form.addRow(relax_btn)
        form.addRow(snap_btn)
        return group

    # Brush --------------------------------------------------------------
    def _brush_group(self):
        group = QtWidgets.QGroupBox("Relax Brush")
        form = QtWidgets.QFormLayout(group)
        self.brush_radius = _dspin(brush.brush.radius, 0.001, 10000.0, 0.1)
        self.brush_strength = _dspin(brush.brush.strength, 0.0, 1.0, 0.05)
        self.brush_radius.valueChanged.connect(lambda v: setattr(brush.brush, "radius", v))
        self.brush_strength.valueChanged.connect(lambda v: setattr(brush.brush, "strength", v))
        btn = QtWidgets.QPushButton("Activate Brush (select retopo mesh)")
        btn.clicked.connect(lambda: _run(
            brush.activate, self.brush_radius.value(), self.brush_strength.value(),
            self.relax_boundary.isChecked()))
        form.addRow("Radius (world)", self.brush_radius)
        form.addRow("Strength", self.brush_strength)
        form.addRow(btn)
        return group


def show():
    control = WINDOW_NAME + "WorkspaceControl"
    if cmds.workspaceControl(control, exists=True):
        cmds.deleteUI(control)
    window = RetopoWindow()
    window.show(dockable=True)
    return window
