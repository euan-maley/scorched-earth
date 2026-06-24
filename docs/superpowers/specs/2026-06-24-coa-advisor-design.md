# COA Advisor — Design Spec

**Date:** 2026-06-24
**Branch:** `feat/burn-advisor` (local, not pushed until working or ready for testing)
**Status:** Phase 1 design, approved in brainstorming, pending implementation plan.

## The idea

Scorched Earth tells you *when* to burn (the green light) but not *what* to burn on.
This feature closes that loop. It turns the budget signal into actionable work: given how
much weekly budget you have and how much time before the reset, it proposes expensive,
budget-sized jobs in your linked repos and (in later phases) runs them.

The framing is deliberately wider than "burn it all" mode. Green is the *urgent* trigger
("burn now or forfeit"), but the real product is a **weekly budget-spending planner**: you
have N% of weekly budget and a window of time, here is expensive work worth pointing it at,
run it now or queue it for the optimal slot.

The unique input nobody else has is Scorched Earth's own math: it already computes windows
left before the reset, % weekly remaining, and your learned active hours. That lets it
**size** the suggested work to fit the available burn, which is the differentiator.

### Naming (the war register, consistent with the rest of the tool)

- **`/coa` (Course of Action)** generates the report: scan the repo, budget-match, present
  the ranked job queue.
- **`/roe` (Rules of Engagement)** edits the confines that bound the work: which repos, cost
  ceilings, goals, what the agent may and may not do.

## Scope

### In scope (Phase 1, this spec): the advisor

Link repos, scan them for expensive work, and produce a **budget-matched, ranked Course of
Action** with a ready-to-run launch command per job. The user runs the jobs themselves
(execution path C). No autonomous queue-runner, no scheduling yet.

Phase 1 exists to prove the make-or-break question cheaply: **are the suggestions good enough
to trust?** before building the risky autonomous executor.

### Out of scope (designed-for, later phases)

- **Phase 2:** the queue-runner. Drains the COA queue, re-checking remaining budget between
  jobs, with guardrails (worktree/branch isolation, commit-not-push, run tests after, a
  morning-after review surface). Local headless execution (path B).
- **Phase 3:** scheduling (run at the last window, or a proactive earlier slot in the week)
  and the cloud-routine execution path (A).

The Phase 1 job schema reserves the `status` and `launch` fields precisely so the Phase 2
queue-runner plugs in without reshaping anything.

### Execution paths (full vision, for context)

Three user-selectable execution paths, recommended in this order:

- **C. Prep-and-handoff** (Phase 1, and always the fallback): produce the plan + launch
  command, the user pulls the trigger.
- **B. Local headless** (`claude -p` in a worktree, Phase 2): autonomous on the user's
  machine.
- **A. Cloud routine** (`/schedule`, Phase 3): autonomous on Anthropic infra, survives
  laptop sleep, **last recommended** unless the user opts in, because it spends in a separate
  context that may not surface in the weekly bar the way an interactive session does.

## Architecture & surfaces

The hard constraint: scanning a repo adversarially for expensive work needs a Claude agent,
not Python. The budget arithmetic should stay pure Python (fast, testable, keeps `core.py`
and the statusline hot path untouched). So the feature splits along that line. We are not
dogmatic about Python: each component uses whatever fits, deterministic math in Python,
judgment in Claude.

**Python (new module, isolated from the hot path):**
- `advisor.py` — the budget-to-job matcher. Pure. Takes the current snapshot plus a tiered
  job list, returns the ranked queue that fills the available burn. Unit-testable.
- Config/state under `~/.claude/scorched-earth/`: the linked-repos registry (`repos.json`)
  and the global default ROE.
- CLI verbs: `scorch link <path>`, `scorch advise` (print the matched queue from existing
  lists), `scorch roe` (print the effective rules).

**Skill / commands (the Claude-facing surface):**
- `/coa` — orchestrates the scan agent when needed, then renders the Course of Action.
- `/roe` — edits the rules of engagement conversationally and writes them.

Division of labor: **Python = config + matching math + rendering; Claude = the agent scan +
value/size judgment + orchestration.**

## Rules of Engagement (`/roe`)

ROE is the confines that bound the advisor (and later the executor). Three rule families:

