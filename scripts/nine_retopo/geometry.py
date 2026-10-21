"""Maya-independent geometry helpers.

Everything here works on plain ``(x, y, z)`` tuples so it can be unit tested
outside of Maya.
"""

import math

EPSILON = 1e-12


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def length(a):
    return math.sqrt(dot(a, a))


def distance(a, b):
    return length(sub(a, b))


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def average(points):
    points = list(points)
    n = float(len(points))
    return (sum(p[0] for p in points) / n,
            sum(p[1] for p in points) / n,
            sum(p[2] for p in points) / n)


def polyline_length(points, closed=False):
    pts = list(points)
    if closed and pts:
        pts.append(pts[0])
    return sum(distance(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def resample_polyline(points, count, closed=False):
    """Return ``count`` points spaced evenly by arc length along a polyline.

    Open polylines keep both end points. Closed polylines return ``count``
    points around the loop starting at ``points[0]`` (the start is not
    repeated at the end).
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        raise ValueError("a rail needs at least two points")
    if closed:
        pts.append(pts[0])

    seg_lengths = [distance(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg_lengths)
    if total <= EPSILON:
        return [pts[0]] * count
    if closed:
        step = total / count
    elif count == 1:
        return [pts[0]]
    else:
        step = total / (count - 1)

    result = []
    seg = 0
    walked = 0.0
    for k in range(count):
        target = k * step
        while seg < len(seg_lengths) - 1 and walked + seg_lengths[seg] < target:
            walked += seg_lengths[seg]
            seg += 1
        seg_len = seg_lengths[seg]
        t = 0.0 if seg_len <= EPSILON else min(max((target - walked) / seg_len, 0.0), 1.0)
        result.append(lerp(pts[seg], pts[seg + 1], t))
    if not closed:
        result[-1] = pts[-1]
    return result


def align_order(rail_a, rail_b, closed=False):
    """Indices into ``rail_b`` so that ``rail_b[order[i]]`` lies across from rail_a[i].

    Both rails must have the same number of points. Open rails may be
    reversed; closed rails may also be rotated.
    """
    if len(rail_a) != len(rail_b):
        raise ValueError("rails must have the same number of points")
    n = len(rail_b)
    candidates = [list(range(n)), list(reversed(range(n)))]
    if not closed:
        cost = lambda o: distance(rail_a[0], rail_b[o[0]]) + distance(rail_a[-1], rail_b[o[-1]])
        return min(candidates, key=cost)

    best = None
    best_cost = None
    for cand in candidates:
        for offset in range(n):
            rotated = cand[offset:] + cand[:offset]
            cost = sum(distance(rail_a[i], rail_b[rotated[i]]) for i in range(n))
            if best_cost is None or cost < best_cost:
                best, best_cost = rotated, cost
    return best


def align_rails(rail_a, rail_b, closed=False):
    """Reorder ``rail_b`` so that rail_b[i] lies across from rail_a[i]."""
    return [rail_b[i] for i in align_order(rail_a, rail_b, closed)]


def border_loops(faces):
    """Open borders of a mesh as ``(vertex_ids, closed)`` chains (not split)."""
    use = {}
    for verts in faces:
        n = len(verts)
        for i in range(n):
            key = frozenset((verts[i], verts[(i + 1) % n]))
            use[key] = use.get(key, 0) + 1
    border = [tuple(k) for k, count in use.items() if count == 1]
    try:
        return chains_from_edges(border)
    except ValueError:
        return []


def border_path(ids, closed, a, b):
    """Vertices of border chain ``ids`` from ``a`` to ``b``, the short way round."""
    ia, ib = ids.index(a), ids.index(b)
    if not closed:
        return ids[ia:ib + 1] if ia <= ib else list(reversed(ids[ib:ia + 1]))
    n = len(ids)
    forward = [ids[(ia + k) % n] for k in range((ib - ia) % n + 1)]
    backward = [ids[(ia - k) % n] for k in range((ia - ib) % n + 1)]
    return forward if len(forward) <= len(backward) else backward


def sweep_rows(row, stroke, rows):
    """Extrude ``row`` along ``stroke``: ``rows`` new rows, each shifted by the
    stroke's offset from its start point at evenly spaced arc lengths."""
    samples = resample_polyline(stroke, rows + 1)
    origin = samples[0]
    result = [list(row)]
    for k in range(1, rows + 1):
        offset = sub(samples[k], origin)
        result.append([add(p, offset) for p in row])
    return result


def build_strip_grid(rail_a, rail_b, spans_across, closed=False):
    """Build a quad grid between two aligned rails.

    Returns ``(vertices, faces)``. Vertex ``j * n + i`` is column ``i`` on
    row ``j``; row 0 is ``rail_a`` and row ``spans_across`` is ``rail_b``.
    """
    if spans_across < 1:
        raise ValueError("spans_across must be at least 1")
    if len(rail_a) != len(rail_b):
        raise ValueError("rails must have the same number of points")
    n = len(rail_a)
    vertices = []
    for j in range(spans_across + 1):
        t = j / float(spans_across)
        vertices.extend(lerp(rail_a[i], rail_b[i], t) for i in range(n))

    faces = []
    columns = n if closed else n - 1
    for j in range(spans_across):
        for i in range(columns):
            i2 = (i + 1) % n
            faces.append((j * n + i, j * n + i2, (j + 1) * n + i2, (j + 1) * n + i))
    return vertices, faces


def auto_spans(rail_a, rail_b, spans_across, closed=False):
    """Pick a segment count along the rails that gives roughly square quads."""
    along = 0.5 * (polyline_length(rail_a, closed) + polyline_length(rail_b, closed))
    a = resample_polyline(rail_a, 8, closed)
    b = align_rails(a, resample_polyline(rail_b, 8, closed), closed)
    across = sum(distance(p, q) for p, q in zip(a, b)) / len(a)
    if across <= EPSILON:
        return 1
    quad = across / spans_across
    return max(3 if closed else 1, int(round(along / quad)))


def auto_across(rail_a, rail_b, closed=False):
    """Segments between two aligned rails that give roughly square quads."""
    segments = len(rail_a) if closed else len(rail_a) - 1
    seg_length = polyline_length(rail_a, closed) / max(segments, 1)
    if seg_length <= EPSILON:
        return 1
    across = sum(distance(p, q) for p, q in zip(rail_a, rail_b)) / len(rail_a)
    return max(1, int(round(across / seg_length)))


def bridge_cost(rail_a, closed_a, rail_b, closed_b, samples=8):
    """Average gap between two rails once lined up; None if they can't bridge."""
    if closed_a != closed_b:
        return None
    a = resample_polyline(rail_a, samples, closed_a)
    b = align_rails(a, resample_polyline(rail_b, samples, closed_b), closed_a)
    return sum(distance(p, q) for p, q in zip(a, b)) / samples


def border_sides(faces):
    """Split a mesh's open borders into sides at their corners.

    A corner is a border vertex with only two edges (the corner of a quad
    grid). Returns a list of ``(vertex_ids, closed)``; a border loop without
    corners (the rim of a cylinder) is one closed side.
    """
    degree = {}
    edges = set()
    for verts in faces:
        n = len(verts)
        for i in range(n):
            edges.add(frozenset((verts[i], verts[(i + 1) % n])))
    for key in edges:
        for v in key:
            degree[v] = degree.get(v, 0) + 1

    sides = []
    for ids, closed in border_loops(faces):
        corners = [i for i, v in enumerate(ids) if degree[v] == 2]
        if closed:
            if not corners:
                sides.append((ids, True))
                continue
            ids = ids[corners[0]:] + ids[:corners[0]]
            corners = [c - corners[0] for c in corners] + [len(ids)]
            ids = ids + [ids[0]]
        else:
            corners = sorted(set([0] + corners + [len(ids) - 1]))
        for start, end in zip(corners, corners[1:]):
            if end > start:
                sides.append((ids[start:end + 1], False))
    return sides


def chains_from_edges(edges):
    """Group ``(v0, v1)`` edge pairs into ordered vertex chains.

    Returns a list of ``(vertex_ids, closed)``. Raises ``ValueError`` when the
    edges branch.
    """
    adjacency = {}
    for v0, v1 in edges:
        adjacency.setdefault(v0, set()).add(v1)
        adjacency.setdefault(v1, set()).add(v0)
    for v, nbrs in adjacency.items():
        if len(nbrs) > 2:
            raise ValueError("edge selection branches at vertex %d" % v)

    chains = []
    visited = set()
    # Open chains first, walking from an end point.
    starts = [v for v, nbrs in adjacency.items() if len(nbrs) == 1]
    starts += [v for v in adjacency if v not in starts]
    for start in starts:
        if start in visited:
            continue
        chain = [start]
        visited.add(start)
        prev, cur = None, start
        while True:
            nxt = [v for v in adjacency[cur] if v != prev and v not in visited]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            chain.append(cur)
            visited.add(cur)
        closed = len(chain) > 2 and chain[0] in adjacency[chain[-1]]
        chains.append((chain, closed))
    return chains


def closest_param_on_segment(point, a, b):
    """Parameter in [0, 1] of the point on segment ``a``-``b`` closest to ``point``."""
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom <= EPSILON:
        return 0.0
    return min(max(dot(sub(point, a), ab) / denom, 0.0), 1.0)


def edge_ring(faces, a, b):
    """Walk the quad edge ring through edge ``(a, b)``.

    ``faces`` is a list of vertex id lists. Returns ``(edges, closed)`` where
    ``edges`` is an ordered list of ``(v0, v1)`` pairs oriented consistently
    with ``(a, b)``: every ``v0`` lies on the same side of the ring. The walk
    stops at borders and at faces that are not quads.
    """
    edge_faces = {}
    for f, verts in enumerate(faces):
        n = len(verts)
        for i in range(n):
            key = frozenset((verts[i], verts[(i + 1) % n]))
            edge_faces.setdefault(key, []).append(f)

    root = frozenset((a, b))

    def walk(face):
        result = []
        cur = (a, b)
        visited = set()
        while face is not None and face not in visited:
            visited.add(face)
            verts = faces[face]
            if len(verts) != 4:
                break
            ia, ib = verts.index(cur[0]), verts.index(cur[1])
            next_a = verts[(ia - 1) % 4] if verts[(ia + 1) % 4] == cur[1] else verts[(ia + 1) % 4]
            next_b = verts[(ib - 1) % 4] if verts[(ib + 1) % 4] == cur[0] else verts[(ib + 1) % 4]
            cur = (next_a, next_b)
            key = frozenset(cur)
            if key == root:
                return result, True
            result.append(cur)
            others = [f for f in edge_faces.get(key, ()) if f != face]
            face = others[0] if others else None
        return result, False

    adjacent = edge_faces.get(root, [])
    if not adjacent:
        raise ValueError("edge (%d, %d) is not part of any face" % (a, b))
    forward, closed = walk(adjacent[0])
    if closed:
        return [(a, b)] + forward, True
    backward = walk(adjacent[1])[0] if len(adjacent) > 1 else []
    return list(reversed(backward)) + [(a, b)] + forward, False


def polygon_normal(points):
    """Newell normal of a polygon (not normalized)."""
    nx = ny = nz = 0.0
    count = len(points)
    for i in range(count):
        cx, cy, cz = points[i]
        nx_, ny_, nz_ = points[(i + 1) % count]
        nx += (cy - ny_) * (cz + nz_)
        ny += (cz - nz_) * (cx + nx_)
        nz += (cx - nx_) * (cy + ny_)
    return (nx, ny, nz)


def falloff(dist, radius):
    """Smooth brush falloff: 1 at the centre, 0 at ``radius``."""
    if radius <= EPSILON or dist >= radius:
        return 0.0
    t = 1.0 - (dist / radius) ** 2
    return t * t


def relax_step(positions, neighbors, weights):
    """One Laplacian smoothing step.

    ``positions`` maps vertex id to point, ``neighbors`` maps vertex id to its
    connected vertex ids and ``weights`` maps each vertex to move to a blend
    factor in [0, 1]. Returns a dict of the moved vertices' new positions.
    """
    result = {}
    for vid, w in weights.items():
        nbrs = neighbors.get(vid)
        if not nbrs or w <= 0.0:
            continue
        target = average(positions[n] for n in nbrs)
        result[vid] = lerp(positions[vid], target, min(w, 1.0))
    return result


def smooth_polyline(points, iterations=3, closed=False):
    """Smooth a freehand stroke; open strokes keep their end points."""
    pts = [tuple(p) for p in points]
    n = len(pts)
    if n < 3:
        return pts
    for _ in range(iterations):
        out = list(pts)
        for i in range(n):
            if not closed and (i == 0 or i == n - 1):
                continue
            prev_p = pts[(i - 1) % n]
            next_p = pts[(i + 1) % n]
            out[i] = lerp(pts[i], scale(add(prev_p, next_p), 0.5), 0.5)
        pts = out
    return pts


def is_closed_stroke(points, tolerance=0.08):
    """True when a stroke ends near where it started.

    ``tolerance`` is a fraction of the stroke length.
    """
    if len(points) < 4:
        return False
    total = polyline_length(points)
    return total > EPSILON and distance(points[0], points[-1]) < total * tolerance
