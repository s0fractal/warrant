# WRT-001 generic verifier-refactor gate

Date: 2026-07-26  
Scope: uncommitted `impl/warrant.py` verifier refactor, WRT-001, ADR-008 rev 10,
and the updated Sigma wrapper prototype  
Verdict: **FAIL-CLOSED INTENT ACCEPTED; HOLD THE GOVERNED PATCH UNTIL THE
REFERENCE USES ONE RECORD SNAPSHOT, GO AGREES ON CONTEXT FAILURE, AND DISPATCH
IS VERSION/REASON-SCOPED**

The patch correctly avoids registering `0.2+sigma-wave.1`. It also moves context
construction into `verify_store`, catches construction failure, and gives future
runtime code the verifier's reporter. Existing covered behavior remains green.

However “one context” is not yet one verification snapshot, the new observable
failure rule immediately diverges from the Go implementation, and the global
dispatcher interface can affect stores that do not contain its runtime. These
are generic Warrant concerns, independent of wave/R1, and should be closed
before this governed change is committed.

## Reproduced baseline

- `python3 impl/warrant.py selftest`: `SELFTEST: ALL PASS`;
- `tests/agree_check.sh`: all currently covered Python/Go/Rust canonicalization,
  negative, settlement, and pedantic checks pass;
- Sigma `tools/test-all.sh`: `TEST-ALL: ALL GREEN`;
- updated join probe passes its supplied happy path and 15 negatives;
- Python missing-trust verification returns one global error without crashing;
- `0.2+sigma-wave.1` is absent from the real Warrant `ACCEPTED`/`RUNTIMES`.

The current suites do not exercise the new missing/corrupt-trust rule or the
runtime hook.

## Findings

### [P1] Python and Go now disagree fail-open/fail-closed

On an empty initialized store with settlement verification requested and a
missing trust-config path:

```text
Python:
  ERR settlement  settlement context unavailable: FileNotFoundError
  verify: 0 records, 1 errors, 0 warnings
  exit 1

Go:
  verify: 0 records, 0 errors, 0 warnings
  exit 0
```

Go's `settlementCtx` silently replaces an unreadable trust file with `{}`:

```go
if m, err := readJSON(trustPath); err == nil {
    trust = m
}
```

Thus two honest Warrant implementations now disagree on whether the requested
settlement verification happened. `agree_check.sh` remains green because its
settlement differential never supplies a missing or malformed trust config.

This is a governed observable semantic change, not a Python-only implementation
detail. Before commit:

- make Go return the same global error for a supplied-but-unreadable,
  malformed, or schema-invalid trust config;
- use one stable cross-language reason string rather than Python's exception
  class name;
- add missing file, invalid JSON, trailing JSON, wrong top-level type, and
  closed-schema violation to `tests/settlement.py`;
- require equal error/warning counts, message class, and nonzero exit.

Rust currently has no equivalent settlement path; document that scope rather
than describing the generic refactor as three-way behavior-preserving.

### [P1] `verify_store` still verifies two record snapshots

`verify_store` first executes:

```python
recs = store.all_records(load_errors)
```

Then `_settlement_context(store, ...)` independently executes:

```python
recs = store.all_records()
```

Instrumentation of one successful settlement verification gives:

```text
store.all_records calls       2
base recs is ctx["recs"]      False
settlement context instances  1
```

So there is one context object but two filesystem observations. A concurrent
writer can place a record between the reads, making:

- base schema/signature/reference checks use snapshot A;
- active roots, active records, key state, and runtime use snapshot B;
- the hook receive both `recs=A` and `ctx["recs"]=B`.

This preserves the TOCTOU class that the refactor was intended to remove.
Malformed files are also reported through `load_errors` only on the first read,
while the context silently skips them on its separate read.

Load records exactly once. Either:

1. pass the already-loaded `recs` into `_settlement_context`; or
2. make context construction own the one load and have base verification iterate
   `ctx["recs"]`.

The same immutable/single logical snapshot must reach base checks and every
dispatcher. Add a test Store whose `all_records()` returns different values on
its second call and assert the verifier calls it exactly once.

### [P1] The dispatcher API is global rather than version/reason scoped

`_RUNTIME_DISPATCHERS` is an ordered mutable list. Every registered function is
called once for every store, including stores containing only old `0.1`/`0.2`
records. If a future wave dispatcher raises before or while deciding that a
store is irrelevant, the core emits a global runtime ERR and changes the result
of that legacy store.

