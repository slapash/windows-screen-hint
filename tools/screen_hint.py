"""Ephemeral, non-interactive Windows guidance overlay.

Uses only the Python standard library. The renderer never observes or clicks;
it only draws a short-lived hint at verified screen coordinates.
"""

from __future__ import annotations

import argparse
import ctypes
import os
from dataclasses import dataclass
from typing import Sequence


WM_MOUSEACTIVATE = 0x0021
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
MA_NOACTIVATE = 3

GWL_WNDPROC = -4
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

ORANGE = "#ff7900"
TRANSPARENT_KEY = "#010203"


@dataclass(frozen=True)
class Hint:
    kind: str
    x: int
    y: int
    width: int = 0
    height: int = 0
    diameter: int = 0
    label: str = ""
    duration_ms: int = 2500


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show a temporary click-through visual hint on Windows."
    )
    subparsers = parser.add_subparsers(dest="kind", required=True)

    cursor = subparsers.add_parser("cursor", help="Show a fake cursor and halo")
    cursor.add_argument("x", type=int)
    cursor.add_argument("y", type=int)

    ring = subparsers.add_parser("ring", help="Show a pulsing ring")
    ring.add_argument("x", type=int)
    ring.add_argument("y", type=int)
    ring.add_argument("--diameter", type=int, required=True)

    rect = subparsers.add_parser("rect", help="Outline a rectangular control")
    rect.add_argument("x", type=int)
    rect.add_argument("y", type=int)
    rect.add_argument("width", type=int)
    rect.add_argument("height", type=int)
    rect.add_argument("--label", default="")

    for child in (cursor, ring, rect):
        child.add_argument("--duration-ms", type=int, default=2500)

    return parser


def parse_cli(argv: Sequence[str] | None = None) -> Hint:
    args = build_parser().parse_args(argv)
    if not 100 <= args.duration_ms <= 10_000:
        raise ValueError("duration-ms must be between 100 and 10000")

    if args.kind == "ring":
        if args.diameter <= 0:
            raise ValueError("diameter must be positive")
        return Hint(
            kind="ring",
            x=args.x,
            y=args.y,
            diameter=args.diameter,
            duration_ms=args.duration_ms,
        )

    if args.kind == "rect":
        if args.width <= 0 or args.height <= 0:
            raise ValueError("rect width and height must be positive")
        return Hint(
            kind="rect",
            x=args.x,
            y=args.y,
            width=args.width,
            height=args.height,
            label=args.label,
            duration_ms=args.duration_ms,
        )

    return Hint(kind="cursor", x=args.x, y=args.y, duration_ms=args.duration_ms)


def hint_bounds(hint: Hint) -> tuple[int, int, int, int]:
    if hint.kind == "rect":
        return hint.x, hint.y, hint.width, hint.height
    if hint.kind == "ring":
        radius = hint.diameter // 2
        return hint.x - radius, hint.y - radius, hint.diameter, hint.diameter
    return hint.x - 28, hint.y - 28, 64, 72


def validate_against_desktop(
    hint: Hint, desktop: tuple[int, int, int, int]
) -> None:
    dx, dy, dw, dh = desktop
    x, y, width, height = hint_bounds(hint)
    intersects = x < dx + dw and x + width > dx and y < dy + dh and y + height > dy
    if not intersects:
        raise ValueError("hint does not intersect the virtual desktop")


def overlay_message_result(message: int) -> int | None:
    if message == WM_NCHITTEST:
        return HTTRANSPARENT
    if message == WM_MOUSEACTIVATE:
        return MA_NOACTIVATE
    return None


def virtual_desktop(user32: object | None = None) -> tuple[int, int, int, int]:
    if os.name != "nt":
        raise RuntimeError("screen_hint is Windows-only")
    user32 = user32 or ctypes.windll.user32
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def _geometry(width: int, height: int, x: int, y: int) -> str:
    return f"{width}x{height}{x:+d}{y:+d}"


