import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from nine_retopo import geometry as g  # noqa: E402


def close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


class ResampleTest(unittest.TestCase):
    def test_open_keeps_end_points(self):
        pts = [(0, 0, 0), (1, 0, 0), (1, 3, 0)]
        out = g.resample_polyline(pts, 5)
        self.assertEqual(len(out), 5)
        self.assertTrue(close(out[0], (0, 0, 0)))
        self.assertTrue(close(out[-1], (1, 3, 0)))
        self.assertTrue(close(out[1], (1, 0, 0)))

    def test_closed_square(self):
        sq = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        out = g.resample_polyline(sq, 8, closed=True)
        self.assertEqual(len(out), 8)
        self.assertTrue(close(out[1], (0.5, 0, 0)))
        self.assertTrue(close(out[7], (0, 0.5, 0)))

    def test_degenerate_segments(self):
        pts = [(0, 0, 0), (0, 0, 0), (2, 0, 0)]
        out = g.resample_polyline(pts, 3)
        self.assertTrue(close(out[1], (1, 0, 0)))


class AlignTest(unittest.TestCase):
    def test_open_reverses(self):
        a = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        b = [(2, 1, 0), (1, 1, 0), (0, 1, 0)]
        self.assertEqual(g.align_rails(a, b)[0], (0, 1, 0))

    def test_closed_rotates(self):
        a = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)]
        b = [(0, 2, 1), (-2, 0, 1), (0, -2, 1), (2, 0, 1)]
        aligned = g.align_rails(a, b, closed=True)
        self.assertEqual(aligned[0], (2, 0, 1))
        self.assertEqual(aligned[1], (0, 2, 1))


class GridTest(unittest.TestCase):
    def test_open_grid(self):
        a = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        b = [(0, 2, 0), (1, 2, 0), (2, 2, 0)]
        verts, faces = g.build_strip_grid(a, b, 2)
        self.assertEqual(len(verts), 9)
        self.assertEqual(len(faces), 4)
        self.assertTrue(close(verts[4], (1, 1, 0)))

    def test_closed_grid_wraps(self):
        a = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)]
        b = [(x, y, 1) for x, y, _ in a]
        verts, faces = g.build_strip_grid(a, b, 1, closed=True)
        self.assertEqual(len(faces), 4)
        self.assertEqual(faces[-1], (3, 0, 4, 7))

    def test_auto_spans_square_quads(self):
        a = [(0, 0, 0), (10, 0, 0)]
        b = [(0, 2, 0), (10, 2, 0)]
        self.assertEqual(g.auto_spans(a, b, 2), 10)


class ChainTest(unittest.TestCase):
    def test_open_chain_order(self):
        chains = g.chains_from_edges([(2, 3), (1, 2), (3, 4)])
        self.assertEqual(len(chains), 1)
        ids, closed = chains[0]
        self.assertFalse(closed)
        self.assertIn(ids, ([1, 2, 3, 4], [4, 3, 2, 1]))

    def test_closed_loop_and_second_chain(self):
        chains = g.chains_from_edges([(0, 1), (1, 2), (2, 0), (5, 6)])
        self.assertEqual(sorted(c for _, c in chains), [False, True])

    def test_branch_raises(self):
        with self.assertRaises(ValueError):
            g.chains_from_edges([(0, 1), (0, 2), (0, 3)])


class RingTest(unittest.TestCase):
    # 3 x 2 quad grid, vertex id = row * 4 + column.
    GRID = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6],
            [4, 5, 9, 8], [5, 6, 10, 9], [6, 7, 11, 10]]

    def test_open_ring_keeps_orientation(self):
        edges, closed = g.edge_ring(self.GRID, 5, 6)
        self.assertFalse(closed)
        self.assertEqual(sorted(edges), [(1, 2), (5, 6), (9, 10)])

    def test_ring_across_columns(self):
        edges, closed = g.edge_ring(self.GRID, 1, 5)
        self.assertFalse(closed)
        self.assertEqual(sorted(edges), [(0, 4), (1, 5), (2, 6), (3, 7)])

    def test_closed_ring(self):
        # Cylinder of 4 quads: bottom 0-3, top 4-7.
        faces = [[i, (i + 1) % 4, 4 + (i + 1) % 4, 4 + i] for i in range(4)]
        edges, closed = g.edge_ring(faces, 1, 5)
        self.assertTrue(closed)
        self.assertEqual(len(edges), 4)
        self.assertEqual(edges[0], (1, 5))
        self.assertTrue(all(v0 < 4 for v0, _ in edges))

    def test_stops_at_triangle(self):
        faces = [[0, 1, 4, 3], [1, 2, 4]]
        edges, _ = g.edge_ring(faces, 0, 3)
        self.assertEqual(edges, [(0, 3), (1, 4)])

    def test_closest_param(self):
        self.assertAlmostEqual(g.closest_param_on_segment((3, 5, 0), (0, 0, 0), (10, 0, 0)), 0.3)
        self.assertEqual(g.closest_param_on_segment((-4, 0, 0), (0, 0, 0), (10, 0, 0)), 0.0)


