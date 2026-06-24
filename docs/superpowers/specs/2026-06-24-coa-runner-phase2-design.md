# COA Queue-Runner (Phase 2a) — Design Spec

**Date:** 2026-06-24
**Branch:** `feat/burn-advisor` (local, not pushed until ready to ship)
**Status:** Design approved in brainstorming, pending implementation plan.

## The idea

Phase 1 (the advisor) answers *what's worth burning budget on*: it scans linked repos and
produces a ranked, budget-matched Course of Action — a list of expensive jobs, each with a
`launch` string. But Phase 1 runs nothing; the user pulls every trigger by hand.

The **queue-runner** closes that gap: it drains the COA autonomously on the user's own
machine while they're away, doing real Claude work in isolation, and leaves a morning-after
debrief. It turns "here's what to burn on" into "I burned it; here's what came back."

This spec covers the **runner only**. The `scorch coa --serve` localhost bridge (turning the
COA HTML's COPY buttons into live Queue/Run actions) is **Phase 2b** — a separate, smaller
spec that plugs into the same `.scorched/queue.json` the runner already drains. We prove the
runner is trustworthy first, exactly as Phase 1 proved the suggestions were good before
building any executor.

## Scope

**In scope:**
- A persisted job queue (`.scorched/queue.json`) and CLI to populate it.
- An autonomous runner that drains the queue, one job at a time, sized to the available burn.
- Per-job isolation (worktree + branch), sandboxed headless execution, a test gate.
- A morning-after review surface (HTML war-HUD + Markdown record).

**Out of scope (later):**
- The `scorch coa --serve` bridge (Phase 2b).
- Scheduling / cloud-routine execution (Phase 3).
- Auto-merging branches. The runner commits but never pushes and never merges; the human is
  the merge gate.

## The loop (data flow)

```
/coa                              →  COA: jobs with launch strings (Phase 1)
scorch coa queue --all | <ids>    →  writes .scorched/queue.json
scorch coa run                    →  drains the queue (overnight):
                                       per job → worktree+branch → pre-warm deps →
                                       sandboxed claude -p → test gate → record result
scorch coa review                 →  HTML war-HUD + Markdown debrief
(you)                             →  merge or discard each branch
```

The runner is **sequential** — one job at a time. Both budget accounting and worktree sanity
want serial execution; concurrency buys little and risks a lot.

## Executing one job

The scan agent's `launch` string is the **task**. The runner supplies the **operating
instructions** around it. For each job the runner:

1. **Creates an isolated worktree + branch** (`scorched/<job-id>`) off the repo's current
   HEAD, so the job's commits land on a throwaway branch and never touch the working tree.
2. **Pre-warms dependencies into the worktree** (see "Network model" below): runs the repo's
   ROE `setup_cmd` (e.g. `npm ci`, `pip install -e .`) *with* network, as a trusted
   runner-controlled step — never the agent — so gitignored deps land in the isolated worktree.
3. **Runs the job headless and sandboxed**: `claude -p` with a runner-built prelude prompt
   ("work only in this worktree, make additive changes, commit with a clear message, **do not
   push**, don't touch other repos") followed by the job's `launch` as the task. Execution is
   confined by Claude Code's OS sandbox (filesystem → the worktree, network → the API only).
4. **Runs the test gate**: the repo's ROE `test_cmd` (or the job's `verify` override). Pass or
   fail is recorded; **the branch is kept either way**.
5. **Records the result** and moves to the next job.

### On failure
A job that fails its test gate is recorded as failed, its **branch is kept** for morning
triage, and the run **continues** to the next job. One bad job doesn't forfeit the remaining
unattended budget, and failed work is still inspectable.

## Network model (the dependency problem)

The sandbox denies network by default. Two kinds of network matter:

- **The Anthropic API** — `claude -p` must reach it or the job can't think at all. The sandbox
  permits this endpoint and only this endpoint for the agent.
- **The job's setup** — a fresh worktree contains only git-*tracked* files, so gitignored
  dependencies (`node_modules`, `.venv`) are absent. The job's first `npm ci` / `pip install`
  would need network, which the sandbox denies — killing the job before it does real work.

**Resolution (Option A — pre-warm):** the *runner* performs the install step itself, before
sandboxing, using a known, pre-approved `setup_cmd` from the repo's ROE. The *agent* then runs
with network fully denied (API only). The one operation that legitimately needs the internet
is done by the trusted runner from a known command; the free-roaming agent never gets network.
This mirrors the bridge's security principle ("the server runs `launch`, not echoed commands"):
the trusted side does the privileged thing, the autonomous side is jailed.

A job whose `setup_cmd` is empty simply skips the pre-warm. Mid-task fetches are not supported
in v1 (a job that needs to download something *during* the work, not at setup, will fail its
gate and surface in the review). A future ROE host-allowlist (Option B) could grant the agent
scoped network if this proves limiting — but it is explicitly out of scope here.

## Budget accounting (predictive, not live)

The runner **cannot read live `rate_limits`** — that data is delivered only to the statusline
command, never to a background process. So:

- **Read the snapshot** from `state.json` (the last statusline fire's view of windows left, %
  weekly remaining, active hours).
- **Staleness guard:** if there's no snapshot, or it predates the current 5-hour window, the
  runner **refuses** rather than guessing — the same honesty rule `scorch --report` already
  enforces (no fabricated dashboard).
- **Compute the envelope** from the ROE cost rules + snapshot (the same inputs the Phase 1
  advisor uses).
- **Predictively decrement:** subtract each job's `est_windows` from the remaining envelope as
  it completes. Before starting a job, if it won't fit, **stop** (the queue is already
  tier-and-fill ranked, so the best-fitting work ran first).