That weakens the new-version guarantee: even without accepting a wave body,
installing a wave dispatcher can change old-store verification. Duplicate
registration and dispatcher ordering are also unspecified.

Use an exact registry keyed by at least:

```text
(body_version, reason_runtime) -> dispatcher
```

Have the core invoke a handler only for a shape-validated reason whose body
version authorizes that runtime. Attribute exceptions to that reason-bearing
record with the normative active/inactive severity. A store with no matching
reason must never execute the handler and must retain its pre-registration
result.

Add vectors for:

- dispatcher installed, no matching reason → identical legacy report;
- matching reason → one invocation;
- duplicate registration refused;
- handler exception → deterministic per-reason failure;
- unknown version/runtime → existing schema outcome, no handler call.

### [P1/P2] Passing raw `settlement` input reopens the second-authority seam

The hook receives both the derived `ctx` and the original raw `settlement`
dictionary:

```python
_dispatch(store, recs, ctx, settlement, out)
```

A runtime can therefore read a different trust path or call
`_settlement_context` again—the exact split-authority behavior WRT-001 forbids.
It also receives two record dictionaries that are currently different
snapshots.

Do not pass raw trust/genesis inputs to runtime handlers. Pass:

- the single authoritative context/snapshot;
- a small verifier-owned mode/status value if a handler must distinguish base,
  successful settlement, and failed settlement requests;
- the one reporter.

The dispatcher should lack both the data and the need to rebuild authority.

### [P2] The refactor has no direct regression tests

The Sigma probe still monkey-patches and wraps `verify_store`; it does not
register through `_RUNTIME_DISPATCHERS`. Consequently it cannot demonstrate
same-context, same-reporter, version-scoped invocation, or handler-exception
behavior of the landed hook.

Add Warrant-local tests before marking deferred item 0 DONE:

- context builder called once;
- record store read once;
- dispatcher observes the exact same context/snapshot;
- reporter findings appear in the one printed summary and returned tuple;
- missing context is one stable global ERR;
- dispatcher exception is bounded;
- empty registry preserves the pre-patch report.

## Effective-lifecycle findings relevant before R1

### [P1] Any eligible actor can currently supersede another actor's record

The new effective set removes the target of every supersede in
`active_records`. But Warrant settlement eligibility requires only a
schema-valid record with a cryptographically valid signature matching the
body's self-declared actor. Actor/key binding warnings do not remove the record
from `active_records`, and Warrant §7 currently defines no authorization
relationship between a superseder and its target.

I filed a supersede using a different self-declared actor against the happy
fixture's cited assertion:

```text
attacker supersede in active_records    True
target in active_records                True
target in derived effective set         False
```

Thus the proposed lifecycle layer lets any eligible filer censor an assertion,
projection, or citation by naming its WarrantID. A threshold-authorized R1
checkpoint would faithfully commit the already-manipulated set unless checkpoint
signers independently detect and repair it.

Effective supersession needs authorization, for example a governed rule binding
the superseder to the target's actor/policy and key state. The exact rule belongs
in Warrant, not only ADR-008. This means deferred items 1 and 2 are not cleanly
separable: key-state/policy authorization is needed to define the effective set.

Also define supersede-of-supersede semantics. The current one-pass formula lets
an ineffective/replaced superseder continue removing its own target. Add
authorized, unauthorized, chained, competing, and cross-policy supersede
vectors.

### [P1] The R0 filing prohibition is not representable in the current schema

WRT-001 now says an R0 wave reason MUST NOT be filed settlement-active. But the
closed check/view schemas have no mode, checkpoint reference, or other field
that distinguishes R0 from R1. The supplied probe still files exactly such an
active R0 Warrant and treats its zero-error public verification as the happy
path.

Before R1, choose an enforceable boundary:

- expose R0 as a direct ephemeral query API that creates no Warrant reason; or
- version the check/view schema with an explicit mode and make the public
  verifier reject settlement-active R0 reasons.

An R1 stored reason should carry the authorized checkpoint WarrantID explicitly.
Do not infer the mode from host configuration.

## Recommended next order

Do not start the R1 object yet. Finish the generic refactor first:

1. one record load/snapshot shared by base context and dispatch;
2. Python/Go parity for fail-closed trust construction with differential vectors;
3. a version/runtime-keyed dispatcher that receives no raw authority;
4. Warrant-local hook/reporter/exception tests.

Then design effective lifecycle and R1 together, because supersede
authorization depends on policy/key state. Keep R0 outside settlement-carried
Warrants. Only after those decisions should `0.2+sigma-wave.1` or its successor
enter a real registry.

