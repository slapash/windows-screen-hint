import importlib.util
import pathlib
import sys
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "tools" / "click_watch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("click_watch", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ClickWatchGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_inside(self):
        watch = self.module.ClickWatch(100, 100, 50, 50)
        self.assertTrue(watch._in_target(120, 120))

    def test_edge_right_inclusive(self):
        watch = self.module.ClickWatch(100, 100, 50, 50)
        self.assertTrue(watch._in_target(150, 125))

    def test_edge_bottom_inclusive(self):
        watch = self.module.ClickWatch(100, 100, 50, 50)
        self.assertTrue(watch._in_target(125, 150))

    def test_outside_left(self):
        watch = self.module.ClickWatch(100, 100, 50, 50)
        self.assertFalse(watch._in_target(99, 125))

    def test_outside_top(self):
        watch = self.module.ClickWatch(100, 100, 50, 50)
        self.assertFalse(watch._in_target(125, 99))

    def test_negative_coordinates_supported(self):
        watch = self.module.ClickWatch(-200, -100, 50, 50)
        self.assertTrue(watch._in_target(-180, -80))
        self.assertFalse(watch._in_target(-140, -80))


class ClickWatchCliTests(unittest.TestCase):
    def test_missing_y_rejected(self):
        import subprocess
        import sys as _sys

        r = subprocess.run(
            [_sys.executable, str(MODULE_PATH), "--x", "10"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r.returncode, 2)
        self.assertIn("--y", r.stderr)

    def test_tiny_timeout_rejected(self):
        import subprocess
        import sys as _sys

        r = subprocess.run(
            [_sys.executable, str(MODULE_PATH), "--x", "10", "--y", "10",
             "--timeout-ms", "50"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r.returncode, 2)
        self.assertIn("timeout", r.stderr)

    def test_no_target_rejected(self):
        import subprocess
        import sys as _sys

        r = subprocess.run(
            [_sys.executable, str(MODULE_PATH), "--timeout-ms", "1000"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
