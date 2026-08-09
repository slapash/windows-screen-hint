import importlib.util
import pathlib
import sys
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "tools" / "uia_probe.py"


def load_module():
    spec = importlib.util.spec_from_file_location("uia_probe", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class UiaProbeScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_exact_label_scores_one(self):
        self.assertEqual(self.module._score("Save", "Save"), 1.0)

    def test_case_insensitive_exact(self):
        self.assertEqual(self.module._score("save", "Save"), 1.0)

    def test_query_contained_in_label(self):
        self.assertGreater(self.module._score("novo", "Novo documento"), 0.8)

    def test_label_contained_in_query(self):
        self.assertGreater(self.module._score("Save As", "Save"), 0.7)

    def test_token_overlap_scores_positive(self):
        self.assertGreater(self.module._score("save file", "File Save"), 0.0)

    def test_unrelated_scores_zero(self):
        self.assertEqual(self.module._score("bluetooth", "Memory"), 0.0)

    def test_empty_label_scores_zero(self):
        self.assertEqual(self.module._score("save", ""), 0.0)


class UiaProbeTraversalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_descendant_walk_is_depth_first_and_bounded(self):
        root, a, a1, b = object(), object(), object(), object()

        class Walker:
            children = {root: a, a: a1, a1: None, b: None}
            siblings = {a: b, a1: None, b: None}

            def GetFirstChildElement(self, node):
                return self.children.get(node)

            def GetNextSiblingElement(self, node):
                return self.siblings.get(node)

        self.assertEqual(
            list(self.module._walk_descendants(Walker(), root, max_nodes=2)),
            [a, a1],
        )


class UiaProbeFuzzyFindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def _element(self, index, label):
        return self.module.Element(index=index, role="Button", label=label)

    def test_find_returns_top_scoring_first(self):
        elements = [
            self._element(1, "Result"),
            self._element(2, "2"),
            self._element(3, "Memory"),
        ]
        matches = self.module.fuzzy_find(elements, "2", top=5)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][1].index, 2)

    def test_find_respects_top_limit(self):
        elements = [self._element(i, f"Item {i}") for i in range(20)]
        matches = self.module.fuzzy_find(elements, "item", top=3)
        self.assertLessEqual(len(matches), 3)

    def test_find_excludes_zero_scores(self):
        elements = [self._element(1, "Save"), self._element(2, "Close")]
        matches = self.module.fuzzy_find(elements, "export", top=5)
        self.assertEqual(len(matches), 0)


class UiaProbeWindowSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_app_matches_process_name(self):
        windows = [
            (100, "Untitled", 2000),
            (200, "Calculator", 3000),
        ]
        hwnd, title, pid = self.module.select_window(
            app="calc", pid=None, title=None, _windows=windows, _process_name=lambda p: "win32calc.exe"
        )
        self.assertEqual(hwnd, 200)

    def test_app_matches_window_title(self):
        windows = [
            (100, "Untitled", 2000),
            (200, "Calculator", 3000),
        ]
        hwnd, title, pid = self.module.select_window(
            app="calculator", pid=None, title=None, _windows=windows, _process_name=lambda p: "unknown.exe"
        )
        self.assertEqual(hwnd, 200)

    def test_pid_selects_exact_window(self):
        windows = [(100, "A", 2000), (200, "B", 3000)]
        hwnd, _, _ = self.module.select_window(
            app=None, pid=3000, title=None, _windows=windows, _process_name=lambda p: "x.exe"
        )
        self.assertEqual(hwnd, 200)

    def test_title_containment(self):
        windows = [(100, "Settings", 2000), (200, "Downloads", 3000)]
        hwnd, _, _ = self.module.select_window(
            app=None, pid=None, title="load", _windows=windows, _process_name=lambda p: "x.exe"
        )
        self.assertEqual(hwnd, 200)

    def test_no_match_raises(self):
        windows = [(100, "Settings", 2000)]
        with self.assertRaisesRegex(RuntimeError, "no visible window"):
            self.module.select_window(
                app=None, pid=9999, title=None, _windows=windows, _process_name=lambda p: "x.exe"
            )


if __name__ == "__main__":
    unittest.main()
