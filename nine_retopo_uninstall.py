"""Drag and drop this file into the Maya viewport to uninstall 9ame Retopo.

Unloads the plug-in, removes the module file and clears the loaded Python
modules, so a fresh copy can be installed without restarting Maya.
"""

import os
import sys

import maya.cmds as cmds

MODULE_NAME = "nine_retopo"
PLUGIN_NAME = "nineRetopo"
CONTEXTS = ("nineRetopoRailCtx", "nineRetopoRelaxBrushCtx")
WORKSPACE_CONTROL = "nineRetopoWindowWorkspaceControl"
OPTION_VAR = "nineRetopo_liveSurface"
OVERLAY_TYPE = "nineRetopoOverlay"


def unload():
    """Remove everything 9ame Retopo put into the running Maya session."""
    if cmds.currentCtx() in CONTEXTS:
        cmds.setToolTo("selectSuperContext")
    for ctx in CONTEXTS:
        if cmds.contextInfo(ctx, exists=True):
            cmds.deleteUI(ctx, toolContext=True)
    if cmds.workspaceControl(WORKSPACE_CONTROL, exists=True):
        cmds.deleteUI(WORKSPACE_CONTROL)

    if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        # Overlay locators would turn into unknown nodes once the plug-in is gone.
        overlays = cmds.ls(type=OVERLAY_TYPE, long=True) or []
        transforms = cmds.listRelatives(overlays, parent=True, fullPath=True) or []
        if transforms:
            cmds.delete(transforms)
            # Deleted nodes live on in the undo queue and keep the plug-in busy.
            cmds.flushUndo()

    if cmds.pluginInfo(PLUGIN_NAME, query=True, registered=True):
        cmds.pluginInfo(PLUGIN_NAME, edit=True, autoload=False)
    if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN_NAME, force=True)

    for name in list(sys.modules):
        if name == MODULE_NAME or name.startswith(MODULE_NAME + "."):
            del sys.modules[name]
    sys.path[:] = [p for p in sys.path
                   if not os.path.isdir(os.path.join(p, MODULE_NAME))]


def uninstall(confirm=True):
    if confirm and cmds.confirmDialog(
            title="9ame Retopo", message="Uninstall 9ame Retopo?",
            button=["Uninstall", "Cancel"], defaultButton="Uninstall",
            cancelButton="Cancel", dismissString="Cancel") != "Uninstall":
        return False

    unload()
    cmds.optionVar(remove=OPTION_VAR)
    mod_file = os.path.join(cmds.internalVar(userAppDir=True), "modules",
                            MODULE_NAME + ".mod")
    if os.path.isfile(mod_file):
        os.remove(mod_file)

    if confirm:
        cmds.confirmDialog(title="9ame Retopo",
                           message="Uninstalled. You can delete the folder now.",
                           button=["OK"])
    return True


def onMayaDroppedPythonFile(*args):
    # Maya imports dropped files by name; drop the cached module so the next
    # drop (e.g. from a newer folder) runs that file instead of this one.
    sys.modules.pop(__name__, None)
    uninstall()
