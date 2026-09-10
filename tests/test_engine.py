"""Engine unit tests (stdlib unittest). Run: python3 -B -m unittest discover -s tests"""
from __future__ import annotations

import os
import random
import shutil
import struct
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.dont_write_bytecode = True

from ansisaver import ansi, grid as G, palette, sauce as S, sizing, transitions  # noqa: E402
from ansisaver.ansi import BLANK  # noqa: E402

ESC = "\x1b"


def sauce_record(title="T", author="A", group="G", date="20200101", datatype=1, filetype=1, tinfo1=80, tinfo2=25, flags=0, tinfos="IBM VGA"):
    return struct.pack("<5s2s35s20s20s8sLBBHHHHBB22s", b"SAUCE", b"00", title.encode().ljust(35), author.encode().ljust(20),
                       group.encode().ljust(20), date.encode(), 0, datatype, filetype, tinfo1, tinfo2, 0, 0, 0, flags, tinfos.encode().ljust(22, b"\0"))


class SauceTests(unittest.TestCase):
    def test_parse_and_strip(self):
        body = b"hello\x1a"
        data = body + sauce_record(title="Hi", flags=1)
        out, sc = S.parse(data)
        self.assertEqual(out, b"hello")
        self.assertEqual(sc.title, "Hi")
        self.assertTrue(sc.ice)
        self.assertEqual(sc.columns, 80)
        self.assertEqual(sc.year, 2020)

    def test_comments(self):
        data = b"x" + b"COMNT" + b"first".ljust(64) + sauce_record()
        data = data[:-128] + sauce_record()[:104] + bytes([1]) + sauce_record()[105:]
        out, sc = S.parse(data)
        self.assertEqual(sc.comments, ["first"])
        self.assertEqual(out, b"x")

    def test_no_sauce(self):
        out, sc = S.parse(b"plain")
        self.assertIsNone(sc)
        self.assertEqual(out, b"plain")


class InterpreterTests(unittest.TestCase):
    def cells(self, text, **kw):
        g, st = ansi.interpret(text, **kw)
        return g, st

    def test_colors_and_bright(self):
        g, _ = self.cells(f"{ESC}[1;31mA{ESC}[0m{ESC}[44m {ESC}[0m")
        self.assertEqual(g.cell(0, 0), ("A", palette.VGA16[9], None))
        self.assertEqual(g.cell(1, 0), (" ", palette.VGA16[7], palette.VGA16[4]))

    def test_ice_colors(self):
        g, _ = self.cells(f"{ESC}[5;44mX", ice=True)
        self.assertEqual(g.cell(0, 0)[2], palette.VGA16[12])
        g, _ = self.cells(f"{ESC}[5;44mX", ice=False)
        self.assertEqual(g.cell(0, 0)[2], palette.VGA16[4])

    def test_cursor_moves_and_transparency(self):
        g, st = self.cells(f"AB{ESC}[5CX{ESC}[2;3HY{ESC}[s{ESC}[u")
        self.assertEqual(g.cell(0, 0)[0], "A")
        self.assertEqual(g.cell(7, 0)[0], "X")
        self.assertEqual(g.cell(2, 1)[0], "Y")
        self.assertEqual(g.cell(3, 0), BLANK)

    def test_immediate_wrap(self):
        line = "x" * 80
        g, st = self.cells(line + "\r\n" + "y")
        # 80 chars wrap immediately -> CRLF then produces an empty row
        self.assertEqual(g.cell(79, 0)[0], "x")
        self.assertEqual(g.cell(0, 2)[0], "y")
        g2, _ = self.cells(line + "\r\n" + "y", wrap="pending")
        self.assertEqual(g2.cell(0, 1)[0], "y")

    def test_truecolor_and_pablo(self):
        g, _ = self.cells(f"{ESC}[38;2;1;2;3m{ESC}[48;5;196mA{ESC}[0;100;101;5tB")
        self.assertEqual(g.cell(0, 0)[1], palette.rgb(1, 2, 3))
        self.assertEqual(g.cell(0, 0)[2], palette.xterm256(196))
        self.assertEqual(g.cell(1, 0)[2], palette.rgb(100, 101, 5))

    def test_erase_line_bce(self):
        g, _ = self.cells(f"{ESC}[42m{ESC}[K{ESC}[0mZ")
        self.assertEqual(g.cell(5, 0)[2], palette.VGA16[2])

    def test_unknown_and_sub(self):
        g, st = self.cells(f"A{ESC}[?7h{ESC}[99zB\x1aGARBAGE")
        self.assertEqual(g.cell(1, 0)[0], "B")
        self.assertEqual(g.cell(2, 0), BLANK)
        self.assertEqual(st["unknown_csi"], 1)

    def test_cp437_glyphs(self):
        text = ansi.decode(bytes([0x01, 0x03, 0xB0, 0xDB, 0x7F]), "cp437")
        self.assertEqual(text, "☺♥░█⌂")

    def test_encoding_detection(self):
        self.assertEqual(ansi.detect_encoding(b"plain"), "cp437")
        self.assertEqual(ansi.detect_encoding("█".encode()), "utf8")
        self.assertEqual(ansi.detect_encoding(bytes([0xDB, 0xB0])), "cp437")
        sc = S.parse(b"x" + sauce_record(tinfos="Amiga Topaz 1+"))[1]
        self.assertEqual(ansi.detect_encoding(b"x", sc), "latin1")


