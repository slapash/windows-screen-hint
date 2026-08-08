"""Click watch — wait for a real mouse click inside a target rectangle.

The universal "did the user do it?" check for guided tutoring. Instead of
trying to read application state (which many apps do not expose — canvas
apps, games, custom-drawn controls, and even Calculator's history line),
this installs a low-level global mouse hook (WH_MOUSE_LL) and reports the
first click that lands inside the target rectangle.

Works on ANY Windows application: the target is just screen coordinates,
which uia_probe.py already returns as physical pixels. No UIA tree needed.

Requirements: Python standard library + ctypes only (same ethos as
screen_hint.py). Windows only.

Usage:
  python tools/click_watch.py --x 279 --y 513 --w 43 --h 33 --timeout-ms 20000
  python tools/click_watch.py --find "2" --app "Calculator" --timeout-ms 20000

Exit codes:
  0  clicked inside the target (prints {"clicked": true, ...})
  3  timed out (prints {"clicked": false, "reason": "timeout", "clicks": [...]})
  4  clicked somewhere else then timed out (includes the off-target clicks)

Every click during the watch is recorded with physical screen coordinates
and whether it landed in the target, so the tutor can give feedback like
"you clicked at (120, 300) but the target is at (279, 513, 43, 33)".
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Sequence, Tuple

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207

PM_REMOVE = 0x0001


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


def _enable_per_monitor_dpi_awareness() -> None:
    """Match the physical-screen coordinate contract of the other tools."""
    if sys.platform != "win32":
        raise RuntimeError("click_watch is Windows-only")
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        user32.SetProcessDPIAware()


class ClickWatch:
    """Installs a WH_MOUSE_LL hook and records clicks until target hit/timeout."""

    def __init__(self, x: int, y: int, width: int, height: int):
        self.target = (x, y, width, height)
        self.clicks: List[Dict[str, Any]] = []
        self.hit = False
        self._hook: Optional[int] = None
        self._user32 = ctypes.windll.user32

        self._HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )

    def _in_target(self, px: int, py: int) -> bool:
        x, y, w, h = self.target
        return x <= px <= x + w and y <= py <= y + h

    def _callback(self, n_code: int, wparam: int, lparam: int) -> int:
        if n_code == 0:  # HC_ACTION
            if wparam in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                px, py = int(info.pt.x), int(info.pt.y)
                record = {
                    "button": {
                        WM_LBUTTONDOWN: "left",
                        WM_LBUTTONUP: "left_up",
                        WM_RBUTTONDOWN: "right",
                        WM_MBUTTONDOWN: "middle",
                    }.get(wparam, "other"),
                    "x": px,
                    "y": py,
                    "in_target": self._in_target(px, py),
                }
                self.clicks.append(record)
                if wparam in (WM_LBUTTONDOWN, WM_LBUTTONUP) and record["in_target"]:
                    self.hit = True
        return self._user32.CallNextHookEx(None, n_code, wparam, lparam)

    def start(self) -> None:
        if self._hook is not None:
            return
        self._proc = self._HOOKPROC(self._callback)
        ctypes.set_last_error(0)
        self._hook = self._user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._proc, None, 0
        )
        if not self._hook:
            raise ctypes.WinError(ctypes.get_last_error())

    def stop(self) -> None:
        if self._hook:
            self._user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def run(self, timeout_ms: int) -> Dict[str, Any]:
        self.start()
        deadline = time.monotonic() + max(100, timeout_ms) / 1000.0
        try:
            while not self.hit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                # Pump messages so the hook can fire.
                msg = wintypes.MSG()
                while self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    self._user32.TranslateMessage(ctypes.byref(msg))
                    self._user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.005)
        finally:
            self.stop()

        if self.hit:
            hit_click = next(c for c in reversed(self.clicks) if c["in_target"])
            return {"clicked": True, "reason": "in_target", **hit_click}
        if any(c["in_target"] for c in self.clicks):
            return {"clicked": True, "reason": "in_target"}
        if self.clicks:
            return {"clicked": False, "reason": "off_target_timeout", "clicks": self.clicks}
        return {"clicked": False, "reason": "timeout", "clicks": self.clicks}


def _probe_bounds(app: str, find: str, top: int = 1) -> Tuple[int, int, int, int]:
    """Reuse uia_probe to resolve (app, find) into physical target bounds."""
    import importlib.util
    import pathlib

    probe_path = pathlib.Path(__file__).resolve().parent / "uia_probe.py"
    spec = importlib.util.spec_from_file_location("uia_probe", probe_path)
    probe = importlib.util.module_from_spec(spec)
    sys.modules["uia_probe"] = probe
    spec.loader.exec_module(probe)

    _enable_per_monitor_dpi_awareness()
    hwnd, title, pid = probe.select_window(app=app)
    elements = probe.probe_window(hwnd, max_elements=500)
    matches = probe.fuzzy_find(elements, find, top=top)
    if not matches:
        raise RuntimeError(
            f"click_watch: no element matching {find!r} in window {title!r} "
            f"(--find requires uia_probe.py beside this script)"
        )
    score, el = matches[0]
    return el.x, el.y, el.width, el.height


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for a real mouse click inside a target rectangle (Windows)."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--x", type=int, help="target left (physical screen px)")
    target.add_argument("--find", metavar="LABEL", help="resolve target via uia_probe")

    parser.add_argument("--y", type=int, help="target top (used with --x)")
    parser.add_argument("--w", type=int, default=0, help="target width")
    parser.add_argument("--h", type=int, default=0, help="target height")
    parser.add_argument("--app", help="window for --find (uia_probe selection)")
    parser.add_argument("--timeout-ms", type=int, default=20000,
                        help="how long to wait (default 20000)")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not 100 <= args.timeout_ms <= 120000:
        print("click_watch: timeout-ms must be between 100 and 120000", file=sys.stderr)
        return 2
    try:
        _enable_per_monitor_dpi_awareness()
        if args.x is not None:
            if args.y is None:
                print("click_watch: --y is required with --x", file=sys.stderr)
                return 2
            x, y, w, h = args.x, args.y, args.w, args.h
        else:
            x, y, w, h = _probe_bounds(app=args.app, find=args.find)

        watch = ClickWatch(x, y, w, h)
        result = watch.run(args.timeout_ms)
        result["target"] = {"x": x, "y": y, "w": w, "h": h}
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0 if result["clicked"] else (4 if result["reason"] == "off_target_timeout" else 3)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"click_watch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
