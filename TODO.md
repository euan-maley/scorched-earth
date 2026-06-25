# TODO

## Current Session (2026-06-25, pt.4) — DEFCON stack PUBLISHED (v1.6.9); public docs aligned + skriv

**DONE this session:**
- [x] **v1.6.9 published to public `origin/main`** (`d719659`, the user's release commit, pushed externally between pt.3 and pt.4). DEFCON COA + `⚪ no rush` tier + first-run setup are now LIVE publicly. Release bumped plugin.json/pyproject 1.6.7→1.6.9 and stripped `docs/superpowers/` planning docs (incl. the pt.3 specs) from the public tree.
- [x] **Audited + aligned all public-facing writing** to current capabilities (`7787033`, pushed). README gained a "Burn it on something" COA section + first-run-setup note + `/coa` `/roe` `/war-room` in the install list; plugin.json + both marketplace.json descriptions now name the DEFCON COA layer. **skriv:** fixed 3 dash-as-punctuation in public copy (README no-rush line, coa.md + war-room.md descriptions); command *bodies* left as-is (technical instructions, skriv-exempt).
- [x] **Verified every cited capability is real & working** before writing: live `scorch advise` (9-job DEFCON COA), `/war-room` cockpit boots on 127.0.0.1 w/ one-time token, `scorch roe`/`coa review` respond, JSON re-validated.

**RESOLVED:** the long-standing "decide whether to push" question — published as **v1.6.9**; local `main` == `origin/main` (in sync).

**RESUME / open:**
1. **Demo-video DEFCON COA swap** (open since pt.2, now fully unblocked — the COA render exists AND is public): re-record CRT-framed, swap into the tour in place of `coa_t_crt`, relock the 3 COA captions + `scorch advise` divider to the DEFCON wording. Pipeline at `~/Downloads/scorched-earth-captures/_pipeline/`.
2. Optional polish: a real `scorch list` subcommand (first-run setup confirms repos via `cat repos.json`).
3. Confirm the two stripped specs (first-run-setup, no-rush-tier) are backed up locally if wanted — v1.6.9 removed them from the repo tree.

---

## Prior Session (2026-06-25, pt.3) — "no rush" statusline tier + first-run setup, both MERGED to local main

**DONE this session** (subagent-driven-development, lean: spec→implementer→task-review→fix per feature; each single-task branch's review doubled as the whole-branch gate):
- [x] **Visible "no rush" tier** (`bd7945f`, `4265242`; branch `feat/no-rush-tier`, merged FF). Split `compute()`'s overloaded `off` into **`low`** (deep reserves → statusline shows **`⚪ no rush`**, dim) and **`off`** (weekly budget exhausted). Ladder is now `low → amber → green`; amber/green and the thresholds (GREEN 1.0, AMBER 0.70) untouched. Also fixed a latent bug — the exhausted case used to print `HEADLINE["off"]` = *"Well stocked…"*; each state now gets its true banner. Touched `core.py` · `statusline.py` · `report.py` · `bin/scorch` + the-math/README; 8 new checks (`test_scorched` 57→65). Review caught 2 doc gaps the spec mandated + a loose test assert — all fixed.
- [x] **First-run setup for `/scorched-earth`** (`b136a6a`→`e94855a`; branch `feat/first-run-setup`, merged --no-ff). New `skills/scorched-earth/setup.md` (self-contained primer + guided flow); SKILL.md gate keyed on sentinel `~/.claude/scorched-earth/onboarded`. Flow: familiarize Claude → tour user → pick light style → link repos (`scorch link`, optional) → write sentinel + fall through to verdict. Re-runnable; never loaded once onboarded (zero routine cost). Review caught an **Important** path bug (bare CWD-relative `setup.md` ref broke when run from any other repo) → now resolves via the skill's own directory w/ `~/scorched-earth/...` fallback. Note: `scorch list` doesn't exist (spec assumed it did) → used `cat repos.json`.
- [x] Docs folded in: CLAUDE.md (setup.md architecture line + `onboarded` sentinel), `docs/the-math.md` (5-state enum), README (three-tier readout), `docs/playbook.md` (flow + Current Status + test count), this TODO.
- [x] **Suites green on merged main: 65 + 34 + 78 + 70 = 247.** Feature branches deleted.

**Specs:** `docs/superpowers/specs/2026-06-25-no-rush-tier-design.md`, `docs/superpowers/specs/2026-06-25-first-run-setup-design.md`.

**NOT pushed:** local `main` is now **26 commits ahead of `origin/main`** (DEFCON refactor + these two features). Same keep-WIP-local pattern.

**RESUME / open:**
1. Still pending from pt.2: decide whether to **push** local `main` to public `origin/main`, and the **demo-video DEFCON COA swap** (unblocked).
2. Optional polish: in setup the repo-list confirmation reads raw `repos.json` (no `scorch list` verb exists) — a clean `scorch list` subcommand could replace the `cat`.

---

## Prior Session (2026-06-25, pt.2) — DEFCON COA refactor COMPLETE + MERGED to local main

**DONE this session:**
- [x] **DEFCON COA refactor** (full SDD run: 11 tasks + opus whole-branch final review + fix wave, every gate reviewed clean): budget/effort estimation removed entirely from the COA layer. Jobs rated by **DEFCON 1-5** criticality (1 = most critical / biggest blast radius); `auto_run_min_defcon` approval gate (DEFCON 1-2 need approval; batch `scorch coa run --approve`, cockpit auto-approves as operator-driven); `max_jobs` caps the run. Runner/cockpit drain in DEFCON order, halt on the **real** usage-limit (predictive EnvelopeTracker/headroom deleted; `_run_killable` untouched). Scan prompt hunts **overnight DEFCON-1 campaigns** alongside knockouts. All HUDs (COA, After-Action, cockpit) render DEFCON badges + approval markers; no budget UI.
- [x] **New COA HTML render DONE** (this was the demo-swap blocker — now cleared). Preview script pattern at `/tmp/coa-defcon-preview.html`.
- [x] **UI tweaks** (`coa_template.html`): ROE header now reads "RULES OF ENGAGEMENT *(as set by user)*"; each command box carries a dim **`RUN CMD`** label + hover tooltip clarifying it's a run/execute command.
- [x] **Merged to LOCAL `main`** (fast-forward → `e8a8881`); `feat/defcon-coa` branch deleted. Suites green on merged main: **57 + 34 + 78 + 70 = 239**.

**NOT pushed (user said "not for now"):** local `main` is **17 commits ahead of `origin/main`** (`8779732`, still the 1.6.7 version bump). The DEFCON refactor + this close-out are LOCAL only. `origin/main` still serves the older budget-model COA.

**RESUME HERE next session:**
1. **Decide whether to push** the DEFCON work to public `origin/main` (it supersedes the just-published budget model). If yes: `git push origin main`.
2. **Demo-video swap** (now unblocked — the new COA page exists): re-record the DEFCON COA HTML in the CRT capture rig, swap into the tour in place of `coa_t_crt`, update the `scorch advise` divider + 3 COA captions to the locked DEFCON wording (see the Prior Session block below + `_pipeline/HANDOFF.md`).

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
