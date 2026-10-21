"""zRail-style rail drawing tool.

Drag on the live surface to draw a rail. While the stroke is drawn, the
strip it would make is previewed live; releasing builds it, and every
following rail continues from the edge of the previous strip, welded to it.
A stroke drawn next to any other border side of a retopo mesh (the end of
a strip, say) grows the mesh from that side instead.
Start with mesh edges selected to continue from an existing retopo mesh.
Shift-drag starts a new chain. Ctrl-drag over a retopo mesh slides a new
edge loop along the ring under the cursor and inserts it on release.

Chains remember their rails (chain.py), so changing the span counts in the
tool window rebuilds the chain being drawn, or the selected chain.
"""

import maya.api.OpenMaya as om
import maya.cmds as cmds

from nine_retopo import chain, display, geometry, loops, mesh_utils, strip
from nine_retopo.surface import Projector, get_live_surface
from nine_retopo.viewport import MeshRaycaster

CONTEXT = "nineRetopoRailCtx"
RAIL_COLOR = 17  # yellow
CUT_COLOR = 18  # cyan
# A stroke bridges to a mesh border side only when its average gap to it is
# within this many times the longer of the two.
SIDE_REACH = 4.0


def _preview_curve(points, closed, curve=None, color=RAIL_COLOR):
    """Create or update a linear curve through ``points``."""
    pts = list(points) + ([points[0]] if closed else [])
    if curve and cmds.objExists(curve):
        cmds.curve(curve, replace=True, degree=1, point=pts)
        return curve
    curve = cmds.curve(degree=1, point=pts, name="retopoRail#")
    shape = cmds.listRelatives(curve, shapes=True, fullPath=True)[0]
    cmds.setAttr(shape + ".overrideEnabled", True)
    cmds.setAttr(shape + ".overrideColor", color)
    if cmds.attributeQuery("lineWidth", node=shape, exists=True):
        cmds.setAttr(shape + ".lineWidth", 3)
    return cmds.ls(curve, long=True)[0]


def _delete(node):
    if node and cmds.objExists(node):
        cmds.delete(node)


def _rail_after_cut(rail, inserted):
    """Insert the new loop's vertices into ``rail`` where it crosses its edges.

    ``inserted`` is a list of ``(point_a, point_b, new_point)`` for every
    split edge. Keeps the chain's far edge in step with the mesh so the next
    strip still welds vertex for vertex.
    """
    pts = rail.points
    if len(pts) < 2:
        return rail
    tol = geometry.polyline_length(pts, rail.closed) / rail.segments * 0.01
    same = lambda p, q: geometry.distance(p, q) <= tol
    result = []
    for i in range(len(pts)):
        result.append(pts[i])
        if i == len(pts) - 1 and not rail.closed:
            break
        p, q = pts[i], pts[(i + 1) % len(pts)]
        for a, b, new in inserted:
            if (same(p, a) and same(q, b)) or (same(p, b) and same(q, a)):
                result.append(new)
                break
    return strip.Rail(result, rail.closed, rail.mesh)


class StripPreview(object):
    """A throwaway mesh showing the strip the current stroke would build."""

    def __init__(self):
        self.mesh = None
        self._size = None

    def update(self, grid):
        size = (grid.columns, grid.rows)
        if self._size != size or not (self.mesh and cmds.objExists(self.mesh)):
            self.clear()
            mesh = cmds.polyPlane(subdivisionsX=grid.columns - 1,
                                  subdivisionsY=grid.rows - 1,
                                  constructionHistory=False, name="retopoPreview#")[0]
            self.mesh = cmds.ls(mesh, long=True)[0]
            self._size = size
            display.style_preview(self.mesh)
        points = om.MPointArray([om.MPoint(*p) for p in grid.vertices])
        om.MFnMesh(mesh_utils.mesh_path(self.mesh)).setPoints(points, om.MSpace.kWorld)

    def clear(self):
        display.delete_with_overlay(self.mesh)
        self.mesh = None
        self._size = None


