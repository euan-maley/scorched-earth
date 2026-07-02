# Playbook: Scorched Earth

How to rebuild this project from scratch.

## Tech Stack

- **Python 3 (stdlib only)** for the core math, CLI, and state - Python is already
  invoked inside the host statusline, and stdlib-only keeps the statusline hot path
  dependency-free and fast.
- **Bash** for the thin statusline segment and the installer - that's the statusline
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
no-op elsewhere - the sitrep file is still written either way.

## Architecture

Claude Code pipes a JSON object to the statusline command on stdin. It contains
`rate_limits.five_hour` and `rate_limits.seven_day`, each `{ used_percentage,
resets_at }` (resets_at = unix seconds). That is the single source of truth - the
same data `/usage` shows. No API calls, no log scraping.

Flow:

1. The host statusline (`~/.claude/statusline.sh`) parses the four values it already
   has and passes them to `statusline-segment.sh`.
2. The segment calls the Python core, which:
   - appends a `(now, five_hour%, seven_day%)` sample and updates the calibration of
     **R** (weekly% burned by one full 5h window),
   - writes the latest snapshot to `~/.claude/scorched-earth/state.json`,
   - returns the verdict (`max` BURN IT ALL / `push` clear shot / `steady` eyes on the
     target / `ease` hold your fire / `done` good job soldier) + recommended per-window burn %.
3. `scorch` CLI and the `/scorched-earth` skill read `state.json` so they work even
   outside the statusline (terminal, in-session).

State lives under `~/.claude/scorched-earth/`:
- `state.json` - latest snapshot + computed recommendation.
- `calibration.json` - rolling samples and the current R estimate.

## Integrations

- **Claude Code statusline** - consumes `rate_limits` from stdin JSON
  (https://code.claude.com/docs/en/statusline.md). `rate_limits` is present only for
  Pro/Max subscribers and only after the first API response of a session; each bucket
  may be independently absent. Always degrade gracefully.

## Deployment

Personal: `install.sh` on each machine. Distribution: packaged as a Claude Code
plugin/skill; install flow asks the user how they want the light displayed.

## Gotchas

- **The plugin version string gates updates.** `claude plugin update` only pulls a fresh copy
  when the version number in `plugin.json` changes; merging to `main` alone does NOT reach existing
  testers. Bump `plugin.json` + `pyproject.toml` for any change you want people to receive.
- **A running server caches Python code, not templates.** The serve handlers re-read the
  `*_template.html` files per request, but modules are cached in-process: after editing any
  `.py`, restart `scorch coa --serve` / `roe --web` before live-verifying (a 2026-07-02
  park-feature drive silently exercised the old code until restart).
- **Served tabs and browser cache:** every dynamic response sends `Cache-Control: no-store`
  (since v2.7.4; a reopened shell iframe was observed painting a stale cached page before).
- **The queue-file round-trip must carry every Job field.** `_job_to_dict` silently dropped
  `model` once (and `depth` before that); a new Job field needs adding there plus a
  round-trip check, or it vanishes on every queue-path run.
- `rate_limits` and either bucket can be missing early in a session → segment must
  emit nothing, never error (the statusline must keep rendering).
- `resets_at` is unix **seconds**, not ms.
- R needs a few samples that straddle real usage before it's trustworthy. Until then,
  the readout marks the estimate as provisional and can prompt the user for a starting
  value (their plan / observed windows-per-week).
- The 5h window resets independently of the weekly window - `windows_left` must count
  the partial current window plus full windows up to the weekly reset.
- **Straddle correction:** the current window's unused capacity is also capped by the time
  left before the *weekly* reset (`min(current_remaining, secs_to_weekly / WINDOW_SECONDS)`).
  Without this, a window straddling the weekly reset credits next week's capacity to this
  week and can flip the verdict (`max`→`push`). Tested by "straddle: still max …".
- **Cold-start forecast guard:** the linear fallback refuses to extrapolate when < 1 day of
  the weekly cycle has elapsed (or the reset is > 7 days out, i.e. clock skew) - otherwise the
  rate inflates several-fold (the old `max(0.25, elapsed)` floor) or goes negative. It returns
  a `low`/"too early in the cycle to forecast" result that assumes full spend (no false nudge).
- **Windows are sleep-discounted.** Counting every rolling 5h window (including overnight)
  overstates usable windows and under-warns. `core.compute(active_fraction=...)` scales the
  future tail by `active_hours/24`; `habits.active_hours` learns active hours from when the
  statusline fires (16h fallback). The current window isn't discounted (you're awake in it).
