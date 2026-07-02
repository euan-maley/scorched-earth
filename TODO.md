# TODO

## Current Session (2026-07-02, pt.2): product review of the 13-item backlog work

Goal: review the shipped features from the 2026-07-01 backlog list, hands-on QA first, then code review of the riskiest/flagged areas. Fix small as we go, report big for triage.

1. [ ] Setup: confirm linked repos + staged jobs, boot `scorch coa --serve` (shell) in background, connect Playwright
2. [ ] QA sweep A (browser): shell tabs #13, sitrep refresh #12, freshness #5/#6, approval tooltips #1, cratered legend #9, AFTER-ACTION tab + OPEN buttons
3. [ ] QA sweep B (live run): one real haiku docs job; live progress #7, CRT monitor, deliverable -> AAR OPEN
4. [ ] QA sweep C (terminal/engine): ROE editor #10 (pty), run modes #3/#4 (--session real spawn, takeover to the exec boundary), roadblock ladder #11 (stalling stub + resume), HALTED #2/#8 (crafted limit state, real limit unforceable)
5. [ ] Code review: parallel agents on /artifact, exec_modes.py, runner roadblock ladder, coa_serve shell routes + QA-flagged areas
6. [x] Findings: small fixes committed as found (docs in same commit); ranked findings list for triage
7. [x] Fix wave: all review findings fixed (fable on the runner-semantics core, sonnet agents on the mechanical batches); attended_perms ROE dial added (user request)
8. [x] ROE editor HTML frontend (#10 follow-up, user request): a 5th shell tab over the roe_edit model behind a guarded POST /roe; /roe command launches it via `scorch roe --web` (built + browser-verified; closes the last Phase 2 roadmap item)

---

## Prior Session (2026-07-02): merge, release v2.7.2/v2.7.3, CRT + AAR tab, hands-on haiku, dispatch image - DONE

Shipped Phase 3 + 4 to the public plus two rounds of live-visibility polish, all released.

- **Published v2.7.2:** merged `feat/coa-observability-freshness` (Phase 1+2+3+4) into `main`, tagged, GitHub Release; refreshed README + marketplace to name the run modes / roadblock net.
- **CRT field monitor (#7):** a beige retro-monitor overlay in the War Room cockpit (`▣ CRT`), green phosphor screen streaming each running job's latest step off the SSE progress log. Matched to the demo video by sampling an actual frame (screen `#0d170f`, muted jade text `#4d8560`, khaki bezel).
- **AFTER-ACTION shell tab:** new `/aar` route re-renders the latest run across repos (`rr_from_record`); each deliverable/roadblock row has an **OPEN** button served by a token-guarded, path-validated `/artifact` route. 4th big tab in the shell.
- **fix(runner): idempotent worktree** - a leftover `scorched/<id>` branch no longer craters a re-run; execute_job clears the stale pair first. Found during the real haiku run.
- **Published v2.7.3** (CRT + AAR + fix), then **merged the two haiku docstrings** (clamp_defcon, _cycle) into `main`. Suites **371** (78/75/99/119).
- **Hands-on haiku test:** ran `scorch coa run` for real with `--model haiku` in this repo; two docs jobs SECURED in sandboxed worktrees, gate-verified, deliverables written. Confirmed the whole engine works end-to-end with a real model.
- **Dispatch image:** built `~/Downloads/scorched-earth-dispatch.png` (2160x2700, IG 4:5) - General Claudewitz field dispatch, solid fire-red/amber (no gradients), centered AUTHORIZED stamp, P.S. as plain text above the CTA. Source: `<scratchpad>/dispatch.html`.

**Open / next:** version-string gates plugin updates (merging alone does not reach testers; bump to push changes). Leftover `scorched/doc-*` branches + `.scorched/wt/` cleaned at close. The **ROE editor HTML frontend** (#10 follow-up) is still the one deferred Phase 2 item.

---

## Prior Session (2026-07-01, pt.3): Phase 3 + 4 - execution engine + live progress - DONE

Built the whole execution-engine spec (`docs/superpowers/specs/2026-07-01-execution-engine-and-progress-design.md`) in 8 verified stages, one commit each, on `feat/coa-observability-freshness`. Suites 310 -> **361** (78/75/92/116). No plan-skill ceremony (user's call), TDD-ish per stage.

- **Stage 1 - config:** 5 new ROE fields (`run_mode`, `context_cmd`, `attended_branch`, `roadblock_idle_secs`, `advise_on_roadblock`); the cyclable/toggleable ones wired into `/roe`. Global default + per-repo via the existing `merge_roe` cascade.
- **Stage 2 - model (#4):** `Job.model`; officer emits it; `build_claude_cmd` appends `--model <alias>`. CLI verified: bare aliases + claude-* ids work with `-p`, so no family->id map.
- **Stage 3 - modes + takeover (#3):** new `exec_modes.py` (resolve_mode cascade, operating_orders, compose_attended_prompt); `scorch coa run --here` execs claude in the current window, OS-sandboxed via a CLI `--settings` file.
- **Stage 4 - session (#3):** `scorch coa run --session` spawns a new window (iTerm -> Terminal.app -> print fallback), fully free; runs `context_cmd` first.
- **Stage 5 - deliverables (#3):** every run captures `.scorched/deliverables/<id>.md`; surfaced in the AAR (md column + card link).
- **Stage 6 - roadblock ladder (#11):** idle watchdog + gate-fail -> `roadblocked` (branch kept), report + desktop notify, `scorch coa resume`. Wired through run_queue, the cockpit engine, board_state, AAR + cockpit badges.
- **Stage 7 - auto-solver (#11):** one bounded advising agent tries to recover before pausing (ROE `advise_on_roadblock`).
- **Stage 8 - live progress (#7):** `summarize_stream_line` feeds a per-job progress line into `state_json` (throttled SSE); a CRT progress line on the War Room running card.

**Verified:** 361 unit/integration checks green; template renders (AAR + cockpit, roadblocked + progress) confirmed; CLI dispatch guards (`--here`/`--session`/`resume`). **Hand-verify pending (needs a real claude + terminal, cannot run headless here):** execvp takeover in a live window, the osascript session spawn, and the real `--model`/`--settings`/resume flags in anger.

**Open:** branch still LOCAL/unpushed (now 18 commits: 3 Phase 1 + 7 Phase 2 + 8 Phase 3/4 + spec/docs). Deferred: the ROE editor **HTML frontend** (Phase 2 #10 follow-up, still unbuilt by choice).

---

## Prior Session (2026-07-01): Phase 2 - merged shell (#13) + the UI items - DONE (bar the ROE html follow-up)

Built the unified **War Room shell** (Option A: one 127.0.0.1 server, one token, three big tabs SITREP / COURSE OF ACTION / WAR ROOM via iframes) and then landed all the deferred UI items inside it, one stage per commit, each verified. 7 commits on `feat/coa-observability-freshness` (LOCAL, unpushed - Phase 1 rides the same branch). Suites 78 / 64 / 89 / 79 = **310** (was 45/76/73/78 = 272).

- **Stage 0 - shell:** `shell.py` + `shell_template.html`; `coa_serve.make_server(shell_repos=)` shell mode (frame at `/`, cockpit at `/war-room`, folds in `/sitrep` `/coa` `/coa.json`); `bin/scorch` `_serve_shell` (both `coa --serve` and `advise --serve` route through it). Iframes (no CSS/JS collision, failure isolation). `/favicon.ico` -> 204 before the token gate (killed the 403 console noise). Real Playwright drive: 3 tabs render, hash deep-links, lazy-load, cockpit SSE paints the live board, 0 console errors.
- **Stage 1 - HALTED (#2/#8):** cockpit reads `stop_reason` -> red HALTED flag + resume hint on `limit`; operator-pause/clean stay IDLE. Verified all 3 states in-browser.
- **Stage 2 - freshness (#5/#6):** COA "SCANNED Nh ago" from `scannedAt` + honest Refresh tooltip; War Room manual REFRESH re-reads `/state`. Verified end-to-end (external jobs.json add -> REFRESH surfaces it; SSE alone did not).
- **Stage 3 - ROE editor TERMINAL (#10):** pure `roe_edit.py` model (controls + apply reducer + save preserving freeform) + a curses arrow-key list in `scorch roe` (hjkl too; `--json`/non-tty -> JSON). Fixed an ESC-as-quit bug (arrows begin with ESC). Arrow decoding is standard curses+keypad on a real terminal, not reproducible headlessly (hjkl is the verified path).
- **Stage 4 - sitrep refresh (#12):** `report.render_html(served=True)` emits a Refresh button that reloads `/sitrep`; offline file omits it. Verified in-browser.
- **Stage 5 - cratered legend (#9):** explanatory tooltips on the AAR field legend + cockpit CRATERED badge (fail state = job/gate failed, work discarded).
- **Stage 6 - approval legibility (#1):** COA + cockpit approval badges now tooltip WHY (DEFCON below the auto-run threshold) + HOW (`scorch coa run --approve` / press RUN as operator).

**Remaining Phase 2 item:** the ROE editor **HTML frontend** (#10 follow-up) - a panel/tab in the shell over the same `roe_edit` model, backed by a guarded `POST /roe`. User chose terminal-first; this is the clean next task.

**Open:** branch still LOCAL/unpushed (7 Phase 2 commits + 3 Phase 1). Push/merge decision pending (was deliberately held at Phase 1 close-out).

---

## ROADMAP: bug/idea backlog (user list, 2026-07-01) - fix + build ALL, phased

Ordering locked with the user: backend before UI, merged shell (#13) before the UI work, executor settled before the live-progress view. User chose "merge shell first, UI once."

**Phase 1 - Backend bug fixes (no UI dep):** DONE (branch `feat/coa-observability-freshness`, 2 commits)
- [x] Observability: `stop_reason` / `stopped` in `state_json` (#2/#8 backend). +3 cockpit checks.
- [x] Freshness: `scannedAt` (mtime) in `coa_state` + `/coa` stale-aware re-scan (#5/#6 backend + #5 scan-skip). +2 advisor checks.

**Phase 2 - Merged shell (#13) THEN all UI once:** DONE except the ROE html follow-up.
- [x] Build the unified shell: SITREP + COURSE OF ACTION + WAR ROOM, big tabs, one server + token, iframes (Stage 0)
- [x] HALTED state + resume hint (#2/#8) (Stage 1)
- [x] Freshness UI + honest Refresh + war-room refresh (#5/#6) (Stage 2)
- [x] ROE interactive editor, TERMINAL (#10) (Stage 3) -- curses arrow-key list + pure roe_edit model
- [x] Sitrep refresh (#12) (Stage 4)
- [x] "Cratered" legend + approval legibility how/why (#9, #1) (Stages 5-6)
- [ ] **ROE editor HTML frontend (#10 follow-up):** an ROE panel/tab in the shell over the same `roe_edit` model, backed by a guarded `POST /roe` (the one remaining Phase 2 item; user chose terminal-first)

**Phase 3 - Execution engine (increasing coupling):** DONE (2026-07-01 pt.3)
- [x] Model selection per task, Claude picks fable/sonnet/opus/haiku (#4)
- [x] In-repo / non-headless run + deliverable + session context, usable in the active iTerm2 window (#3) -- three run modes (headless/takeover/session), deliverables per job
- [x] Secure start-to-end permissions/goal + manager roadblock safety net + notify user on roadblock (#11) -- roadblock ladder: watchdog -> advising agent -> pause + report + notify -> resume

**Phase 4 - Live progress view (#7):** DONE (2026-07-01 pt.3) -- per-task last-command line in `state_json` (throttled SSE) + a CRT progress line on the War Room running card.

Answered inline (not tasks, feed #9/#1 UI legibility in Phase 2): "cratered" = the fail state (job or its gate failed, work discarded); approval is needed when `defcon < auto_run_min_defcon` (default 3), granted via `scorch coa run --approve` or the cockpit Run button (operator-present).

---

## Prior Session (2026-06-29): hold your fire (over-burn warning) + deck rename/recolor

Branch `feat/hold-your-fire-deck` (not yet merged or published).

**DONE this session:**
- [x] **New `ease` ("hold your fire") burn state** in `core.py`: fires when a measured recent overpace (`recent_per_window`, trailing ~2 days from `habits.py`) would strand more than `EASE_IDLE_WINDOWS` (default 3) usable windows before the reset. Self-disengaging near the reset, mutually exclusive with `max`, pure (the caller passes the rate in). New `habits.recent_per_window` helper, wired via `state.update_from_statusline`.
- [x] **Deck rename + recolor** across every surface. Keys went meaning-based: `green→max, amber→push, low→steady, (new) ease, off→done`. Palette: red BURN IT ALL, green clear shot take it, white eyes on the target, yellow hold your fire, purple good job soldier (Purple Heart). `done` now PRINTS instead of blanking. Touched core, statusline, state, habits, report + sitrep accents, the COA `verdict` map, bin/scorch. COA/DEFCON color code left alone.
- [x] **Rebrand** off the "green light" tagline (README + CLAUDE.md) to a "fire-team readout"; documented the deck + the `ease` math (the-math.md) + playbook Current Status / verdict names.
- [x] **Tests:** renamed assertions + added `ease` coverage (fires on overpace; silent when sustainable / no rate / in max / near reset). 76 checks in test_scorched green (advisor/cockpit/runner unchanged: 43/70/78).
- [x] Design spec committed at `docs/superpowers/specs/2026-06-29-hold-your-fire-and-deck-recolor-design.md`.

**RESUME / open:**
1. Bumped to **v2.7.1** (plugin.json + pyproject); not yet published. Publish flow: merge the branch to `main`, push, tag `v2.7.1`, GitHub Release, then `claude plugin marketplace update` + `claude plugin update` to pull it. Refresh demo/screenshots for the new deck colors if desired.
2. Possible follow-ups (out of scope this session): a real-time `ease` desktop nudge (rate-limited), and per-repo/ROE configurability of `EASE_IDLE_WINDOWS`.

---

## Prior Session (2026-06-26): v2.7.0 public (served tabbed COA, bare commands, statusline dedup, SEO)

**DONE this session:**
- [x] **v2.7.0 published** (plugin.json + pyproject, tagged `v2.7.0` + GitHub Release). The version walked 1.6.9 to 1.6.10 to 2.6.9 to 2.7.0 across the session; only a changed version *string* reaches users (same string keeps the cached copy).
- [x] **Served, tabbed COA report** (`coa_view.py`, `scorch advise --serve`): a 127.0.0.1 token-guarded page with per-repo TABS and a Refresh button that re-reads each repo's `jobs.json` with no re-scan. `/coa` background-launches it like `/war-room`. `render_html` now takes `repos=[(path,COA)…]` + a token; the template `paint()`s the active repo and shows tabs when >1 repo. Fixed the blank-report trap (advise skips repos with no jobs). +9 tests, 256 total.
- [x] **Bare command aliases for all users** (`/coa` `/sitrep` `/roe` `/war-room` `/scorched-earth`): the SessionStart hook copies `commands/*.md` into the user's `~/.claude/commands/` (plugin commands are otherwise namespaced as `/scorched-earth:coa`). Collision-safe via a `managed-by` tag; never clobbers a user's own command.
- [x] **Statusline double-burn fix**: the wrapper suppresses its own token when the inner statusline already emits the segment (detected from the inner *source*, since the fire gradient randomizes colors so output comparison can't spot the dup).
- [x] **Demo-video DEFCON COA swap DONE** (the long-open pt.2/pt.4 item): rebuilt the CRT tour with the DEFCON COA page, boot/shutdown CRT screens, and a synthesized ambient bed; compressed under 10MB at `~/Downloads/scorched-earth-demo.mp4` (BIOS reads v2.6.9). Pipeline preserved at `~/Downloads/scorched-earth-captures/_pipeline/`.
- [x] **SEO**: GitHub description rewritten + 15 topics added (was none), README keyword subtitle, marketplace keywords widened, v2.7.0 Release, fixed a broken README mp4 link.
- [x] **Docs audit**: aligned the public md files to current behavior (low vs off tier labels in SKILL.md + setup.md, the war-room "shared budget" line, served-COA gaps in README/playbook, "superseded" banners on the 3 design briefs). Ran a parallel 3-agent audit of every tracked .md against the code.
- [x] **Em dashes scrubbed**: removed all em + en dashes from every tracked Markdown doc (201 em, 9 en), and from user-facing product strings (statusline notifications, scorch CLI output, COA/cockpit/AAR template titles/tooltips/`&mdash;` placeholders). Internal code comments/docstrings left as-is. NOT version-bumped; rides the next release. 256 checks green throughout; templates render with no console errors.

**House rule:** never use em dashes in any output, chat or generated content (saved to memory + a note in CLAUDE.md). Use commas, colons, periods, or parentheses.

**RESUME / open:**
1. Social-preview image: upload `assets/social-card-1280x640.png` in repo Settings (manual; biggest remaining SEO lever, can't be done via CLI).
2. Next version bump bundles the pending unbumped runtime changes (SKILL.md tier-label fix + the user-facing em-dash scrub).
3. Demo repos for the served-COA demo live under `~/Downloads/scorched-coa-demo/` (server already shut down); delete if not needed.

---

## Prior Session (2026-06-25, pt.4) - DEFCON stack PUBLISHED (v1.6.9); public docs aligned + skriv

**DONE this session:**
- [x] **v1.6.9 published to public `origin/main`** (`d719659`, the user's release commit, pushed externally between pt.3 and pt.4). DEFCON COA + `⚪ no rush` tier + first-run setup are now LIVE publicly. Release bumped plugin.json/pyproject 1.6.7→1.6.9 and stripped `docs/superpowers/` planning docs (incl. the pt.3 specs) from the public tree.
- [x] **Audited + aligned all public-facing writing** to current capabilities (`7787033`, pushed). README gained a "Burn it on something" COA section + first-run-setup note + `/coa` `/roe` `/war-room` in the install list; plugin.json + both marketplace.json descriptions now name the DEFCON COA layer. **skriv:** fixed 3 dash-as-punctuation in public copy (README no-rush line, coa.md + war-room.md descriptions); command *bodies* left as-is (technical instructions, skriv-exempt).
- [x] **Verified every cited capability is real & working** before writing: live `scorch advise` (9-job DEFCON COA), `/war-room` cockpit boots on 127.0.0.1 w/ one-time token, `scorch roe`/`coa review` respond, JSON re-validated.

**RESOLVED:** the long-standing "decide whether to push" question - published as **v1.6.9**; local `main` == `origin/main` (in sync).

**RESUME / open:**
1. **Demo-video DEFCON COA swap** (open since pt.2, now fully unblocked - the COA render exists AND is public): re-record CRT-framed, swap into the tour in place of `coa_t_crt`, relock the 3 COA captions + `scorch advise` divider to the DEFCON wording. Pipeline at `~/Downloads/scorched-earth-captures/_pipeline/`.
2. Optional polish: a real `scorch list` subcommand (first-run setup confirms repos via `cat repos.json`).
3. Confirm the two stripped specs (first-run-setup, no-rush-tier) are backed up locally if wanted - v1.6.9 removed them from the repo tree.

---

## Prior Session (2026-06-25, pt.3) - "no rush" statusline tier + first-run setup, both MERGED to local main

**DONE this session** (subagent-driven-development, lean: spec→implementer→task-review→fix per feature; each single-task branch's review doubled as the whole-branch gate):
- [x] **Visible "no rush" tier** (`bd7945f`, `4265242`; branch `feat/no-rush-tier`, merged FF). Split `compute()`'s overloaded `off` into **`low`** (deep reserves → statusline shows **`⚪ no rush`**, dim) and **`off`** (weekly budget exhausted). Ladder is now `low → amber → green`; amber/green and the thresholds (GREEN 1.0, AMBER 0.70) untouched. Also fixed a latent bug - the exhausted case used to print `HEADLINE["off"]` = *"Well stocked…"*; each state now gets its true banner. Touched `core.py` · `statusline.py` · `report.py` · `bin/scorch` + the-math/README; 8 new checks (`test_scorched` 57→65). Review caught 2 doc gaps the spec mandated + a loose test assert - all fixed.
- [x] **First-run setup for `/scorched-earth`** (`b136a6a`→`e94855a`; branch `feat/first-run-setup`, merged --no-ff). New `skills/scorched-earth/setup.md` (self-contained primer + guided flow); SKILL.md gate keyed on sentinel `~/.claude/scorched-earth/onboarded`. Flow: familiarize Claude → tour user → pick light style → link repos (`scorch link`, optional) → write sentinel + fall through to verdict. Re-runnable; never loaded once onboarded (zero routine cost). Review caught an **Important** path bug (bare CWD-relative `setup.md` ref broke when run from any other repo) → now resolves via the skill's own directory w/ `~/scorched-earth/...` fallback. Note: `scorch list` doesn't exist (spec assumed it did) → used `cat repos.json`.
- [x] Docs folded in: CLAUDE.md (setup.md architecture line + `onboarded` sentinel), `docs/the-math.md` (5-state enum), README (three-tier readout), `docs/playbook.md` (flow + Current Status + test count), this TODO.
- [x] **Suites green on merged main: 65 + 34 + 78 + 70 = 247.** Feature branches deleted.

**Specs:** `docs/superpowers/specs/2026-06-25-no-rush-tier-design.md`, `docs/superpowers/specs/2026-06-25-first-run-setup-design.md`.

**NOT pushed:** local `main` is now **26 commits ahead of `origin/main`** (DEFCON refactor + these two features). Same keep-WIP-local pattern.

**RESUME / open:**
1. Still pending from pt.2: decide whether to **push** local `main` to public `origin/main`, and the **demo-video DEFCON COA swap** (unblocked).
2. Optional polish: in setup the repo-list confirmation reads raw `repos.json` (no `scorch list` verb exists) - a clean `scorch list` subcommand could replace the `cat`.

---

## Prior Session (2026-06-25, pt.2) - DEFCON COA refactor COMPLETE + MERGED to local main

**DONE this session:**
- [x] **DEFCON COA refactor** (full SDD run: 11 tasks + opus whole-branch final review + fix wave, every gate reviewed clean): budget/effort estimation removed entirely from the COA layer. Jobs rated by **DEFCON 1-5** criticality (1 = most critical / biggest blast radius); `auto_run_min_defcon` approval gate (DEFCON 1-2 need approval; batch `scorch coa run --approve`, cockpit auto-approves as operator-driven); `max_jobs` caps the run. Runner/cockpit drain in DEFCON order, halt on the **real** usage-limit (predictive EnvelopeTracker/headroom deleted; `_run_killable` untouched). Scan prompt hunts **overnight DEFCON-1 campaigns** alongside knockouts. All HUDs (COA, After-Action, cockpit) render DEFCON badges + approval markers; no budget UI.
- [x] **New COA HTML render DONE** (this was the demo-swap blocker - now cleared). Preview script pattern at `/tmp/coa-defcon-preview.html`.
- [x] **UI tweaks** (`coa_template.html`): ROE header now reads "RULES OF ENGAGEMENT *(as set by user)*"; each command box carries a dim **`RUN CMD`** label + hover tooltip clarifying it's a run/execute command.
- [x] **Merged to LOCAL `main`** (fast-forward → `e8a8881`); `feat/defcon-coa` branch deleted. Suites green on merged main: **57 + 34 + 78 + 70 = 239**.

**NOT pushed (user said "not for now"):** local `main` is **17 commits ahead of `origin/main`** (`8779732`, still the 1.6.7 version bump). The DEFCON refactor + this close-out are LOCAL only. `origin/main` still serves the older budget-model COA.

**RESUME HERE next session:**
1. **Decide whether to push** the DEFCON work to public `origin/main` (it supersedes the just-published budget model). If yes: `git push origin main`.
2. **Demo-video swap** (now unblocked - the new COA page exists): re-record the DEFCON COA HTML in the CRT capture rig, swap into the tour in place of `coa_t_crt`, update the `scorch advise` divider + 3 COA captions to the locked DEFCON wording (see the Prior Session block below + `_pipeline/HANDOFF.md`).

---

## Prior Session - published COA stack to public `main`; DEFCON refactor WIP; full CRT demo video built

**Repo state:**
- **public `main`** (origin, `df0dd5b`): the full COA advisor stack SHIPPED - Phase 1 + 2a/2b/2c + depth + multi-repo + **parallel per-repo execution** + the **budget→headroom UX revision** + `/war-room`. Installable via `/plugin marketplace add euan-maley/scorched-earth`. Internal `docs/superpowers/` stripped from the public tree (kept at `~/Downloads/scorched-earth-planning-docs/`); they remain in git history (offer a history scrub if it matters).
- **`feat/defcon-coa`** (LOCAL, 8 commits, UNPUSHED - current branch): the **DEFCON refactor** - replaces budget/cost estimation entirely with a **DEFCON 5-1 criticality rating** (impact, not cost) + an **approval / `auto_run_min_defcon` gate**. spec + plan (11 tasks) + 6 feat commits across jobs/roe/advisor/coa_io/runner/coa_serve + tests. **DEFCON 1 = biggest blast radius** (whole-codebase audits, full test-suite builds, backend creations) - NOT "do first." **New COA HTML render pending** (user building).

**DONE this session:** parallel per-repo execution (SDD, 2 tasks + fixes); cockpit proposed-flicker fix; `/war-room` command; **COA budget→headroom UX revision** (brainstorm→spec→plan→7 tasks + final-review fix wave: `_run_killable` deadlock, queue-CLI forfeit, exit-code phantom-pass); **published** the stack to public `main`; built a market-quality **CRT demo video**.

**Demo/video (NOT in repo - PRESERVED to `~/Downloads/scorched-earth-captures/`):**
- `tour_crt.mp4` (~74s) = deliverable: 8-bit **beige CRT** (convex barrel-warp via `lenscorrection k1=+0.13`, phosphor glow `eq=brightness=0.020:gamma=1.11`), green-on-black **terminal title cards** with frame-perfect plastic key-click audio (every ~2 *visible* glyphs; spaces don't click), and the 3 product demos (**SITREP → COURSE OF ACTION → WAR ROOM**) all CRT-framed with synthetic-cursor + lower-third captions.
- **Pipeline at `~/Downloads/scorched-earth-captures/_pipeline/`** (scripts + `seg/` intermediates + wavs + `*_clicks.json` + `tour.txt`). See `_pipeline/HANDOFF.md`. Recreate venv: `python3 -m venv pwenv && pwenv/bin/pip install playwright` (chromium cached in `~/Library/Caches/ms-playwright`). NB: scripts hardcode the OLD scratchpad path in `SP=` - repoint to the pipeline dir when resuming.

**RESUME HERE when the DEFCON COA page is ready:** user sends path/URL → (1) re-record it in the capture rig (CRT), (2) swap into the tour in place of `coa_t_crt`, (3) update the `scorch advise` divider + 3 COA captions to the **locked DEFCON wording**:
- divider: `ranking every operation by impact - DEFCON 5 to 1 …`
- cap 1: `COURSE OF ACTION · DEFCON-ranked target list` · cap 2: `every target rated DEFCON 5-1 · impact, not cost` · cap 3: `DEFCON 1 = biggest blast radius`
- (intro list line ALREADY says `DEFCON-ranked target list`.)
- Also: decide when to finish/merge `feat/defcon-coa` (supersedes the just-published budget model).

---

## Prior Session - COA advisor + cockpit, FULLY built through multi-repo · branch `feat/burn-advisor` · 215 checks green

Huge session (61 commits). Built the entire **COA execution stack** on top of Phase 1, each
phase brainstorm→spec→plan→subagent-driven-dev (fresh implementer + independent review per
task, opus on the security/concurrency/budget cores, opus whole-branch final review). All
**LOCAL/unpushed** by choice so public `main` stays clean. Suite: 57 core + 34 advisor + 65
runner + 59 cockpit = **215 green**.

**DONE this session (all reviewed "ready to merge"):**
- [x] **Phase 2a - queue-runner** (`runner.py`): drains `.scorched/queue.json`, runs each job headless `claude -p` in a sandboxed git worktree (Claude Code OS sandbox via worktree-local `.claude/settings.json`: API-only network, `failIfUnavailable`, no escape hatch - confirmed flags via claude-code-guide), additive-only ROE leash, commit-not-push, test gate, predictive budget (can't read live rate_limits - predict + re-sync on snapshot advance). HTML **After-Action Report** (`review_report.py` + `review_template.html`) doubles as live monitor (auto-refresh) and debrief.
- [x] **AAR + COA + cockpit design HTMLs** integrated from Claude-design handoffs (briefs in `docs/design/`): `review.html`→`review_template.html`, `cockpit.html` (War Room)→`cockpit_template.html`. Drop-in via `__*_JSON__` token contract; I caught/fixed contract collisions each time (token-in-comment, `<head>` injection, `.cwin`→`.cdepth` styling).
- [x] **Phase 2b - live cockpit** (`coa_serve.py` + `cockpit_template.html`): `scorch coa --serve` → 127.0.0.1 ThreadingHTTPServer (one-time token every request, job-ids-not-commands, repo validated, ROE server-side) hosting a kanban War Room; event-driven `Engine.advance` (no bg loop, while-loop, 4 runaway guards); SSE pushes board state; drag queue/reorder, Run/Stop. EnvelopeTracker (predict-then-resync), pick_next, board_state, queue I/O.
- [x] **Phase 2c - Kill** a running job (`_run_killable` Popen SIGTERM→SIGKILL + thread-local `_kill_ctx`; `Engine.kill` + `POST /kill`; KILL button). Always discards work, no refund, killed→Proposed, chain continues. Operator-intent-wins fix.
- [x] **DEPTH 1-10 rating** replaces shown window cost: agent emits `depth`, `est_windows` derived (coarse band, internal for matcher/runner, never shown per-card). Backward-compat both ways. Cards show DEPTH, drop window cost + S/M/L/XL tier; aggregate gauges keep windows.
- [x] **Multi-repo run** (one job at a time, GLOBALLY): per-repo trackers → ONE global EnvelopeTracker (shared budget, honest); `run(repos)` sweeps an active set sequentially; `/run` accepts a repos list; cockpit repo **checkboxes** (default armed, seenRepos auto-arm) + Run-all.
- [x] **Cockpit UX polish**: starts **paused** (stage queue, then Run); bigger Run/Stop; **REPOS** tab-strip label; global **NOW RUNNING** header readout + active-repo tab marker; **fixed** depth-snapping-on-queue (`_job_to_dict` now persists `depth`); fixed Stop-is-permanent (Run clears stop); fixed rapid-/queue lost-update (mutations under the lock) + atomic write_queue.

**IN PROGRESS - resume HERE next session:**
- [ ] **Parallel per-repo execution** - user wants checked repos to run **concurrently** (separate queues, one job per repo, repos at the same time), NOT the one-at-a-time sweep I built. **PLAN WRITTEN, NOT BUILT**: `docs/superpowers/plans/2026-06-24-parallel-repos.md` (commit 817dccd). 2 tasks: (1) Engine - one drain worker per repo + ONE global EnvelopeTracker with **charge-at-pick reservation under the lock** so concurrent workers can't overspend the shared pool; per-repo `_running`/`_kill_events`/`_workers`; `state_json.running` becomes a LIST. (2) Cockpit - render multiple RUNNING. **Next session: dispatch Task 1 via subagent-driven-development** (fresh ledger, opus review on the concurrency/budget core). Was mid-sentence presenting the plan when the user said switch out.

**Live demo (throwaway, NOT in repo):** `<scratchpad>/warroom_demo.py` - real server + War Room template but a STUB executor (no real claude, no budget burned, no repos touched). Two fake repos for the tab toggle; jobs honor Kill; paused-default. Re-create from the session log if needed.

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

## Readiness Audit (2026-06-24) - fixed before publish

Multi-agent audit (correctness / safety / packaging / testing / arch / design+dx / concept):
- [x] **Correctness:** windows_left straddle over-count (credited next-week capacity); forecast cold-start rate inflation + >7d-out reset; concurrent-statusline `.tmp` write race (now pid-unique); report dead-code weeks bug
- [x] **Safety/robustness:** report KeyError on unknown level; tolerant `Snapshot.from_dict` (schema drift no longer crashes CLI/report); state files now `0600`
- [x] **DX/UX honesty:** partial manual flags now error instead of silently ignoring; `--report` refuses to fabricate a zeros dashboard before any reading; cross-platform open (`xdg-open`) + notify (`notify-send`)
- [x] **Docs truth:** SKILL.md "SCORCH"→"BURN IT ALL" + fire style listed; default-style clarified (fire seeded at install); the-math.md default-R note + multi-bucket caveat; playbook test count; README placeholders + platform note + light states
- [x] **Tests/CI:** 33→57 checks (straddle, verdict-flip regression, cold-start, from_dict, report render, state round-trip + corruption recovery, statusline never-errors invariant); harness collects failures instead of aborting; GitHub Actions CI added
- [x] **Packaging:** `pyproject.toml` (python ≥3.8 floor); gradient.py documented in CLAUDE.md
- [x] **Add a git remote + push** (private GitHub)

## Backlog

- [x] Pre-public prep: MIT `LICENSE` file added; `homepage`/`repository` in `plugin.json`; untracked `kivna/` + `.slainte` (gitignored, kept local - no second machine so the handoff loss is fine). Repo is publish-clean except for the deliberate choice to leave `TODO.md` tracked.
- [x] **Published public** (2026-06-24). Logo + landscape banner, sitrep screenshots, embedded mp4 player in the README, `/sitrep` command. README skriv-passed.
- [x] Slimmed git history: stripped dead demo binaries (old gif/webm, burn/poster PNGs) via `filter-branch` + force-push. `.git` 20M → 7.1M (fresh clones get the small pack; GitHub's reported size lags until their server gc). Pre-strip backup bundle at `~/Downloads/scorched-earth-preslim.bundle`.
- [ ] `scorch --watch` live re-print (flag exists; field-test it)
- [ ] Optional: surface the 🔥 forecast nudge on the statusline too (not just notify)
- [ ] Let users tune "active hours" manually (currently learned only)
- [ ] Fire perf: it's canvas-animated; consider pausing when tab hidden (visibilitychange)
- [ ] R/active-hours still learning on this machine (~2 readings); sharpen over a couple weeks
