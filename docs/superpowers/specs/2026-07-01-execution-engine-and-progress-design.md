# Design: execution engine (run modes, per-task model, roadblock safety net) + live progress

Date: 2026-07-01
Status: approved (brainstormed with user), ready for implementation plan.

## Summary

Phase 3 + 4 of the backlog, designed as one holistic system because the pieces interlock:
the safety net and the progress view both attach *per run mode*, so the run-mode model is
the spine everything else hangs off.

Four subsystems:

- **#3 run modes:** a job can run in one of three modes the user picks. `headless` (today's
  sandboxed, unattended worktree runner, unchanged) stays the default; two new **attended**
  modes run in the real repo working tree, non-sandboxed, with the human present: `takeover`
  (seizes the current terminal window) and `session` (opens a new session, optionally after a
  context-gathering command like `switch in`). Every mode captures a per-job **deliverable**.
- **#4 per-task model:** each job carries a `model` (fable/sonnet/opus/haiku); the runner passes
  `--model` on every launch. The COA officer picks it during the scan.
- **#11 permissions/goal + roadblock safety net:** attended modes get the ROE leash + goal
  injected as binding operating orders (headless keeps the OS sandbox). A **roadblock
  escalation ladder** detects a stuck job, tries a bounded **advising agent** to auto-solve,
  and on failure pauses, writes a roadblock report, notifies the developer, and leaves the job
  **resumable** so it continues after a human fix rather than restarting.
- **#7 live per-task progress:** a CRT progress panel in the War Room shows what a running
  headless job is doing *right now* (its last command), streamed from the existing output
  reader.

Nothing here touches the statusline hot path. `core.py` stays pure and untouched.

## Non-goals

- Not replacing the sandboxed unattended runner. It is the product's core ("approve, walk away,
  wake up to it done") and stays exactly as-is; the new modes sit *alongside* it.
- No changes to the burn-rate model, the deck, or `core.py`.
- No remote / multi-machine execution. Attended modes are local to the user's terminal.
- The ROE HTML editor (deferred Phase 2 item) is out of scope; `run_mode` and friends are wired
  into the existing terminal `/roe` editor now, and inherit the HTML editor for free when it lands.

---

## A. The run-mode model (the spine)

A job runs in one of three modes:

| Mode | Runs in | Terminal | Sandbox | Attended | Trigger surface |
|------|---------|----------|---------|----------|-----------------|
| `headless` (default) | throwaway worktree `.scorched/wt/<id>` | none (piped) | yes (Seatbelt / bwrap, existing) | no | `scorch coa run`, War Room cockpit |
| `takeover` | real working tree | **current window** (`os.execvp`) | no | yes | `scorch coa run --here <job-id>` |
| `session` | real working tree | **new iTerm2 tab/window** (osascript) | no | yes | `scorch coa run --session <job-id>`; a card action in the shell |

### Mode resolution (the cascade)

Resolved top-down, first hit wins:

