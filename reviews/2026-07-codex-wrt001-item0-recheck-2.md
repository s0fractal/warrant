# WRT-001 item 0 — second independent recheck

Date: 2026-07-26  
Scope: the revised uncommitted Python/Go verifier boundary, tests, WRT-001,
and Sigma ADR-008 rev 12/probe  
Verdict: **ITEM 0 IS STILL NOT DONE; DO NOT COMMIT THE GOVERNED REFACTOR OR
START R1**

Several previous findings are genuinely fixed:

- `verify_store` parses and nested-validates the trust file once and passes the
  parsed value to `_settlement_context`;
- the new empty-store malformed-trust vectors agree in Python and Go;
- core runtime overlays are refused;
- the test exercises base, settlement, and failed-settlement modes;
- a real non-filing R0 fixture now leaves the Warrant record count unchanged.

The independent countervectors below still break the claimed item-0 contract.

## Reproduced baseline

- `python3 impl/warrant.py selftest`: `SELFTEST: ALL PASS`.
- `tests/agree_check.sh`: all supplied differential, settlement, runtime-hook,
  and pedantic checks pass.
- Sigma `tools/test-all.sh`: `TEST-ALL: ALL GREEN`.
- The revised join probe prints `CW filed: False`, `records 4/4`, and the
  supplied query result passes.

The green suites do not cover non-empty failed-trust stores, re-litigation
snapshot reads, private RuntimeView state, or pinned-genesis TOCTOU.

## Findings

### [P1] `verify_store` still does not use one record snapshot

The initial verifier load is single, but an active accept/reject re-litigation
path calls `settlement_admissibility(store, ...)`. That function and its helpers
reload records repeatedly:

- `verify_store` calls `settlement_admissibility`: `impl/warrant.py:1095-1105`;
- `settlement_admissibility` calls `tunnel`, `store.all_records`, and
  `tunnel_fingerprints`: `impl/warrant.py:544-557`;
- `tunnel` and `tunnel_fingerprints` each load records again:
  `impl/warrant.py:486-492`, `532-541`.

On a two-record active lineage—an accepted root and an accepted same-subject
successor—I instrumented the `Store` instance:

```text
verify (0, 1) all_records_calls 5
```

Thus base checks/context/runtime handlers see snapshot A while re-litigation can
see snapshots B–E. This directly contradicts WRT-001 item 0 and reintroduces a
record-authority TOCTOU. The new test gets `1` only because its one-record
fixture never enters re-litigation.

Thread the already-loaded `recs` through `settlement_admissibility`, `tunnel`,
and `tunnel_fingerprints`; do not permit a verifier-internal helper to reload
records. Add the two-record vector above and require exactly one call. Go already
passes its loaded `records`/`blobs` maps to these helpers and is the correct
shape.

### [P1] Invalid trust still produces different Python and Go verification semantics on a non-empty store

The new malformed-trust differential uses only an empty store, where both
implementations report `(1 error, 0 warnings)`. On a real record they choose
different fallback modes:

- Python leaves `ctx=None` and continues base-grade;
- Go builds an empty settlement context and continues settlement-grade.

For one otherwise-valid root:

```text
Python: (1 error, 1 warning)
Go:     (1 error, 2 warnings)  # extra unadopted root
```

For one record under an invalid threshold-policy blob:

```text
Python:
  (1 error, 1 warning)

Go:
  (2 errors, 2 warnings)
  extra ERR  invalid threshold policy
  extra WARN unadopted root
```

The one stable global ERR is not sufficient if the rest of the public report
diverges. Define the failed-context continuation exactly. The current Python
behavior—report the global error, run only base checks, expose
`settlement-failed` to Python handlers—is the cleaner meaning of “the requested
settlement verification did not happen”. Make Go follow it, or deliberately
choose the other behavior in both. Add non-empty valid-policy and invalid-policy
fixtures to the differential harness and compare the complete report.

### [P1] Python still authenticates one `genesis.json` value and consumes another

