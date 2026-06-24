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
  - **cost** — `max_windows`, `per_job_max_windows`, `min_weekly_left`
  - **task** — `allowed_types` (e.g. `["test","docs","refactor","perf","audit"]`)
  - **goal** — `goals` (objectives to weight), `exclude_paths` (globs to ignore)
  Apply the user's request (e.g. "cap overnight jobs at 2 windows", "never touch migrations")
  by editing that JSON file, then show the result with `scorch roe <repo>`.

Confirm the change in one line. Only the keys the user asked about should change.
