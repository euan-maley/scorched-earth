---
description: View or edit the Rules of Engagement (cost / task / goal confines) for a linked repo
argument-hint: "[repo path]"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Read, Edit, Write
---

View or edit the **Rules of Engagement (ROE)**: the confines that bound what the advisor and
(later) the executor may do.

- To **view** the effective rules: run `scorch roe <repo>` (it prints the merged JSON of the
  global default plus `<repo>/.scorched/roe.json`).
- To **edit**: the rules are three families, written to `<repo>/.scorched/roe.json`:
  - **cost / run-length** — `min_weekly_left` (don't propose unless weekly-left is above this),
    `max_jobs` (the run-length leash: stop after N jobs; off by default).
  - **task** — `allowed_types` (e.g. `["test","docs","refactor","perf","audit"]`),
    `auto_run_min_defcon` (default `3`: jobs with a DEFCON *below* this — i.e. high-impact
    DEFCON 1–2 — are gated behind explicit approval and only run with `scorch coa run --approve`).
  - **goal** — `goals` (objectives to weight), `exclude_paths` (globs to ignore).
  Apply the user's request (e.g. "stop after 5 jobs a night", "let DEFCON-2 work auto-run",
  "never touch migrations") by editing that JSON file, then show the result with
  `scorch roe <repo>`. There is no per-window/per-job cost cap — the runner halts on the real
  usage limit, not a budget estimate.

Confirm the change in one line. Only the keys the user asked about should change.