- **R can't be read live**, only estimated from Δweekly%/Δ5h% over time. Guard it: discard
  out-of-band per-pair estimates (`R_MIN..R_MAX`, ~1-20%) and hold the default until
  `MIN_PAIRS` clean pairs. A single noisy pair (e.g. 0.25) will otherwise swing the verdict.
- **Forecast is capped by capacity:** `habits.forecast(max_burnable=...)` caps
  `expected_remaining`, so projected leftover is never lower than the physical floor.
- **The sitrep recomputes live.** `report._stats` recomputes the recommendation AND forecast
  from the snapshot (not the cached `state.json` fields) and re-estimates R from calibration,
  so verdict/voice/projections never go stale. Canonical `HEADLINE` lives in `core.py`.
- **Fire animation:** the burn-mode fire is a continuously-animated canvas. Playwright
  screenshots time out on it - verify the report by opening it (`scorch --report`), not by
  screenshot. Consider pausing on `visibilitychange` later.
- **Skill-file cross-references must not be CWD-relative.** When a skill's markdown tells
  Claude to read a sibling file (e.g. SKILL.md → `setup.md`), a bare relative path resolves
  against the user's working directory and breaks whenever the skill is invoked from any repo
  other than the plugin root - the common case. Reference it via the skill's own directory
  (the harness provides the skill base dir on invocation) with an absolute `~/scorched-earth/
  skills/...` fallback, mirroring the `scorch || ~/scorched-earth/bin/scorch` PATH pattern.

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
marketplace + installer. War-general voice throughout. The statusline shows a six-state
firing deck, each with its own token + color: **🔥 BURN IT ALL** (`max`, red), **🟢 clear
shot, take it** (`push`, green), **⚪ eyes on the target** (`steady`, white), **⚠️ hold your
fire** (`ease`, yellow - the over-burn warning: at your recent pace you'll run dry before the
reset; self-disengaging so it never fights BURN IT ALL), and **🎖️ good job, soldier** (`done`,
purple Purple Heart, now prints instead of blanking). The `/scorched-earth` skill opens with a
**first-run setup** (sentinel-gated `~/.claude/scorched-earth/onboarded`): it primes Claude on
the model, tours the user, sets the light style, and links repos, then falls through to the
verdict; re-runnable, and never loaded once onboarded. Phase 2a (COA queue-runner) and Phase
2b (live cockpit) are built and DEFCON-native: jobs are rated by criticality (DEFCON 1-5,
1 = most critical) - budget estimation removed. ROE gates DEFCON 1-2 jobs behind
`auto_run_min_defcon` approval; `max_jobs` caps the run. The runner drains in DEFCON order
and halts on the real usage-limit (no predicted envelope). The scan role hunts overnight
DEFCON-1 campaigns. The cockpit kanban pushes live SSE board state per repo. All reports
(COA, After-Action) carry DEFCON badges; no budget columns. The COA report is also served
live with `scorch advise --serve` (`coa_view.py`): a 127.0.0.1 token-guarded page with per-repo
tabs and a Refresh button that re-reads each repo's `jobs.json` (no re-scan); `/coa`
background-launches it. The served page now stamps each repo with `scannedAt` (the `jobs.json`
mtime) so staleness is knowable, and `/coa` is **stale-aware**: it re-scans when the repo has
moved on since the last scan (a newer HEAD commit or a dirty tree), not just when `jobs.json`
is missing, so re-running actually refreshes. The cockpit `state_json` exposes `stopped` +
`stop_reason` (`operator` on Stop, `limit` on the usage-ceiling halt) so a halt is
distinguishable from a clean finish (the HALTED banner + staleness label render in the
merged-shell UI). Phase 2 opens with the **unified War Room shell** (`shell.py` +
`shell_template.html`): one 127.0.0.1 token-guarded server (the `coa_serve` server in shell
mode) hosts a big-tab frame over all three surfaces (SITREP / COURSE OF ACTION / WAR ROOM),
each an iframe backed by its existing renderer, unchanged. Tabs are hash-routed and lazy (the
cockpit SSE opens only when you enter the War Room). `scorch coa --serve` and
`scorch advise --serve` both launch it (on the cockpit and COA tabs respectively); the offline
`scorch --sitrep` file still writes standalone. Inside the shell so far: the cockpit shows a
**HALTED** banner + resume hint on a usage-limit halt (vs a clean IDLE), the COA tab shows a
**SCANNED Nh ago** freshness label with an honest Refresh (re-reads jobs.json, never re-scans),
the War Room has a manual **REFRESH** that pulls an external scan, and the SITREP tab has a
**Refresh** that reloads the server-rendered field (served mode only; the offline file omits it).
`/roe` now opens an
**interactive ROE editor** (`roe_edit.py` model + a curses arrow-key list, `hjkl` too;
`--json`/non-tty prints JSON) covering the wired rules.