The trust file itself is now single-read, but `_trust_roots` hashes
`genesis.json` with `read_bytes()` and then reparses the path with a separate
`read_text()`:

```python
got = blob_hash(g.read_bytes())
if trust["genesis_json_sha256"] == got:
    doc = json.loads(g.read_text())
```

I pinned bytes containing `{"roots":[]}`, changed only the value returned by
the second read to an attacker root, and obtained:

```text
pinned-bytes-roots []
parsed-after-swap [attacker-WID]
attacker-active True
```

This defeats the out-of-band hash pin and is an authority escalation. Go parses
the same `raw` bytes it hashed, so the implementations differ under the race.

Read `genesis.json` once, hash those bytes, and parse those exact bytes with the
strict parser. Add a swap/read-count regression. The “one trust parse” boundary
is not closed while a hash-pinned trust input retains this second-read seam.

### [P1] `_RuntimeView` still exposes the original mutable verifier state and raw store

The class says it “never” exposes mutable records/raw store and that a handler
“cannot” reproduce the dictionary-size crash. In fact its public Python object
contains:

```python
view._store
view._recs
view.reads  # mutable dict
```

The previous mutation vector remains executable:

```python
def handler(view, ...):
    view._recs["0" * 64] = {"body": {}, "sigs": []}
```

Result:

```text
view-exposes True True dict
RuntimeError: dictionary changed size during iteration
```

Again the crash occurs after the handler returns, outside the handler exception
guard. A handler can also write through `view._store` and erase/reset the
public metering dictionary.

`tests/runtime_hook.py` only mutates the copy returned by `record_body` and then
inspects the *test handler's parameter names*. That does not prove the view has
no mutable/raw authority.

Python in-process extension code cannot be a security sandbox. Choose and state
the real trust model:

1. if registered handlers are governed trusted verifier code, call them part of
   the TCB and stop claiming they cannot reach authority; still ensure the view
   stores an immutable/deep-copied record snapshot so accidental/private
   mutation cannot corrupt core verification; or
2. if handlers are adversarial plugins, move execution behind a real process /
   WASM/capability boundary.

In either model, do not retain the verifier's live `recs` map in the handler
object. Add the exact `_recs` mutation vector, not a signature introspection
proxy.

### [P2] CAS “accounting” is mutable and does not count failed digest reads

The resolver increments `view.reads` only after the digest matches. With a file
present under a false hash:

```text
blob(false_hash) -> None
usage before     {'blobs': 0, 'bytes': 0}
usage after      {'blobs': 0, 'bytes': 0}
```

Bytes were read and hashed but the claimed future budget meter recorded no
work. A handler can also clear or edit the public dictionary.

Budget is correctly deferred, so item 0 need not freeze the final cost model.
But WRT-001 must not call this an “accounted resolver” or its future metering
point yet. If a provisional counter remains, make it verifier-owned/read-only
to the handler and count actual attempted work, including wrong-digest reads.
The current “bad CAS” test uses an absent hash, not a present wrong-digest blob.

### [P2] The parity statement still needs a precise boundary

Trust parsing/validation now has Python↔Go vectors, while handler/CAS is
explicitly Python-only. That wording is improved. The public **failed-trust
verification report**, however, is not cross-language equivalent on non-empty
stores, and the Python snapshot contract differs from Go under re-litigation.

State parity at the public `verify` report level, not merely at the
preflight-error line, and gate it with non-empty stores.

## Gate recommendation

Keep `0.2+sigma-wave.1` unregistered and keep R1 deferred. Close item 0 in this
order:

1. thread one record snapshot through every verifier-internal helper;
2. make failed-trust continuation identical in Python and Go;
3. hash and parse the same `genesis.json` bytes;
4. remove live `_recs`/raw-store claims from the runtime view and define the
   handler trust model;
5. make CAS usage verifier-owned or explicitly non-normative; and
6. add the exact countervectors above.

Only then relabel item 0 `DONE` and begin authorized lifecycle + key-state + R1.
