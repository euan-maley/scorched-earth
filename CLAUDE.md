# Scorched Earth

A green light for Claude usage: signals when remaining weekly budget can only be
spent by maxing out every remaining 5-hour window.

## Architecture (one line each)

- `src/scorched_earth/core.py` — pure math: snapshot + R → hard recommendation. No I/O.
- `src/scorched_earth/calibrate.py` — self-measures R (weekly% burned per full window) from snapshot deltas.
- `src/scorched_earth/habits.py` — pure: cross-week history → day-of-week profile → end-of-week forecast + preemptive flag. Also the field-view helpers: `average_days`, `week_days`, `last_completed_reset`, `current_week_days` (actual-so-far + projected-ahead).
- `src/scorched_earth/report.py` — generates the self-contained HTML **sitrep**: 8-bit war / scorched-earth crop-field HUD. THE FIELD is a Stardew-style pixel farm (procedural SVG engine ported from the design handoff) with a LAST WEEK / AVERAGE / THIS WEEK toggle; Python computes the data + HUD stats, a sliver of JS renders the field and live countdowns. `scorch --report` / `--sitrep`.
- `src/scorched_earth/state.py` — read/write snapshot, calibration, and habits files under `~/.claude/scorched-earth/`; the hot-path `update_from_statusline`.
- `src/scorched_earth/statusline.py` — statusline entry: parse stdin JSON, emit the light token, fire the once-per-week forecast notification (macOS `osascript` / Linux `notify-send`).
- `src/scorched_earth/gradient.py` — pure truecolor/256-color fire-gradient text for the `fire` light style and `scorch --fire-demo`.
- `bin/scorch` — CLI readout (hard signal + forecast), reads the cached snapshot, manual overrides for use outside Claude Code.
- `statusline-segment.sh` — thin bash wrapper the host statusline pipes `$DATA` into; emits the light token.
- `statusline-wrapper.sh` — plugin install path: runs the user's captured prior statusline + appends our token (so we wrap, never clobber).
- `hooks/hooks.json` + `hooks/setup.sh` — SessionStart hook that idempotently wires the statusLine to the wrapper and seeds the style. Self-heals across plugin updates (version-stamped path) because it runs each session. Also installs **bare (unprefixed) command aliases** (`/coa`, `/sitrep`, `/roe`, `/war-room`, `/scorched-earth`) into the user's `~/.claude/commands/` by copying `commands/*.md` there — plugin commands are forced to the `/scorched-earth:` namespace, so this is the only way to give users the short forms. Collision-safe: each copy is tagged `managed-by: scorched-earth-plugin`, and the hook only writes files that are absent or already tagged — it never clobbers a command the user wrote themselves.
- `skills/scorched-earth/SKILL.md` — `/scorched-earth` in-session readout + conversational style-setting. Opens with a first-run gate: on the user's first invocation (no `onboarded` sentinel) it routes to `setup.md`, then falls through to the readout.
- `skills/scorched-earth/setup.md` — guided first-run setup the gate delegates to: primes Claude on the model (self-contained primer — green-light math + DEFCON/COA), then tours the user, sets the light style, and links repos. Re-runnable on demand; never loaded on the routine readout path (so it costs nothing once onboarded).
- `commands/sitrep.md` — `/sitrep` slash command: runs `scorch --sitrep` to generate + open the HTML report.
- `install.sh` — manual (non-plugin) install: puts `scorch` on PATH, offers light styles, wires the segment.
- `.claude-plugin/plugin.json` — plugin manifest. Skills/commands/hooks/bin are auto-discovered by directory convention (no explicit declaration needed).
- `src/scorched_earth/jobs.py` / `roe.py` / `advisor.py` — COA advisor: job schema (rated by DEFCON 1-5 criticality), rules of engagement (`auto_run_min_defcon` approval gate, `max_jobs`), and the pure DEFCON-sorted matcher. No I/O.
- `src/scorched_earth/coa_report.py` — renders a COA result to Markdown (the record) and HTML (the presentation) from one structured source; DEFCON badges replace budget columns. HTML fills the bundled `coa_template.html` by injecting one JSON blob (same pattern report.py uses for the sitrep).
- `src/scorched_earth/coa_template.html` — the self-contained war-HUD COA template (from the design handoff). `render_html` substitutes its `__COA_JSON__` token with the live data; the template's JS renders the battle plan (DEFCON badges, no budget gauge) from that one object.
- `src/scorched_earth/coa_io.py` — advisor I/O: the linked-repos registry, ROE/jobs loaders, COA output writers (central config + per-repo `.scorched/`).
- `src/scorched_earth/runner.py` — COA queue-runner (Phase 2a): drains `.scorched/queue.json` in DEFCON order under the ROE leash; halts on a real usage-limit (no budget envelope). `plan_run` is the pure pre-run disposition core; the per-job work is the injected `execute_job`. I/O tier; never on the statusline hot path.
- `src/scorched_earth/review_report.py` + `review_template.html` — renders the live After-Action Report (md + HTML) from one `RunResult`; DEFCON badges per job; auto-refreshes while running, settles when done.
- `src/scorched_earth/coa_serve.py` + `cockpit_template.html` — COA live cockpit (Phase 2b): a 127.0.0.1 `ThreadingHTTPServer` (one-time token, job-ids-not-commands, ROE server-side) hosting an event-driven `Engine.advance` step (no background loop) that drains by DEFCON and halts on the real rate limit; SSE pushes board state to a kanban cockpit. `scorch coa --serve`.
- `commands/coa.md` / `commands/roe.md` — `/coa` (generate a Course of Action) and `/roe` (edit the Rules of Engagement).
- `commands/war-room.md` — `/war-room` slash command: background-launches `scorch coa --serve` (the live cockpit) and hands back the token URL; `/war-room stop` kills it.

## Packaging facts (confirmed against installed plugins + docs)

- `rate_limits` (the weekly/5h usage data) is delivered ONLY to the statusLine command — no hook, skill, or slash command can read it. The statusline is therefore the mandatory engine.
- A plugin manifest cannot contribute a `statusLine` (it's a settings.json field). The SessionStart hook writes it. settings.json is read at launch, so a freshly-wired statusLine takes effect next session.
- Plugin `bin/` is on PATH only inside Claude Code's Bash tool, not the user's terminal — `install.sh` symlink covers terminal use.
- `userConfig` is not used (no real-world examples; undocumented runtime exposure). The style choice is handled conversationally by the skill / `scorch --style` instead.

State files under `~/.claude/scorched-earth/`: `state.json` (latest snapshot + recommendation + forecast), `calibration.json` (R samples, resets weekly), `habits.json` (cross-week history, does NOT reset), `style` (light style), `fc-notified` (last weekly cycle nudged), `onboarded` (first-run setup completed — its presence makes the skill skip setup).

## Invariants

- `core.py` stays pure and dependency-free (stdlib only) so it runs in the statusline hot path.
- The statusline must keep working if scorched-earth fails — the segment degrades to empty, never errors out.
- R is a plan constant (ratio of 5h cap to weekly cap), measured from the user's own deltas, not hardcoded.

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