**Phase 3 + 4 (execution engine + live progress) are built** (`exec_modes.py` + runner
extensions). A job runs in one of three **run modes**, picked from the new ROE `run_mode`
(global default + per-repo, resolved by `resolve_mode`): `headless` (the default: sandboxed
throwaway worktree, unattended), `takeover` (`scorch coa run --here <id>` execs an interactive
claude in your current window, still OS-sandboxed via a CLI `--settings` file so it never
touches the repo's own `.claude`), and `session` (`scorch coa run --session <id>` spawns a new
window, fully free, running an optional `context_cmd` like `/kerd:switch in` first). Attended
modes inject the ROE leash + goal as operating orders. Each job also gets a **per-task model**
(`--model`, chosen by the officer) and writes a **deliverable** to
`.scorched/deliverables/<id>.md` (surfaced in the AAR). The **roadblock safety net**: a stuck
job (silent past `roadblock_idle_secs`, default 600) or a failed gate becomes a `roadblocked`
outcome (branch kept); if `advise_on_roadblock` is on, one bounded **advising agent** tries to
recover, else the runner writes `.scorched/roadblocks/<id>.md`, fires a desktop notification,
and leaves it for `scorch coa resume <id>`. The War Room shows a **live progress line** (the
job's latest tool call / text) on the running card, pushed over the existing SSE (throttled), and
a full **CRT field monitor** (`▣ CRT`, a beige retro-monitor overlay with a green phosphor screen)
that streams every running job's steps. The shell now has a fourth tab, **AFTER-ACTION** (`/aar`),
which re-renders the latest run with an **OPEN** button on each deliverable/roadblock (served by a
token-guarded, path-validated `/artifact` route). The runner's worktree setup is idempotent: a
re-run over a leftover `scorched/<id>` branch clears the stale pair instead of hard-failing.

**v2.7.4 (the product-review release):** a full hands-on QA + code review of the 13-item
backlog work fixed one critical (a usage limit during `resume` destroyed the kept roadblock
work) and a wave of majors/minors: the CLI now dequeues finished jobs like the cockpit (a
re-run never silently re-executes), kept work always survives re-dispatch and mid-job limits
(auto-resume from the kept branch), a limit/kill during the advising attempt escalates instead
of reading as roadblocked, setup/gate subprocesses are killable, per-task `model` survives the
queue round-trip, the curses ROE editor survives short terminals, process-group kill, quoted
copy-paste commands, binary diffs counted, honest `scannedAt` (a scan-meta sidecar, not
jobs.json mtime), and `Cache-Control: no-store` on every served response. New features: the
ROE **attended_perms** dial (`skip` default: attended runs get `--dangerously-skip-permissions`
so a dispatched job works instead of queueing prompts; `edits` / `prompt` dial it back), and
the **served ROE editor** (the RULES OF ENGAGEMENT shell tab, launched by `/roe` via
`scorch roe --web`): a GLOBAL scope tab + per-repo rules-source toggles (follow global vs
repo-specific, with stripped overrides parked and restored on round-trip), instant-save clicks
through the token-guarded `POST /roe`, and a peace-of-mind SAVE button that verifies persisted
state without writing. `scorch roe --global` opens the terminal editor on the global rules.

78 unit checks (`python3 tests/test_scorched.py`) + 91 advisor checks
(`python3 tests/test_advisor.py`) + 139 runner checks (`python3 tests/test_runner.py`) +
116 cockpit checks (`python3 tests/test_cockpit.py`) = **424 total**; all gated in CI via
`.github/workflows/test.yml`. Forecast and R both start provisional and sharpen with real usage.
