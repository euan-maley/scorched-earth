---
description: Open the Rules of Engagement editor (cost / task / goal confines) for your linked repos
argument-hint: "[repo path] | stop"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Bash(pgrep:*), Bash(pkill:*), Read, Edit, Write
---

Open the **Rules of Engagement (ROE) editor** in the browser: the confines that bound what the
advisor and the executor may do. It's `scorch roe --web` under the hood (the unified shell
opened on the RULES OF ENGAGEMENT tab); this command runs it in the background and hands you
the URL. Every click saves instantly to that repo's `.scorched/roe.json`.

## If `$ARGUMENTS` is `stop`

Find and stop the running editor server:

```bash
pgrep -f "roe --web" >/dev/null && pkill -f "roe --web" && echo "ROE editor stopped." || echo "No ROE editor running."
```

Report the result, then stop. Don't launch anything.

## Otherwise (launch; an optional repo path scopes to one linked repo)

`scorch roe --web` blocks on its event loop, so it MUST run in the background - never
foreground (that hangs the turn).

1. Launch it detached and capture its output (second form is the PATH fallback):

   ```bash
   scorch roe --web $ARGUMENTS 2>&1 || ~/scorched-earth/bin/scorch roe --web $ARGUMENTS 2>&1
   ```

   Run this in the **background**. The CLI prints one line and then serves:
   `War Room on http://127.0.0.1:PORT/?t=TOKEN#roe` (flushed, so it appears immediately) and it
   auto-opens your default browser on the RULES OF ENGAGEMENT tab.

2. Read the background output to get that line, and relay the **full URL** verbatim, on its own
   line, with this caveat: *the URL embeds a one-time access token - treat it as a credential;
   don't paste it into shared chats, screenshots, or shared terminals.*

3. Tell the user the editor runs until stopped (**`/roe stop`** shuts it down), that the same
   editor also exists in the terminal as `scorch roe <repo>` (arrow keys / hjkl, `s` save,
   `q` quit), and that the other shell tabs (SITREP / COA / WAR ROOM / AFTER-ACTION) are one
   click away in the same window.

## Editing conversationally instead

If the user asked for a specific change rather than "open the editor" (e.g. "stop after 5 jobs
a night", "let DEFCON-2 work auto-run", "never touch migrations"), skip the server: apply it by
editing `<repo>/.scorched/roe.json` directly, then show the result with
`scorch roe --json <repo>`. The rule families:

- **cost / run-length** - `min_weekly_left` (don't propose unless weekly-left is above this),
  `max_jobs` (stop after N jobs; off by default).
- **task** - `allowed_types` (e.g. `["test","docs","refactor","perf","audit"]`),
  `auto_run_min_defcon` (default `3`: DEFCON 1-2 jobs are gated behind explicit approval and
  only run with `scorch coa run --approve`), `unattended_types` (types allowed to run headless).
- **execution mode** - `run_mode` (`headless` default / `takeover` / `session`),
  `attended_perms` (`skip` default: attended sessions run with no permission prompts; `edits`
  auto-approves file edits only; `prompt` asks for everything), `context_cmd` (attended
  pre-task command, e.g. `/kerd:switch in`), `attended_branch` (fresh `scorched/<id>` branch vs.
  your current branch), `roadblock_idle_secs` (seconds of silence before stuck; default 600),
  `advise_on_roadblock` (auto-solve attempt before pausing; default on).
- **goal** - `goals` (objectives to weight), `exclude_paths` (globs to ignore).

There is no per-window/per-job cost cap - the runner halts on the real usage limit, not a
budget estimate. Confirm the change in one line. Only the keys the user asked about should
change.
