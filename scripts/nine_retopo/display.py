"""How retopo geometry looks in the viewport.

Retopo meshes get a translucent shader, and an overlay locator from the
plug-in that draws their faces and wireframe on top of the high poly. They
are tagged so the drawing tool can find them again. While the rail tool is
active, selected objects are drawn with their full wireframe.
"""

import maya.cmds as cmds

TAG = "nineRetopoMesh"
PLUGIN = "nineRetopo"
OVERLAY_TYPE = "nineRetopoOverlay"
OVERLAY_VAR = "nineRetopo_showOverlay"
RETOPO_SHADER = ("nineRetopo_mtl", (0.32, 0.28, 0.95), 0.35)
PREVIEW_SHADER = ("nineRetopoPreview_mtl", (0.25, 0.95, 0.35), 0.45)

_saved_wireframe = None


def _shading_group(spec):
    name, color, transparency = spec
    group = name + "SG"
    if not cmds.objExists(name):
        cmds.shadingNode("lambert", asShader=True, name=name)
        cmds.setAttr(name + ".color", *color, type="double3")
        cmds.setAttr(name + ".transparency", transparency, transparency, transparency,
                     type="double3")
        cmds.setAttr(name + ".ambientColor", 0.15, 0.15, 0.15, type="double3")
    if not cmds.objExists(group):
        cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=group)
        cmds.connectAttr(name + ".outColor", group + ".surfaceShader", force=True)
    return group


def _assign(mesh, spec):
    cmds.sets(mesh, edit=True, forceElement=_shading_group(spec))


def remove_orphan_overlays():
    """Delete overlays whose retopo mesh no longer exists."""
    for overlay in cmds.ls(type=OVERLAY_TYPE, long=True) or []:
        if not cmds.listConnections(overlay + ".inMesh", source=True, destination=False):
            cmds.delete(cmds.listRelatives(overlay, parent=True, fullPath=True))


def attach_overlay(mesh, preview=False):
    """Draw ``mesh`` on top of the high poly with a nineRetopoOverlay locator.

    Does nothing when the plug-in (which defines the overlay) isn't loaded.
    """
    if not cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        return None
    shape = cmds.listRelatives(mesh, shapes=True, type="mesh", fullPath=True,
                               noIntermediate=True)[0]
    existing = cmds.listConnections(shape + ".worldMesh[0]", type=OVERLAY_TYPE,
                                    shapes=True) or []
    if existing:
        return existing[0]
    short = mesh.split("|")[-1]
    xform = cmds.createNode("transform", name=short + "_overlay#", skipSelect=True)
    overlay = cmds.createNode(OVERLAY_TYPE, name=short + "_overlayShape#", parent=xform,
                              skipSelect=True)
    cmds.connectAttr(shape + ".worldMesh[0]", overlay + ".inMesh")
    cmds.setAttr(overlay + ".preview", preview)
    # Reference display keeps the locator out of viewport selection.
    cmds.setAttr(overlay + ".overrideEnabled", True)
    cmds.setAttr(overlay + ".overrideDisplayType", 2)
    cmds.setAttr(xform + ".hiddenInOutliner", True)
    cmds.setAttr(xform + ".visibility", preview or overlays_visible())
    for attr in ("translate", "rotate", "scale"):
        cmds.setAttr(xform + "." + attr, lock=True)
    return overlay


def _overlays_of(mesh):
    result = []
    for shape in cmds.listRelatives(mesh, shapes=True, type="mesh", fullPath=True) or []:
        result += cmds.listConnections(shape + ".worldMesh", type=OVERLAY_TYPE,
                                       shapes=True) or []
    return result


def overlays_visible():
    if not cmds.optionVar(exists=OVERLAY_VAR):
        return True
    return bool(cmds.optionVar(query=OVERLAY_VAR))


def set_overlays_visible(visible):
    """Show or hide every retopo overlay (the meshes keep their shader)."""
    cmds.optionVar(intValue=(OVERLAY_VAR, int(bool(visible))))
    for overlay in cmds.ls(type=OVERLAY_TYPE, long=True) or []:
        if cmds.getAttr(overlay + ".preview"):
            continue
        xform = cmds.listRelatives(overlay, parent=True, fullPath=True)[0]
        cmds.setAttr(xform + ".visibility", bool(visible))


def is_retopo(mesh):
    return cmds.attributeQuery(TAG, node=mesh, exists=True)


def unstyle_retopo(mesh):
    """Undo :func:`style_retopo`: plain shading, no overlay, no tag."""
    for overlay in _overlays_of(mesh):
        cmds.delete(cmds.listRelatives(overlay, parent=True, fullPath=True))
    cmds.sets(mesh, edit=True, forceElement="initialShadingGroup")
    if is_retopo(mesh):
        cmds.deleteAttr(mesh + "." + TAG)


def delete_with_overlay(mesh):
    """Delete ``mesh`` together with the overlay drawing it."""
    if not (mesh and cmds.objExists(mesh)):
        return
    for overlay in _overlays_of(mesh):
        cmds.delete(cmds.listRelatives(overlay, parent=True, fullPath=True))
    cmds.delete(mesh)


def style_retopo(mesh):
    """Tag ``mesh`` as retopo geometry and give it the translucent look."""
    if not cmds.attributeQuery(TAG, node=mesh, exists=True):
        cmds.addAttr(mesh, longName=TAG, attributeType="bool", defaultValue=True)
    _assign(mesh, RETOPO_SHADER)
    remove_orphan_overlays()
    attach_overlay(mesh)


def style_preview(mesh):
    _assign(mesh, PREVIEW_SHADER)
    attach_overlay(mesh, preview=True)


def retopo_meshes():
    """Transforms of every tagged retopo mesh in the scene."""
    nodes = cmds.ls("*." + TAG, objectsOnly=True, long=True, recursive=True) or []
    return [n for n in nodes if cmds.listRelatives(n, shapes=True, type="mesh")]


def show_selected_wireframe():
    """Draw the full wireframe on selected objects; remembers the old setting."""
    global _saved_wireframe
    if _saved_wireframe is None:
        _saved_wireframe = cmds.displayPref(query=True, wireframeOnShadedActive=True)
    cmds.displayPref(wireframeOnShadedActive="full")


def restore_wireframe():
    global _saved_wireframe
    if _saved_wireframe is not None:
        cmds.displayPref(wireframeOnShadedActive=_saved_wireframe)
        _saved_wireframe = None
