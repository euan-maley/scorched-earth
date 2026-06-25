# DEFCON criticality replaces budget estimation in the COA advisor

**Date:** 2026-06-25
**Branch:** `feat/defcon-coa`
**Scope:** COA advisor only. The statusline weekly-burn signal (`core.py`, `calibrate.py`,
`habits.py`, `report.py`, `statusline.py`) is **untouched** — it measures real usage from
real deltas and remains the engine.

## Problem

The COA advisor asks a scan agent to estimate per-job complexity/depth/length, converts
that to a window-cost (`est_windows`), and runs a budget matcher that "fits" jobs into the
remaining 5-hour window. That estimation is fakery — the runner itself notes it "can't read
live rate_limits — predict + re-sync." It also biases the advisor toward small, sizeable-
looking knockouts and away from the highest-value work this plugin exists for: **extreme
overnight campaigns** you approve, walk away from, and wake up to.

## Goals

1. **Remove all per-job budget/effort estimation** from the COA layer — no agent rating
   complexity, depth, or length.
2. **Rate jobs by a DEFCON criticality index (1–5)** measuring *impact on the project*,
   not effort/scale.
3. **Expand the advisor's role** to actively hunt extreme/overnight campaigns *alongside*
   the existing small TODO-knockouts — an addition, not a replacement.

## DEFCON scale (1 = maximum readiness, per military convention)

- **DEFCON 1** — project-defining. Overnight campaigns: build a whole backend in one pass,
  generate a full regression + UI-capability test harness, line-by-line security audit of
  every file, deep research/analysis spike. Wake up to it done, pending approve/rollback.
- **DEFCON 2** — major. A whole feature/subsystem or significant refactor.
- **DEFCON 3** — standard. A normal feature or meaningful fix.
- **DEFCON 4** — minor. Small TODO knockouts, cleanups.
- **DEFCON 5** — cosmetic/trivial. Typos, comments, formatting.

DEFCON measures **impact only**. A one-line fix closing a critical security hole can be
DEFCON 1; a giant-but-cosmetic mass-rename can be DEFCON 4. Effort/scale is no longer rated.

## Design

### 1. Job data model — `jobs.py`

- **Remove:** `est_windows`, `depth`, the `tier` property, `tier_for`, `windows_for_depth`,
  `depth_for_windows`, `_DEPTH_WINDOWS`, `_TIER_BOUNDS`.
- **Add:** `defcon: int` (1–5, default 3). `value` stays as a within-DEFCON tie-breaker,
  now optional (defaults 0).
- `parse_jobs` requires `id` + `defcon`. A legacy dict with no `defcon` defaults to DEFCON 3
  so old `queue.json` files don't crash. No depth↔windows back-compat mapping — clean break.
- Clamp `defcon` to [1, 5].

### 2. Matcher — `advisor.py`

Becomes a pure **priority sort**, no budget. `match(jobs, roe)` returns a `COA` with:
- `queue` — eligible jobs sorted by `(defcon asc, value desc)`.
- `blocked` — **ROE rule** violations only (disallowed `type`, excluded path).

**Remove:** `over_budget`, `headroom_windows`, `fits_windows`, `weekly_reserve_pct` as a
matcher field, `window_headroom`, the value/cost density ranking, the `headroom` parameter.
The weekly-burn % remains available to the report layer as **display context only**, never
a gate.

`note` text updated: no "windows free now"; instead summarize counts by DEFCON
(e.g. "3 jobs queued — 1 at DEFCON 1 (approval required), 2 auto-run.").

### 3. ROE — `roe.py`

- **Remove (cost family):** `max_windows`, `per_job_max_windows`, `max_est_windows`.
- **Keep:** `max_jobs` (run-length leash), `min_weekly_left` (grounded in the real weekly
  signal), `allowed_types`, `unattended_types`, `test_cmd`, `setup_cmd`, `exclude_paths`,
  `goals`.
