"""9ame Retopo plug-in: adds a "9ame Retopo" menu to Maya's main window."""

import os
import runpy

import maya.api.OpenMaya as om
import maya.cmds as cmds
import maya.mel as mel

VERSION = "0.1.0"
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
    om.MFnPlugin(plugin, "9ame", VERSION)
    if not cmds.about(batch=True):
        cmds.evalDeferred(_build_menu)


def uninitializePlugin(plugin):
    om.MFnPlugin(plugin)
    if not cmds.about(batch=True):
        _delete_menu()
