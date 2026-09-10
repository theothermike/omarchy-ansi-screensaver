"""Canvas width for replay and the animation heuristic (stdlib unittest).
Run: python3 -B -m unittest discover -s tests"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.dont_write_bytecode = True

from ansisaver import ansi as A, library as L  # noqa: E402

ESC = "\x1b"


def grid_of(text, cols, wrap="immediate"):
    it = A.Interpreter(cols=cols, wrap=wrap)
    it.feed(text)
    return it.grid(), it.stats


class CanvasWidthTests(unittest.TestCase):
    def test_full_width_rows_do_not_gain_blank_lines_at_the_canvas_width(self):
        # rows exactly 79 wide followed by CRLF, like a classic 80-column piece with a 1-column margin
        text = "\r\n".join("#" * 79 for _ in range(5)) + "\r\n"
        g80, _ = grid_of(text, 80)
        self.assertEqual(g80.height, 5)
        self.assertEqual([g80.painted_width(r) for r in range(5)], [79] * 5)
        # replaying at the *measured* width (79) is the bug: every row wraps one column early
        g79, _ = grid_of(text, 79)
        self.assertGreater(g79.height, 5)
        self.assertTrue(any(g79.painted_width(r) == 0 for r in range(g79.height)), "blank rows appear between the art")

    def test_canvas_columns_rules(self):
        self.assertEqual(L.canvas_columns({"columns": 132}), 132)
        self.assertEqual(L.canvas_columns({"cols": 79, "original": "original.ans", "format": "ansi"}), 80)
        self.assertEqual(L.canvas_columns({"cols": 79, "original": "original.ans", "format": "ansimation"}), 80)
        self.assertEqual(L.canvas_columns({"sauce": {"datatype": 1, "tinfo1": 132}, "original": "original.ans"}), 132)
        self.assertEqual(L.canvas_columns({"sauce": {"datatype": 1, "tinfo1": 0}, "original": "original.ans"}), 80)
        self.assertEqual(L.canvas_columns({"original": "original.txt", "format": "ansi"}), 0)
        self.assertEqual(L.canvas_columns({"original": "original.ans", "format": "ascii"}), 0)

    def test_normalize_records_the_canvas_width(self):
        norm = L.normalize(b"\x1b[31mhello\r\n", "x.ans")
        self.assertEqual(norm.meta["columns"], 80)
        self.assertEqual(L.canvas_columns(norm.meta), 80)
        norm = L.normalize(b"plain\r\n", "x.txt")
        self.assertEqual(norm.meta["columns"], 0)


class AnimationHeuristicTests(unittest.TestCase):
    def test_leading_clear_is_static(self):
        text = ESC + "[2J" + ESC + "[31m" + "\r\n".join("art" for _ in range(3))
        _, stats = grid_of(text, 80)
        self.assertEqual(stats["clears"], 0)
        self.assertEqual(L.classify(None, stats, "cp437", True), "ansi")

    def test_clear_after_painting_is_animation(self):
        text = ESC + "[31mframe one\r\n" + ESC + "[2J" + "frame two\r\n"
        _, stats = grid_of(text, 80)
        self.assertEqual(stats["clears"], 1)
        self.assertEqual(L.classify(None, stats, "cp437", True), "ansimation")


if __name__ == "__main__":
    unittest.main()