class GridTests(unittest.TestCase):
    def test_roundtrip_and_no_bold(self):
        g, _ = ansi.interpret(f"{ESC}[1;33;44mA{ESC}[7m {ESC}[0m  {ESC}[31mB{ESC}[0m   ")
        flat = G.grid_to_flat(g)
        self.assertNotIn("[1m", flat)
        self.assertNotIn("[7m", flat)
        self.assertNotIn("[5m", flat)
        back = G.read_flat(flat)
        for y in range(g.height):
            for x in range(g.painted_width(y)):
                a, b = g.cell(x, y), back.cell(x, y)
                self.assertEqual((a[0], a[2]), (b[0], b[2]))
                if a[0] != " ":
                    self.assertEqual(a[1], b[1])  # fg is invisible on spaces
        self.assertTrue(flat.rstrip("\n").endswith(f"{ESC}[0m"))

    def test_trailing_trim_keeps_bg_spaces(self):
        g, _ = ansi.interpret(f"A{ESC}[44m {ESC}[0m   ")
        self.assertEqual(g.painted_width(0), 2)

    def test_compose_offsets(self):
        g, _ = ansi.interpret("AB\nCD")
        f = G.compose(g, 10, 5, x_off=3, y_off=1)
        self.assertEqual(f[1][3][0], "A")
        self.assertEqual(f[2][4][0], "D")
        self.assertEqual(f[0][0], BLANK)


class TransitionTests(unittest.TestCase):
    def test_all_end_black(self):
        g, _ = ansi.interpret(f"{ESC}[44m  {ESC}[31m██\n{ESC}[0m▄▀░▒▓")
        frame = G.compose(g, 12, 6, 2, 1)
        for name, gen in transitions.GENERATORS.items():
            frames = list(gen(frame, random.Random(1), 30))
            self.assertTrue(frames, name)
            last = frames[-1]
            self.assertTrue(all(c == BLANK for row in last for c in row), name)
            self.assertTrue(all(len(row) == 12 for f in frames for row in f), name)


class SizingTests(unittest.TestCase):
    def test_model_prediction(self):
        mon = {"name": "eDP-1", "width": 2880, "height": 1920, "scale": 1.6, "transform": 0}
        font = {"kind": "vga", "families": ["Px437 IBM VGA 8x16"], "adjust": None, "metrics": sizing.METRICS["vga"]}
        p = sizing.plan_monitor(mon, 80, font, calibration={}, text_scale=1.0)
        self.assertEqual(p["predicted_cols"], 80)
        self.assertGreaterEqual(p["predicted_rows"], 25)
        cal = {"eDP-1|vga": {"pt": 20.0, "cols": 60, "rows": 20}}
        p2 = sizing.plan_monitor(mon, 80, font, calibration=cal, text_scale=1.0)
        self.assertEqual(p2["sizing"], "calibrated")
        self.assertLess(p2["font_pt"], 20.0)
        self.assertGreaterEqual(p2["predicted_cols"], 80)


@unittest.skipUnless(shutil.which("ttfx"), "ttfx not installed")
class TtfxGoldenTests(unittest.TestCase):
    def test_final_frame_matches(self):
        text = "\n" + f"  {ESC}[1;36m╔══╗{ESC}[0m\n  {ESC}[44m  {ESC}[0m{ESC}[33m▓▒░{ESC}[0m\n" + f"{ESC}[42m{ESC}[K{ESC}[0m"
        g, _ = ansi.interpret(text)
        rows = [list(r) for r in g.rows]
        rows[0] = [(".", 0, None)] + rows[0][1:] if rows[0] else [(".", 0, None)]
        flat = G.grid_to_flat(G.Grid(cols=g.cols, rows=rows))
        W, H = max(g.painted_cols, 1), g.height
        r = subprocess.run(["ttfx", "--seed", "1", "--ignore-terminal-dimensions", "--canvas-width", str(W), "--canvas-height", str(H),
                            "--anchor-canvas", "nw", "--anchor-text", "nw", "--existing-color-handling", "always", "--no-eol",
                            "--no-restore-cursor", "--virtual-clock", "--frame-rate", "1000", "wipe"], input=flat.encode(), capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        back = G.read_flat(r.stdout.rsplit(b"\x1b7", 1)[-1].decode("utf-8", "replace"))
        for y in range(1, g.height):
            for x in range(g.painted_width(y)):
                a, b = g.cell(x, y), back.cell(x, y)
                if a[0] == " " and b[0] == " " and a[2] == b[2]:
                    continue
                self.assertEqual((a[0], a[2]), (b[0], b[2]), (x, y))
                if a[0] != " ":
                    self.assertEqual(a[1], b[1], (x, y))


if __name__ == "__main__":
    unittest.main()
