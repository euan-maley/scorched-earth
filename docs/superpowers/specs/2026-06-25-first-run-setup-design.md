# First-run setup flow for the `/scorched-earth` skill

**Date:** 2026-06-25
**Scope:** The `/scorched-earth` skill only. No Python, no CLI surface, no statusline-hot-path
changes. The weekly-burn engine (`core.py`, `calibrate.py`, `habits.py`, `report.py`,
`statusline.py`) and the COA stack are untouched — setup only *drives* their existing entry
points (`scorch --style`, `scorch link`, `scorch list`).

## Problem

Installing the plugin wires the statusline and seeds a default light style, but there is no
onboarding. Two gaps:

1. **The COA advisor has nothing to advise on.** Repos must be linked (`scorch link <path>`)
   before `/coa` / `/war-room` do anything, and nothing prompts the user to do that — they
   have to discover `scorch link` on their own.
2. **Claude starts cold.** On a fresh session it hasn't read the green-light math or the
   DEFCON/COA model, so the first conversation about "should I burn?" or "what should I run
   overnight?" is under-informed.

A guided first-run setup closes both: it primes Claude on the model and walks the user
through the choices that make the rest of the plugin useful (light style, linked repos).

## Goals

1. **Trigger on the first `/scorched-earth` run**, gated on a sentinel file, and stay out of
   the way on every run after.
2. **Familiarize Claude** with the model before it guides the user.
3. **Walk the user** through a short tour, a light-style choice, and repo-linking.
4. **Re-runnable** on demand without reinstalling.
5. **Zero cost on the routine path** — the normal "should I burn?" readout must not pay any
   token or latency tax for setup that has already happened.

## Non-goals

- No persistent "training" of Claude. Familiarization loads the model into the *current
  session's* context; it does not and cannot carry across sessions. Ongoing sessions still
  rely on `CLAUDE.md` + `docs/` as today. The spec is honest about this in the primer.
