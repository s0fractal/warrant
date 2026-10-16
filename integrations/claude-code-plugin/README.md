# warrant — a decision witness for Claude Code

**What did my agent get refused yesterday, and why? What did it get to run
after asking?** Telemetry is weakest at exactly these points: a rejected tool
call emits no tool result. This plugin keeps a local, signed record of them. You
can verify it offline, and no one can edit it without the verifier noticing.

```
/plugin install warrant --marketplace s0fractal/warrant
pipx install warrant-verify          # the warrant CLI the hook files through
```

Then ask Claude `/warrant:decisions`, or run it yourself:

```
python3 ~/.claude/plugins/.../scripts/decisions.py --hours 24
```

A smoke run of the installed plugin, from one simulated auto-mode denial:

```
store: .../store
verify: 2 records, 0 errors, 3 warnings

last 1 h: 1 witnessed decisions, 0 open asks
  2026-10-16 05:40  denied                 Bash  {"command": "echo smoke"}
      auto mode denied the call; harness reason: [Smoke Test]
      record 857ec81c76dc1a13  tool_use_id toolu_smoke
```

Each denial is two records: the request and the refusal. The three warnings are
expected:

- **binding unverified, once per record.** Nothing has yet said that this key
  speaks for `claude-code-witness`. A trust config does that
  (`warrant trust add`, see the main README).
- **UNVERIFIABLE: reject with prose-only reasons.** The classifier's reasoning
  is not something a reader can re-run. The record keeps its verdict, not its
  logic, and the verifier says so.

## What it records, and what it cannot

| Harness event | Filed | Says |
|---|---|---|
| `PermissionDenied` (auto mode) | `reject` | the harness's reason, verbatim |
| `PermissionRequest`, then the same call runs (`PostToolUse` / `PostToolUseFailure`) | `accept` | "asked, then executed", and that the witness cannot tell who approved |
| a call that ran without being asked about | nothing | volume is not provenance |
| a person denies the dialog | nothing (no hook fires) | shown as an **open ask**: denied by hand, interrupted or still open |

Each record's subject binds the harness's `tool_use_id` and `session_id`, which
Claude Code also writes into its own telemetry. `tools/otel_audit.py` joins the
two ([`docs/telemetry-correlation.md`](../../docs/telemetry-correlation.md)).

## What a record proves

That this machine's hook saw the harness report this outcome for this exact tool
call, and that nothing has been edited since. It does **not** prove that the
classifier was right, that a person read the dialog, or who approved an
executed call. The hook signs as `claude-code-witness` with one local key, so
every record also reports one custody (`sanction_independent: false`). It is a
witness, not the decider.

## Never in the way

The hook prints nothing and always exits 0, so it cannot allow, deny or delay a
call. Filing runs asynchronously. The one synchronous step, noting a
`PermissionRequest`, is a single atomic file write. Failures go to
`~/.warrant/claude-code/witness.log`.

## Where things live

`~/.warrant/claude-code/` (override with `WARRANT_CC_HOME`):

- `store/` is a plain warrant store. Share it, or open it in the
  [browser lab](https://s0fractal.github.io/warrant/).
- `keys/witness.key` is the signing key. It is kept outside the store, so
  sharing the store never shares the key.
- `pending/` holds asks not yet resolved. They are swept after a week.

The store is local, holds your tool inputs, and is never sent anywhere. Inputs
over 64 KiB are bound by SHA-256 instead of being stored inline. Uninstalling
the plugin leaves the store in place.

## Test

```
python3 integrations/claude-code-plugin/test_plugin.py
```

The test proves:

- the hook never writes to stdout;
- each event files exactly the records listed above;
- a changed input, a different session or an unasked call files nothing;
- tampering turns verification red;
- a missing CLI breaks nothing and reports `NOT RUN`;
- large inputs are bound by hash;
- the vendored `scripts/warrant_approval.py` is byte-identical to
  `integrations/approval/warrant_approval.py`.

Five mutations of `witness.py` were each confirmed to turn the test red: two keys
instead of one, ignoring the session, printing to stdout, dropping the size cap,
and filing unasked calls.

Status: prototype, version 0.1.0. No independent review has run.
