"""9ame Retopo plug-in.

Adds a "9ame Retopo" menu to Maya's main window and registers
``nineRetopoOverlay``, a locator that draws a connected retopo mesh on top
of everything else (front facing faces only) so it stays readable while it
lies on the high poly surface.
"""

import os
import runpy

import maya.api.OpenMaya as om
import maya.api.OpenMayaRender as omr
import maya.api.OpenMayaUI as omui
import maya.cmds as cmds
import maya.mel as mel

VERSION = "0.2.0"
MENU = "nineRetopoMenu"

MENU_ITEMS = (
    ("Open Retopo Window", "from nine_retopo import ui; ui.show()"),
    None,
    ("Set Live Surface", "from nine_retopo import surface; surface.set_live_surface()"),
    ("Clear Live Surface", "from nine_retopo import surface; surface.clear_live_surface()"),
    None,
    ("Draw Rails", "from nine_retopo import rail_tool; rail_tool.activate()"),
    ("New Rail Chain", "from nine_retopo import rail_tool; rail_tool.reset()"),
    ("Build Strip", "from nine_retopo import strip; strip.build_strip()"),
    ("Insert Edge Loop", "from nine_retopo import loops; loops.insert_edge_loop()"),
    ("Relax Selection", "from nine_retopo import relax; relax.relax_selection()"),
    ("Snap To Surface", "from nine_retopo import surface; surface.snap_selection()"),
    ("Relax Brush", "from nine_retopo import brush; brush.activate()"),
)


def maya_useNewAPI():
    pass


# Overlay ------------------------------------------------------------------
FACE_COLOR = om.MColor((0.36, 0.30, 1.0, 0.38))
WIRE_COLOR = om.MColor((0.55, 0.95, 1.0, 1.0))
POINT_COLOR = om.MColor((1.0, 1.0, 1.0, 1.0))
PREVIEW_FACE_COLOR = om.MColor((0.25, 0.95, 0.35, 0.40))
PREVIEW_WIRE_COLOR = om.MColor((0.75, 1.0, 0.75, 1.0))


class RetopoOverlay(omui.MPxLocatorNode):
    TYPE_NAME = "nineRetopoOverlay"
    TYPE_ID = om.MTypeId(0x0007F3A1)  # local / in-house range
    DRAW_CLASSIFICATION = "drawdb/geometry/nineRetopoOverlay"
    DRAW_REGISTRANT = "nineRetopoOverlayOverride"
    in_mesh = None
    preview = None

    @staticmethod
    def creator():
        return RetopoOverlay()

    @staticmethod
    def initialize():
        typed = om.MFnTypedAttribute()
        RetopoOverlay.in_mesh = typed.create("inMesh", "rim", om.MFnData.kMesh)
        typed.storable = False
        typed.hidden = True
        om.MPxNode.addAttribute(RetopoOverlay.in_mesh)
        numeric = om.MFnNumericAttribute()
        RetopoOverlay.preview = numeric.create("preview", "pv", om.MFnNumericData.kBoolean, False)
        om.MPxNode.addAttribute(RetopoOverlay.preview)


class OverlayData(om.MUserData):
    def __init__(self):
        super(OverlayData, self).__init__(False)
        self.tris = om.MPointArray()
        self.lines = om.MPointArray()
        self.points = om.MPointArray()
        self.preview = False


def _overlay_geometry(mesh_obj, to_local, camera_path):
    """Triangles, edge lines and points of the faces that face the camera."""
    fn = om.MFnMesh(mesh_obj)
    points = fn.getPoints(om.MSpace.kObject)
    counts, connects = fn.getVertices()
    cam = om.MFnCamera(camera_path)
    ortho = cam.isOrtho()
    eye = om.MPoint() * camera_path.inclusiveMatrix()
    view_dir = cam.viewDirection(om.MSpace.kWorld)

    tris, lines, verts = om.MPointArray(), om.MPointArray(), om.MPointArray()
    seen_edges, seen_verts = set(), set()
    k = 0
    for n in counts:
        ids = connects[k:k + n]
        k += n
        pts = [points[i] for i in ids]
        normal = om.MVector()
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            normal.x += (a.y - b.y) * (a.z + b.z)
            normal.y += (a.z - b.z) * (a.x + b.x)
            normal.z += (a.x - b.x) * (a.y + b.y)
        if ortho:
            facing = normal * view_dir < 0
        else:
            center = om.MPoint()
            for p in pts:
                center += om.MVector(p)
            center = center / float(n)
            facing = normal * (eye - center) > 0
        if not facing:
            continue
        local = [p * to_local for p in pts]
        for i in range(1, n - 1):
            tris.append(local[0])
            tris.append(local[i])
            tris.append(local[i + 1])
        for i in range(n):
            a, b = ids[i], ids[(i + 1) % n]
            key = (a, b) if a < b else (b, a)
            if key not in seen_edges:
                seen_edges.add(key)
                lines.append(local[i])
                lines.append(local[(i + 1) % n])
            if ids[i] not in seen_verts:
                seen_verts.add(ids[i])
                verts.append(local[i])
    return tris, lines, verts


