"""How retopo geometry looks in the viewport.

Retopo meshes get a translucent shader so the high poly shows through, and
are tagged so the drawing tool can find them again. While the rail tool is
active, selected objects are drawn with their full wireframe.
"""

import maya.cmds as cmds

TAG = "nineRetopoMesh"
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


def style_retopo(mesh):
    """Tag ``mesh`` as retopo geometry and give it the translucent look."""
    if not cmds.attributeQuery(TAG, node=mesh, exists=True):
        cmds.addAttr(mesh, longName=TAG, attributeType="bool", defaultValue=True)
    _assign(mesh, RETOPO_SHADER)


def style_preview(mesh):
    _assign(mesh, PREVIEW_SHADER)


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
