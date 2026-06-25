# TODO

## Current Session (2026-06-25) — DEFCON COA refactor landed; full sweep + docs

**DONE this session:**
- [x] **DEFCON COA refactor** (Tasks 1-10): budget estimation removed entirely. Jobs rated by DEFCON 1-5 criticality (1 = most critical); `auto_run_min_defcon` approval gate replaces budget threshold; `max_jobs` caps the run. Runner drains in DEFCON order, halts on real usage-limit (no predicted envelope). Scan hunts overnight DEFCON-1 campaigns. All four reports (COA HTML/MD, After-Action HTML/MD) carry DEFCON badges; no budget columns.
- [x] **Task 11 (sweep + docs):** straggler grep clean; dead code removed (`_EPS`, `board_state` dead advisor import, `.cdepth` CSS, redundant test assertions); `render_md` markdown spacing fixed; CLAUDE.md, playbook, TODO updated. Test counts: 57 + 34 + 78 + 70 = 239 all green.

---

## Prior Session — published COA stack to public `main`; DEFCON refactor WIP; full CRT demo video built

**Repo state:**
- **public `main`** (origin, `df0dd5b`): the full COA advisor stack SHIPPED — Phase 1 + 2a/2b/2c + depth + multi-repo + **parallel per-repo execution** + the **budget→headroom UX revision** + `/war-room`. Installable via `/plugin marketplace add euan-maley/scorched-earth`. Internal `docs/superpowers/` stripped from the public tree (kept at `~/Downloads/scorched-earth-planning-docs/`); they remain in git history (offer a history scrub if it matters).
- **`feat/defcon-coa`** (LOCAL, 8 commits, UNPUSHED — current branch): the **DEFCON refactor** — replaces budget/cost estimation entirely with a **DEFCON 5–1 criticality rating** (impact, not cost) + an **approval / `auto_run_min_defcon` gate**. spec + plan (11 tasks) + 6 feat commits across jobs/roe/advisor/coa_io/runner/coa_serve + tests. **DEFCON 1 = biggest blast radius** (whole-codebase audits, full test-suite builds, backend creations) — NOT "do first." **New COA HTML render pending** (user building).

**DONE this session:** parallel per-repo execution (SDD, 2 tasks + fixes); cockpit proposed-flicker fix; `/war-room` command; **COA budget→headroom UX revision** (brainstorm→spec→plan→7 tasks + final-review fix wave: `_run_killable` deadlock, queue-CLI forfeit, exit-code phantom-pass); **published** the stack to public `main`; built a market-quality **CRT demo video**.