class OverlayOverride(omr.MPxDrawOverride):
    @staticmethod
    def creator(obj):
        return OverlayOverride(obj)

    def __init__(self, obj):
        super(OverlayOverride, self).__init__(obj, None, True)

    def supportedDrawAPIs(self):
        return omr.MRenderer.kAllDevices

    def isBounded(self, obj_path, camera_path):
        return False

    def hasUIDrawables(self):
        return True

    def prepareForDraw(self, obj_path, camera_path, frame_context, old_data):
        data = old_data if isinstance(old_data, OverlayData) else OverlayData()
        data.tris, data.lines, data.points = (om.MPointArray(), om.MPointArray(),
                                              om.MPointArray())
        data.preview = om.MPlug(obj_path.node(), RetopoOverlay.preview).asBool()
        plug = om.MPlug(obj_path.node(), RetopoOverlay.in_mesh)
        if not plug.isDestination:
            return data  # the retopo mesh was deleted; draw nothing
        try:
            mesh_obj = plug.asMObject()
        except RuntimeError:
            return data
        if mesh_obj.isNull():
            return data
        data.tris, data.lines, data.points = _overlay_geometry(
            mesh_obj, obj_path.inclusiveMatrixInverse(), camera_path)
        return data

    def addUIDrawables(self, obj_path, draw_manager, frame_context, data):
        if not isinstance(data, OverlayData) or not len(data.lines):
            return
        draw_manager.beginDrawInXray()
        draw_manager.setColor(PREVIEW_FACE_COLOR if data.preview else FACE_COLOR)
        draw_manager.mesh(omr.MUIDrawManager.kTriangles, data.tris)
        draw_manager.setColor(PREVIEW_WIRE_COLOR if data.preview else WIRE_COLOR)
        draw_manager.setLineWidth(1.5)
        draw_manager.mesh(omr.MUIDrawManager.kLines, data.lines)
        draw_manager.setColor(POINT_COLOR)
        draw_manager.setPointSize(4.0)
        draw_manager.mesh(omr.MUIDrawManager.kPoints, data.points)
        draw_manager.endDrawInXray()


def _build_menu():
    _delete_menu()
    main_window = mel.eval("$tmp = $gMainWindow")
    cmds.menu(MENU, parent=main_window, label="9ame Retopo", tearOff=True)
    for item in MENU_ITEMS:
        if item is None:
            cmds.menuItem(divider=True, parent=MENU)
        else:
            label, command = item
            cmds.menuItem(label=label, command=command, sourceType="python", parent=MENU)
    cmds.menuItem(divider=True, parent=MENU)
    cmds.menuItem(label="Uninstall", parent=MENU,
                  command=lambda *_: cmds.evalDeferred(_uninstall))


def _uninstall():
    # Deferred so the plug-in isn't unloaded from inside its own menu callback.
    plugin_dir = os.path.dirname(cmds.pluginInfo("nineRetopo", query=True, path=True))
    script = os.path.join(os.path.dirname(plugin_dir), "nine_retopo_uninstall.py")
    runpy.run_path(script)["uninstall"]()


def _delete_menu():
    if cmds.menu(MENU, exists=True):
        cmds.deleteUI(MENU)


def initializePlugin(plugin):
    fn = om.MFnPlugin(plugin, "9ame", VERSION)
    fn.registerNode(RetopoOverlay.TYPE_NAME, RetopoOverlay.TYPE_ID,
                    RetopoOverlay.creator, RetopoOverlay.initialize,
                    om.MPxNode.kLocatorNode, RetopoOverlay.DRAW_CLASSIFICATION)
    omr.MDrawRegistry.registerDrawOverrideCreator(
        RetopoOverlay.DRAW_CLASSIFICATION, RetopoOverlay.DRAW_REGISTRANT,
        OverlayOverride.creator)
    if not cmds.about(batch=True):
        cmds.evalDeferred(_build_menu)


def uninitializePlugin(plugin):
    fn = om.MFnPlugin(plugin)
    omr.MDrawRegistry.deregisterDrawOverrideCreator(
        RetopoOverlay.DRAW_CLASSIFICATION, RetopoOverlay.DRAW_REGISTRANT)
    fn.deregisterNode(RetopoOverlay.TYPE_ID)
    if not cmds.about(batch=True):
        _delete_menu()
