---
name: decisions
description: Show the permission decisions the warrant witness recorded for this machine's Claude Code sessions - auto-mode denials, calls that were asked about and then ran, and asks with no observed outcome - with the store's verification result. Use when the user asks what was denied or approved, why a tool call was refused, or for an audit of agent permissions.
argument-hint: "[hours]"
allowed-tools: Bash(python3 *)
---

Run the witness report. Use the number of hours the user gave (`$ARGUMENTS`), or 24 if none:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/decisions.py" --hours 24
```

Then summarize for the user, keeping these distinctions exact:

- **denied**: auto mode refused the call. Quote the harness reason as recorded.
- **asked, then executed**: a permission prompt was raised and the call ran. The record does not say whether the person, an allow rule or another hook approved it. Do not say "the user approved".
- **asked, no execution observed**: no hook fires on a manual denial, so this means denied by hand, interrupted or still open. Do not guess which.
- The `verify` line is the store's integrity check. If it shows errors, say so first. If it says NOT RUN, the `warrant` CLI is missing: suggest `pipx install warrant-verify`.

Records are signed by a local witness key, not by the decider. They show what this machine's harness reported and that nobody has edited it since. They do not show that a decision was right.
