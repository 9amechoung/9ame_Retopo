"""Editable rail chains.

A chain drawn with the rail tool remembers its rails on the mesh (as JSON
in a string attribute), so its span counts can be changed after drawing:
the chain is rebuilt from the same rails with the new counts.

- ``along``: segments along the rails (the drawn, "blue" direction), shared
  by every strip of the chain.
- ``across``: segments between two rails (the "red" direction), per strip.
"""

import json

import maya.api.OpenMaya as om
import maya.cmds as cmds

from nine_retopo import display, mesh_utils, strip

ATTR = "nineRetopoChain"


def new_record(first_rail, along):
    return {"along": along, "across": [],
            "rails": [{"points": [list(p) for p in first_rail.points],
                       "closed": first_rail.closed}],
            "verts": 0}


def add_strip(record, rail, across):
    record["rails"].append({"points": [list(p) for p in rail.points],
                            "closed": rail.closed})
    record["across"].append(across)


def save(mesh, record):
    record["verts"] = cmds.polyEvaluate(mesh, vertex=True)
    if not cmds.attributeQuery(ATTR, node=mesh, exists=True):
        cmds.addAttr(mesh, longName=ATTR, dataType="string")
    cmds.setAttr(mesh + "." + ATTR, json.dumps(record), type="string")


def load(mesh):
    if not (mesh and cmds.objExists(mesh)
            and cmds.attributeQuery(ATTR, node=mesh, exists=True)):
        return None
    try:
        return json.loads(cmds.getAttr(mesh + "." + ATTR) or "")
    except ValueError:
        return None


def forget(mesh):
    """Stop treating ``mesh`` as an editable chain (e.g. after hand edits)."""
    if mesh and cmds.objExists(mesh) and cmds.attributeQuery(ATTR, node=mesh, exists=True):
        cmds.deleteAttr(mesh + "." + ATTR)


def selected_chain():
    """The first selected mesh that carries a chain record, or None."""
    for node in cmds.ls(selection=True, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if load(node):
            return node
    return None


@mesh_utils.undoable
def rebuild(mesh, along=None, across=None):
    """Rebuild chain ``mesh`` with new span counts.

    ``across`` applies to every strip of the chain. Returns ``(mesh,
    far_rail)``; ``far_rail`` is where drawing continues from.
    """
    record = load(mesh)
    if not record:
        raise RuntimeError("'%s' is not a drawn rail chain." % mesh.split("|")[-1])
    if along is not None:
        record["along"] = along
    if across is not None:
        record["across"] = [across] * len(record["across"])
    if cmds.polyEvaluate(mesh, vertex=True) != record["verts"]:
        om.MGlobal.displayWarning("The chain was edited by hand; rebuilding replaces "
                                  "those edits (Ctrl+Z to get them back).")

    rails = [strip.Rail([tuple(p) for p in r["points"]], r["closed"])
             for r in record["rails"]]
    parent = cmds.listRelatives(mesh, parent=True, fullPath=True)
    name = mesh.split("|")[-1]
    display.delete_with_overlay(mesh)

    pending = rails[0]
    result = None
    for i, rail in enumerate(rails[1:]):
        # Later strips match the far edge of the one before so they weld.
        result, pending = strip.build_strip_from_rails(
            pending, rail, record["along"] if i == 0 else 0, record["across"][i],
            merge=True, snap=True)
    if parent:
        result = cmds.ls(cmds.parent(result, parent[0]), long=True)[0]
    result = cmds.ls(cmds.rename(result, name), long=True)[0]
    save(result, record)
    pending.mesh = result
    return result, pending
