"""Drag and drop this file into the Maya viewport to install 9ame Retopo.

It writes a module file pointing at this folder, so Maya finds the scripts
and plug-in on every launch, and loads the plug-in right away.
"""

import os
import runpy
import sys

import maya.cmds as cmds

MODULE_NAME = "nine_retopo"
PLUGIN_NAME = "nineRetopo"


def install():
    root = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    # Remove any previous install (also from another folder) first.
    runpy.run_path(os.path.join(root, "uninstall.py"))["unload"]()

    modules_dir = os.path.join(cmds.internalVar(userAppDir=True), "modules")
    if not os.path.isdir(modules_dir):
        os.makedirs(modules_dir)
    with open(os.path.join(modules_dir, MODULE_NAME + ".mod"), "w") as f:
        f.write("+ %s 0.1.0 %s\n" % (MODULE_NAME, root))

    # Make it usable in this session without restarting Maya.
    scripts = root + "/scripts"
    if scripts not in sys.path:
        sys.path.append(scripts)
    plugin = root + "/plug-ins/" + PLUGIN_NAME + ".py"
    cmds.loadPlugin(plugin)
    cmds.pluginInfo(PLUGIN_NAME, edit=True, autoload=True)
    cmds.confirmDialog(title="9ame Retopo",
                       message="Installed. Use the '9ame Retopo' menu.",
                       button=["OK"])


def onMayaDroppedPythonFile(*args):
    install()
