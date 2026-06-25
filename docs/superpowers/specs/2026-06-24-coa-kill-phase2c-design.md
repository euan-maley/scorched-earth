# COA Kill-a-Running-Job (Phase 2c) — Design Spec

**Date:** 2026-06-24
**Branch:** `feat/burn-advisor` (local, not pushed until ready to ship)
**Status:** Design approved in conversation, pending implementation plan.

## The idea

The cockpit can queue, reorder, run, and stop — but once a job is **running**, the only control
is Stop (which waits for the current job to finish). There's no way to abort a job that's gone
wrong or that you no longer want. **Kill** adds that: a per-running-job button that terminates the
job *now*, **always discards its partial work**, and returns the card to Proposed so you can
re-queue it (or leave it).

Deliberately simple — no pause, no keep-the-work option, no confirmation:

- **You lose the tokens.** A partial `claude -p` run already burned real budget; Kill stops it
  spending *more* but can't refund what's gone. The job's predictive `est_windows` stays charged
  (the honest, conservative choice) and re-syncs to ground truth on the next statusline reading.
  No fake refund.
- **You lose the work.** The partial worktree/branch is discarded (`git worktree remove --force`
  + `branch -D`). No "keep" option.

## Behavior

- A **Kill** button appears only on the **RUNNING** card. Clicking it fires `POST /kill {repo, id}`.
- The server terminates the running `claude -p` (SIGTERM, then SIGKILL after a short grace),
  **discards the worktree + branch**, records the job as outcome `killed`, clears the running
  slot, and the engine **continues to the next queued job** (kill one → the next takes over).
- Because `board_state`'s finished filter keeps only `pass`/`fail`, a `killed` job (still in
  `jobs.json`, not queued, not pass/fail) **reappears in Proposed** automatically — re-queueable.
- The run record / AAR still logs the job as `killed` (an honest record of what happened), even
  though the board returns the card to Proposed.
- Kill targets only the currently-running job; a `/kill` for a non-running or mismatched id is a
  clean no-op.

## Architecture (builds on Phase 2a/2b)

The one foundational change is making the running job **killable** — the executor currently uses a
blocking `subprocess.run` with no handle to interrupt it.

- **`runner.py`:**
  - A new pure-ish helper `_run_killable(cmd, cwd, kill_event, grace=...) -> str` — spawns the
    command via `subprocess.Popen`, waits, and if `kill_event` is set, terminates (SIGTERM → after
    `grace`, SIGKILL) and returns `"killed"`; otherwise returns `"done"` when the process exits.
    Unit-testable with a real long-running child (e.g. `sleep`) + a `kill_event` set from a thread.
  - `execute_job(repo, job, roe, kill_event=None)` gains the optional `kill_event`; it runs the
    `claude -p` step through `_run_killable`. On `"killed"` it **discards the worktree + branch**
    and returns `("killed", None, "killed by operator — work discarded.")`. Without a `kill_event`
    (the batch `scorch coa run` path), behavior is unchanged.
  - `run_one(..., kill_event=None)` threads `kill_event` through to `execute`.
- **`coa_serve.py` (Engine):**
  - Tracks the running job's `kill_event` (a `threading.Event`) under the lock alongside `_running`.
  - `advance` creates the event before executing and passes it to `run_one`.
  - `kill(self, repo, job_id)` — under the lock, if the running job matches `(repo, id)`, sets the
    event. The blocked `run_one` then returns `"killed"`; the engine appends the `killed` outcome,
    persists, charges `est_windows` (no refund), clears the running slot, and the loop continues.
  - New endpoint `POST /kill {repo, id}` (token-guarded, job-ids only) → `engine.kill`, started on
    a worker thread like `/run`. Repo validated against `engine.repos`.
- **`cockpit_template.html`:** a **KILL** button on the running card → `post("/kill", {repo, id})`
  with the `X-Scorch-Token` header (job-id only, never a command).

## Out of scope

- Pause/resume (impossible for headless `claude -p` — the work can't be frozen).
- Keep-the-work / merge-the-partial-branch (always discard).
- Killing queued/proposed cards (those are removed by dragging out / `/unqueue`, not "killed").
- Measuring actual partial spend (the runner predicts, never measures — unchanged).

## Testing

- **Unit (deterministic):** `_run_killable` against a real `sleep` child — set the event from a
  thread, assert it returns `"killed"` promptly and the process is dead; and the not-killed path
  returns `"done"`.
- **Hermetic engine test (stub executor that blocks on the kill_event):** `engine.kill` from
  another thread ends the running job as `killed`, clears busy/running, the chain continues to the
  next job, and the killed job is absent from `board_state` finished (so it's back in Proposed).
- **Server test:** `POST /kill` is token-guarded (403 without), job-ids only, unknown repo → 400,
  routes to `engine.kill`.
- `core.py`/statusline untouched; the existing batch `scorch coa run` path (no `kill_event`) stays
  green.

## Open decisions resolved in conversation

- **Kill, not Cancel+Hold** — no pause (impossible), one button.
- **Always discard the work** — no keep option, no confirmation.
- **No budget refund** — tokens are spent; the predictive charge stays and re-syncs on next reading.
- **Killed card → Proposed** — via the existing `board_state` pass/fail filter; re-queueable.
- **Chain continues** — kill one, the next queued job takes over.
