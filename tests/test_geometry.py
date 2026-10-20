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


if __name__ == "__main__":
    unittest.main()