class BorderTest(unittest.TestCase):
    def test_grid_has_four_sides(self):
        sides = g.border_sides(RingTest.GRID)
        self.assertEqual(len(sides), 4)
        self.assertEqual(sorted(len(ids) for ids, _ in sides), [3, 3, 4, 4])
        self.assertFalse(any(closed for _, closed in sides))
        ends = sorted(tuple(sorted((ids[0], ids[-1]))) for ids, _ in sides)
        self.assertEqual(ends, [(0, 3), (0, 8), (3, 11), (8, 11)])

    def test_cylinder_rims_are_closed(self):
        faces = [[i, (i + 1) % 4, 4 + (i + 1) % 4, 4 + i] for i in range(4)]
        sides = g.border_sides(faces)
        self.assertEqual(len(sides), 2)
        self.assertTrue(all(closed for _, closed in sides))

    def test_auto_across_square(self):
        a = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        b = [(0, 3, 0), (1, 3, 0), (2, 3, 0)]
        self.assertEqual(g.auto_across(a, b), 3)

    def test_bridge_cost_prefers_near_rail(self):
        side = [(0, 0, 0), (0, 1, 0)]
        near = [(0.5, 0, 0), (0.5, 1, 0)]
        far = [(5, 0, 0), (5, 1, 0)]
        self.assertLess(g.bridge_cost(side, False, near, False),
                        g.bridge_cost(side, False, far, False))
        self.assertIsNone(g.bridge_cost(side, False, near, True))


class BorderOpsTest(unittest.TestCase):
    def test_border_loop_of_grid(self):
        loops = g.border_loops(RingTest.GRID)
        self.assertEqual(len(loops), 1)
        ids, closed = loops[0]
        self.assertTrue(closed)
        self.assertEqual(len(ids), 10)

    def test_border_path_short_way(self):
        ids = [0, 1, 2, 3, 7, 11, 10, 9, 8, 4]
        self.assertEqual(g.border_path(ids, True, 1, 3), [1, 2, 3])
        self.assertEqual(g.border_path(ids, True, 1, 4), [1, 0, 4])
        self.assertEqual(g.border_path([5, 6, 7, 8], False, 8, 6), [8, 7, 6])

    def test_align_order(self):
        a = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        b = [(2, 1, 0), (1, 1, 0), (0, 1, 0)]
        self.assertEqual(g.align_order(a, b), [2, 1, 0])

    def test_sweep_rows(self):
        row = [(0, 0, 0), (1, 0, 0)]
        stroke = [(5, 0, 0), (5, 2, 0)]
        rows = g.sweep_rows(row, stroke, 2)
        self.assertEqual(len(rows), 3)
        self.assertTrue(close(rows[1][1], (1, 1, 0)))
        self.assertTrue(close(rows[2][0], (0, 2, 0)))


class RelaxTest(unittest.TestCase):
    def test_moves_towards_neighbour_average(self):
        pos = {0: (0, 0, 0), 1: (1, 5, 0), 2: (2, 0, 0)}
        nbrs = {1: [0, 2]}
        out = g.relax_step(pos, nbrs, {1: 1.0})
        self.assertTrue(close(out[1], (1, 0, 0)))

    def test_falloff(self):
        self.assertEqual(g.falloff(0, 1), 1.0)
        self.assertEqual(g.falloff(1, 1), 0.0)

    def test_normal(self):
        n = g.polygon_normal([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
        self.assertGreater(n[2], 0)


class StrokeTest(unittest.TestCase):
    def test_smooth_keeps_ends(self):
        pts = [(0, 0, 0), (1, 1, 0), (2, -1, 0), (3, 0, 0)]
        out = g.smooth_polyline(pts, 2)
        self.assertEqual(out[0], pts[0])
        self.assertEqual(out[-1], pts[-1])
        self.assertLess(abs(out[1][1]), 1)

    def test_closed_stroke(self):
        circle = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0), (0.95, -0.05, 0)]
        self.assertTrue(g.is_closed_stroke(circle))
        line = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)]
        self.assertFalse(g.is_closed_stroke(line))


if __name__ == "__main__":
    unittest.main()