- **Honesty in the review:** spend is labeled *estimated* ("~X windows; confirm against
  `/usage`"), never claimed as measured. The runner predicts; it cannot confirm mid-run.

## Safety model (layered — each layer shrinks blast radius)

| Layer | What it bounds |
|-------|----------------|
| OS sandbox | Filesystem writes → the worktree; network → the API only |
| ROE `unattended_types` leash | Only additive/verifiable job types run unattended; transformative/destructive types are skipped and marked "blocked by ROE" |
| Pre-warm, not agent network | The only network grant goes to a trusted runner-run `setup_cmd`, never the agent |
| Worktree + branch | Commits land on a throwaway branch, never the working tree |
| commit-not-push | Output never leaves the machine automatically |
| Test gate | A verification checkpoint after each job |
| Morning-after human gate | Nothing reaches `main` without the user reviewing and merging |
| Sequential execution | One job at a time; bounded, auditable |

**To confirm during planning (not assumed here):** the exact mechanism for sandboxed headless
execution — whether Claude Code's sandbox is a CLI flag or a `settings.json` field, whether
`claude -p` honors it in headless mode, and how it composes with (or replaces) permission
bypass. In a properly configured sandbox, in-sandbox operations may run without prompting and
only escape attempts fail — which would be *safer* than a blanket bypass. This is a
claude-code-guide lookup, resolved in the plan before any runner code is written.

## Module structure

Keeps `core.py` and the statusline hot path **untouched** (invariant). The runner is an I/O-
tier module like `state.py` / `statusline.py`, not pure.

| Module | Role |
|--------|------|
| `runner.py` (new) | Orchestration: queue drain loop, predictive accounting, per-job worktree/pre-warm/spawn/test/record. The **job-spawn step is dependency-injected** so tests substitute a stub instead of spawning real Claude. |
| `coa_io.py` (extend) | `read_queue` / `enqueue` / `write_queue` for `.scorched/queue.json`; run-record read/write under `.scorched/runs/<date>.json`. |
| `review_report.py` (new) | `render_review_md` + `render_review_html` from a structured `RunResult`, reusing the template-injection pattern (a new `review_template.html` war-HUD debrief). Renders both the **live** view (in-progress, with auto-refresh) and the **final** debrief — same template, same source. |
| `roe.py` (extend) | Add `test_cmd`, `setup_cmd`, and `unattended_types` fields. |
| `jobs.py` (extend) | Optional per-job `verify` override (overrides ROE `test_cmd` for the gate). |
| `bin/scorch` | New verbs: `coa queue`, `coa run`, `coa review` (+ thin `--merge` / `--discard` helpers for acting on a reviewed branch). |
| `commands/coa.md` | Document the queue → run → review flow. |

### The `RunResult` (structured source for the review *and* the live view)
One structured object per run, persisted to `.scorched/runs/<date>.json`, drives the Markdown
record and the HTML war-HUD (same single-source pattern as `coa_report.py`). Per job it
carries: id, title, type, branch, gate outcome (pass/fail/blocked-by-ROE/skipped-no-budget),
diffstat, estimated windows spent, and a merge/discard hint. It also carries a run-level
`state` field (`running` | `done`).

The runner **rewrites the JSON and re-renders the HTML after every job**, so the same artifact
is both the live monitor and the final record — it fills in job-by-job during the run and sits
as the debrief afterward.

## Live monitoring

Two passive views, both fed by the incremental `RunResult` — no server, no new security surface:

- **Terminal stream:** `scorch coa run` prints progress to stdout as it goes (job started →
  pre-warm → tests pass/fail → next, plus the running envelope). Background it and redirect to
  a logfile to `tail -f`.
- **Auto-refresh HTML:** after each job the runner re-renders the review HTML. While
  `state == running`, the page carries a `<meta http-equiv="refresh">` (a few seconds) so an
  open browser tab fills in job-by-job on its own; when the run finishes the runner re-renders
  once more **without** the refresh tag, leaving the final debrief. Open it once at the start
  (or via `scorch coa review` mid-run) and glance whenever.

A real pushed live dashboard (localhost server) is the Phase 2b `--serve` bridge; the
auto-refresh file deliberately gets the passive-monitoring feel without that machinery.

The HTML war-HUD (the "After-Action Report") is specified for a Claude design pass in
`docs/design/2026-06-24-coa-review-hud-brief.md` — same handoff pattern that produced the
sitrep and COA templates (a self-contained file driven by one `const AAR = {…}` JSON blob,
with the six per-job outcome states and the live-vs-done refresh behavior).

## Testing

The existing `tests/test_advisor.py` harness, extended. **Pure parts** are unit-tested
directly: queue I/O round-trip, predictive accounting (a pure function over snapshot + queue +
ROE), review render from a fixed `RunResult`, the new ROE fields. **Orchestration** is tested
via the injected fake-spawn — simulating pass / fail / blocked-by-ROE / envelope-exhaustion /
stale-snapshot-refusal — with **no real `claude`, no real network, no real worktrees** beyond
temp dirs. `core.py` and the statusline suite are untouched and must stay green.

## CLI surface (summary)

```
scorch coa queue --all              # enqueue every job from the latest COA
scorch coa queue <id> [<id>...]     # enqueue specific jobs
scorch coa run                      # drain the queue under the full safety model
scorch coa review                   # render + open the morning-after debrief (HTML + MD)
scorch coa review --merge <id>      # merge a reviewed branch (thin helper)
scorch coa review --discard <id>    # delete a reviewed branch + worktree
```

## Open questions resolved in brainstorming

- **Scope:** runner first, own spec; the `--serve` bridge is a separate Phase 2b spec.
- **Execution:** headless `claude -p` inside Claude Code's OS sandbox (capable + contained).
- **Containment:** full — sandbox + ROE leash + commit-not-push + test gate + human merge gate.
- **Queue source:** persisted `.scorched/queue.json` (bridge-ready), not ad-hoc COA draining.
- **Test command:** ROE `test_cmd` per repo, with a per-job `verify` override.
- **On failure:** keep branch, mark failed, continue the run.
- **Review surface:** HTML war-HUD + Markdown record (dual output, like the COA).
- **Network:** Option A — runner pre-warms deps via a trusted `setup_cmd`; the agent runs offline.
