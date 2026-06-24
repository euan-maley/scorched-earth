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
     with `scorch roe <repo>` first, then dispatch an adversarial + constructive scan agent
     bounded by those rules (respect `exclude_paths`, `allowed_types`, `goals`). The agent
     returns a JSON array of jobs matching the schema (`id, repo, title, type, est_windows,
     value, rationale, launch`); write it to `<repo>/.scorched/jobs.json`. The adversarial lens
     finds gaps (thin tests, stale deps, weak error handling); the constructive lens finds big
     exhaustive jobs worth the compute.
3. Run `scorch advise <repo>` (fallback `~/scorched-earth/bin/scorch advise`) to budget-match and
   print the ranked queue. It refuses if there's no live snapshot yet; relay that as-is.
4. Summarize the top of the queue and point the user at the written COA. Don't invent numbers;
   relay what `scorch` prints.