1. **Per-task override** (an explicit flag at run time, or a mode tagged on a card).
2. **Per-repo ROE** `run_mode`.
3. **Global default ROE** `run_mode` (the user's "preference for all tasks").
4. **Hard fallback:** `headless`.

This rides the existing `coa_io.load_roe` = `merge_roe(global_default, per_repo)` machinery.
No new config plumbing: `run_mode` is just a new ROE field, so the global-vs-per-repo split
falls out for free.

### The two attended modes share one prompt composer

`takeover` and `session` differ *only* in terminal placement. Both build the same **opening
prompt** for a fresh interactive `claude` session:

```
[optional context_cmd, e.g. "/kerd:switch in"]   (attended only, if set)
[ROE leash + the job's goal, as binding operating orders]   (see section E)
[job.launch (the task)]
```

We hand the fresh interactive session that single opening message and let the agent *itself*
run the context command (a real slash command / skill invocation) and then the task. No
keystroke scripting, no pty/expect: robust, and it gives the roadmap's "session context"
clause for free.

- **`takeover`** is invoked from the window you want seized. `scorch coa run --here <id>`
  assembles the prompt + model, then `os.execvp("claude", [...])` in the repo cwd, *replacing*
  the scorch process. Your shell becomes the claude session; on exit you are back at your prompt.
- **`session`** opens a new iTerm2 tab via `osascript` (macOS), `cd`s to the repo, and launches
  `claude` with the composed prompt. Your current window stays free. Fallbacks in order:
  iTerm2 -> Terminal.app -> print the exact command for the user to paste (never fail silently).

Both attended modes run in the repo's **actual working tree** on the **current branch** by
default (`attended_branch = off`), matching the "in-repo, I can see it" intent; the human
commits. Flip `attended_branch` on per repo to run on a fresh `scorched/<id>` branch instead.

### Why three trigger surfaces, not one

A background War Room server has no terminal and is not the live agent, so it *cannot* seize
your window or run in a session for you. The mode therefore dictates the surface: headless
stays server/CLI-driven; `takeover` must be invoked from the target window (so `execvp` can
seize it); `session` spawns its own window. The shell UI can still *tag* a job's intended
mode, but for attended modes it hands you the exact command rather than running it behind your
back.

---

## B. Config: new ROE fields

Added to the `ROE` dataclass (all optional, all overlay cleanly through `roe_from_dict` /
`merge_roe`):

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `run_mode` | `"headless"｜"takeover"｜"session"` | `"headless"` | default run mode (global + per-repo) |
| `context_cmd` | `str｜None` | `None` | pre-task command for attended modes, e.g. `/kerd:switch in` |
| `attended_branch` | `bool` | `False` | attended jobs get a `scorched/<id>` branch vs. current branch |
| `roadblock_idle_secs` | `int` | `600` | seconds of no output before a headless job is flagged stuck (10 min) |
| `advise_on_roadblock` | `bool` | `True` | try the advising agent before pausing (section E) |

All five become controls in the terminal `/roe` editor, extending `roe_edit.py`'s `controls`
list: a 3-way cycle (`run_mode`), a text field (`context_cmd`), a toggle (`attended_branch`),
a numeric/stepper (`roadblock_idle_secs`), a toggle (`advise_on_roadblock`). Only wired fields
are exposed, per the existing editor rule. They inherit the HTML editor whenever it lands.

`save` continues to preserve freeform keys.

---

## C. #4 per-task model selection

- **Job schema:** `jobs.Job` gains `model: Optional[str] = None` (`fable｜sonnet｜opus｜haiku`,
  `None` = inherit the session default). `parse_jobs` reads it; unknown/absent -> `None`.
- **Scan:** the COA officer (commands/coa.md) picks a model per job during the scan and emits it
  in the job dict. Guidance baked into the officer instructions: trivial knockouts -> haiku/fable,
  normal work -> sonnet, DEFCON-1 project-defining campaigns / deep audits -> opus. Model id
  strings follow the current family (e.g. `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`,
  `claude-fable-5`); the officer emits the short family name and the runner maps it to a concrete
  `--model` value, so the mapping lives in one place and tracks model releases.
- **Runner:** `build_claude_cmd` appends `--model <id>` when the job has one, for `headless` and
  `takeover`/`session` alike. Exact flag verified against claude-code-guide during the build.
- **session mode caveat:** an already-running interactive session cannot hot-swap its own model,
  so for `session` the model is advisory (surfaced in the opening prompt: "this job wants opus").
  For a *new* session we can pass `--model` at launch, so it is honored there.
- **Override:** a per-task model override is accepted at run time (mirrors the mode override).

---

## D. Deliverables

Every mode captures a per-job **deliverable** to `.scorched/deliverables/<job-id>.md`: a short
written record of what the job produced (summary, files touched, follow-ups / open items). This
makes an audit or research job's output a *report you read*, not just a diff.

- **headless:** the runner writes the deliverable from the job outcome + diffstat after the run,
  and the opening prompt asks the agent to leave a one-paragraph summary it can capture.
- **attended:** the opening prompt instructs the session to write the deliverable file on
  completion (it is in the real tree, so it just writes the file).

The deliverable path is surfaced per job in the After-Action Report (a "DELIVERABLE" link on
the card) alongside the existing merge/discard commands.

---

## E. #11 permissions/goal + roadblock safety net

### Permissions + goal (start to end)

- **headless:** keeps the OS sandbox (`write_sandbox_settings`, unchanged) as the hard boundary.
- **attended (no sandbox):** the ROE leash and the job's goal are injected into the opening
  prompt as **binding operating orders**: stay inside `exclude_paths` / `allowed_types`, pursue
  the stated `goals`, additive and focused, do not touch other repos. The human presence is the
  enforcement; the injected orders keep the agent on-mission.

### The roadblock escalation ladder

Applies to **headless** jobs (attended jobs have you watching). A watchdog in the runner's
drain loop detects a roadblock, then escalates:

1. **Detect.** A roadblock is any of: no output for `roadblock_idle_secs` (default 600s = stuck),
   a gate failure, a nonzero exit with no diff, or an error loop. (The existing `rate_limit`
   detection stays a separate halt, not a roadblock.)
2. **Advise (auto-solve), if `advise_on_roadblock`.** Spawn a **bounded advising agent**: a
   fresh sandboxed claude invocation in the same worktree, handed the roadblock context (the
   goal, the ROE leash, the last output tail, the error, the diff so far) and tasked with
   diagnosing and applying a fix so the job can continue. One bounded attempt (single invocation,
   same additive leash, same test gate).
3. **Solved -> resume.** If the advising agent's fix passes the gate, the job resumes and
   finishes.
4. **Can't solve -> pause + report + notify.** Stop the job, mark a new outcome **`roadblocked`**
   (distinct from `fail`), write a **roadblock report** to `.scorched/roadblocks/<job-id>.md`
   (what happened, where it stopped, best-guess root cause, suggested fix), and fire the
   developer notification via the existing `statusline` notify path (macOS `osascript` /
   Linux `notify-send`).
5. **Resume after fix.** `scorch coa resume <job-id>` picks the job back up *from where it
   stopped* and continues to completion, not a restart.

### Resumability (the load-bearing new capability)

To resume a headless job with its context intact, each job is launched with a **stable session
id** (`--session-id <deterministic-uuid-from-job-id>`); `scorch coa resume` re-invokes with
`--resume <that-id>` plus the roadblock context. The exact `claude` flags (`--session-id`,
`--resume`, and whether `-p` sessions are resumable) are **verified against claude-code-guide
during the build**, not assumed here; if `-p` resume is unavailable, the fallback is to re-launch
with the accumulated diff + roadblock report as fresh context (a warm restart, not cold).

### New outcome + state

- `JobOutcome.outcome` gains `roadblocked`. `_summary` counts it ("N roadblocked").
- `roadblocked` jobs are **not** re-queued automatically (unlike `limit`); they wait for
  `resume`. The board/AAR shows them distinctly with a "needs you" marker + the report link.

### Staging note

The advising-agent auto-solver (step 2) is the richer tier and ships **after** the MVP ladder
(detect -> pause -> report -> notify -> resume). Both are designed in now so the data model
(the `roadblocked` outcome, the report file, the session id, the ROE toggles) is right from the
first commit.

---

## F. #7 live per-task progress (CRT)

For **headless** jobs (attended jobs are already visible in your terminal):

- **Capture.** The drain reader thread in `_run_killable` already reads the job's
  `stream-json` output line by line. Parse each line for the **latest meaningful event** (last
  tool call / last assistant text) and hold it as the job's "last command" on the engine state.
- **Expose.** `Engine.state_json` adds a per-running-job `progress` field (last command + a
  short recent tail + elapsed). A throttled progress broadcast (at most every ~2s) rides the
  existing SSE `board` channel so it does not flood.
- **Render.** A **CRT progress panel** in the War Room shell shows what each running job is
  doing right now, styled to match the 8-bit HUD. Attended jobs render a "running in your
  window/tab" placeholder instead of a live feed.

No new server or endpoint: it extends the existing engine state + SSE + cockpit template.

---

## G. Data model changes (summary)

- `roe.ROE`: `+ run_mode, context_cmd, attended_branch, roadblock_idle_secs, advise_on_roadblock`.
- `jobs.Job`: `+ model`.
- `runner.JobOutcome.outcome`: `+ "roadblocked"`.
- `runner`: prompt composer (attended), `execvp` takeover, session spawn (osascript + fallbacks),
  deliverable writer, roadblock watchdog + advising agent + report writer + notify, session-id
  launch + resume.
- `coa_serve.Engine.state_json`: `+ per-job progress`; throttled progress broadcast.
- `coa_io`: deliverable + roadblock report paths (per-repo `.scorched/deliverables`,
  `.scorched/roadblocks`).
- `roe_edit`: `+ five controls`.
- `commands/coa.md`: officer emits `model`; new `--here` / `--session` / `resume` docs.
- `cockpit_template.html` / shell: CRT progress panel; mode tags; deliverable + roadblock links.

## H. Implementation staging (one spec, sequenced build)

Each stage is an independently verifiable commit, matching the repo's per-stage discipline.

1. **Config foundation.** ROE fields + `roe_edit` controls + `/roe` wiring. (pure + editor tests)
2. **#4 model.** `Job.model`, officer emits it, `build_claude_cmd --model`, family->id mapping.
3. **Mode spine + `takeover`.** Mode resolution cascade, prompt composer, `execvp` current window.
4. **`session` mode.** New-tab spawn (osascript + Terminal + print fallbacks), `context_cmd`.
5. **Deliverables.** Capture + write + AAR surfacing across all modes.
6. **#11 MVP ladder.** Watchdog (idle/gate/no-diff), `roadblocked` outcome, report writer,
   notify, session-id launch + `scorch coa resume`.
7. **#11 auto-solver.** Bounded advising agent, resume-on-solve.
8. **#7 progress.** Engine progress capture + throttled SSE + CRT panel.

## Testing approach

- **Pure / unit:** mode resolution cascade, prompt composer (given ROE + job -> exact opening
  text), `roe_edit` controls + `apply` + `save`, `Job.model` parse, `roadblocked` in `_summary`,
  deliverable/roadblock path helpers, family->model-id mapping. All I/O-free, in the existing
  harnesses (test_scorched / test_advisor / test_runner / test_cockpit).
- **Runner (injected `execute`):** watchdog fires on a silent stub; `roadblocked` recorded and
  not re-queued; resume re-invokes with the captured session id; advising-agent path solved vs
  unsolved; deliverable written. All via the existing injected-executable seam (no real claude).
- **Server / UI:** engine `state_json` carries `progress`; SSE pushes it throttled; real
  Playwright drive of the CRT panel and mode tags in the shell, 0 console errors.
- **Manual / verified-at-build (cannot be unit-tested headlessly):** `execvp` takeover in a real
  iTerm2 window; the osascript new-tab spawn; the actual `claude --model` / `--session-id` /
  `--resume` flags (confirmed via claude-code-guide before wiring). These are driven by hand and
  the exact CLI contract is verified, not assumed.

## Open risks / to verify during build

- **`claude` CLI contract:** exact flags for model selection, deterministic session id, and
  `-p` resume. Verified via claude-code-guide at stage 2 (model) and stage 6 (resume) before
  wiring; fallbacks specified above if resume of `-p` sessions is unavailable.
- **osascript / iTerm2 dependency:** `session` mode is macOS + iTerm2 first; the Terminal.app and
  print fallbacks keep it functional elsewhere. No hard failure if neither is present.
- **Attended safety:** attended modes are non-sandboxed by design (in-repo, human present). The
  injected ROE leash + goal is advisory, not enforced; this is an accepted tradeoff for the
  "run it in front of me" modes and is documented in the command help.