- No new Python module, no new `scorch` subcommand, no new slash command.
- No change to the SessionStart hook (it is the statusline engine; its invariant is "never
  fail the session"). Setup is purely skill-driven and only runs when the user invokes the
  skill.

## Approach

**Skill gate + sibling `setup.md`.** SKILL.md gains a short gate at the very top; the full
guided flow and the model primer live in a sibling `setup.md` that routine runs never load.

Rejected alternatives:
- *Everything inline in SKILL.md* — SKILL.md is fully loaded on every invocation, so an
  inline primer would cost tokens on every routine burn-check. Rejected for goal 5.
- *Separate `/scorch-setup` command* — contradicts the chosen trigger (first `/scorched-earth`
  run). `setup.md` instead doubles as the re-run target.

### State / sentinel

- File: `~/.claude/scorched-earth/onboarded` (sits alongside `style`, `fc-notified` under
  `STATE_DIR`). Plain marker file; its presence means setup has completed. Content is a
  short human-readable line (e.g. the completion date) for the curious — not parsed by
  anything.
- Created by the skill at the end of setup via a plain `touch`/write (Bash). No Python.
- Re-run: the user asks ("redo scorched-earth setup", "re-run setup") or removes the file
  (`rm ~/.claude/scorched-earth/onboarded`). Both documented in `setup.md`. When the user
  explicitly asks to re-run, the skill follows `setup.md` even though the sentinel exists.

### SKILL.md gate (added at the top of "What to do")

Before the normal readout, the skill checks:

```bash
test -f ~/.claude/scorched-earth/onboarded && echo onboarded || echo first-run
```

- `first-run` → read and follow `setup.md` (the setup flow ends by falling through to the
  normal readout, so the first run still finishes with a verdict).
- `onboarded` → proceed directly to the existing readout, unless the user explicitly asked
  to re-run setup.

The gate is a few lines; the bulk stays in `setup.md`.

### `setup.md` flow (in order)

1. **Familiarize Claude.** Claude reads the embedded primer so it can guide knowledgeably:
   - the green-light guarantee (you cannot spend the weekly budget unless you max every
     remaining 5-hour window) and R (self-measured fraction of the weekly cap one full
     window burns);
   - the sitrep (the HTML war/crop-field HUD, `/sitrep`);
   - the COA advisor model — DEFCON 1–5 criticality (1 = biggest blast radius, *not* "do
     first"), the `auto_run_min_defcon` approval gate, the queue-runner, and the live
     war-room cockpit (`/coa`, `/roe`, `/war-room`).
   This is a read step — no user-facing output yet. Honest caveat included in the primer:
   this primes the current session only.

2. **Explain to the user.** A short tour of what they just installed: the statusline light,
   `/sitrep`, the COA advisor + `/war-room`. A few lines, not a wall of text.

3. **Pick the light style.** Offer the five styles (reuse the wording from SKILL.md's
   "Setting the statusline light style") and set the choice:

   ```bash
   scorch --style <fire|emoji|text|minimal|off>
   ```

   Default stays `fire` if the user has no preference.

4. **Link repos.** Ask which repos the user wants the COA advisor watching. Accept pasted
   absolute paths; as a convenience, offer to scan a dev directory the user names for git
   repos and present them. For each chosen repo:

   ```bash
   scorch link <path>
   ```

   Confirm the result with `scorch list`. Linking is optional — a user who only wants the
   green light can skip it (the COA features simply stay idle until they link something
   later).

5. **Finish.** Write the sentinel, then fall through to the normal `scorch` readout so the
   first run still ends with a burn verdict:

   ```bash
   date > ~/.claude/scorched-earth/onboarded
   ```

## Components & boundaries

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `SKILL.md` (gate) | Detect first-run vs onboarded; route to `setup.md` or the normal readout; honor an explicit re-run request | `onboarded` sentinel; `setup.md` |
| `skills/scorched-earth/setup.md` (new) | The guided flow + the model primer; sentinel creation; re-run docs | `scorch --style`, `scorch link`, `scorch list` (existing); primer is self-contained |

`setup.md` is self-contained (the primer is embedded, not a pointer to `docs/`) so it works
regardless of where the plugin is installed. SKILL.md and `setup.md` change independently:
the gate doesn't care what's inside the flow, and the flow doesn't care how it was triggered.

## Error handling / edge cases

- **`STATE_DIR` missing.** The SessionStart hook `mkdir -p`s it, but setup should not assume
  a session ran first; `date > …/onboarded` after `mkdir -p ~/.claude/scorched-earth` is
  safe. The skill creates the dir if needed before writing the sentinel.
- **`scorch` not on PATH** (terminal vs in-session). SKILL.md already handles this with the
  `scorch … || ~/scorched-earth/bin/scorch` fallback; `setup.md` uses the same pattern for
  every `scorch` call.
- **User skips repo-linking.** Allowed; setup still completes and writes the sentinel. The
  tour notes they can link repos later.
- **Re-run when already onboarded.** Only on explicit user request; otherwise the gate
  short-circuits to the readout so routine invocations are never interrupted.
- **Bad repo path** (`scorch link` on a non-existent dir). Report what `scorch` prints; the
  CLI already realpath-expands and gitignores — surface its output, don't fabricate success.

## Testing

The change is skill markdown (Claude-driven), not Python, so there are no new unit tests —
the existing 239-check suite stays green and unaffected (no source files touched). Verify by
exercising the flow manually:

1. `rm -f ~/.claude/scorched-earth/onboarded`, invoke `/scorched-earth` → setup runs:
   tour shown, style set, a repo linked (confirm in `scorch list`), sentinel written, verdict
   printed at the end.
2. Invoke `/scorched-earth` again → no setup, straight to the verdict (gate short-circuits).
3. Ask "re-run scorched-earth setup" with the sentinel present → setup runs again.

## Doc impact

- `CLAUDE.md` — one architecture line for `skills/scorched-earth/setup.md`; note the
  `onboarded` sentinel in the STATE_DIR file list.
- `README.md` — a first-run note (installing then running `/scorched-earth` walks you
  through setup).
- `docs/playbook.md` — setup step + Current Status.
- `TODO.md` — session close-out.