- **Cost rules** (ties the COA to the budget math): spend down to X% weekly remaining, max N
  windows per COA, a per-job ceiling, and a floor (don't propose burning unless weekly-left
  is above Y% or we're green).
- **Task rules** (operational confines, mostly shaping the scan in Phase 1, the executor's
  leash in Phase 2): allowed job types (test / docs / refactor / perf / audit), hard
  prohibitions (never push, never touch `main`, no major dependency bumps, no file deletes),
  requirements (work in a worktree/branch, run the test suite after).
- **Goal rules** (what to aim for and weight): prioritize a path or objective ("get `core/`
  to 80% coverage", "harden error handling"), and exclusions ("ignore `vendor/`, `legacy/`").

**Storage:**
- Per-repo ROE lives **inside the target repo** at `.scorched/roe.json`. It travels with the
  repo, is version-controlled there, and a team can share it.
- A **global default ROE** lives centrally (`~/.claude/scorched-earth/roe.default.json`);
  per-repo files inherit and override it.
- The central **linked-repos registry** (`repos.json`) tracks which paths are in scope.

## The COA flow (`/coa`)

Optionally scoped to a repo; default is all linked repos. For each repo:

1. **Read the budget.** Pull the snapshot from `state.json` (windows left, % weekly
   remaining, active hours, verdict). No snapshot: refuse rather than guess (the `--report`
   honesty rule), or accept manual figures.
2. **Load effective ROE.** Global default merged with the repo's `.scorched/roe.json`.
3. **Ensure a job list** (three modes):
   - **Use found:** if `.scorched/jobs.json` (or a backlog the ROE points to) exists, use it.
   - **Generate if missing:** no list, spawn the scan agent.
   - **Force regenerate:** `/coa --refresh` re-scans regardless.
   The scan is the **adversarial + constructive agent**, bounded by ROE (goals, exclusions,
   allowed types). Adversarial finds gaps (thin coverage, stale deps, weak error handling);
   constructive finds big exhaustive jobs worth the compute. It writes the tiered job list
   back to the repo.
4. **Match (pure).** Convert available capacity into a compute envelope, then **tier-and-fill**:
   greedily select jobs by value-per-window until the envelope is full, honoring ROE cost
   caps. Output is the ranked COA queue that drains the available burn.
5. **Render** to both formats (see Output), and open the HTML.

### Job schema

What the scan writes and the matcher reads:

```
id           # stable identifier
repo         # which repo
title        # short label
type         # test | docs | refactor | perf | audit | ...
tier         # S | M | L | XL   (human-readable compute size)
est_windows  # rough cost in window-units, emitted by the scan agent (matcher input)
value        # the agent's worth ranking (matcher input, drives priority)
rationale    # why it's worth running (the adversarial/constructive finding)
launch       # the prompt/command to run it (Phase 1 hands this to the user)
status       # proposed | queued | done   (Phase 2+ uses this)
```

The scan agent emits `est_windows` and `value` directly; `tier` is a derived human-readable
label (a bucketing of `est_windows`), not a separate input. `status` + `launch` are the seams
Phase 2's queue-runner plugs into.

### Matching (tier-and-fill)

Pure Python, deterministic given the agent-assigned `est_windows` and `value`:

- **Envelope** = available capacity as window-units: `windows_left` discounted by
  `active_fraction`, then capped by ROE cost rules (e.g. "max N windows").
- **Fill**: greedily select jobs by value-per-window (value / est_windows) until the envelope
  is full, skipping jobs that violate ROE (disallowed type, over per-job cap, tier cap).
- **Output**: the ordered queue plus a summary of what fit and what spilled over.

The agent judges value and size during the scan; Python does the exact arithmetic and the
deterministic fill.

## Output: one source, two renderings

The matcher produces a single **structured COA result** (ranked queue + envelope + what-fit /
what-spilled). Both outputs render from that one object, so they never disagree (the same
pattern `report.py` uses to turn `state` into HTML):

- **Markdown = the record.** Written to `.scorched/coa/YYYY-MM-DD.md` in the repo. Diffable,
  greppable, version-controlled. Builds a history of what was recommended (and later, run).
- **HTML = the presentation.** The sitrep's war-HUD aesthetic, opens in the browser. Reuses
  the sitrep's pixel engine; can later become a panel/view of the sitrep itself.

## Error handling

All degrade honestly rather than fabricate:

- No snapshot: refuse or take manual figures.
- Linked repo path missing: skip it with a clear note, don't crash the whole COA.
- Scan agent fails or returns nothing: say so, keep any existing list.
- Empty result after scan: "no work worth burning on found" (honest, not padded).
- ROE parse error: fall back to the global default and warn.
- Zero available capacity (not green, no slack): "nothing to burn right now", don't force-fit.

## Testing

- **Matcher** (the pure core): thorough unit tests across tiers, envelopes, and ROE cost
  caps. This is the part that must be exact.
- **ROE** load plus default/override merge: round-trip tests.
- **Job schema** parse/validate.
- **Renderers**: Markdown from a fixed COA result (golden file); HTML smoke-render (like the
  existing report-render test).
- **Registry** (link/unlink): round-trip.
- **Scan agent**: not unit-tested (it is an agent). Test the plumbing around it with a mocked
  agent output, that it writes valid schema and respects ROE bounds.

## Invariants honored

- `core.py` stays pure and dependency-free; the statusline hot path is untouched. The advisor
  is a separate module that *reads* `state.json`, never sits in the statusline path.
- The statusline keeps working if the advisor fails (it is wholly separate).
- Honesty rule preserved: the COA refuses to fabricate a plan with no budget data, exactly as
  `--report` refuses a zeros dashboard.

## Resolved decisions

- **Cost source:** the scan agent emits `est_windows` directly. `tier` is a derived label
  (a bucketing of `est_windows`), not a separate matcher input.
- **Config format:** JSON throughout, for consistency with the rest of the project
  (`repos.json`, `roe.default.json`, `.scorched/roe.json`, `.scorched/jobs.json`). No new
  format dependency.
- **Surfaces:** `/coa` and `/roe` are standalone commands (like `/sitrep`), with `scorch`
  CLI verbs underneath (`scorch link`, `scorch advise`, `scorch roe`).
