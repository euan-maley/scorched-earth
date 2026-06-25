# COA Budget Model + UX Revision — Design

**Date:** 2026-06-25
**Branch:** `feat/burn-advisor` (local/unpushed)
**Status:** approved design → writing-plans next

## Problem

The COA advisor reuses the Phase-1 weekly burn signal (`windows_left`) as its
execution budget gate. `windows_left` is *windows-of-time-until-the-weekly-reset*,
discounted for sleep and pro-rated across a straddling window. That is the correct
number for the green-light ("can your weekly reserve still be spent before reset?")
but the **wrong** number for "what can I run right now."

Observed live: `five_hour_pct=5` (current 5h window 95% free), `seven_day_pct=81`
(19% weekly reserve), but `seven_day_reset` is ~1h away, so `windows_left` collapsed
to **0.20**. The COA matcher forfeited **all 9** scanned jobs ("nothing fits") — even
though the user has a 95%-free 5-hour window in front of them and the runner can keep
working straight across the weekly reset into a fresh week.

Two distinct questions were sharing one number:
- **Weekly green-light** — "use it or lose it before reset" (time-bounded). KEEP.
- **COA execution headroom** — "what can I run now, and when do I stop." NEW.

Three things to fix (user-raised):
1. The COA generation workflow is mechanical and shouldn't clutter the main thread.
2. The budget gate is wrong for execution (above).
3. The HTML report generation is a manual step; `scorch advise` only prints Markdown.

## Design

### Part A — Decouple COA execution headroom from the weekly green-light

**A1. New headroom number (separate from `windows_left`).**
COA execution headroom = the unused capacity of the **current 5-hour window**, in
window-units (0..1.0):

```
headroom = max(0, (100 - five_hour_pct) / 100)        # the user's "% usage left in current window"
weekly_reserve_pct = max(0, 100 - seven_day_pct)      # shown as context only, NOT a gate
```

- `headroom` is the soft-fit basis (in the observed case `0.95`). `weekly_reserve_pct`
  (19%) and the weekly reset time are shown as **context** next to it, not converted to
  windows and not used to gate — the gate is soft and the real-limit halt is the true
  backstop, so an optimistic suggestion is acceptable (no `R` dependency, less risk).
- Pure helper, reads the cached snapshot. Lives in `advisor.py` (COA, pure). A parallel
  `read_headroom(state)` in `runner.py` mirrors `read_envelope` for the execution path.
  **`core.py`, `calibrate.py`, `statusline.py` are NOT touched** — the green-light is
  unchanged.

**A2. `advisor.match` annotates, never forfeits.**
- Signature moves from `match(windows_left, jobs, roe)` to `match(headroom, jobs, roe)`.
- Every ROE-allowed job is returned, ranked by value as today, each carrying a
  `fit` flag: `"fits"` (cumulative tier-and-fill stays within `headroom`) or
  `"over"` (beyond it). **No job is dropped for budget.**
- ROE-blocked jobs are still surfaced separately (`blocked-roe`), as today.
- `COA` dataclass: replace `left_on_table` with `over_budget`; keep `queue` = the
  `fits` set. Both are ranked. (Convenience accessors as needed.)

**A3. Report (`coa_report.py`, md + html).**
- "Left on the table" → **"Over budget (queue anyway)"**.
- Add a headroom readout: `~0.95 window free now · weekly resets in 1h, 19% reserve`.
- HTML badges per job: `FITS` vs `OVER`. Both md + html rendered from one source.

**A4. Cockpit (`coa_serve.py` + `cockpit_template.html`).**
- Board shows the headroom readout + weekly-reserve context (a HUD line).
- Proposed cards carry a `fits`/`over` badge; fitting jobs are visually suggested
  (soft) but everything is freely queueable — the badge is **cosmetic, never a wall**.
- **Drop the budget gate from execution.** Workers drain whatever is queued. This
  supersedes the just-built shared-budget reservation: the `EnvelopeTracker`
  (predict-then-resync) and the charge-at-pick reservation under the lock **retire**.
  Per-repo concurrent workers REMAIN; what changes is they no longer gate/charge a
  budget envelope — they drain until the shared halt fires.

**A5. Runner (`runner.py`).**
- `pick_next` drops the budget argument/gate — returns the next ROE-allowed queued job.
- Drain loop stops on: **queue empty**, OR a headless `claude -p` job returns a
  **usage-limit** error (→ halt the whole queue; that job and the remaining queued
  jobs become `halted: limit`, *not* `fail`, so a later run resumes), OR an
  **optional user cap** is reached.
- **Usage-limit detection** is the one open implementation question: how to reliably
  recognize the limit signal from a headless `claude -p` (parse stderr / exit code /
  message). VERIFY via a claude-code-guide lookup before building; if unrecognizable,
  fall back to the optional cap as the only bound and document the gap.
