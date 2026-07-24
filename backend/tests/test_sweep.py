"""Tests for the benchmark sweep SVG renderer.

`collect` is pure network I/O (it needs a live server on a specific build), so it is
structured around an injectable fetch callable but left untested here; only the pure
`render` path is covered.
"""

import unittest
import xml.etree.ElementTree as ET

from scripts.sweep import (
    MARGIN_LEFT,
    PLOT_W,
    WORKERS_MAX,
    WORKERS_MIN,
    axis_max,
    render_svg,
    x_for_workers,
    y_for_seconds,
    y_ticks,
)

SVG_NS = "{http://www.w3.org/2000/svg}"


def fake_run(*, gil, seq, threads, interp):
    return {
        "gil_enabled": gil,
        "n": 200000,
        "python": "3.14.6",
        "points": [
            {"workers": w, "sequential": seq, "threads": threads, "interpreters": interp}
            for w in range(WORKERS_MIN, WORKERS_MAX + 1)
        ],
    }


class ScalingTests(unittest.TestCase):
    def test_x_maps_endpoints(self):
        self.assertEqual(x_for_workers(WORKERS_MIN), MARGIN_LEFT)
        self.assertEqual(x_for_workers(WORKERS_MAX), MARGIN_LEFT + PLOT_W)

    def test_y_inverts_axis(self):
        self.assertLess(y_for_seconds(10.0, 10.0), y_for_seconds(0.0, 10.0))

    def test_y_ticks_land_on_integers(self):
        # Whole-number gridlines, top tick == y_max, roughly 4-7 ticks.
        self.assertEqual(y_ticks(12.0), [0, 2, 4, 6, 8, 10, 12])
        self.assertEqual(y_ticks(10.0), [0, 2, 4, 6, 8, 10])
        self.assertEqual(y_ticks(4.0), [0, 1, 2, 3, 4])

    def test_axis_max_hugs_data(self):
        # Smallest multiple of 2 that clears data * 1.05 (min 2).
        self.assertEqual(axis_max(10.234), 12.0)  # real-run max ~10.2s -> 12, not 20
        self.assertEqual(axis_max(8.0), 10.0)  # 8.4 -> 10 (coordinate test unaffected)
        self.assertEqual(axis_max(2.0), 4.0)
        self.assertEqual(axis_max(0.0), 2.0)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.gil = fake_run(gil=True, seq=8000, threads=7000, interp=2000)
        self.ft = fake_run(gil=False, seq=9000, threads=2000, interp=2500)
        self.svg = render_svg(self.gil, self.ft)

    def test_well_formed_xml(self):
        root = ET.fromstring(self.svg)
        self.assertEqual(root.tag, f"{SVG_NS}svg")

    def test_five_data_polylines(self):
        root = ET.fromstring(self.svg)
        self.assertEqual(len(root.findall(f".//{SVG_NS}polyline")), 5)

    def test_hand_calculated_coordinates(self):
        # max plotted value is GIL sequential 8000 ms -> 8.0 s; axis_max(8.0) = 10.0.
        # y_for_seconds(v, 10) = 476 - (v/10)*412; x_for_workers(1) = 70.0.
        # GIL sequential (8.0 s) at w=1 -> 476 - 0.8*412 = 146.4
        self.assertIn("70.0,146.4", self.svg)
        # GIL threads (7.0 s) at w=1 -> 476 - 0.7*412 = 187.6
        self.assertIn("70.0,187.6", self.svg)

    def test_expected_texts(self):
        for text in (
            "Time to run W copies of the same CPU-bound task (n=200000)",
            "workers",
            "seconds",
            "sequential (reference)",
            "threads (GIL)",
            "interpreters (GIL)",
            "threads (free-threaded)",
            "interpreters (free-threaded)",
        ):
            self.assertIn(text, self.svg)

    def test_no_em_dash(self):
        self.assertNotIn("\u2014", self.svg)  # em dash codepoint, written escaped


class SpeedupRenderTests(unittest.TestCase):
    def setUp(self):
        # speedup = sequential / mode. threads 8000/1000 = 8.0x (the max) -> axis_max 10.
        self.gil = fake_run(gil=True, seq=8000, threads=1000, interp=2000)
        self.ft = fake_run(gil=False, seq=8000, threads=1000, interp=2500)
        self.svg = render_svg(self.gil, self.ft, mode="speedup")

    def test_five_data_polylines(self):
        root = ET.fromstring(self.svg)
        self.assertEqual(len(root.findall(f".//{SVG_NS}polyline")), 5)

    def test_reference_is_flat_at_1x(self):
        # 1.0x on axis_max(8.0)=10 -> y = 476 - (1/10)*412 = 434.8, at every worker.
        self.assertIn("70.0,434.8", self.svg)
        self.assertIn("710.0,434.8", self.svg)

    def test_hand_calculated_speedup(self):
        # threads (GIL) 8000/1000 = 8.0x at w=1 -> x=70.0, y=476-(8/10)*412=146.4
        self.assertIn("70.0,146.4", self.svg)

    def test_speedup_labels(self):
        for text in (
            "Speedup vs sequential, W copies of the same CPU-bound task (n=200000), higher is better",
            "speedup (x)",
        ):
            self.assertIn(text, self.svg)


class IoRenderTests(unittest.TestCase):
    def _io_run(self, gil):
        return {
            "gil_enabled": gil, "task": "io", "delay_ms": 50, "python": "3.14.6",
            "points": [
                {"workers": w, "sequential": 400, "threads": 60, "interpreters": 90}
                for w in range(WORKERS_MIN, WORKERS_MAX + 1)
            ],
        }

    def test_title_reflects_io_task(self):
        svg = render_svg(self._io_run(True), self._io_run(False))
        self.assertIn("I/O-bound task (HTTP, delay=50ms)", svg)

    def test_speedup_title_reflects_io_task(self):
        svg = render_svg(self._io_run(True), self._io_run(False), mode="speedup")
        self.assertIn(
            "Speedup vs sequential, W copies of the same I/O-bound task (HTTP, delay=50ms), "
            "higher is better",
            svg,
        )


if __name__ == "__main__":
    unittest.main()
