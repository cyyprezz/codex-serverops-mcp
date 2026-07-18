# ADR 014: Per-user Task Scheduler broker lifetime

Status: accepted

## Context

The MCP SDK starts a Windows STDIO server inside a Job Object configured to terminate its child
process tree when that client closes. `DETACHED_PROCESS` and a new process group do not escape that
Job Object. The first real two-process MCP restart check therefore terminated the broker and its
SSH worker together with the first STDIO process. A stale status file cannot preserve ownership or
the in-memory worker token.

## Decision

Install one clearly named Windows Task Scheduler task per current-user SID. It starts the exactly
pinned `serverops-broker` distribution at user logon and on demand. The task uses
`TASK_LOGON_INTERACTIVE_TOKEN`, stores no password, uses least-privilege `TASK_RUNLEVEL_LUA`, and is
not hidden. It ignores duplicate starts, has no execution-time limit and is not stopped by battery
policy.

Registration is an explicit installer preview/apply step. The task name includes a SID-derived
digest, and its description contains a versioned ownership marker. Installation, update and
removal refuse an unmarked name collision. Before start, replacement or removal, ServerOps also
validates the exact description grammar, action digest, action count, principal, run level and
current-user logon trigger. It also checks the execution action type and working directory plus
every setting written during registration, including enabled state, demand/logon behavior,
battery policy, execution limit and duplicate-instance policy. The normal MCP process only asks
an already installed managed task to run; if no task exists, development and diagnostic paths
retain direct startup.

The broker still owns all worker connections and tokens. Task Scheduler does not receive SSH or
sudo credentials. A broker restart does not adopt orphaned workers; after acquiring the unique
broker pipe it removes only status records whose PIDs are certainly dead and preserves live or
unreadable records for investigation.

## Consequences

Closing or restarting the MCP STDIO process no longer closes the broker-owned SSH process. The
broker continues only while the Windows user is logged on; computer reboot recovery and broker
crash adoption remain out of scope for version 0.1. Uninstall stops the broker and removes only the
marked ServerOps task. The real restart acceptance gate must use the installed candidate task and
must remove its disposable development-wheel task afterward.

Microsoft API references:

- `RegisterTaskDefinition` logon types: https://learn.microsoft.com/windows/win32/taskschd/taskfolder-registertaskdefinition
- Principal run level: https://learn.microsoft.com/windows/win32/taskschd/principal-runlevel
- Multiple-instance policy: https://learn.microsoft.com/windows/win32/taskschd/tasksettings-multipleinstances
- Task settings: https://learn.microsoft.com/windows/win32/taskschd/tasksettings