- **New task rule:** `auto_run_min_defcon: int = 3`. Jobs *more critical* than this
  (i.e. DEFCON number **<** the threshold — 1 and 2 by default) are queued but flagged
  **approval-required**: the runner will not launch them unattended. DEFCON ≥ threshold
  auto-run, still subject to the existing additive-vs-transformative `unattended_types`
  safety gate. This is a **task rule**, not a cost cap.

### 4. Runner + cockpit — `runner.py`, `coa_serve.py`

- **Delete the predictive budget layer:** `EnvelopeTracker`, `plan_run`'s budget
  forfeiting, per-window charge/reservation, headroom reads, fit/over annotations.
- The runner drains the battle plan in **DEFCON order** and runs until: the work is done,
  `max_jobs` is hit, an approval-required (DEFCON < `auto_run_min_defcon`) job is reached
  without approval, or the **real** rate limit halts it. The existing halt-on-real-usage-
  limit + snapshot re-sync behavior **stays** — it is the honest stop signal.
- `state_json`: drop `headroom`/`fits`/window fields; each job dict carries `defcon` and an
  `approval_required` boolean.
- The cockpit's per-repo concurrent workers and global one-job-per-repo behavior are
  retained where they don't depend on the shared budget pool; the **shared-budget
  reservation** (whose only purpose was overspend protection against an estimate) is removed
  — concurrency is now bounded by worker count and `max_jobs`, not a budget pool.

### 5. Scan agent's expanded role — `commands/coa.md`, `bin/scorch` prompt

The scan prompt now explicitly directs the agent to surface the **full spectrum**:

- **Extreme / overnight campaigns** (DEFCON 1): build an entire roadmap phase in one pass,
  generate complete test harnesses (regression + UI capability), exhaustive line-by-line
  security analysis, deep research/analysis spikes — framed as "approve, walk away, wake up
  to it done."
- **…alongside** the existing knockouts (DEFCON 4–5) and normal work (DEFCON 2–3).
- Each job emits `id`, `repo`, `title`, `type`, `defcon` (1–5), `value` (tie-break), a
  one-line impact `rationale`, and `launch`. The agent rates **impact on the project**,
  never effort/length. The prompt explicitly forbids effort/duration estimation.

### 6. Reports & templates — `coa_report.py`, `coa_template.html`, `cockpit_template.html`, `review_template.html`

- Cards swap the DEPTH/tier/window-cost readout for a **DEFCON badge** (1 = red-alert
  styling, 5 = quiet), sorted most-critical-first; approval-required jobs carry a marker.
- Aggregate headroom/windows gauges → the real weekly-burn signal as honest context.
- The `__*_JSON__` contract carries `defcon` + `approval_required` instead of
  `depth`/`est_windows`/`tier`/headroom. Remove the dead `TIER` const noted in the backlog.

### 7. Tests

- `test_advisor.py` — priority sort by `(defcon, value)`, ROE-block (type/path), legacy
  default-DEFCON parse, clamp; no budget assertions.
- `test_runner.py` — drain order by DEFCON, approval-required halt, no `EnvelopeTracker`,
  halt-on-real-limit + re-sync intact, `max_jobs` cap.
- `test_cockpit.py` — DEFCON board state, `approval_required` surfaced, no headroom/budget
  fields; concurrency bounded by workers not budget.
- The 57 core checks (`tests/test_scorched.py`) are untouched.

## Non-goals

- No change to the statusline / weekly-burn engine.
- No back-compat shim translating old depth/windows jobs into DEFCON (default-3 on parse is
  the only concession).
- No new budget signal of any kind in the COA layer.

## Risks / judgment calls

- **Default `auto_run_min_defcon = 3`** (DEFCON 1–2 need approval). Tunable via ROE.
- **Clean break** on the data model — any persisted `queue.json` with old jobs parses to
  DEFCON 3 rather than a mapped value.
- Removing the shared-budget reservation slightly changes multi-repo concurrency semantics
  (now worker/`max_jobs`-bounded, not budget-bounded); acceptable since the budget pool was
  built on an estimate we're deleting.
