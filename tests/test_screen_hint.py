import importlib.util
import pathlib
import sys
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "tools" / "screen_hint.py"


def load_module():
    spec = importlib.util.spec_from_file_location("screen_hint", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ScreenHintArgumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_rect_parses_geometry_label_and_duration(self):
        hint = self.module.parse_cli(
            ["rect", "131", "457", "77", "51", "--label", "Clique ici", "--duration-ms", "2500"]
        )
        self.assertEqual(hint.kind, "rect")
        self.assertEqual((hint.x, hint.y, hint.width, hint.height), (131, 457, 77, 51))
        self.assertEqual(hint.label, "Clique ici")
        self.assertEqual(hint.duration_ms, 2500)

    def test_ring_requires_positive_diameter(self):
        with self.assertRaisesRegex(ValueError, "diameter"):
            self.module.parse_cli(["ring", "100", "100", "--diameter", "0"])

    def test_duration_is_limited_to_ten_seconds(self):
        with self.assertRaisesRegex(ValueError, "duration"):
            self.module.parse_cli(["cursor", "100", "100", "--duration-ms", "10001"])

    def test_default_duration_is_short_and_valid(self):
        hint = self.module.parse_cli(["cursor", "100", "100"])
        self.assertGreaterEqual(hint.duration_ms, 100)
        self.assertLessEqual(hint.duration_ms, 10_000)

    def test_rect_must_intersect_virtual_desktop(self):
        hint = self.module.parse_cli(["rect", "2500", "2500", "50", "50"])
        with self.assertRaisesRegex(ValueError, "virtual desktop"):
            self.module.validate_against_desktop(hint, (0, 0, 1920, 1080))

    def test_negative_coordinates_are_valid_on_left_hand_monitor(self):
        hint = self.module.parse_cli(["rect", "-100", "20", "50", "50"])
        self.module.validate_against_desktop(hint, (-1920, 0, 3840, 1080))

    def test_hit_test_and_mouse_activation_are_noninteractive(self):
        self.assertEqual(self.module.overlay_message_result(self.module.WM_NCHITTEST), self.module.HTTRANSPARENT)
        self.assertEqual(self.module.overlay_message_result(self.module.WM_MOUSEACTIVATE), self.module.MA_NOACTIVATE)
        self.assertIsNone(self.module.overlay_message_result(0x000F))

    def test_steps_parses_multiple_rects_and_labels(self):
        hint = self.module.parse_cli(
            [
                "steps",
                "--rect", "131", "457", "77", "51",
                "--label", "1/4  Click 2",
                "--rect", "288", "457", "76", "51",
                "--label", "2/4  Click +",
                "--duration-ms", "8000",
            ]
        )
        self.assertEqual(hint.kind, "steps")
        self.assertEqual(len(hint.items), 2)
        self.assertEqual(hint.items[0], (131, 457, 77, 51, "1/4  Click 2"))
        self.assertEqual(hint.items[1], (288, 457, 76, 51, "2/4  Click +"))
        self.assertEqual(hint.duration_ms, 8000)

    def test_steps_label_count_must_match_rect_count(self):
        with self.assertRaisesRegex(ValueError, "label"):
            self.module.parse_cli(
                [
                    "steps",
                    "--rect", "131", "457", "77", "51",
                    "--rect", "288", "457", "76", "51",
                    "--label", "1/2  Click 2",
                ]
            )

    def test_steps_labels_pad_with_empty_strings(self):
        hint = self.module.parse_cli(
            [
                "steps",
                "--rect", "131", "457", "77", "51",
                "--rect", "288", "457", "76", "51",
            ]
        )
        self.assertEqual(hint.items[0], (131, 457, 77, 51, ""))
        self.assertEqual(hint.items[1], (288, 457, 76, 51, ""))

    def test_steps_bounds_span_all_rects(self):
        hint = self.module.parse_cli(
            [
                "steps",
                "--rect", "131", "457", "77", "51",
                "--rect", "288", "457", "76", "51",
            ]
        )
        x, y, w, h = self.module.hint_bounds(hint)
        self.assertEqual((x, y, w, h), (131, 457, 233, 51))

    def test_steps_must_intersect_virtual_desktop(self):
        hint = self.module.parse_cli(
            [
                "steps",
                "--rect", "3000", "3000", "50", "50",
            ]
        )
        with self.assertRaisesRegex(ValueError, "virtual desktop"):
            self.module.validate_against_desktop(hint, (0, 0, 1920, 1080))


if __name__ == "__main__":
    unittest.main()
