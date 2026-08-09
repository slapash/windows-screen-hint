---
name: windows-screen-hint
description: Use when guiding Windows clicks with an overlay, or when tutoring a user through a desktop task with live hints.
version: 2.0.0
author: Omar Benaidy
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [windows, overlay, computer-use, accessibility, ui-automation, tutor]
    related_skills: [computer-use, professor-mode]
---

# Windows Screen Hint — Guided Desktop Tutoring

## Overview

Two tools, one goal: **show a human exactly where to click, without clicking for them.**

- `scripts/screen_hint.py` — the **hand**: draws a short-lived fake cursor, pulsing ring, labeled rectangle, or a multi-step sequence of rectangles over the Windows desktop. Topmost, non-activating, click-through.
- `scripts/uia_probe.py` — the **eyes**: lists the target window's UI Automation elements (role, label, physical screen bounds) as JSON, or fuzzy-finds one element by accessible name.

Both use only Python standard library plus `comtypes` for the UIA probe. Neither ever injects input — the human performs every click.

## When to Use

Use this skill when:

- a user wants to see exactly where to click in a Windows application;
- you are **tutoring**: the user asked "how do I do X?" and you guide them step by step with live hints;
- Computer Use / UI Automation has discovered a control but the human should perform the click;
- a tutorial or QA flow needs a temporary visual pointer without changing focus.

Do not use it when:

- the agent should perform the click itself (use `computer_use` input actions instead);
- the target bounds are stale or estimated;
- the application is not on Windows;
- persistent overlays, drawing tools, or recording are required.

## Resolve the Scripts

Load this skill with `skill_view(name='windows-screen-hint')`. Use the absolute `skill_dir` returned by the tool:

```text
<skill_dir>\scripts\screen_hint.py
<skill_dir>\scripts\uia_probe.py
```

Do not guess another profile's skill path.

## Commands

```bash
python "<skill_dir>/scripts/screen_hint.py" cursor X Y --duration-ms 2500
python "<skill_dir>/scripts/screen_hint.py" ring X Y --diameter 100 --duration-ms 2500
python "<skill_dir>/scripts/screen_hint.py" rect X Y WIDTH HEIGHT --label "Click here" --duration-ms 3000
python "<skill_dir>/scripts/screen_hint.py" steps --rect X Y WIDTH HEIGHT --label "1/4 ..." [--rect ...]... --duration-ms 10000
```

Constraints:

- duration: 100–10000 ms;
- rectangle width and height: positive integers;
- ring diameter: positive integer;
- coordinates: **physical virtual-desktop screen coordinates**;
- negative coordinates are valid on monitors left or above the primary display;
- `steps` accepts one or more `--rect` (each with `X Y WIDTH HEIGHT`); `--label` count must match `--rect` count (labels pad with empty strings if omitted).

### UIA probe

```bash
python "<skill_dir>/scripts/uia_probe.py" --app "Calculator" --find "2" --top 5
python "<skill_dir>/scripts/uia_probe.py" --app "Notepad" --list --max 100
python "<skill_dir>/scripts/uia_probe.py" --pid 1234 --role "Button" --find "novo" --pretty
python "<skill_dir>/scripts/uia_probe.py" --title "Settings" --find "bluetooth"
```

Selection (at most one of `--app` / `--pid` / `--title`; default: foreground window):

- `--app NAME` — window whose process name **or title** contains NAME (case-insensitive);
- `--pid N` — window owned by PID N;
- `--title TEXT` — window whose title contains TEXT.

Filters:

- `--list` — dump all elements (capped by `--max`, default 500);
- `--find TEXT` — fuzzy-match elements by accessible name; best scores first (`--top N`, default 10);
- `--role ROLE` — only elements of that control type (e.g. Button, Edit, MenuItem, TabItem, CheckBox);
- `--include-empty` — keep (0,0,0,0) bounds elements (default: dropped);
- `--pretty` — pretty-print JSON.

Output: JSON with `window_id`, `title`, `pid`, `process`, `count`, and either `elements` (list mode) or `matches` (find mode, each with `score` + element). Exit 0 on success, 2 on failure.

## Coordinate Contract (verified on Win11, 125% DPI)

