# Scorched Earth

A fire-team readout for Claude usage: signals when remaining weekly budget can only be
spent by maxing out every remaining 5-hour window (BURN IT ALL), and when you're burning
so fast you'll run dry before the reset (hold your fire).

## Architecture (one line each)

- `src/scorched_earth/core.py` - pure math: snapshot + R (+ optional measured recent rate) → a six-state burn verdict (`max | push | steady | ease | done | unknown`). No I/O. The `ease` ("hold your fire") override replaces a `push`/`steady` call when a recent overpace would strand more than `EASE_IDLE_WINDOWS` usable windows before the reset; self-disengaging near the reset, mutually exclusive with `max`.
- `src/scorched_earth/calibrate.py` - self-measures R (weekly% burned per full window) from snapshot deltas.
- `src/scorched_earth/habits.py` - pure: cross-week history → day-of-week profile → end-of-week forecast + preemptive flag. Also `recent_per_window` (trailing ~2-day actual burn rate, % of weekly per window, that feeds core's `ease` check) and the field-view helpers: `average_days`, `week_days`, `last_completed_reset`, `current_week_days` (actual-so-far + projected-ahead).
- `src/scorched_earth/report.py` - generates the self-contained HTML **sitrep**: 8-bit war / scorched-earth crop-field HUD. THE FIELD is a Stardew-style pixel farm (procedural SVG engine ported from the design handoff) with a LAST WEEK / AVERAGE / THIS WEEK toggle; Python computes the data + HUD stats, a sliver of JS renders the field and live countdowns. `scorch --report` / `--sitrep`.
- `src/scorched_earth/state.py` - read/write snapshot, calibration, and habits files under `~/.claude/scorched-earth/`; the hot-path `update_from_statusline`.
- `src/scorched_earth/statusline.py` - statusline entry: parse stdin JSON, emit the light token, fire the once-per-week forecast notification (macOS `osascript` / Linux `notify-send`).
- `src/scorched_earth/gradient.py` - pure truecolor/256-color fire-gradient text for the `fire` light style and `scorch --fire-demo`.
- `bin/scorch` - CLI readout (hard signal + forecast), reads the cached snapshot, manual overrides for use outside Claude Code.
- `statusline-segment.sh` - thin bash wrapper the host statusline pipes `$DATA` into; emits the light token.
- `statusline-wrapper.sh` - plugin install path: runs the user's captured prior statusline + appends our token (so we wrap, never clobber). Suppresses its own token if the inner statusline already emits the segment (i.e. the user also ran `install.sh`), detecting it from the inner *source* rather than its output - the fire gradient randomizes colors each refresh, so output comparison can't spot the duplicate.
- `hooks/hooks.json` + `hooks/setup.sh` - SessionStart hook that idempotently wires the statusLine to the wrapper and seeds the style. Self-heals across plugin updates (version-stamped path) because it runs each session. Also installs **bare (unprefixed) command aliases** (`/coa`, `/sitrep`, `/roe`, `/war-room`, `/scorched-earth`) into the user's `~/.claude/commands/` by copying `commands/*.md` there - plugin commands are forced to the `/scorched-earth:` namespace, so this is the only way to give users the short forms. Collision-safe: each copy is tagged `managed-by: scorched-earth-plugin`, and the hook only writes files that are absent or already tagged - it never clobbers a command the user wrote themselves.
- `skills/scorched-earth/SKILL.md` - `/scorched-earth` in-session readout + conversational style-setting. Opens with a first-run gate: on the user's first invocation (no `onboarded` sentinel) it routes to `setup.md`, then falls through to the readout.
- `skills/scorched-earth/setup.md` - guided first-run setup the gate delegates to: primes Claude on the model (self-contained primer - green-light math + DEFCON/COA), then tours the user, sets the light style, and links repos. Re-runnable on demand; never loaded on the routine readout path (so it costs nothing once onboarded).
- `commands/sitrep.md` - `/sitrep` slash command: runs `scorch --sitrep` to generate + open the HTML report.
- `install.sh` - manual (non-plugin) install: puts `scorch` on PATH, offers light styles, wires the segment.
- `.claude-plugin/plugin.json` - plugin manifest. Skills/commands/hooks/bin are auto-discovered by directory convention (no explicit declaration needed).
- `src/scorched_earth/jobs.py` / `roe.py` / `advisor.py` - COA advisor: job schema (rated by DEFCON 1-5 criticality), rules of engagement (`auto_run_min_defcon` approval gate, `max_jobs`), and the pure DEFCON-sorted matcher. No I/O.
- `src/scorched_earth/coa_report.py` - renders a COA result to Markdown (the record) and HTML (the presentation) from one structured source; DEFCON badges replace budget columns. `render_html` takes either a single COA or `repos=[(path, COA), …]` for the **multi-repo tabbed view**, and a `token` that arms the in-page Refresh button (served mode). HTML fills `coa_template.html` by injecting one JSON blob (`__COA_JSON__`) + the token (`__COA_TOKEN__`).
- `src/scorched_earth/coa_template.html` - the self-contained war-HUD COA template. Its JS `paint()`s the active repo's battle plan from `DATA.repos[active]`; when there's >1 repo it shows a **per-repo tab strip** (mirrors the cockpit tabs). When `__COA_TOKEN__` is set it shows a **Refresh** button that fetches `/coa.json` and repaints (served mode); static file:// renders just bake the data in.
- `src/scorched_earth/coa_view.py` - the **served, read-only COA**: a tiny 127.0.0.1 token-guarded `ThreadingHTTPServer` (`GET /` → the tabbed page, `GET /coa.json` → fresh `coa_state`). `coa_state` re-reads each repo's `jobs.json` + ROE and re-runs the pure matcher - it never re-scans the repos, and stamps each repo with `scannedAt` (the `jobs.json` mtime, via `coa_io.jobs_scanned_at`) so the page can show staleness. Its `render_page` + `coa_state` now also back the **COURSE OF ACTION tab of the merged shell** (Phase 2); its own `make_server` is retained (and tested) but the CLI no longer launches it standalone - `scorch advise --serve` opens the shell on the COA tab instead.
- `src/scorched_earth/coa_io.py` - advisor I/O: the linked-repos registry, ROE/jobs loaders, COA output writers (central config + per-repo `.scorched/`).
- `src/scorched_earth/runner.py` - COA queue-runner (Phase 2a): drains `.scorched/queue.json` in DEFCON order under the ROE leash; halts on a real usage-limit (no budget envelope). `plan_run` is the pure pre-run disposition core; the per-job work is the injected `execute_job`. I/O tier; never on the statusline hot path.
- `src/scorched_earth/review_report.py` + `review_template.html` - renders the live After-Action Report (md + HTML) from one `RunResult`; DEFCON badges per job; auto-refreshes while running, settles when done.
- `src/scorched_earth/coa_serve.py` + `cockpit_template.html` - COA live cockpit (Phase 2b): a 127.0.0.1 `ThreadingHTTPServer` (one-time token, job-ids-not-commands, ROE server-side) hosting an event-driven `Engine.advance` step (no background loop) that drains by DEFCON and halts on the real rate limit; SSE pushes board state to a kanban cockpit. `state_json` exposes `stopped` + `stop_reason` (`operator` on Stop, `limit` on the usage-ceiling halt) so the UI can distinguish a halt from a clean finish. `make_server(shell_repos=…)` also runs in **shell mode** (Phase 2): it serves the merged big-tab frame at `/`, moves the cockpit to `/war-room`, and folds in the read-only tabs (`/sitrep`, `/coa`, `/coa.json`) under the one token so a single server hosts all three surfaces; `/favicon.ico` short-circuits to 204 before the token gate. `scorch coa --serve`.
- `src/scorched_earth/shell.py` + `shell_template.html` - the **unified War Room shell** (Phase 2, #13): one big-tab frame (SITREP / COURSE OF ACTION / WAR ROOM) served by the single `coa_serve` server in shell mode. Each tab is an iframe backed by an existing renderer, unchanged: `render_sitrep` (the served weekly SITREP, via `report.render_html`), the read-only COA (`coa_view`), and the live cockpit. Tabs are hash-routed (`#sitrep|#coa|#war-room`) and lazy (an iframe loads only on first visit, so the cockpit SSE opens only when you enter the War Room). `render_shell` fills `shell_template.html` (`__SHELL_TOKEN__`). Both `/coa` (opens on the COA tab) and `/war-room` (opens on the cockpit tab) launch it; static `scorch --sitrep` still writes the offline file.
- `commands/coa.md` / `commands/roe.md` - `/coa` (generate a Course of Action) and `/roe` (edit the Rules of Engagement).
- `commands/war-room.md` - `/war-room` slash command: background-launches `scorch coa --serve` (now the unified shell, opened on the live cockpit tab) and hands back the token URL; `/war-room stop` kills it.

## Packaging facts (confirmed against installed plugins + docs)

- `rate_limits` (the weekly/5h usage data) is delivered ONLY to the statusLine command - no hook, skill, or slash command can read it. The statusline is therefore the mandatory engine.
- A plugin manifest cannot contribute a `statusLine` (it's a settings.json field). The SessionStart hook writes it. settings.json is read at launch, so a freshly-wired statusLine takes effect next session.
- Plugin `bin/` is on PATH only inside Claude Code's Bash tool, not the user's terminal - `install.sh` symlink covers terminal use.
- `userConfig` is not used (no real-world examples; undocumented runtime exposure). The style choice is handled conversationally by the skill / `scorch --style` instead.

State files under `~/.claude/scorched-earth/`: `state.json` (latest snapshot + recommendation + forecast), `calibration.json` (R samples, resets weekly), `habits.json` (cross-week history, does NOT reset), `style` (light style), `fc-notified` (last weekly cycle nudged), `onboarded` (first-run setup completed - its presence makes the skill skip setup).

## Invariants

- `core.py` stays pure and dependency-free (stdlib only) so it runs in the statusline hot path.
- The statusline must keep working if scorched-earth fails - the segment degrades to empty, never errors out.
- R is a plan constant (ratio of 5h cap to weekly cap), measured from the user's own deltas, not hardcoded.
- The burn deck is six states (`max | push | steady | ease | done | unknown`) with a fixed palette: red BURN IT ALL, green clear shot, white eyes on the target, yellow hold your fire, purple good job soldier (Purple Heart). The level *keys* are meaning-based, never color names. `ease` is computed in `core` but the caller passes the measured recent rate in, so `core` stays pure. Keep the COA/DEFCON color code separate; it does not use these keys.
- No em dashes or en dashes in docs, UI strings, CLI output, or commit text. Use commas, colons, periods, or parentheses. The repo was scrubbed clean; keep it that way (regular hyphens in compound words are fine).

## Session Workflow

When wrapping up a session (`/kerd:switch out` or `/kerd:dian`):
1. Update `TODO.md`: check off completed items, add new ones.
2. Update `docs/playbook.md`: new steps/tools/config, and always the "Current Status" section.

## Doc Impact Table

| Doc | Update When |
|-----|-------------|
| README.md | Project description, setup steps, or structure changes |
| docs/playbook.md | New setup steps, integrations, gotchas, tech stack changes, or status changes |
| docs/the-math.md | The model, thresholds, or calibration approach changes |
| TODO.md | Every session close-out |
