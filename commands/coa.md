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
     it to `<repo>/.scorched/jobs.json`. The returned array must use the schema
     (`id, repo, title, type, depth, value, rationale, launch`).

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
     when little is left). Set `depth` (1–10, your honest relative cost rating) and `value` to its
     worth. Depth 1–2 is a quick strike (a few minutes of focused work); 9–10 is a major
     multi-window operation (whole-repo exhaustive pass). Do NOT emit `est_windows` — the tool
     derives the budget cost from `depth`, so you never guess windows.
   - **Skip the trivial.** Do NOT propose quick one-off fixes, lint nits, or anything a human
     would just do inline; they waste a burn window. Skip work needing a product/design decision,
     work with no way to verify it, and speculative features the user never asked for.
3. Run `scorch advise <repo>` (fallback `~/scorched-earth/bin/scorch advise`) to budget-match and
   print the ranked queue. It refuses if there's no live snapshot yet; relay that as-is.
4. Summarize the top of the queue and point the user at the written COA. Don't invent numbers;
   relay what `scorch` prints.

## Autonomous execution (Phase 2)

Once a COA exists you can have Scorched Earth burn it for you, unattended:

- `scorch coa queue --all` — enqueue the matched jobs into `.scorched/queue.json`.
- `scorch coa run` — drain the queue: each job runs headless in a sandboxed git worktree
  (`scorched/<job-id>`), additive-only by ROE leash, commit-not-push, with a test gate after.
  Budget is spent predictively (the runner can't read usage live); it stops when the envelope
  is exhausted. Opens a live After-Action Report that fills in as jobs complete.
- `scorch coa review` — reopen the latest After-Action Report. `--merge <id>` / `--discard <id>`
  print the git command to take or drop a job's branch.

Safety: only additive/verifiable job types run unattended (widen via ROE `unattended_types`);
nothing is pushed or merged without you. Set `test_cmd` and `setup_cmd` in the repo's ROE.

**Linux caveat:** the runner executes each job in an OS sandbox (settings written into the
worktree's `.claude/settings.json`: API-only network, filesystem confined). On macOS this
isolation is built in; on **Linux it requires `bubblewrap` and `socat` installed**. If unavailable,
`failIfUnavailable` means the job hard-fails rather than running unconfined.

## Live cockpit (Phase 2b)

`scorch coa --serve [<repo>]` opens a localhost cockpit — a live kanban board (Proposed →
Queued → Running → Secured/Cratered) with a per-repo tab toggle. Drag a job into Queued, reorder
what burns first, hit Run, and watch cards advance in place as work completes. The runner is
event-driven (one job at a time; no background loop). Security: binds 127.0.0.1, a one-time token
is required on every request, the server runs only the agent-supplied launch for a queued job-id
(never a command from the page), ROE is enforced server-side, and it dies when you Ctrl-C. The access token is embedded in the cockpit URL (e.g. `http://127.0.0.1:PORT/?t=TOKEN`), so treat the URL as a credential — never paste it into chat, screenshots, or shared terminals. Every
job still runs under the Phase 2a sandbox. Closing the window or Ctrl-C stops it. A running job can be **killed** from its card — this aborts it, **discards its work** (you lose the partial output and the tokens already spent), and returns the card to Proposed; the next queued job takes over.
