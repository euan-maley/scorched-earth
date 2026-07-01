---
description: Generate a Course of Action: scan linked repos for expensive work and rank it by DEFCON impact
argument-hint: "[repo path] [--refresh]"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Read, Grep, Glob, Agent, Task
---

Generate a **Course of Action (COA)**: a DEFCON-ranked list of expensive jobs worth running -
from project-defining overnight campaigns down to ordinary knockouts. The COA is sorted by
IMPACT (DEFCON), never by effort or how long a job would take.

1. Resolve the target repo(s): the `$ARGUMENTS` path if given (strip `--refresh`), else all
   linked repos (`scorch link <path>` adds one).

2. Dispatch ONE subagent - the **COA officer** - and give it the following instructions
   verbatim (substituting the actual repo path(s) and whether `--refresh` was passed):

   ---
   **COA officer instructions**

   You are the COA officer. Run the full scan-and-advise pipeline for the repo(s) listed below
   and return a tidy ~4-line briefing. Do not narrate your steps - just do the work and return
   the briefing at the end.

   **Target repos:** `<repo path(s)>`
   **Refresh flag:** `<yes/no>`

   ### Step 1 - Ensure a fresh job list

   A scan writes `<repo>/.scorched/jobs.json`; that file's mtime is the last scan time. For each
   target repo, decide whether to (re)scan. Do **not** blindly reuse an old `jobs.json`: if the
   repo has moved on since it was written, its jobs are stale and a re-run must refresh them.

   **Re-scan** the repo if ANY of these hold:
   - `<repo>/.scorched/jobs.json` is missing, or
   - the refresh flag is **yes**, or
   - the repo changed since the last scan. Compute (epoch seconds; the dual `stat` covers macOS + Linux):
     ```bash
     f="<repo>/.scorched/jobs.json"
     scanned=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)
     last_commit=$(git -C "<repo>" log -1 --format=%ct 2>/dev/null || echo 0)
     dirty=$(git -C "<repo>" status --porcelain 2>/dev/null)
     ```
     Re-scan if `last_commit` is greater than `scanned`, or `dirty` is non-empty. (If the repo
     is not a git repo, `last_commit` stays 0: reuse an existing `jobs.json` unless refresh is yes.)

   Otherwise the existing `jobs.json` is still current (nothing changed since the scan): **reuse it
   as-is**, and say so in the briefing (a cached scan from <relative age> ago, repo unchanged;
   `--refresh` forces a fresh one).

   To run the scan:
     1. Load the repo's effective rules with `scorch roe <repo>` (fallback
        `~/scorched-earth/bin/scorch roe <repo>`). Honour `exclude_paths`, `allowed_types`,
        and `goals` throughout.
     2. Read the repo's own signals first - `TODO`/`FIXME` markers, recent commit themes,
        any roadmap/CHANGELOG, open issues if reachable - and surface the expensive items
        already flagged. Do **not** invent work before grounding in what the repo already calls out.
     3. Apply an **adversarial lens** to fill the gaps: thin coverage, weak error handling,
        security holes, stale dependencies, undocumented modules, dead code, flaky tests.
     4. Apply a **constructive lens** to propose the big exhaustive campaigns worth a night of
        compute (whole roadmap phases, exhaustive audits, full test harnesses, deep research spikes).
     5. **Rate every job by DEFCON impact - see the rating block below.** Surface BOTH the
        extreme DEFCON-1 overnight campaigns AND the ordinary knockouts in the same scan.
     6. Note **blast radius** in each job's `rationale`: additive/low-risk work (test coverage,
        docs, audits-as-reports, type coverage) is safe to run unsupervised; transformative work
        (refactors, dep upgrades, migrations, perf, bug burndown) changes code and wants tests +
        review - flag it as review-required in the `rationale`.
     7. Emit each job per the schema in the rating block below and write the JSON array to
        `<repo>/.scorched/jobs.json`.

   **DEFCON rating (the core of the scan):**

   ```
   Rate every job by DEFCON - its IMPACT on the project, never its effort or length:
     - DEFCON 1: project-defining overnight campaigns. Actively look for these. Examples:
       build an entire roadmap phase (e.g. a whole backend) in one pass; generate a complete
       regression + UI-capability test harness; an exhaustive line-by-line security audit of
       every file; a deep research/analysis spike. Framed as "approve, walk away, wake up to
       it done - pending approve/rollback."
     - DEFCON 2: a whole feature/subsystem or a significant refactor.
     - DEFCON 3: a normal feature or meaningful fix.
     - DEFCON 4: small TODO knockouts, cleanups.
     - DEFCON 5: cosmetic/trivial (typos, comments, formatting).
   Do NOT estimate effort, duration, or window cost. Surface BOTH extreme DEFCON-1 campaigns
   AND ordinary knockouts in the same scan. Emit each job as:
     {"id","repo","title","type","defcon",1-5,"value",0-10 tie-break,"rationale","launch"}
   ```

   `defcon` is impact (1 = most critical, 5 = trivial). `value` is a 0-10 within-DEFCON
   tie-breaker. `launch` is the Claude Code command/prompt to kick the job off. `repo` is the
   absolute repo path; `type` is one of
   `test_coverage|docs|audit|refactor|dep_upgrade|migration|perf|bug_burndown|…`.

   ### Step 2 - Run `scorch advise`

   Run:

   ```
   scorch advise <repo> --no-open
   ```

   (fallback: `~/scorched-earth/bin/scorch advise <repo> --no-open`)

   `scorch advise` sorts every eligible job into the battle plan - **DEFCON-ordered, most
   critical first** (ties broken by `value`) - and routes ROE-disallowed types to **blocked**.
   Jobs below the ROE's `auto_run_min_defcon` gate (default DEFCON 1-2) are marked
   **(approval required)**: they need explicit `--approve` to run unattended. Nothing is sized
   or forfeited - the runner halts only on the real usage limit. It writes the HTML + Markdown
   record (`--no-open` skips popping the static file - the **live tabbed view** opens in step 4).
   It never writes a blank report: if a repo has no jobs yet it says so and skips it. If it
   reports no live snapshot yet, relay that message as-is.

   ### Step 3 - Return a briefing

   Return exactly this structure (fill in from `scorch advise` output - do NOT invent numbers):

   ```
   Battle plan (by DEFCON, most critical first):
     1. <title> - DEFCON <N>, value <N> [approval required?]
     2. <title> - DEFCON <N>, value <N> [approval required?]
     3. <title> - DEFCON <N>, value <N> [approval required?]

   Blocked by ROE: <N> job(s).
   Scan: <fresh, just now | cached from <relative age> ago, repo unchanged>
   Report: <path to HTML COA record>
   ```
   ---

