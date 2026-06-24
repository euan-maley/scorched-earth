# Playbook: Scorched Earth

How to rebuild this project from scratch.

## Tech Stack

- **Python 3 (stdlib only)** for the core math, CLI, and state — Python is already
  invoked inside the host statusline, and stdlib-only keeps the statusline hot path
  dependency-free and fast.
- **Bash** for the thin statusline segment and the installer — that's the statusline
  contract Claude Code expects.

## Setup

```bash
git clone https://github.com/euan-maley/scorched-earth ~/scorched-earth
cd ~/scorched-earth
./install.sh        # links `scorch` onto PATH and wires the statusline light
```

No pip dependencies. Requires **`python3` ≥ 3.8** on PATH (ships with macOS; `apt install
python3` / `dnf install python3` on Linux). Cross-platform note: the core light and CLI work
anywhere Python does; the once-per-week desktop **notification** and the `--sitrep` auto-open
use macOS (`osascript`/`open`) with a Linux fallback (`notify-send`/`xdg-open`), and silently
no-op elsewhere — the sitrep file is still written either way.

## Architecture

Claude Code pipes a JSON object to the statusline command on stdin. It contains
`rate_limits.five_hour` and `rate_limits.seven_day`, each `{ used_percentage,
resets_at }` (resets_at = unix seconds). That is the single source of truth — the
same data `/usage` shows. No API calls, no log scraping.

Flow:

1. The host statusline (`~/.claude/statusline.sh`) parses the four values it already
   has and passes them to `statusline-segment.sh`.
2. The segment calls the Python core, which:
   - appends a `(now, five_hour%, seven_day%)` sample and updates the calibration of
     **R** (weekly% burned by one full 5h window),
   - writes the latest snapshot to `~/.claude/scorched-earth/state.json`,
   - returns the light (green / amber / off) + recommended per-window burn %.
3. `scorch` CLI and the `/scorched-earth` skill read `state.json` so they work even
   outside the statusline (terminal, in-session).

State lives under `~/.claude/scorched-earth/`:
- `state.json` — latest snapshot + computed recommendation.
- `calibration.json` — rolling samples and the current R estimate.

## Integrations

- **Claude Code statusline** — consumes `rate_limits` from stdin JSON
  (https://code.claude.com/docs/en/statusline.md). `rate_limits` is present only for
  Pro/Max subscribers and only after the first API response of a session; each bucket
  may be independently absent. Always degrade gracefully.

## Deployment

Personal: `install.sh` on each machine. Distribution: packaged as a Claude Code
plugin/skill; install flow asks the user how they want the light displayed.

## Gotchas

- `rate_limits` and either bucket can be missing early in a session → segment must
  emit nothing, never error (the statusline must keep rendering).
- `resets_at` is unix **seconds**, not ms.
- R needs a few samples that straddle real usage before it's trustworthy. Until then,
  the readout marks the estimate as provisional and can prompt the user for a starting
  value (their plan / observed windows-per-week).
- The 5h window resets independently of the weekly window — `windows_left` must count
  the partial current window plus full windows up to the weekly reset.
- **Straddle correction:** the current window's unused capacity is also capped by the time
  left before the *weekly* reset (`min(current_remaining, secs_to_weekly / WINDOW_SECONDS)`).
  Without this, a window straddling the weekly reset credits next week's capacity to this
  week and can flip the verdict (green→amber). Tested by "straddle: still green …".
- **Cold-start forecast guard:** the linear fallback refuses to extrapolate when < 1 day of
  the weekly cycle has elapsed (or the reset is > 7 days out, i.e. clock skew) — otherwise the
  rate inflates several-fold (the old `max(0.25, elapsed)` floor) or goes negative. It returns
  a `low`/"too early in the cycle to forecast" result that assumes full spend (no false nudge).
- **Windows are sleep-discounted.** Counting every rolling 5h window (including overnight)
  overstates usable windows and under-warns. `core.compute(active_fraction=...)` scales the
  future tail by `active_hours/24`; `habits.active_hours` learns active hours from when the
  statusline fires (16h fallback). The current window isn't discounted (you're awake in it).
- **R can't be read live**, only estimated from Δweekly%/Δ5h% over time. Guard it: discard
  out-of-band per-pair estimates (`R_MIN..R_MAX`, ~1–20%) and hold the default until
  `MIN_PAIRS` clean pairs. A single noisy pair (e.g. 0.25) will otherwise swing the verdict.
- **Forecast is capped by capacity:** `habits.forecast(max_burnable=...)` caps
  `expected_remaining`, so projected leftover is never lower than the physical floor.
- **The sitrep recomputes live.** `report._stats` recomputes the recommendation AND forecast
  from the snapshot (not the cached `state.json` fields) and re-estimates R from calibration,
  so verdict/voice/projections never go stale. Canonical `HEADLINE` lives in `core.py`.
- **Fire animation:** the burn-mode fire is a continuously-animated canvas. Playwright
  screenshots time out on it — verify the report by opening it (`scorch --report`), not by
  screenshot. Consider pausing on `visibilitychange` later.

## The sitrep (HTML report)

`scorch --sitrep` (alias `--report`) writes a self-contained HTML field report via
`report.py` and opens it. Aesthetic: 8-bit war / scorched-earth crop field. THE FIELD is a
Stardew-style top-down pixel farm whose seven weekday plots grow lush when you burn light
and char when you burn heavy. The procedural SVG pixel engine (sprites, palettes, soil
states, scarecrow/trough/fence, motion) was ported 1:1 from a standalone React design
prototype to vanilla JS and vendored into `report.py` (no external dependency at runtime).
Python computes the data and HUD stats; a small JS layer renders the field and ticks the live
countdowns.

The field has a three-way toggle: LAST WEEK (actual burn that week), AVERAGE (all-time
day-of-week habit), THIS WEEK (actual for elapsed days + projected/recommended for days
ahead, with projected plots dimmed/"PLANNED" and today tagged "NOW").

## Current Status

Working end-to-end. Core math + R self-calibration, `scorch` CLI, statusline light (fire
gradient default, wired into Euan's `~/.claude/statusline.sh`), habits/forecast layer with
a once-per-week preemptive notification, the HTML sitrep, skill + plugin manifest +
marketplace + installer. War-general voice throughout. 57 unit checks passing (run
`python3 tests/test_scorched.py`; also gated in CI via `.github/workflows/test.yml`). Forecast
and R both start provisional and sharpen with real usage.
