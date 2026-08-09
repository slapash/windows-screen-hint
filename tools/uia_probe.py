"""UIA probe — discover Windows UI Automation elements for guided tutoring.

The "eyes" half of the tutor: given a target window (by app name, PID, or
window title), list its UI Automation elements with role, label, and physical
screen bounds as JSON, or fuzzy-find one element by label.

Designed for agent consumption: JSON on stdout, exit 0 on success, exit 2 on
usage/runtime failure (same convention as screen_hint.py). Never injects
input — this tool only observes the accessibility tree.

Requirements:
  pip install comtypes

Usage:
  python tools/uia_probe.py --app "Calculator" --list
  python tools/uia_probe.py --app "Notepad" --find "Save" --top 5
  python tools/uia_probe.py --pid 1234 --role "Button" --find "novo" --pretty
  python tools/uia_probe.py --title "Settings" --find "bluetooth"

Selection (at most one of --app / --pid / --title; default: foreground window):
  --app NAME     match the window whose owning process name contains NAME
                 (case-insensitive, e.g. "notepad", "Calculator")
  --pid N        match the top-level window owned by PID N
  --title TEXT   match the window whose title contains TEXT

Filters:
  --list         dump all elements (capped by --max)
  --find TEXT    fuzzy-match elements by accessible name; best scores first
  --role ROLE    only elements whose control-type role equals ROLE
                 (e.g. Button, Edit, MenuItem, TabItem, CheckBox, ...)
  --top N        max results for --find (default 10)
  --max N        max elements dumped for --list (default 500)
  --include-empty  keep elements with (0,0,0,0) bounds (default: dropped)
  --pretty       pretty-print the JSON
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── Control-type IDs (UIA) → friendly role names ─────────────────────────
CONTROL_TYPES: Dict[int, str] = {
    50000: "Button",
    50001: "Calendar",
    50002: "CheckBox",
    50003: "ComboBox",
    50004: "Edit",
    50005: "Hyperlink",
    50006: "Image",
    50007: "ListItem",
    50008: "List",
    50009: "Menu",
    50010: "MenuBar",
    50011: "MenuItem",
    50012: "ProgressBar",
    50013: "RadioButton",
    50014: "ScrollBar",
    50015: "Slider",
    50016: "Spinner",
    50017: "StatusBar",
    50018: "Tab",
    50019: "TabItem",
    50020: "Text",
    50021: "ToolBar",
    50022: "ToolTip",
    50023: "Tree",
    50024: "TreeItem",
    50025: "Custom",
    50026: "Group",
    50027: "Thumb",
    50028: "DataGrid",
    50029: "DataItem",
    50030: "Document",
    50031: "SplitButton",
    50032: "Window",
    50033: "Pane",
    50034: "Header",
    50035: "HeaderItem",
    50036: "Table",
    50037: "TitleBar",
    50038: "Separator",
    50039: "SemanticZoom",
    50040: "AppBar",
}

ROLE_TO_ID = {name: cid for cid, name in CONTROL_TYPES.items()}

# Interesting roles for tutoring; others still appear but --list keeps them all.
DWMWA_CLOAKED = 14


@dataclass
class Element:
    index: int
    role: str
    label: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    pid: int = 0
    window_id: int = 0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "role": self.role,
            "label": self.label,
            "bounds": [self.x, self.y, self.width, self.height],
            "pid": self.pid,
            "window_id": self.window_id,
            **self.attributes,
        }


# ── Native window discovery ──────────────────────────────────────────────
def _enum_windows() -> List[Tuple[int, str, int]]:
    """Return [(hwnd, title, pid)] for visible, non-cloaked top-level windows."""
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    results: List[Tuple[int, str, int]] = []
    title_buf = ctypes.create_unicode_buffer(512)
    pid_ref = wintypes.DWORD()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        # Skip cloaked windows (UWP background frames, ghosted UWP shells).
        cloaked = wintypes.DWORD()
        try:
            hr = dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
            )
            if hr == 0 and cloaked.value:
                return True
        except (AttributeError, OSError):
            pass
        length = user32.GetWindowTextW(hwnd, title_buf, 512)
        title = title_buf.value[:length] if length else ""
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_ref))
        results.append((int(hwnd), title, int(pid_ref.value)))
        return True

    user32.EnumWindows(_cb, 0)
    return results


def select_window(
    app: Optional[str] = None,
    pid: Optional[int] = None,
    title: Optional[str] = None,
    *,
    _windows: Optional[List[Tuple[int, str, int]]] = None,
    _process_name: Any = None,
) -> Tuple[int, str, int]:
    """Return (hwnd, title, pid) of the best matching window or raise.

    ``_windows`` / ``_process_name`` are test seams; callers never pass them.
    """
    windows = _windows if _windows is not None else _enum_windows()
    proc_name = _process_name or _process_name_impl
    if not windows:
        raise RuntimeError("no visible windows found")

    if pid is not None:
        matches = [(h, t, p) for (h, t, p) in windows if p == pid]
        if not matches:
            raise RuntimeError(f"no visible window with PID {pid}")
        return matches[0]

    if app is not None:
        needle = app.lower()
        scored = []
        for h, t, p in windows:
            name = proc_name(p).lower()
            if needle in name or needle in t.lower():
                scored.append((_rank(name, needle), _rank(t.lower(), needle), h, t, p))
        if not scored:
            raise RuntimeError(f"no visible window for app name {app!r}")
        scored.sort(key=lambda item: (item[0], item[1], -item[2]))
        return scored[0][2], scored[0][3], scored[0][4]

    if title is not None:
        needle = title.lower()
        for h, t, p in windows:
            if needle in t.lower():
                return h, t, p
        raise RuntimeError(f"no visible window with title containing {title!r}")

    # Foreground window default.
    user32 = ctypes.windll.user32
    fg = int(user32.GetForegroundWindow())
    if fg:
        for h, t, p in windows:
            if h == fg:
                return h, t, p
    # Fall back to the most recently used (first in EnumWindows order).
    return windows[0]


def _process_name_impl(pid: int) -> str:
    import os

    try:
        import psutil  # optional; falls back to toolhelp below

        return psutil.Process(pid).name()
    except Exception:
        pass
    try:
        # Toolhelp32 snapshot without psutil.
        import ctypes.wintypes as wt

        kernel32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return f"pid{pid}"
        try:
            from ctypes import wintypes

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260),
                ]

            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
                while True:
                    if entry.th32ProcessID == pid:
                        return entry.szExeFile
                    if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        pass
    return f"pid{pid}"


def _rank(candidate: str, needle: str) -> int:
    """Rough ordering score: exact prefix is best, then containment position."""
    pos = candidate.find(needle)
    if pos < 0:
        return 10_000
    return pos


# ── UIA traversal ─────────────────────────────────────────────────────────
def _uia():
    """Return (IUIAutomation, UIAutomationClient module).

    Generates COM typelib bindings on first use. The CUIAutomation coclass
    does not expose the primary interface through comtypes directly, so we
    CoCreateInstance with the documented CLSID and an explicit interface.
    """
    import comtypes
    import comtypes.client

    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA

    # CUIAutomation CLSID: {ff48dba4-60ef-4201-aa87-54103eef594e}
    clsid = comtypes.GUID("{ff48dba4-60ef-4201-aa87-54103eef594e}")
    automation = comtypes.CoCreateInstance(clsid, interface=UIA.IUIAutomation)
    return automation, UIA


def _role_of(control_type: int) -> str:
    return CONTROL_TYPES.get(control_type, f"Type{control_type}")


def _rect_of(com_rect) -> Tuple[int, int, int, int]:
    """UIA bounding rectangle (tagRECT) → (x, y, w, h) in physical screen px."""
    try:
        left = int(com_rect.left)
        top = int(com_rect.top)
        right = int(com_rect.right)
        bottom = int(com_rect.bottom)
    except Exception:
        return 0, 0, 0, 0
    return left, top, max(0, right - left), max(0, bottom - top)


def _walk_descendants(walker, root, max_nodes: int):
    """Yield at most ``max_nodes`` descendants without materializing the tree.

    UIA's FindAll(TreeScope_Descendants, ...) builds the full descendant
    collection before the caller can enforce its limit.  An explicit stack
    keeps probing bounded for large accessibility trees.
    """
    first = walker.GetFirstChildElement(root)
    if first is None:
        return
    pending = [first]
    visited = 0
    while pending and visited < max_nodes:
        node = pending.pop()
        visited += 1
        sibling = walker.GetNextSiblingElement(node)
        child = walker.GetFirstChildElement(node)
        # Stack is LIFO: sibling first preserves a depth-first UI order.
        if sibling is not None:
            pending.append(sibling)
        if child is not None:
            pending.append(child)
        yield node


def probe_window(
    hwnd: int,
    *,
    role_filter: Optional[str] = None,
    max_elements: int = 500,
    include_empty: bool = False,
) -> List[Element]:
    automation, UIA = _uia()
    root = automation.ElementFromHandle(ctypes.c_void_p(hwnd))
    if root is None:
        raise RuntimeError(f"UIA: no element for window {hwnd}")

    if max_elements <= 0:
        return []
    walker = automation.CreateTreeWalker(automation.CreateTrueCondition())

    elements: List[Element] = []
    role_id = ROLE_TO_ID.get(role_filter) if role_filter else None

    for node in _walk_descendants(walker, root, max_elements):
        try:
            name = node.CurrentName or ""
            ctype = int(node.CurrentControlType)
            rect = node.CurrentBoundingRectangle
            x, y, w, h = _rect_of(rect)
            proc_id = int(node.CurrentProcessId or 0)
        except Exception:
            continue

        role = _role_of(ctype)
        if role_filter is not None:
            if role_id is not None:
                if ctype != role_id:
                    continue
            elif role_filter.lower() not in role.lower():
                continue

        if not include_empty and (w <= 0 or h <= 0):
            continue

        elements.append(
            Element(
                index=len(elements) + 1,
                role=role,
                label=name,
                x=x,
                y=y,
                width=w,
                height=h,
                pid=proc_id,
                window_id=hwnd,
            )
        )
    return elements


# ── Fuzzy label matching ──────────────────────────────────────────────────
def _score(query: str, label: str) -> float:
    q = query.strip().lower()
    c = label.strip().lower()
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c:
        return 0.9
    if c in q:
        return 0.8
    qt = set(q.split())
    ct = set(c.split())
    inter = len(qt & ct)
    union = len(qt | ct)
    if inter and union:
        return 0.3 + 0.4 * (inter / union)
    return 0.0


def fuzzy_find(
    elements: List[Element], query: str, top: int = 10
) -> List[Tuple[float, Element]]:
    scored = [(_score(query, e.label), e) for e in elements]
    scored.sort(key=lambda pair: (-pair[0], pair[1].index))
    return [(s, e) for s, e in scored if s > 0.0][:top]


def _enable_per_monitor_dpi_awareness() -> None:
    """Opt into per-monitor DPI awareness so UIA rects are physical pixels."""
    if os.name != "nt":
        raise RuntimeError("uia_probe is Windows-only")
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        user32.SetProcessDPIAware()


# ── CLI ───────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover Windows UI Automation elements (observe only; never clicks)."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--app", help="window whose process name contains APP")
    target.add_argument("--pid", type=int, help="window owned by PID")
    target.add_argument("--title", help="window whose title contains TITLE")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="dump all elements")
    mode.add_argument("--find", metavar="TEXT", help="fuzzy-find by accessible name")

    parser.add_argument("--role", help="filter by control-type role (e.g. Button)")
    parser.add_argument("--top", type=int, default=10, help="max --find results")
    parser.add_argument("--max", type=int, default=500, help="max --list elements")
    parser.add_argument("--include-empty", action="store_true",
                        help="keep zero-bounds elements (default: dropped)")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Match the screen_hint.py coordinate contract: per-monitor DPI
        # awareness so UIA bounding rects are PHYSICAL screen pixels.
        # Without this, a non-DPI-aware process gets logical (scaled)
        # coordinates and the overlay would misplace hints on 125%+ displays.
        _enable_per_monitor_dpi_awareness()
        hwnd, title, pid = select_window(args.app, args.pid, args.title)
        elements = probe_window(
            hwnd,
            role_filter=args.role,
            max_elements=args.max,
            include_empty=args.include_empty,
        )

        payload: Dict[str, Any] = {
            "window_id": hwnd,
            "title": title,
            "pid": pid,
            "process": _process_name_impl(pid),
            "mode": "list" if args.list or args.find is None else "find",
            "count": len(elements),
        }
        if args.find is not None:
            matches = fuzzy_find(elements, args.find, top=args.top)
            payload["query"] = args.find
            payload["matches"] = [
                {"score": round(s, 3), **e.to_dict()} for s, e in matches
            ]
            payload["match_count"] = len(matches)
        else:
            payload["elements"] = [e.to_dict() for e in elements]

        text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
        print(text)
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"uia_probe: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
