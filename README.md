# Windows Screen Hint

A tiny, temporary, **click-through Windows overlay** for showing a user where to click.

It draws a fake cursor, a pulsing ring, or a labeled rectangle above the desktop without taking focus or blocking mouse input. It is designed for computer-use agents, guided tutorials, and manual QA.

- Windows only
- Python 3.11+
- Standard library only (`tkinter` + `ctypes`)
- No Qt, Electron, service, installer, or background daemon
- Automatically closes after at most 10 seconds

## Demo

The first real integration test guided a user through `2 + 2` in Windows Calculator:

```text
[2] → [+] → [2] → [=] → 4
```

The user clicked through each orange rectangle, and the final Calculator UI Automation state reported `L’affichage est 4`.

## Usage

From the repository root:

```bash
python tools/screen_hint.py cursor 640 400 --duration-ms 2500
python tools/screen_hint.py ring 640 400 --diameter 100 --duration-ms 2500
python tools/screen_hint.py rect 131 457 77 51 --label "Click here" --duration-ms 3000
```

Coordinates are physical virtual-desktop screen coordinates. Negative coordinates are supported for monitors placed left of the primary display.

### Commands

```text
cursor X Y
ring X Y --diameter N
rect X Y WIDTH HEIGHT [--label TEXT]
steps --rect X Y WIDTH HEIGHT [--label TEXT] [--rect ...]...
```

Every command accepts:

```text
--duration-ms 100..10000
```

Default duration: `2500` ms.

### Multi-step guidance

`steps` outlines several controls at once — ideal for guided flows where the human follows a numbered sequence. Labels show a step counter (`N/M`), and all rectangles render together for the whole duration:

```bash
python tools/screen_hint.py steps \
  --rect 131 457 77 51 --label "1/4  Click 2" \
  --rect 288 457 76 51 --label "2/4  Click +" \
  --rect 131 457 77 51 --label "3/4  Click 2" \
  --rect 288 510 76 51 --label "4/4  Click =" \
  --duration-ms 10000
```

The first real integration test guided a user through `2 + 2` in Windows Calculator — the final Calculator state reported `4`.

## Why clicks pass through

The overlay combines Windows extended styles with explicit window-message handling:

- `WS_EX_LAYERED`
- `WS_EX_TRANSPARENT`
- `WS_EX_TOOLWINDOW`
- `WS_EX_NOACTIVATE`
- `WM_NCHITTEST → HTTRANSPARENT`
- `WM_MOUSEACTIVATE → MA_NOACTIVATE`

`WS_EX_TRANSPARENT` alone is not treated as proof of click-through behavior. The window procedure explicitly rejects hit testing and activation.

The process opts into per-monitor DPI awareness before reading the virtual desktop geometry.

## Tests

```bash
python -m unittest discover -s tests -p "test_screen_hint.py" -v
python -m py_compile tools/screen_hint.py
```

The test suite covers CLI parsing, duration limits, geometry validation, negative monitor coordinates, and the non-interactive message contract.

## Hermes skill

The reusable skill is included at:

```text
skill/windows-screen-hint/
```

To install it manually, copy that directory into the active Hermes profile's `skills` directory. On a default Windows installation this is typically:

```text
%LOCALAPPDATA%\hermes\skills\windows-screen-hint\
```

Start a new Hermes session after installation so the skill index is refreshed.

## Agent workflow

1. Capture the target application with Computer Use or UI Automation.
2. Read fresh screen bounds for the intended control.
3. Invoke `screen_hint.py rect X Y WIDTH HEIGHT` with a short duration.
4. Let the human click; the overlay never injects input.
5. Recapture application state and verify the expected result.

Do not reuse stale coordinates after a window moves, resizes, changes DPI, or moves between monitors.

## Capture caveat

Some window-only capture APIs display the transparent color key as a solid background when capturing the overlay window in isolation. That is a capture artifact; verify the composited desktop and actual click-through behavior instead.

## Known limitation: Windows Start menu (and shell surfaces)

The overlay does **not** render on top of the Windows **Start menu** (or other shell-level surfaces that live above normal topmost windows — e.g. the lock screen, UAC prompts, and some XAML/DWM surfaces). The Start menu is a special shell layer that sits above `HWND_TOPMOST` Tk windows, so a hint positioned over it is invisible to the user.

Verified on Win11 26100 (2026-08): a `rect` hint over the Start search box rendered, but ended up **behind** the menu. The overlay still works fine over normal applications (win32 Calculator, UWP Settings, Explorer, browsers).

When the target you want to point at lives inside the Start menu, guide the user with a plain-text instruction instead of an overlay (e.g. "type `Personalizar` in the search box and press Enter"), then resume overlays once the app window is open.

## Motivation

This is a small Windows-focused implementation of the visual-guidance idea explored in [`slapash/screen-overlay-spike`](https://github.com/slapash/screen-overlay-spike). It does not port that project's Qt/QML, Wayland, KWin, D-Bus, or AT-SPI architecture.

## License

MIT © 2026 Omar Benaidy