class WindowsOverlay:
    def __init__(self, hint: Hint, desktop: tuple[int, int, int, int]):
        import tkinter as tk
        from ctypes import wintypes

        self.tk = tk
        self.hint = hint
        self.desktop = desktop
        self.user32 = ctypes.windll.user32
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.root.attributes("-topmost", True)

        dx, dy, dw, dh = desktop
        self.root.geometry(_geometry(dw, dh, dx, dy))
        self.canvas = tk.Canvas(
            self.root,
            width=dw,
            height=dh,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()

        self.hwnd = self.user32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id()
        self._configure_ctypes(wintypes)
        self._subclass_window()
        self._apply_styles()
        self._draw()

        self.root.deiconify()
        self.user32.SetWindowPos(
            self.hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        self.root.after(hint.duration_ms, self.close)

    def _configure_ctypes(self, wintypes: object) -> None:
        long_ptr = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(
            long_ptr,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self.user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetWindowLongPtrW.restype = long_ptr
        self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
        self.user32.SetWindowLongPtrW.restype = long_ptr
        self.user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.CallWindowProcW.restype = long_ptr

    def _subclass_window(self) -> None:
        self._old_wndproc = self.user32.GetWindowLongPtrW(self.hwnd, GWL_WNDPROC)
        if not self._old_wndproc:
            raise ctypes.WinError(ctypes.get_last_error())

        @self.WNDPROC
        def wndproc(hwnd, message, wparam, lparam):
            result = overlay_message_result(message)
            if result is not None:
                return result
            return self.user32.CallWindowProcW(
                self._old_wndproc, hwnd, message, wparam, lparam
            )

        self._wndproc_callback = wndproc
        callback_address = ctypes.cast(wndproc, ctypes.c_void_p).value
        ctypes.set_last_error(0)
        previous = self.user32.SetWindowLongPtrW(
            self.hwnd, GWL_WNDPROC, callback_address
        )
        if not previous and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        self._old_wndproc = previous or self._old_wndproc

    def _apply_styles(self) -> None:
        extended = self.user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        extended |= (
            WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )
        ctypes.set_last_error(0)
        previous = self.user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, extended)
        if not previous and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())

    def _local(self, x: int, y: int) -> tuple[int, int]:
        return x - self.desktop[0], y - self.desktop[1]

    def _draw(self) -> None:
        if self.hint.kind == "rect":
            self._draw_rect()
        elif self.hint.kind == "ring":
            self._draw_ring()
        else:
            self._draw_cursor()

    def _draw_rect(self) -> None:
        x, y = self._local(self.hint.x, self.hint.y)
        x2, y2 = x + self.hint.width, y + self.hint.height
        self.canvas.create_rectangle(
            x - 3, y - 3, x2 + 3, y2 + 3, outline=ORANGE, width=6
        )
        self.canvas.create_rectangle(
            x - 8, y - 8, x2 + 8, y2 + 8, outline="#ffb15c", width=2
        )
        if self.hint.label:
            text = self.canvas.create_text(
                x + self.hint.width / 2,
                y2 + 18,
                text=self.hint.label,
                fill="white",
                font=("Segoe UI", 12, "bold"),
            )
            bounds = self.canvas.bbox(text)
            if bounds:
                pad = 7
                background = self.canvas.create_rectangle(
                    bounds[0] - pad,
                    bounds[1] - 3,
                    bounds[2] + pad,
                    bounds[3] + 3,
                    fill=ORANGE,
                    outline=ORANGE,
                )
                self.canvas.tag_lower(background, text)

    def _draw_ring(self) -> None:
        x, y = self._local(self.hint.x, self.hint.y)
        radius = self.hint.diameter / 2
        self._ring = self.canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            outline=ORANGE,
            width=7,
        )
        self._pulse_step = 0
        self._animate_ring()

    def _animate_ring(self) -> None:
        if not self.root.winfo_exists():
            return
        widths = (4, 5, 6, 7, 8, 7, 6, 5)
        self.canvas.itemconfigure(
            self._ring, width=widths[self._pulse_step % len(widths)]
        )
        self._pulse_step += 1
        self.root.after(70, self._animate_ring)

    def _draw_cursor(self) -> None:
        x, y = self._local(self.hint.x, self.hint.y)
        self.canvas.create_oval(
            x - 22, y - 22, x + 22, y + 22, outline="#ffb15c", width=3
        )
        self.canvas.create_oval(
            x - 12, y - 12, x + 12, y + 12, outline=ORANGE, width=6
        )
        self.canvas.create_polygon(
            x + 5,
            y + 6,
            x + 5,
            y + 42,
            x + 15,
            y + 32,
            x + 23,
            y + 49,
            x + 31,
            y + 45,
            x + 23,
            y + 28,
            x + 38,
            y + 27,
            fill=ORANGE,
            outline="white",
            width=2,
        )

    def close(self) -> None:
        try:
            if self.hwnd and self._old_wndproc and self.user32.IsWindow(self.hwnd):
                self.user32.SetWindowLongPtrW(
                    self.hwnd, GWL_WNDPROC, self._old_wndproc
                )
        finally:
            if self.root.winfo_exists():
                self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def enable_per_monitor_dpi_awareness() -> None:
    if os.name != "nt":
        raise RuntimeError("screen_hint is Windows-only")
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        user32.SetProcessDPIAware()


def run_overlay(hint: Hint) -> None:
    enable_per_monitor_dpi_awareness()
    desktop = virtual_desktop()
    validate_against_desktop(hint, desktop)
    WindowsOverlay(hint, desktop).run()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        hint = parse_cli(argv)
        run_overlay(hint)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"screen_hint: {exc}", file=__import__("sys").stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
