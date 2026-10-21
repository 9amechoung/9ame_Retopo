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

Border editing (border_ops.py), following ziRail's hotkeys:
- Ctrl+Shift+click two border vertices selects the border between them;
  Ctrl+Shift+double-click selects a whole border. Up to two are kept; a
  plain click drops them.
- With a border selected, Ctrl+draw (red) redraws it along the stroke and
  Shift+draw (blue) extrudes it along the stroke.
- With two borders selected, Ctrl+middle click bridges them and
  Shift+middle click welds them.
- Ctrl+middle drag from a vertex to another welds it onto the target.
"""

import time
import types

import maya.api.OpenMaya as om
import maya.cmds as cmds

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets
    except ImportError:  # mayapy without Qt
        QtCore = QtWidgets = None

from nine_retopo import border_ops, chain, display, geometry, loops, mesh_utils, strip
from nine_retopo.surface import Projector, get_live_surface
from nine_retopo.viewport import MeshRaycaster

CONTEXT = "nineRetopoRailCtx"
RAIL_COLOR = 17  # yellow
CUT_COLOR = 18  # cyan
REDRAW_COLOR = 13  # red
EXTRUDE_COLOR = 6  # blue
SELECT_COLOR = 21  # orange
WELD_COLOR = 14  # green
STROKE_MODES = ("draw", "redraw", "extrude")
DOUBLE_CLICK = 0.4  # seconds
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


def _modifiers():
    """``(ctrl, shift)`` held right now."""
    if QtWidgets is not None and QtWidgets.QApplication.instance() is not None:
        mods = QtWidgets.QApplication.keyboardModifiers()
        return (bool(mods & QtCore.Qt.ControlModifier),
                bool(mods & QtCore.Qt.ShiftModifier))
    modifier = cmds.draggerContext(CONTEXT, query=True, modifier=True) or ""
    return "ctrl" in modifier, "shift" in modifier


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
        self._stroke_color = RAIL_COLOR
        self._segments = []  # selected borders (border_ops.Segment), at most two
        self._segment_curves = []
        self._pick_a = None  # first vertex of a border pick, (mesh, id)
        self._pick_time = 0.0
        self._target_weld = None  # [source (mesh, id), target or None]
        self._weld_curve = None
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
        _delete(self._weld_curve)
        self._weld_curve = None
        self._pick_a = None
        self._set_segments([])
        display.restore_wireframe()

    def _editable_meshes(self):
        meshes = set(display.retopo_meshes())
        pending = self._pending()
        if pending is not None and pending.mesh:
            meshes.add(pending.mesh)
        return sorted(meshes)

    def _after_topology_change(self, mesh):
        """Vertex ids moved: drop the border selection and the chain state."""
        self._set_segments([])
        self._pick_a = None
        _delete(self._rail_curve)
        self._rail_curve = None
        self._rail = None
        self._chain = None
        cmds.select(mesh)

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
        ctrl, shift = _modifiers()
        button = cmds.draggerContext(CONTEXT, query=True, button=True)
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, anchorPoint=True)
        self._projector = Projector()
        try:
            if button == 2:
                self._middle_press(x, y, ctrl, shift)
                return
            if ctrl and shift:
                self._pick_border(x, y)
                return
        except Exception as exc:  # keep the tool alive, report in the status line
            om.MGlobal.displayError(str(exc))
            return
        if ctrl and not self._segments:
            self._start_cut(x, y)
            return
        if ctrl:
            mode, color = "redraw", REDRAW_COLOR
        elif shift and self._segments:
            mode, color = "extrude", EXTRUDE_COLOR
        else:
            if shift:
                self.reset()
            mode, color = "draw", RAIL_COLOR
        if self._fresh or mode != "draw":
            self._sides = []  # a new chain never grows from an existing mesh
        else:
            self._sides = [side for mesh in display.retopo_meshes()
                           for side in strip.border_rails(mesh)]
        self._mode = mode
        self._stroke_color = color
        self._raycaster = MeshRaycaster(mesh_utils.mesh_path(surface))
        self._stroke = []
        self._stroke_curve = None
        self._last_xy = None
        self._add_point(x, y)

    def _drag(self):
        x, y, _ = cmds.draggerContext(CONTEXT, query=True, dragPoint=True)
        if self._mode in STROKE_MODES:
            self._add_point(x, y)
        elif self._mode == "cut":
            self._update_cut(x, y)
        elif self._mode == "target_weld":
            self._update_target_weld(x, y)

    def _release(self):
        mode, self._mode = self._mode, None
        if mode == "cut":
            self._finish_cut()
            return
        if mode == "target_weld":
            self._finish_target_weld()
            return
        if mode not in STROKE_MODES:
            return
        self._raycaster = None
        self._preview.clear()
        _delete(self._stroke_curve)
        self._stroke_curve = None
        try:
            if mode == "draw" and len(self._stroke) < 2:
                self._set_segments([])  # a plain click drops the border selection
            elif mode == "draw":
                self._finish_stroke(self._stroke)
            elif mode == "redraw":
                self._finish_redraw(self._stroke)
            else:
                self._finish_extrude(self._stroke)
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
            self._stroke_curve = _preview_curve(self._stroke, False, self._stroke_curve,
                                                self._stroke_color)
            if self._mode == "draw":
                self._update_preview()
            elif self._mode == "extrude":
                self._update_extrude_preview()
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
        self._set_segments([])  # merging renumbers vertices
        cmds.select(mesh)

    def _along_for(self, pending):
        # Spans along is a property of the whole chain: only the first strip
        # takes it from the UI, later ones match the edge they continue from.
        return self.spans_along if pending.mesh is None else 0

    # Border selection and border operations ------------------------------
    def _set_segments(self, segments):
        self._segments = list(segments)[-2:]
        self._draw_segments()

    def _draw_segments(self):
        for curve in self._segment_curves:
            _delete(curve)
        self._segment_curves = []
        self._segments = [s for s in self._segments if s.valid()]
        for seg in self._segments:
            self._segment_curves.append(
                _preview_curve(seg.points(), seg.closed, None, SELECT_COLOR))
        if self._pick_a is not None and cmds.objExists(self._pick_a[0]):
            mesh, vid = self._pick_a
            ids = border_ops.whole_border(mesh, vid).ids
            pts = mesh_utils.get_points(mesh)
            i = ids.index(vid)
            p = pts[vid]
            marker = [geometry.lerp(p, pts[ids[i - 1]], 0.5), p,
                      geometry.lerp(p, pts[ids[(i + 1) % len(ids)]], 0.5)]
            self._segment_curves.append(_preview_curve(marker, False, None, SELECT_COLOR))

    def _pick_border(self, x, y):
        """Ctrl+Shift+click: pick border vertex to vertex, double-click a whole border."""
        picked = border_ops.pick_vertex(x, y, self._editable_meshes(), border_only=True)
        if picked is None:
            om.MGlobal.displayWarning("No border vertex under the cursor.")
            return
        now = time.time()
        first, self._pick_a = self._pick_a, None
        try:
            if first == picked and now - self._pick_time < DOUBLE_CLICK:
                self._set_segments(self._segments + [border_ops.whole_border(*picked)])
            elif first is not None and first[0] == picked[0] and first != picked:
                self._set_segments(self._segments + [
                    border_ops.segment_between(picked[0], first[1], picked[1])])
            else:
                self._pick_a = picked
        finally:
            self._pick_time = now
            self._draw_segments()
            cmds.refresh(currentView=True)

    def _middle_press(self, x, y, ctrl, shift):
        segments = [s for s in self._segments if s.valid()]
        if len(segments) == 2 and ctrl:
            self._after_topology_change(
                border_ops.bridge(segments[0], segments[1], self.spans_across))
        elif len(segments) == 2 and shift:
            self._after_topology_change(border_ops.weld(segments[0], segments[1]))
        elif ctrl:
            source = border_ops.pick_vertex(x, y, self._editable_meshes())
            if source is None:
                om.MGlobal.displayWarning("No retopo vertex under the cursor.")
                return
            self._mode = "target_weld"
            self._target_weld = [source, None]
        elif shift:
            om.MGlobal.displayWarning(
                "Select two borders with Ctrl+Shift+click first, then Shift+middle "
                "click welds them (Ctrl+middle click bridges them).")

    def _update_target_weld(self, x, y):
        source = self._target_weld[0]
        target = border_ops.pick_vertex(x, y, self._editable_meshes(), exclude=source)
        self._target_weld[1] = target
        if target is None:
            _delete(self._weld_curve)
            self._weld_curve = None
        else:
            line = [mesh_utils.get_points(source[0])[source[1]],
                    mesh_utils.get_points(target[0])[target[1]]]
            self._weld_curve = _preview_curve(line, False, self._weld_curve, WELD_COLOR)
        cmds.refresh(currentView=True)

    def _finish_target_weld(self):
        _delete(self._weld_curve)
        self._weld_curve = None
        (source, target), self._target_weld = self._target_weld, None
        if target is None:
            return
        try:
            self._after_topology_change(border_ops.target_weld(
                source[0], source[1], target[0], target[1]))
        except Exception as exc:  # keep the tool alive, report in the status line
            om.MGlobal.displayError(str(exc))

    def _stroke_path(self, points):
        """A freehand stroke smoothed and lying on the live surface."""
        points = geometry.smooth_polyline(points, self.smooth)
        return [self._projector.project(p) for p in points]

    def _finish_redraw(self, points):
        """Ctrl+draw with a border selected: move it onto the stroke."""
        if len(points) < 2:
            return
        segment = self._segments[-1]
        pending = self._pending()
        follow = pending is not None and pending.mesh == segment.mesh
        if follow:
            pending_ids = border_ops.ids_at(segment.mesh, pending.points)
        border_ops.redraw(segment, self._stroke_path(points))
        if follow:
            pts = mesh_utils.get_points(segment.mesh)
            self._rail = strip.Rail([pts[i] for i in pending_ids], pending.closed,
                                    pending.mesh)
        self._chain = None
        self._draw_segments()

    def _update_extrude_preview(self):
        segment = self._segments[-1]
        if not segment.valid():
            return
        rows = border_ops.extrude_grid(segment.points(), segment.closed,
                                       self._stroke_path(self._stroke),
                                       self.spans_across, self._projector)
        self._preview.update(types.SimpleNamespace(
            columns=len(rows[0]), rows=len(rows), vertices=[p for r in rows for p in r]))

    def _finish_extrude(self, points):
        """Shift+draw with a border selected: extrude it along the stroke."""
        if len(points) < 2:
            return
        new = border_ops.extrude(self._segments[-1], self._stroke_path(points),
                                 self.spans_across)
        _delete(self._rail_curve)
        self._rail_curve = None
        self._rail = new.rail()
        self._chain = None
        self._fresh = False
        self._set_segments([new])  # keep extending from the new edge
        cmds.select(new.mesh)

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
        self._set_segments([])
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
