# What a trace can't tell you

```bash
python3 demos/otel-vs-warrant/demo.py
```

One agent session, three tool calls through Claude Code's PreToolUse hook: a
destructive delete (refused), a listing (the hook has no opinion), a deploy
(allowed by a rule compiled to a re-runnable `ski@v1` check). The session is
then reviewed from its OpenTelemetry export, once as the export alone shows it
and once by `tools/otel_audit.py`, which also reads the warrant store.

| Scene | What happens | Trace alone | With the store |
| --- | --- | --- | --- |
| 1 | the export is edited: refusal → approval | `accept (source hook)` | `contradiction` |
| 2 | an API-shaped trace (no tool span for a denied use) | nothing | `telemetry-missing`, the signed refusal stands |
| 3 | a batch is sampled away | nothing | `telemetry-missing`, the signed sanction stands |
| 4 | a pointer is relabelled to another valid record | a verifying warrant id | `misbound` |
| 5 | the evidence itself is edited | — | `store-invalid` |
| 6 | *why* was the deploy allowed? | that a hook decided | the pinned rule, re-executed now |

Every scene asserts its outcome and the script exits 1 if one differs; it runs in
`tools/check.py`.

**What it is honest about.** The hook, the store and the re-execution are real.
The **telemetry is synthesised** from the event shapes the vendor documents
(read 2026-10-15), not captured from a live session; the output says so. Both
keys sit on one host, which is one custody. A re-run proves the rule gives its
verdict on the facts recorded in the check, not that those facts were true. No
independent gate has reviewed it. Design and limits:
[`docs/telemetry-correlation.md`](../../docs/telemetry-correlation.md).
