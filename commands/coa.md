---
description: Generate a Course of Action — scan linked repos for expensive work and budget-match it to the available burn
argument-hint: "[repo path] [--refresh]"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Read, Grep, Glob, Agent
---

Generate a **Course of Action (COA)**: the budget-matched, ranked list of expensive jobs worth
running right now, given how much weekly budget is left and how close the reset is.

Steps:

1. Resolve the target repo(s): the `$ARGUMENTS` path if given, else `scorch advise` uses all
   linked repos (`scorch link <path>` adds one).
2. For each target repo, ensure a job list exists at `<repo>/.scorched/jobs.json`:
   - If it exists and `--refresh` was NOT passed, use it.
   - If it's missing, or `--refresh` was passed, run the scan. Load the repo's effective rules
     with `scorch roe <repo>` first, then dispatch the scan agent bounded by those rules (respect
     `exclude_paths`, `allowed_types`, `goals`, the cost caps). It returns a JSON array of jobs
     matching the schema (`id, repo, title, type, est_windows, value, rationale, launch`); write
     it to `<repo>/.scorched/jobs.json`.

   **What the scan hunts for** (the advisor's instinct, not a generic to-do scan): work *this
   moment* is uniquely good for, a real budget to spend, often an unsupervised window. Prefer
   work that is **compute-hungry** (exhaustive, not a quick fix), **bounded and verifiable**
   (clear done-condition, tests can confirm it), **low-coordination** (no product/design call
   mid-run), and **batchable** (churns across many files/modules).

   - **Ground in the user's intent first.** Read the repo's own signals before inventing work:
     `TODO`/`FIXME`, the issue tracker if reachable, a roadmap/CHANGELOG, recent commit themes,
     any existing `.scorched/jobs.json`. Surface the expensive items already flagged.
   - **Adversarial lens** fills the gaps not named: thin coverage, weak error handling, security
     holes, stale deps, undocumented modules, dead code, flaky tests.
   - **Constructive lens** proposes the one big exhaustive job worth a night of compute.
   - **Types, by blast radius.** Additive/low-risk (safe to run less supervised): test coverage,
     documentation, audits-as-reports, type coverage. Transformative/higher-risk (changes code,
     wants tests + review): refactors, dependency upgrades, migrations/codemods, performance,
     bug/flaky-test burndown. Lean additive for anything that might run unsupervised; flag
     transformative work as review-required in its `rationale`.
   - **Size to the budget.** Use the rough windows available (from `scorch`) to scope each job:
     propose work ambitious enough to be worth the window (whole-repo on a big night, one module
     when little is left). Set `est_windows` to the honest cost, `value` to its worth.
   - **Skip the trivial.** Do NOT propose quick one-off fixes, lint nits, or anything a human
     would just do inline; they waste a burn window. Skip work needing a product/design decision,
     work with no way to verify it, and speculative features the user never asked for.
3. Run `scorch advise <repo>` (fallback `~/scorched-earth/bin/scorch advise`) to budget-match and
   print the ranked queue. It refuses if there's no live snapshot yet; relay that as-is.
4. Summarize the top of the queue and point the user at the written COA. Don't invent numbers;
   relay what `scorch` prints.