**Demo/video (NOT in repo — PRESERVED to `~/Downloads/scorched-earth-captures/`):**
- `tour_crt.mp4` (~74s) = deliverable: 8-bit **beige CRT** (convex barrel-warp via `lenscorrection k1=+0.13`, phosphor glow `eq=brightness=0.020:gamma=1.11`), green-on-black **terminal title cards** with frame-perfect plastic key-click audio (every ~2 *visible* glyphs; spaces don't click), and the 3 product demos (**SITREP → COURSE OF ACTION → WAR ROOM**) all CRT-framed with synthetic-cursor + lower-third captions.
- **Pipeline at `~/Downloads/scorched-earth-captures/_pipeline/`** (scripts + `seg/` intermediates + wavs + `*_clicks.json` + `tour.txt`). See `_pipeline/HANDOFF.md`. Recreate venv: `python3 -m venv pwenv && pwenv/bin/pip install playwright` (chromium cached in `~/Library/Caches/ms-playwright`). NB: scripts hardcode the OLD scratchpad path in `SP=` — repoint to the pipeline dir when resuming.

**RESUME HERE when the DEFCON COA page is ready:** user sends path/URL → (1) re-record it in the capture rig (CRT), (2) swap into the tour in place of `coa_t_crt`, (3) update the `scorch advise` divider + 3 COA captions to the **locked DEFCON wording**:
- divider: `ranking every operation by impact — DEFCON 5 to 1 …`
- cap 1: `COURSE OF ACTION · DEFCON-ranked target list` · cap 2: `every target rated DEFCON 5–1 · impact, not cost` · cap 3: `DEFCON 1 = biggest blast radius`
- (intro list line ALREADY says `DEFCON-ranked target list`.)
- Also: decide when to finish/merge `feat/defcon-coa` (supersedes the just-published budget model).

---

## Prior Session — COA advisor + cockpit, FULLY built through multi-repo · branch `feat/burn-advisor` · 215 checks green

Huge session (61 commits). Built the entire **COA execution stack** on top of Phase 1, each
phase brainstorm→spec→plan→subagent-driven-dev (fresh implementer + independent review per
task, opus on the security/concurrency/budget cores, opus whole-branch final review). All
**LOCAL/unpushed** by choice so public `main` stays clean. Suite: 57 core + 34 advisor + 65
runner + 59 cockpit = **215 green**.

**DONE this session (all reviewed "ready to merge"):**
- [x] **Phase 2a — queue-runner** (`runner.py`): drains `.scorched/queue.json`, runs each job headless `claude -p` in a sandboxed git worktree (Claude Code OS sandbox via worktree-local `.claude/settings.json`: API-only network, `failIfUnavailable`, no escape hatch — confirmed flags via claude-code-guide), additive-only ROE leash, commit-not-push, test gate, predictive budget (can't read live rate_limits — predict + re-sync on snapshot advance). HTML **After-Action Report** (`review_report.py` + `review_template.html`) doubles as live monitor (auto-refresh) and debrief.
- [x] **AAR + COA + cockpit design HTMLs** integrated from Claude-design handoffs (briefs in `docs/design/`): `review.html`→`review_template.html`, `cockpit.html` (War Room)→`cockpit_template.html`. Drop-in via `__*_JSON__` token contract; I caught/fixed contract collisions each time (token-in-comment, `<head>` injection, `.cwin`→`.cdepth` styling).
- [x] **Phase 2b — live cockpit** (`coa_serve.py` + `cockpit_template.html`): `scorch coa --serve` → 127.0.0.1 ThreadingHTTPServer (one-time token every request, job-ids-not-commands, repo validated, ROE server-side) hosting a kanban War Room; event-driven `Engine.advance` (no bg loop, while-loop, 4 runaway guards); SSE pushes board state; drag queue/reorder, Run/Stop. EnvelopeTracker (predict-then-resync), pick_next, board_state, queue I/O.
- [x] **Phase 2c — Kill** a running job (`_run_killable` Popen SIGTERM→SIGKILL + thread-local `_kill_ctx`; `Engine.kill` + `POST /kill`; KILL button). Always discards work, no refund, killed→Proposed, chain continues. Operator-intent-wins fix.
- [x] **DEPTH 1–10 rating** replaces shown window cost: agent emits `depth`, `est_windows` derived (coarse band, internal for matcher/runner, never shown per-card). Backward-compat both ways. Cards show DEPTH, drop window cost + S/M/L/XL tier; aggregate gauges keep windows.
- [x] **Multi-repo run** (one job at a time, GLOBALLY): per-repo trackers → ONE global EnvelopeTracker (shared budget, honest); `run(repos)` sweeps an active set sequentially; `/run` accepts a repos list; cockpit repo **checkboxes** (default armed, seenRepos auto-arm) + Run-all.
- [x] **Cockpit UX polish**: starts **paused** (stage queue, then Run); bigger Run/Stop; **REPOS** tab-strip label; global **NOW RUNNING** header readout + active-repo tab marker; **fixed** depth-snapping-on-queue (`_job_to_dict` now persists `depth`); fixed Stop-is-permanent (Run clears stop); fixed rapid-/queue lost-update (mutations under the lock) + atomic write_queue.

**IN PROGRESS — resume HERE next session:**
- [ ] **Parallel per-repo execution** — user wants checked repos to run **concurrently** (separate queues, one job per repo, repos at the same time), NOT the one-at-a-time sweep I built. **PLAN WRITTEN, NOT BUILT**: `docs/superpowers/plans/2026-06-24-parallel-repos.md` (commit 817dccd). 2 tasks: (1) Engine — one drain worker per repo + ONE global EnvelopeTracker with **charge-at-pick reservation under the lock** so concurrent workers can't overspend the shared pool; per-repo `_running`/`_kill_events`/`_workers`; `state_json.running` becomes a LIST. (2) Cockpit — render multiple RUNNING. **Next session: dispatch Task 1 via subagent-driven-development** (fresh ledger, opus review on the concurrency/budget core). Was mid-sentence presenting the plan when the user said switch out.

**Live demo (throwaway, NOT in repo):** `<scratchpad>/warroom_demo.py` — real server + War Room template but a STUB executor (no real claude, no budget burned, no repos touched). Two fake repos for the tab toggle; jobs honor Kill; paused-default. Re-create from the session log if needed.

**Decisions to keep:** officer-briefs-you voice; additive-only unattended (transformative=review-required); one global budget pool (sequential now / reserve-concurrently in the parallel plan); cockpit URL embeds the token (don't paste/screenshot); per-repo `max_windows` yields to the global pool in multi-repo. **scorched-earth has ZERO dependency on superpowers** (that's just my build tooling); `docs/superpowers/` is committed planning docs only.

**Backlog (none merge-blocking):** setup_cmd pre-warm still `capture_output=True` (pipe-buffer deadlock risk → DEVNULL); torn/atomic writes for `_persist` HTML; cookie-based SSE auth (keep token out of URLs); dead `TIER` const in coa/review templates; KILL button optimistic UI nudge; assorted Phase-1 Minors (roe null-clear; advisor epsilon; render_md escaping).

## Earlier Session

- [x] Scaffold kerd structure + git
- [x] Core burn-rate math module + state/calibration
- [x] `scorch` CLI (hard signal + forecast, manual overrides)
- [x] Statusline segment + wire into ~/.claude/statusline.sh
- [x] Package: skill + plugin manifest + installer with light-style options
- [x] Habits/forecast: day-of-week profile, projection, preemptive once-per-week nudge
- [x] Plugin packaging: SessionStart hook wires statusline (wraps existing), bin/skill auto-discovered, `scorch --style`
- [x] Verdict: ship all three layers as one plugin (statusline engine + CLI + skill); see CLAUDE.md packaging facts

- [x] Marketplace entry (`.claude-plugin/marketplace.json`, single-repo `source: "./"`)

## Readiness Audit (2026-06-24) — fixed before publish

Multi-agent audit (correctness / safety / packaging / testing / arch / design+dx / concept):
- [x] **Correctness:** windows_left straddle over-count (credited next-week capacity); forecast cold-start rate inflation + >7d-out reset; concurrent-statusline `.tmp` write race (now pid-unique); report dead-code weeks bug
- [x] **Safety/robustness:** report KeyError on unknown level; tolerant `Snapshot.from_dict` (schema drift no longer crashes CLI/report); state files now `0600`
- [x] **DX/UX honesty:** partial manual flags now error instead of silently ignoring; `--report` refuses to fabricate a zeros dashboard before any reading; cross-platform open (`xdg-open`) + notify (`notify-send`)
- [x] **Docs truth:** SKILL.md "SCORCH"→"BURN IT ALL" + fire style listed; default-style clarified (fire seeded at install); the-math.md default-R note + multi-bucket caveat; playbook test count; README placeholders + platform note + light states
- [x] **Tests/CI:** 33→57 checks (straddle, verdict-flip regression, cold-start, from_dict, report render, state round-trip + corruption recovery, statusline never-errors invariant); harness collects failures instead of aborting; GitHub Actions CI added
- [x] **Packaging:** `pyproject.toml` (python ≥3.8 floor); gradient.py documented in CLAUDE.md
- [x] **Add a git remote + push** (private GitHub)

## Backlog

- [x] Pre-public prep: MIT `LICENSE` file added; `homepage`/`repository` in `plugin.json`; untracked `kivna/` + `.slainte` (gitignored, kept local — no second machine so the handoff loss is fine). Repo is publish-clean except for the deliberate choice to leave `TODO.md` tracked.
- [x] **Published public** (2026-06-24). Logo + landscape banner, sitrep screenshots, embedded mp4 player in the README, `/sitrep` command. README skriv-passed.
- [x] Slimmed git history: stripped dead demo binaries (old gif/webm, burn/poster PNGs) via `filter-branch` + force-push. `.git` 20M → 7.1M (fresh clones get the small pack; GitHub's reported size lags until their server gc). Pre-strip backup bundle at `~/Downloads/scorched-earth-preslim.bundle`.
- [ ] `scorch --watch` live re-print (flag exists; field-test it)
- [ ] Optional: surface the 🔥 forecast nudge on the statusline too (not just notify)
- [ ] Let users tune "active hours" manually (currently learned only)
- [ ] Fire perf: it's canvas-animated; consider pausing when tab hidden (visibilitychange)
- [ ] R/active-hours still learning on this machine (~2 readings); sharpen over a couple weeks