- **Optional cap** (ROE fields, default off/None): `max_jobs` and/or
  `max_est_windows`. When set, the drain halts once the cap is reached (remaining →
  `halted: cap`). Off by default — pure run-until-limit unless the user opts in.
- `plan_run` (pure pre-run disposition) loses `skipped-budget`; dispositions become
  `run` / `blocked-roe`, with the `fits`/`over` annotation surfaced for the report.

**A6. Green-light untouched.** `windows_left` and the Phase-1 verdict remain the
statusline + sitrep signal, unchanged.

### Part B — `scorch advise` writes + opens the HTML report (and keeps the MD)

- `scorch advise [repo] [--no-open]` renders **both** `coa_report.render_md` and
  `render_html`, writes them via `coa_io.write_coa` (per-repo `.scorched/coa/<date>.{md,html}`),
  and **opens the HTML** by default (same opener logic as `scorch --sitrep`).
  `--no-open` skips opening. With a single repo, open its HTML; with multiple repos,
  write all and open none (print the paths) — avoids a browser-tab storm.
- **HTML is the artifact you view; MD is the durable record** for skill history and
  later-session context (the COA-officer subagent and future runs read the MD).
- Refuses (as today) when there is no usable snapshot.

### Part C — `/coa` dispatches a single "COA officer" subagent

- `commands/coa.md` becomes a thin command that dispatches **one** subagent to run the
  whole mechanical pipeline: ensure/refresh `jobs.json` (the scan, when missing or
  `--refresh`) → `scorch advise` (which now budget-annotates + writes + opens the
  report) → return a clean **~4-line briefing**: top jobs by value, count over budget,
  current headroom, report path.
- The main thread shows only that briefing; the user can expand the subagent view for
  the scan/advise detail. `/war-room` and `/sitrep` stay separate one-liner commands.

## Components & boundaries

| Unit | Change | Depends on |
|------|--------|-----------|
| `advisor.py` | `headroom` helper; `match` annotates `fits`/`over`, no forfeit | `jobs.py`, snapshot, `R` |
| `runner.py` | `read_headroom`; `pick_next` ungated; drain halts on usage-limit/cap; `plan_run` drops skipped-budget | `coa_io`, `claude -p` |
| `coa_report.py` | "Over budget" section, headroom readout, fit badges (md+html) | `advisor` COA shape |
| `coa_serve.py` | board headroom readout; drop EnvelopeTracker/reservation; workers drain ungated; shared halt | `runner`, `coa_io` |
| `cockpit_template.html` | headroom HUD line; fit/over badge; suggest-fits | injected JSON |
| `bin/scorch` | `advise` writes+opens html+md (`--no-open`) | `coa_report`, `coa_io` |
| `commands/coa.md` | dispatch one COA-officer subagent; tidy briefing | scan agent, `scorch advise` |
| ROE (`roe.py`/`coa_io`) | optional `max_jobs` / `max_est_windows` caps (default off) | — |

**Untouched:** `core.py`, `calibrate.py`, `statusline.py`, the green-light/sitrep.

## Testing

- `advisor`: headroom math (window-free, weekly-reserve cap, the `min`); `match`
  annotates every job `fits`/`over` and forfeits nothing; ranking preserved;
  ROE-blocked still excluded.
- `runner`: `pick_next` ungated returns next allowed job; drain halts on a simulated
  usage-limit outcome (remaining → `halted: limit`); optional cap halts (→ `halted: cap`);
  `plan_run` no longer emits `skipped-budget`.
- `coa_serve`: workers drain a queue with no envelope; a usage-limit on one job halts
  all workers; board JSON carries headroom + per-job fit flag.
- `coa_report`: md + html render the "Over budget" section + headroom readout + badges;
  no unsubstituted tokens.
- `bin/scorch advise`: writes both files; opens html unless `--no-open`.
- Keep all four existing suites green; the parallel-execution tests are revised for the
  no-envelope model (concurrency proof stays; shared-budget-reservation test is replaced
  by a shared-halt test).

## Risks / notes

- **Supersedes part of the just-built parallel feature.** The charge-at-pick reservation
  + `EnvelopeTracker` were built this session to share a budget envelope across concurrent
  repos. Dropping the envelope removes that machinery; the concurrency (per-repo workers)
  stays. This is a deliberate evolution, not a regression — call it out in the plan.
- **Usage-limit detection** from headless `claude -p` is unverified; it is the riskiest
  unknown. Verify first; the optional cap is the fallback bound.
- **`--no-open` / multi-repo open** behavior for `advise` is a small open detail to settle
  in the plan.
```