- **Both scripts speak physical virtual-desktop screen pixels.** `uia_probe` opts into per-monitor DPI awareness (`SetProcessDpiAwarenessContext(-4)`) before touching UIA; `screen_hint` does the same before drawing.
- **Bounds from UIA `CurrentBoundingRectangle` are physical screen coordinates** — pass them straight to `screen_hint.py rect` with no conversion.
- A non-DPI-aware process gets logical (scaled) coordinates — on a 125% display a 1.25x mismatch silently misplaces hints. Always run the scripts as-is; never re-derive bounds in a scaled process.
- Negative coordinates are valid on monitors left/above the primary.

## Tutoring Protocol (the loop)

This is the full agent loop for teaching a desktop task. The agent (you) is the brain; the two scripts are hand and eyes; the human does every click.

```
ESTUDAR → PLANEJAR → APONTAR → HUMANO CLICA → VERIFICAR → (repeat) → CONCLUIR
```

1. **ESTUDAR** — User asks "how do I do X?" Research the task (web/docs) AND inspect the live target with `uia_probe --list` so the plan matches the real UI. If the target app is not obvious, `--app` by the window title the user names, or ask which window to guide in.
2. **PLANEJAR** — Break the task into small verifiable steps. Each step has: an instruction, the element to find (label/role), and an expected state change to verify. **A step only becomes a hint if its element actually exists in the live tree** — this is what kills hallucinated steps.
3. **APONTAR** — `uia_probe --find "<label>"` to get fresh bounds (add `--role` to disambiguate). Render one hint at a time with `screen_hint.py rect X Y W H --label "N/M <instrução curta>" --duration-ms` (1500–5000). For a known short sequence, `steps` shows all targets at once — but prefer one-at-a-time for teaching. Run the hint in the background when the human must interact before it expires.
4. **HUMANO CLICA** — Tell the user in chat what the hint means, terse. Never add synthetic input. The overlay is click-through; nothing is blocked.
5. **VERIFICAR** — After the click, re-run `uia_probe --find` (or `--list`) and compare with the expected state: new window? label changed? element appeared/disappeared? **Verify by UIA state, not by how the screen looks.** If the state did not change, re-capture fresh bounds (the window may have moved) and re-render, or ask the user what they see.
6. **CONCLUIR** — When steps are exhausted, summarize what was done. Offer to write the captured sequence as a Markdown tutorial.

Rules that never bend:

- **Never click for the user.** The product is teaching; input injection defeats it.
- **Fresh bounds every hint.** Windows move, resize, change DPI. Never reuse coordinates from a previous step.
- **Fails closed.** If `uia_probe --find` returns no match, do NOT guess coordinates — re-study, ask the user, or use `--list` to find the right label.
- **Verify by state.** UIA read-back after each click; visual appearance alone is insufficient.
- **Safety floor.** Never guide through payment, password, 2FA, permission, or destructive-confirmation UI without explicit authorization. Never put secrets in `--label`.

## Guided-Click Workflow (single step, quick version)

1. **Fresh capture.** `uia_probe --app "<app>" --find "<label>"` → current bounds + semantic label.
2. **Check coordinate space.** Bounds are physical screen coordinates; the overlay expects the same. No conversion.
3. **Render only.** `screen_hint.py rect X Y W H --label "..." --duration-ms` (background if the human must act during it).
4. **Human interaction.** Tell the user what the label means; they click through the overlay. Never add synthetic input.
5. **Verify state.** Re-run `uia_probe` and confirm the expected UIA/application state changed.
6. **Clean up.** Confirm all bounded overlay processes exited.

## Multi-Step Guidance

Run short overlays sequentially rather than keeping one permanent process. Example (2+2 in Calculator):

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

Bounds in examples are illustrative. **Always** get fresh bounds from `uia_probe` first.

## Click Watch — the universal "did the user do it?" check

`scripts/click_watch.py` answers the question that UIA state alone cannot:
**did the user actually click the target?** It installs a low-level global
mouse hook (`WH_MOUSE_LL`) and reports the first click that lands inside the
target rectangle.

```bash
python "<skill_dir>/scripts/click_watch.py" --x 279 --y 513 --w 43 --h 33 --timeout-ms 20000
python "<skill_dir>/scripts/click_watch.py" --find "2" --app "Calculator" --timeout-ms 20000
```

