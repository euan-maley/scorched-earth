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
git clone <repo> ~/scorched-earth
cd ~/scorched-earth
./install.sh        # links `scorch` onto PATH and wires the statusline light
```

No pip dependencies. Requires `python3` (ships with macOS).

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

## Current Status

Working end-to-end. Core math + R self-calibration, `scorch` CLI, statusline green/amber
light (wired into Euan's `~/.claude/statusline.sh`), habits/forecast layer with a
once-per-week preemptive notification, skill + plugin manifest + installer. 25 unit
checks passing. Forecast and R both start provisional and sharpen with real usage.
