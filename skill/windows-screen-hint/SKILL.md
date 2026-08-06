---
name: windows-screen-hint
description: Use when guiding Windows clicks with an overlay.
version: 1.0.0
author: Omar Benaidy
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [windows, overlay, computer-use, accessibility, ui-automation]
    related_skills: [computer-use]
---

# Windows Screen Hint

## Overview

Use the bundled `scripts/screen_hint.py` to draw a short-lived fake cursor, pulsing ring, or labeled rectangle over a Windows desktop. The overlay is topmost, non-activating, and click-through: it guides a human without clicking or intercepting input.

The script uses only Python's standard library (`tkinter` and `ctypes`). It is not a substitute for Computer Use or UI Automation; those tools discover and verify targets, while this skill only renders guidance.

## When to Use

Use this skill when:

- a user wants to see exactly where to click in a Windows application;
- Computer Use has discovered a control but the human should perform the click;
- a tutorial or QA flow needs a temporary visual pointer without changing focus;
- a fake cursor, ring, or labeled rectangle is enough.

Do not use it when:

- the agent should perform the click itself;
- the target bounds are stale or estimated;
- the application is not on Windows;
- persistent overlays, drawing tools, or recording are required.

## Resolve the Script

Load this skill with `skill_view(name='windows-screen-hint')`. Use the absolute `skill_dir` returned by the tool and append:

```text
scripts\screen_hint.py
```

Do not guess another profile's skill path. Do not edit another profile unless the user explicitly requests it.

## Commands

```bash
python "<skill_dir>/scripts/screen_hint.py" cursor X Y --duration-ms 2500
python "<skill_dir>/scripts/screen_hint.py" ring X Y --diameter 100 --duration-ms 2500
python "<skill_dir>/scripts/screen_hint.py" rect X Y WIDTH HEIGHT --label "Click here" --duration-ms 3000
```

Constraints:

- duration: 100–10000 ms;
- rectangle width and height: positive integers;
- ring diameter: positive integer;
- coordinates: physical virtual-desktop screen coordinates;
- negative coordinates are valid on monitors left or above the primary display.

## Guided-Click Workflow

1. **Fresh capture.** Capture the target app with `computer_use(action='capture', mode='som')` or equivalent UI Automation. Completion: the intended control has current bounds and a clear semantic label.

2. **Check coordinate space.** Use the bounds reported for the control as screen coordinates. If a Computer Use action expects app-relative coordinates, do not reuse those action coordinates for the overlay. Completion: the rectangle intersects the current virtual desktop.

3. **Render only.** Start `screen_hint.py` with a short duration. Use `terminal(background=true)` when the overlay must remain visible while the human interacts. Completion: the process is running and has not returned an argument or geometry error.

4. **Human interaction.** Tell the user what the label means and let them click through the overlay. Never add synthetic mouse or keyboard input to this renderer. Completion: the hint expires automatically.

5. **Verify state.** Recapture the target app and inspect DOM/UIA/application state. Completion: the expected post-click state is observed; visual appearance alone is insufficient.

6. **Clean up.** Confirm all bounded overlay processes exited and close stale read-only terminal tabs. Completion: no overlay process remains running.

## Multi-Step Guidance

Run short overlays sequentially rather than keeping one permanent process. Example:

```python
import subprocess
import sys

base = [sys.executable, r"<skill_dir>\scripts\screen_hint.py", "rect"]
steps = [
    ["131", "457", "77", "51", "--label", "1/4  Click 2"],
    ["288", "457", "76", "51", "--label", "2/4  Click +"],
    ["131", "457", "77", "51", "--label", "3/4  Click 2"],
    ["288", "510", "76", "51", "--label", "4/4  Click ="],
]
for step in steps:
    subprocess.run(base + step + ["--duration-ms", "7000"], check=True)
```

Bounds in examples are illustrative. Always recapture the live target first.

## Safety Contract

- The renderer draws only; it does not observe, click, type, or log screen content.
- Keep every hint ephemeral; the CLI enforces a ten-second maximum.
- Do not display secrets, passwords, tokens, or private text in labels.
- Do not guide a user through payment, password, permission, or destructive confirmation UI without explicit authorization.
- Do not claim click-through from `WS_EX_TRANSPARENT` alone. The implementation also returns `HTTRANSPARENT` for `WM_NCHITTEST` and `MA_NOACTIVATE` for `WM_MOUSEACTIVATE`.

## Capture Caveat

A window-only capture can show the transparent color key as a solid background when it isolates the layered Tk window. Treat that as a capture artifact if the composited desktop is transparent. Verify with the user-visible desktop, focus state, click-through interaction, and post-action UIA state.

## Common Pitfalls

1. **Stale bounds.** Window movement, resize, DPI changes, and monitor changes invalidate coordinates. Recapture immediately before rendering.
2. **App-relative vs screen coordinates.** Computer Use pointer actions may accept app-local coordinates even when UIA bounds are screen coordinates. The overlay always expects screen coordinates.
3. **Foreground theft.** Do not remove `WS_EX_NOACTIVATE` or the `WM_MOUSEACTIVATE` handler.
4. **False click-through test.** UIA Invoke can bypass ordinary hit testing. Prefer a human click through the visible overlay and verify resulting application state.
5. **Orphaned overlays.** Keep durations short and inspect background processes after interrupted demos.

## Verification Checklist

- [ ] Target bounds came from a fresh capture
- [ ] Overlay command uses physical screen coordinates
- [ ] Duration is at most 10 seconds
- [ ] Overlay does not take focus
- [ ] Human click reaches the application underneath
- [ ] Expected UIA/DOM/application state is verified afterward
- [ ] Overlay process exits automatically