- `--x/--y/--w/--h` — explicit physical screen rectangle; OR
- `--find LABEL [--app APP]` — resolve the target via `uia_probe` first.
- Exit 0 = clicked inside target (`{"clicked": true, "x":…, "y":…}`).
- Exit 3 = timed out with no clicks; exit 4 = clicks happened but off-target
  (the JSON includes every recorded click so you can say "you clicked at
  (120,300), but the target was at (279,513,43,33)").

**Why this exists:** many applications do not expose the state that would
prove a click worked — canvas apps, games, custom-drawn controls, and even
Calculator's history line. A mouse hook is software-agnostic: the target is
just screen coordinates, which `uia_probe` already returns as physical
pixels. For simple steps (click a button, select an option), click-watch is
the verification. For steps whose *effect* matters (a window opened, a value
changed), layer UIA state diff or a vision capture on top.

**Tutor loop with click-watch:**
1. `uia_probe --find "<label>"` → bounds (or use explicit rect).
2. `screen_hint.py rect X Y W H --label "N/M …"` to point (background).
3. `click_watch.py --x X --y Y --w W --h H --timeout-ms 20000` — blocks
   until the user clicks the target, clicks elsewhere, or times out.
4. On exit 0: step confirmed. On exit 3: re-point or re-plan. On exit 4:
   tell the user where they clicked and re-point.
5. For effect steps, re-run `uia_probe` after the confirmed click and diff.

Verified 2026-08: WH_MOUSE_LL sees synthetic clicks (`SetCursorPos` +
`mouse_event`) with physical coordinates when the process is per-monitor DPI
aware — the same contract as the other two tools.

## Safety Contract

- The renderer and probe draw/observe only; neither clicks, types, or logs screen content.
- Keep every hint ephemeral; the CLI enforces a ten-second maximum.
- Do not display secrets, passwords, tokens, or private text in labels.
- Do not guide a user through payment, password, permission, or destructive confirmation UI without explicit authorization.
- Do not claim click-through from `WS_EX_TRANSPARENT` alone. The implementation also returns `HTTRANSPARENT` for `WM_NCHITTEST` and `MA_NOACTIVATE` for `WM_MOUSEACTIVATE`.

## Capture Caveat

A window-only capture can show the transparent color key as a solid background when it isolates the layered Tk window. Treat that as a capture artifact if the composited desktop is transparent. Verify with the user-visible desktop, focus state, click-through interaction, and post-action UIA state.

## Common Pitfalls

1. **Stale bounds.** Window movement, resize, DPI changes, and monitor changes invalidate coordinates. Recapture immediately before rendering.
2. **Logical vs physical coordinates.** A scaled (non-DPI-aware) process reports 1.25x-off bounds on 125% displays. Both scripts here are per-monitor DPI aware; never re-derive bounds in a scaled process.
3. **Foreground theft.** Do not remove `WS_EX_NOACTIVATE` or the `WM_MOUSEACTIVATE` handler.
4. **False click-through test.** UIA Invoke can bypass ordinary hit testing. Prefer a human click through the visible overlay and verify resulting application state.
5. **Orphaned overlays.** Keep durations short and inspect background processes after interrupted demos.
6. **Start menu / shell surfaces.** The overlay does NOT render above the Windows Start menu (or lock screen, UAC, some XAML/DWM surfaces) — they live above `HWND_TOPMOST`. Verified Win11 26100 (2026-08). Fall back to plain-text instruction for targets inside the Start menu; resume overlays once the target app window is open.
7. **Fuzzy find ambiguity.** `--find "2"` may match "2", "Memory", "Result" etc. Add `--role Button` and check the `score` (1.0 = exact label match). If the top hit is not the control you want, refine the query or use `--list` to see all labels.
8. **UIA COM first run.** `comtypes` generates typelib bindings on first use — the first `uia_probe` call may take a few seconds. Subsequent calls are fast.

## Verification Checklist

- [ ] Target bounds came from a fresh `uia_probe` run
- [ ] Overlay command uses physical screen coordinates
- [ ] Duration is at most 10 seconds
- [ ] Overlay does not take focus
- [ ] Human click reaches the application underneath
- [ ] Expected UIA/DOM/application state is verified afterward
- [ ] Overlay process exits automatically
- [ ] Every planned step was validated against the live element tree before rendering
