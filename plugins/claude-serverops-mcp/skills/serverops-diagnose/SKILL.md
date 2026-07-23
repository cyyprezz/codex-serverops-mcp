---
name: serverops-diagnose
description: Diagnose problems on explicitly configured Linux servers through ServerOps. Use for multi-stage, evidence-led investigations that need persistent SSH context, normal Linux commands, logs, service state, files, or interactive terminal observation without adding specialist wrapper tools.
---

# ServerOps Diagnose

Use the existing ServerOps tools as an investigation workspace. Do not invent specialist tools for
commands that can be run reliably through the shell.

## Investigate in stages

1. Clarify the symptom, time window, affected profile, expected behavior, and acceptable scope.
2. Inspect the profile, open one stateful live session, and establish identity, working directory,
   clock, and relevant environment before forming conclusions.
3. Begin with broad read-only observations. Use ordinary Linux commands through `server_exec`; use
   `server_terminal` only when interaction, streaming, or retained terminal state is genuinely
   necessary.
4. State competing hypotheses and collect the smallest evidence that distinguishes them. Narrow
   the investigation iteratively instead of dumping unrelated raw output.
5. Use `server_files` for bounded structured reads. Do not mutate during diagnosis unless the user
   has authorized a change and the preimage and rollback path are understood.
6. Preserve useful shell state in the held session, but re-check session status after interruptions
   or client restarts.

Normal commands such as `df`, `free`, `ps`, `systemctl`, `docker`, and `journalctl` remain commands,
not ServerOps product functions. Database queries, dumps, cron changes, and process termination also
require explicit user scope and normal operational judgment.

## Handle uncertainty

Separate observed facts, interpretations, rejected hypotheses, missing evidence, and changes. Never
retry a timed-out or `outcome_unknown` mutation. Reconnect if necessary and verify the real server
state read-only before continuing.

## Report a useful result

Summarize the most likely cause, evidence, confidence, affected scope, and any remaining unknowns.
Prefer concise findings and relevant excerpts over raw-text floods. List every change separately;
if the investigation remained read-only, say so.
