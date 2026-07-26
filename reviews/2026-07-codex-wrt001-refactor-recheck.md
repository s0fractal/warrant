# WRT-001 generic verifier refactor — independent recheck

Date: 2026-07-26  
Scope: uncommitted `impl/warrant.py`, `impl-go/main.go`,
`tests/runtime_hook.py`, settlement differentials, and WRT-001  
Verdict: **DO NOT COMMIT/ADOPT THIS GOVERNED REFACTOR YET; ITEM 0 IS NOT DONE**

The direction is right: `verify_store` now loads records once, the missing /
syntactically malformed trust cases no longer silently pass in Go, handler
findings use the verifier's reporter, and the existing suites remain green.
However, the claimed generic contract is not closed. I reproduced two verifier
failures outside the new vectors, and the dispatch API cannot implement its
intended content-addressed runtime without recovering raw store authority by
closure/global state.

## Reproduced baseline

- `python3 impl/warrant.py selftest`: `SELFTEST: ALL PASS`.
- `tests/agree_check.sh`: differential 45/45, settlement all agree, runtime-hook
  all pass, pedantic 15/15.
- Sigma `tools/test-all.sh`: `TEST-ALL: ALL GREEN`.
- Sigma join probe: supplied happy/negative assertions pass.

These are useful regression results, but they do not exercise the findings
below.

## Findings

### [P1] Trust construction is still neither single-read nor fail-closed over its semantic input domain

`verify_store` preflights the trust path with `loads_ijson`, discards the parsed
object, then `_settlement_context` calls `_load_trust_config`, which reads the
same path again with plain `json.loads`:

- `impl/warrant.py:843-853`
- `impl/warrant.py:518-521`
- `impl/warrant.py:634-642`

Instrumentation on a valid trust file reports:

```text
verify (0, 0) trust-read-text-calls 2
```

Go has the same two-stage pattern: `verifyDirSettlement` calls `readJSON`, then
`settlementCtx` calls `readJSON` again and silently ignores a second-read error:

- `impl-go/main.go:1982-1993`
- `impl-go/main.go:1675-1689`

This is a trust-config TOCTOU boundary. The bytes that pass preflight are not
necessarily the bytes that define authority. It also leaves schema-invalid
nested values outside the fail-closed guard. On an empty initialized store I
reproduced:

```text
trust {"actors":[]}
  Python: exit 1, AttributeError: 'list' object has no attribute 'items'
  Go:     exit 0, verify: 0 records, 0 errors, 0 warnings

trust {"actors":{"a":1}}
  Python: exit 1, TypeError: 'int' object is not iterable
  Go:     exit 0, verify: 0 records, 0 errors, 0 warnings
```

That directly contradicts the new stable-reason/totality claim and the comment
that “schema-invalid” trust is covered. The current differential only tests
missing, JSON syntax, top-level non-object, trailing bytes, and duplicate keys.

Parse the trust document exactly once, validate its semantic field types once,
and pass the validated value—not its path—into settlement-context construction
in both implementations. At minimum add parity vectors for wrong nested types
in `actors`, `genesis_roots`, and `genesis_json_sha256`, plus the chosen
unknown-field policy. Every failure must produce the one stable global ERR and
no traceback.

### [P1] The “immutable snapshot” passed to handlers is mutable and can crash or corrupt verification

The code calls the record map an immutable observation, but passes the live
mutable `dict` to a handler while iterating it:

- `impl/warrant.py:634-640`
- `impl/warrant.py:861`
- `impl/warrant.py:1014-1029`

A registered handler containing only:

```python
recs["0" * 64] = {"body": {}, "sigs": []}
```

produces:

```text
RuntimeError: dictionary changed size during iteration
```

The exception happens after the handler returns, so the handler `try/except`
does not contain it. A handler can likewise mutate `ctx["active_records"]`,
record bodies, or cached authority state and influence later core checks or
later handlers. This breaks both totality and “one verifier-owned snapshot”.

Do not expose base-verifier mutable state. Give handlers a read-only runtime
view: deeply immutable records/sets and controlled functions whose outputs
cannot mutate the underlying context. Add adversarial mutation vectors for the
record map, nested bodies, active sets, and handler-to-handler isolation.

### [P1] The handler contract has no authenticated blob/CAS resolver, so it cannot implement `wave@v1`

The handler receives:

```text
(ctx, recs, mode, out, wid, reason, body)
```

It receives neither `store` nor a verifier-owned content-addressed blob
resolver. Yet WRT-001 requires it to load and digest-authenticate the check,
entry, query assertion, view, policies, vocabulary, ruleset, and candidate
subjects. None of those bytes exist in `ctx` or `recs`.

Therefore a real handler must capture/reconstruct `Store` through a global or
closure. That is an unreviewed authority path outside the advertised runtime
contract, and it is incompatible with the later “canonical bytes read” budget.

The generic API needs a verifier-owned, read-only execution context with a
digest-authenticating CAS accessor. That accessor is also the natural place to
meter canonical bytes/schema checks later. It should not expose arbitrary paths
or raw settlement inputs. Add a generic fixture whose handler resolves a check
blob only through this accessor, detects wrong-digest/noncanonical bytes, and
cannot escape the accessor's accounting.

### [P2] `runtime_hook.py` does not prove the settlement snapshot/mode contract it advertises

The test runs the handler only under base verification, where `ctx is None`.
Its alleged identity assertion is:

```python
ctx is None or recs is ctx["recs"]
```

so it is vacuously true in every exercised handler call. The harness does not:

- run a valid settlement context and assert `recs is ctx["recs"]`;
- instrument `all_records` and require exactly one call;
- exercise `settlement-failed`;
- test mutation/isolation;
- exercise a runtime CAS read;
- test a handler against the Go verifier.

Replace the prose-level claim with actual settlement and failed-settlement
vectors. The current output “same snapshot” is not evidence for that property.

### [P2] Registration can overlay core runtime semantics

`register_runtime` treats membership in `RUNTIMES[version]` as authorization.
The supplied test therefore deliberately registers a second handler for
`("0.2", "cmd@v1")` and changes the report of a legacy record. The same API can
overlay `("0.2", "ski@v1")`, producing both the built-in execution and the new
handler.

This is weaker than the stated preservation boundary: legacy behavior is
unchanged only while the registry is empty. Reserve core runtime keys, or make
the built-ins themselves the unique pre-registered handlers and refuse any
overlay. Tests should use a dedicated test-only version/runtime instead of
proving that core overlay is accepted.

### [P2] “Cross-implementation parity closed” is too broad

The Go diff implements the trust preflight only. The registry/handler contract
exists only in Python, and the new hook test invokes only Python. WRT-001 does
later defer Go/Rust runtime parity, which is honest, but item 0 and ADR-008 call
the generic refactor “cross-impl parity closed”.

Narrow that claim to the exact vectors that really have Python↔Go parity, or
port the generic runtime execution context and its conformance vectors before
calling the plumbing cross-implementation.

## Gate recommendation

Keep R1/key-state design deferred. First close the generic verifier boundary:

1. parse and validate trust once, passing a value rather than a path;
2. expose one immutable runtime execution context;
3. include a controlled digest-authenticated CAS resolver;
4. reserve core runtime keys;
5. add real settlement/failed-settlement, nested-trust, mutation, and resolver
   vectors; and
6. state precisely which parts have Python↔Go parity.

Only after those vectors pass should WRT-001 deferred item 0 become **DONE**.
Do not register `0.2+sigma-wave.1`, design R1, or seek governance signatures in
this patch.
