---
description: Generate a Course of Action — scan linked repos for expensive work and budget-match it to current-window headroom
argument-hint: "[repo path] [--refresh]"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Read, Grep, Glob, Agent, Task
---

Generate a **Course of Action (COA)**: the budget-matched, ranked list of expensive jobs worth
running right now, given how much headroom is left in the current window.

1. Resolve the target repo(s): the `$ARGUMENTS` path if given (strip `--refresh`), else all
   linked repos (`scorch link <path>` adds one).

2. Dispatch ONE subagent — the **COA officer** — and give it the following instructions
   verbatim (substituting the actual repo path(s) and whether `--refresh` was passed):

   ---
   **COA officer instructions**

   You are the COA officer. Run the full scan-and-advise pipeline for the repo(s) listed below
   and return a tidy ~4-line briefing. Do not narrate your steps — just do the work and return
   the briefing at the end.

   **Target repos:** `<repo path(s)>`
   **Refresh flag:** `<yes/no>`

   ### Step 1 — Ensure a job list

   For each target repo, check whether `<repo>/.scorched/jobs.json` exists.

   - If it exists and refresh is **no**, use it as-is.
   - If it is missing, or refresh is **yes**, run the scan:
     1. Load the repo's effective rules with `scorch roe <repo>` (fallback
        `~/scorched-earth/bin/scorch roe <repo>`). Honour `exclude_paths`, `allowed_types`,
        `goals`, and cost caps throughout.
     2. Read the repo's own signals first — `TODO`/`FIXME` markers, recent commit themes,
        any roadmap/CHANGELOG, open issues if reachable — and surface the expensive items
        already flagged. Do **not** invent work before grounding in what the repo already calls out.
     3. Apply an **adversarial lens** to fill the gaps: thin coverage, weak error handling,
        security holes, stale dependencies, undocumented modules, dead code, flaky tests.
     4. Apply a **constructive lens** to propose the one big exhaustive job worth a night of
        compute.
     5. Classify each job by **blast radius**:
        - *Additive / low-risk* (safe to run unsupervised): test coverage, documentation,
          audits-as-reports, type coverage.
        - *Transformative / higher-risk* (changes code, wants tests + review): refactors,
          dependency upgrades, migrations/codemods, performance work, bug/flaky-test burndown.
          Flag transformative work as review-required in its `rationale`.
     6. **Skip the trivial.** Do NOT propose quick one-off fixes, lint nits, or anything a
        human would just do inline. Skip work that needs a product/design decision, work with
        no way to verify it, and speculative features the user never asked for.
     7. Emit a JSON array of jobs matching this schema and write it to
        `<repo>/.scorched/jobs.json`:

        ```json
        [
          {
            "id": "<slug>",
            "repo": "<absolute repo path>",
            "title": "<short imperative title>",
            "type": "<test_coverage|docs|audit|refactor|dep_upgrade|migration|perf|bug_burndown|…>",
            "depth": <1–10>,
            "value": <1–10>,
            "rationale": "<why now, why this repo, blast-radius note>",
            "launch": "<the Claude Code command or prompt to kick this job off>"
          }
        ]
        ```

        `depth` is your honest relative cost rating (1–2 quick strike; 9–10 multi-window
        exhaustive). `value` is the job's worth. Do NOT emit `est_windows` — the tool derives
        budget cost from `depth`.

   ### Step 2 — Run `scorch advise`

   Run:

   ```
   scorch advise <repo>
   ```

   (fallback: `~/scorched-earth/bin/scorch advise <repo>`)

   `scorch advise` budget-annotates every job against the **current-window headroom** — the
   fraction of the 5-hour window still unspent — and sorts them into:
   - **fits** — within headroom, run these first.
   - **over budget** — eligible but beyond current headroom; still queueable.
   - **blocked** — disallowed by the rules of engagement.

   Nothing is forfeited. Over-budget jobs are still queueable for a future window. The command
   also writes and opens the HTML COA report (the Markdown file is kept as the record). If it
   reports no live snapshot yet, relay that message as-is.

   ### Step 3 — Return a briefing

   Return exactly this structure (fill in from `scorch advise` output — do NOT invent numbers):

   ```
   Top jobs (by value):
     1. <title> — depth <N>, value <N> [fits | over budget | blocked]
     2. <title> — depth <N>, value <N> [fits | over budget | blocked]
     3. <title> — depth <N>, value <N> [fits | over budget | blocked]

   Over budget: <N> job(s) queued for a future window.
   Current headroom: <headroom line from scorch advise>
   Report: <path to HTML COA report>
   ```
   ---

3. When the subagent returns, print **only** its briefing. Note that the user can expand the
   subagent view in the Claude Code UI to see the full scan and advise detail.

## Autonomous execution (Phase 2)

Once a COA exists you can have Scorched Earth burn it for you, unattended:

- `scorch coa queue --all` — enqueue the matched jobs into `.scorched/queue.json`.
- `scorch coa run` — drain the queue: each job runs headless in a sandboxed git worktree
  (`scorched/<job-id>`), additive-only by ROE leash, commit-not-push, with a test gate after.
  The runner halts when the current-window headroom is exhausted. Opens a live After-Action
  Report that fills in as jobs complete.
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
(never a command from the page), ROE is enforced server-side, and it dies when you Ctrl-C. The
access token is embedded in the cockpit URL (e.g. `http://127.0.0.1:PORT/?t=TOKEN`), so treat the
URL as a credential — never paste it into chat, screenshots, or shared terminals. Every job still
runs under the Phase 2a sandbox. Closing the window or Ctrl-C stops it. A running job can be
**killed** from its card — this aborts it, **discards its work** (you lose the partial output and
the tokens already spent), and returns the card to Proposed; the next queued job takes over.