3. When the subagent returns, print **only** its briefing. Note that the user can expand the
   subagent view in the Claude Code UI to see the full scan and advise detail.

4. **Launch the live COA report** (the served, tabbed view with a Refresh button). It runs
   `scorch advise --serve` (per-repo tabs across all linked repos; Refresh re-reads each repo's
   `jobs.json` - no repo re-scan). Like the War Room it **blocks**, so run it in the **background**:

   ```bash
   scorch advise --serve $ARGUMENTS 2>&1 || ~/scorched-earth/bin/scorch advise --serve $ARGUMENTS 2>&1
   ```

   Read the backgrounded output for the line `COA report on http://127.0.0.1:PORT/?t=TOKEN`
   (flushed immediately; it also auto-opens the browser). Relay that **full URL** verbatim on its
   own line, with the caveat: *the URL embeds a one-time access token - treat it as a credential;
   don't paste it into shared chats, screenshots, or shared terminals.* It serves until stopped
   (Ctrl-C, or kill the background process).

## Autonomous execution (Phase 2)

Once a COA exists you can have Scorched Earth burn it for you, unattended:

- `scorch coa queue --all` - enqueue the matched jobs into `.scorched/queue.json`.
- `scorch coa run [--approve]` - drain the queue: each job runs headless in a sandboxed git
  worktree (`scorched/<job-id>`), additive-only by ROE leash, commit-not-push, with a test gate
  after. Jobs below the ROE `auto_run_min_defcon` gate (high-impact DEFCON 1-2) are skipped
  unless you pass `--approve`. The runner halts only on the real usage limit. Opens a live
  After-Action Report that fills in as jobs complete.
- `scorch coa review` - reopen the latest After-Action Report. `--merge <id>` / `--discard <id>`
  print the git command to take or drop a job's branch.

Safety: only additive/verifiable job types run unattended (widen via ROE `unattended_types`);
nothing is pushed or merged without you. Set `test_cmd` and `setup_cmd` in the repo's ROE.

**Linux caveat:** the runner executes each job in an OS sandbox (settings written into the
worktree's `.claude/settings.json`: API-only network, filesystem confined). On macOS this
isolation is built in; on **Linux it requires `bubblewrap` and `socat` installed**. If unavailable,
`failIfUnavailable` means the job hard-fails rather than running unconfined.

## Live cockpit (Phase 2b)

`scorch coa --serve [<repo>]` opens a localhost cockpit - a live kanban board (Proposed →
Queued → Running → Secured/Cratered) with a per-repo tab toggle. Drag a job into Queued, reorder
what burns first, hit Run, and watch cards advance in place as work completes. The runner is
event-driven (one job at a time; no background loop). Security: binds 127.0.0.1, a one-time token
is required on every request, the server runs only the agent-supplied launch for a queued job-id
(never a command from the page), ROE is enforced server-side, and it dies when you Ctrl-C. The
access token is embedded in the cockpit URL (e.g. `http://127.0.0.1:PORT/?t=TOKEN`), so treat the
URL as a credential - never paste it into chat, screenshots, or shared terminals. Every job still
runs under the Phase 2a sandbox. Closing the window or Ctrl-C stops it. A running job can be
**killed** from its card - this aborts it, **discards its work** (you lose the partial output and
the tokens already spent), and returns the card to Proposed; the next queued job takes over.