class RailTool(object):
    def __init__(self):
        self.spans_along = 0
        self.spans_across = 0
        self.smooth = 3
        self._sides = []  # border sides of retopo meshes, gathered per stroke
        self._fresh = False  # next stroke must start a new chain
        self._rail = None
        self._rail_curve = None
        self._stroke = []
        self._stroke_curve = None
        self._last_xy = None
        self._raycaster = None
        self._projector = None
        self._preview = StripPreview()
        self._mode = None
        self._casters = []
        self._ring = None
        self._cut_curve = None
        self._chain = None  # record of the chain being drawn (see chain.py)

    def activate(self):
        if not get_live_surface():
            raise RuntimeError("Set a live surface first.")
        self.reset()
        self._fresh = False  # strokes may grow existing retopo meshes
        # Continue from selected border edges of an existing retopo mesh.
        edge_rails = [r for r in strip.rails_from_selection() if r.mesh]
        if edge_rails:
            self._rail = edge_rails[0]

        callbacks = dict(pressCommand=self._press, dragCommand=self._drag,
                         releaseCommand=self._release,
                         initialize=display.show_selected_wireframe,
                         finalize=self._finalize)
        if cmds.draggerContext(CONTEXT, exists=True):
            cmds.draggerContext(CONTEXT, edit=True, **callbacks)
        else:
            cmds.draggerContext(CONTEXT, cursor="crossHair", space="screen",
                                undoMode="all", name=CONTEXT, **callbacks)
        cmds.setToolTo(CONTEXT)

    def reset(self):
        """Forget the pending rail so the next stroke starts a new chain.

        That stroke becomes a guide rail even next to an existing mesh.
        """
        _delete(self._rail_curve)
        self._rail = None
        self._rail_curve = None
        self._chain = None
        self._fresh = True

    def chain_mesh(self):
        """The mesh of the chain currently being drawn, if it is editable."""
        if self._chain is not None and self._rail is not None and self._rail.mesh \
                and cmds.objExists(self._rail.mesh):
            return self._rail.mesh
        return None

    def apply_spans(self, along=None, across=None):
        """Rebuild the selected chain (or the one being drawn) with new counts."""
        target = chain.selected_chain() or self.chain_mesh()
        if target is None:
            return None
        drawing = target == self.chain_mesh()
        mesh, far = chain.rebuild(target, along, across)
        if drawing:
            self._rail = far
            self._chain = chain.load(mesh)
        cmds.select(mesh)
        return mesh

    def _finalize(self):
        self._preview.clear()
        _delete(self._cut_curve)
        self._cut_curve = None
        display.restore_wireframe()

    def _pending(self):
        pending = self._rail
        if pending is not None and pending.mesh and not cmds.objExists(pending.mesh):
            pending = strip.Rail(pending.points, pending.closed)  # mesh was undone
            self._rail = pending
        return pending

    # Dragger callbacks ----------------------------------------------------
    def _press(self):
        surface = get_live_surface()
        if not surface:
            om.MGlobal.displayError("Set a live surface first.")
            return
        modifier = cmds.draggerContext(CONTEXT, query=True, modifier=True)
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, anchorPoint=True)
        self._projector = Projector()
        if modifier == "ctrl":
            self._start_cut(x, y)
            return
        if modifier == "shift":
            self.reset()
        if self._fresh:
            self._sides = []  # a new chain never grows from an existing mesh
        else:
            self._sides = [side for mesh in display.retopo_meshes()
                           for side in strip.border_rails(mesh)]
        self._mode = "draw"
        self._raycaster = MeshRaycaster(mesh_utils.mesh_path(surface))
        self._stroke = []
        self._stroke_curve = None
        self._last_xy = None
        self._add_point(x, y)

    def _drag(self):
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, dragPoint=True)
        if self._mode == "draw":
            self._add_point(x, y)
        elif self._mode == "cut":
            self._update_cut(x, y)

    def _release(self):
        mode, self._mode = self._mode, None
        if mode == "cut":
            self._finish_cut()
            return
        if mode != "draw":
            return
        self._raycaster = None
        self._preview.clear()
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
            self._update_preview()
            cmds.refresh(currentView=True)

    def _stroke_rail(self, points):
        closed = geometry.is_closed_stroke(points)
        points = geometry.smooth_polyline(points, self.smooth, closed)
        return strip.Rail([self._projector.project(p) for p in points], closed)

    def _source_for(self, rail):
        """The rail the stroke bridges from.

        Candidates are the pending rail (the guide rail or the far edge of
        the chain) and every border side of the retopo meshes, so a stroke
        drawn next to the end of a strip extends it there. The closest one
        wins; the pending rail wins ties.
        """
        stroke_length = geometry.polyline_length(rail.points, rail.closed)
        best, best_cost = None, None
        pending = self._pending()
        candidates = ([pending] if pending is not None else []) + self._sides
        for candidate in candidates:
            cost = geometry.bridge_cost(candidate.points, candidate.closed,
                                        rail.points, rail.closed)
            if cost is None:
                continue
            if candidate is not pending:
                # Only bridge to a mesh side the stroke was drawn next to.
                reach = max(stroke_length, geometry.polyline_length(
                    candidate.points, candidate.closed))
                if cost > SIDE_REACH * reach:
                    continue
            if best_cost is None or cost < best_cost:
                best, best_cost = candidate, cost
        return best

    def _update_preview(self):
        """Show the strip the stroke so far would build."""
        rail = self._stroke_rail(self._stroke)
        source = self._source_for(rail)
        if source is None:
            self._preview.clear()
            return
        try:
            grid = strip.StripGrid(source, rail, self._along_for(source),
                                   self.spans_across, self._projector)
        except (RuntimeError, ValueError):
            self._preview.clear()
            return
        self._preview.update(grid)

    def _finish_stroke(self, points):
        if len(points) < 2:
            return
        rail = self._stroke_rail(points)

        pending = self._pending()
        source = self._source_for(rail)
        if source is None:
            if pending is not None:
                om.MGlobal.displayWarning(
                    "Open and closed rails can't be bridged; starting a new chain.")
            self.reset()
            self._rail = rail
            self._rail_curve = _preview_curve(rail.points, rail.closed)
            return

        mesh, far_rail = strip.build_strip_from_rails(
            source, rail, self._along_for(source), self.spans_across,
            merge=True, snap=True)
        _delete(self._rail_curve)
        self._rail_curve = None
        self._rail = far_rail
        self._fresh = False

        # Remember the rails so span counts can still be changed afterwards.
        if source is not pending:
            # Grown from another side of a mesh: no longer a single chain
            # that can be rebuilt from its rails.
            chain.forget(mesh)
            self._chain = None
        else:
            if pending.mesh is None:
                self._chain = chain.new_record(pending, self.spans_along)
            if self._chain is not None:
                chain.add_strip(self._chain, rail, self.spans_across)
                chain.save(mesh, self._chain)
        cmds.select(mesh)

    def _along_for(self, pending):
        # Spans along is a property of the whole chain: only the first strip
        # takes it from the UI, later ones match the edge they continue from.
        return self.spans_along if pending.mesh is None else 0

    # Edge loop cutting ----------------------------------------------------
    def _start_cut(self, x, y):
        meshes = set(display.retopo_meshes())
        pending = self._pending()
        if pending is not None and pending.mesh:
            meshes.add(pending.mesh)
        self._casters = [(m, MeshRaycaster(mesh_utils.mesh_path(m))) for m in meshes]
        if not self._casters:
            om.MGlobal.displayWarning("No retopo mesh to cut yet.")
            return
        self._mode = "cut"
        self._ring = None
        self._update_cut(x, y)

    def _update_cut(self, x, y):
        best = None
        for mesh, caster in self._casters:
            hit = caster.hit_face(x, y)
            if hit and (best is None or hit[2] < best[1][2]):
                best = (mesh, hit)
        if best is None:
            return  # keep the last ring while the cursor is off the mesh
        mesh, (point, face, _) = best
        try:
            self._ring = loops.ring_under(mesh, point, face)
        except ValueError:
            return
        points = self._ring.cut_points(self._projector)
        if len(points) >= 2:
            self._cut_curve = _preview_curve(points, self._ring.closed,
                                             self._cut_curve, CUT_COLOR)
        cmds.refresh(currentView=True)

    def _finish_cut(self):
        _delete(self._cut_curve)
        self._cut_curve = None
        ring, self._ring = self._ring, None
        self._casters = []
        if ring is None:
            return
        try:
            inserted = loops.split_ring(ring, snap=True)
        except Exception as exc:  # keep the tool alive, report in the status line
            om.MGlobal.displayError(str(exc))
            return
        cmds.select(ring.mesh)
        # A hand cut can't be replayed from the rails, so the chain stops
        # being rebuildable from the span counts.
        chain.forget(ring.mesh)
        pending = self._pending()
        if pending is not None and pending.mesh == ring.mesh:
            self._rail = _rail_after_cut(pending, inserted)
            self._chain = None


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
