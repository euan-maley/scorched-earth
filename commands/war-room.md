---
description: Open the Scorched Earth War Room — the live COA cockpit (kanban + parallel per-repo runner) in the browser
argument-hint: "[repo path] | stop"
allowed-tools: Bash(scorch:*), Bash(*/bin/scorch:*), Bash(pgrep:*), Bash(pkill:*), Read
---

Launch (or stop) the **War Room** — the live COA cockpit served at `127.0.0.1`: a kanban board
(Proposed → Queued → Running → Secured/Cratered) with per-repo tabs, drag-to-queue/reorder,
Run / Run-all, and Kill. Armed repos drain **concurrently** (one job per repo, repos at once)
sharing one weekly budget. It's `scorch coa --serve` under the hood; this command just runs it
in the background and hands you the URL.

## If `$ARGUMENTS` is `stop`

Find and stop the running cockpit:

```bash
pgrep -f "coa --serve" >/dev/null && pkill -f "coa --serve" && echo "War Room stopped." || echo "No War Room running."
```

Report the result, then stop. Don't launch anything.

## Otherwise (launch; an optional repo path scopes to one linked repo)

`scorch coa --serve` blocks on its event loop, so it MUST run in the background — never
foreground (that hangs the turn).

1. Launch it detached and capture its output (second form is the PATH fallback):

   ```bash
   scorch coa --serve $ARGUMENTS 2>&1 || ~/scorched-earth/bin/scorch coa --serve $ARGUMENTS 2>&1
   ```

   Run this in the **background**. The CLI prints one line and then serves:
   `COA cockpit on http://127.0.0.1:PORT/?t=TOKEN` (the print is flushed, so it appears
   immediately) and it auto-opens your default browser.

2. Read the background output to get that line.
   - If it printed **`No repos linked`**, tell the user to link a repo first
     (`scorch link <path>`) and stop — nothing is serving.
   - Otherwise relay the **full URL** verbatim, on its own line, with this caveat:
     *the URL embeds a one-time access token — treat it as a credential; don't paste it into
     shared chats, screenshots, or shared terminals.* The browser should already be opening; if
     it didn't, the user clicks this URL.

3. Tell the user the War Room runs until stopped, and that **`/war-room stop`** shuts it down
   (or Ctrl-C if they later run it in a foreground terminal).

Only relay what the command prints — don't invent a port, token, or status.
