"""ttfx command lines (stdlib unittest). Run: python3 -B -m unittest discover -s tests"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.dont_write_bytecode = True

from ansisaver import effects  # noqa: E402
from ansisaver.theme import Theme  # noqa: E402


def mode_of(effect, color_mode):
    argv = effects.build_argv(effect, "/tmp/x.ans", 80, 25, theme=Theme({}), seed=1, color_mode=color_mode)
    return argv[argv.index("--existing-color-handling") + 1]


class ColourModeTests(unittest.TestCase):
    def test_colour_only_effects_always_animate(self):
        # with the art's colours forced for the whole run these effects show the final frame from the start
        for e in effects.COLOR_ONLY:
            self.assertIn(e, effects.TABLE, e)
            self.assertEqual(mode_of(e, "always"), "dynamic", e)
            self.assertEqual(mode_of(e, "dynamic"), "dynamic", e)

    def test_spatial_effects_follow_the_setting(self):
        for e in ("slide", "wipe", "expand", "scattered"):
            self.assertEqual(mode_of(e, "always"), "always", e)
            self.assertEqual(mode_of(e, "dynamic"), effects.TABLE[e][1], e)


if __name__ == "__main__":
    unittest.main()
