# WRT-001 independent runtime gate

Date: 2026-07-26  
Scope: uncommitted `proposals/WRT-001-wave-v1-runtime.md`, its Sigma-side
reference prototype, and the current Warrant settlement/novelty implementation  
Verdict: **CORRECT NORMATIVE HOME; DO NOT START THE BUDGET YET — CLOSE THE
CHECKPOINT ROLE, TEMPORAL SEMANTICS, REAL VERIFIER INTEGRATION, AND §7 CLOSURE**

Moving C1 into Warrant is the right architectural decision. The proposed
non-retroactive body version is also the right experimental vehicle: a clean
`0.2` implementation continues to reject the new bytes instead of silently
changing the meaning of an existing version.

The current R0 checkpoint construction, however, contains a correctness bypass
and has no stable historical meaning. The prototype also still demonstrates a
wrapper around Warrant rather than the single-context public integration that
WRT-001 requires. These are definition-of-runtime issues; metering them first
would freeze the wrong computation.

## Reproduced baseline

- `sigma-glyph/examples/resonant_precedent_join_probe.py`: supplied happy path
  reports `(0 errors, 0 warnings)` under `quiet=True`; all 13 supplied negatives
  report at least one returned error.
- `sigma-glyph/tools/test-all.sh`: `TEST-ALL: ALL GREEN`, including the 582/582
  Lean wave bridge.
- Warrant `tests/agree_check.sh`: all Python/Go/Rust canonicalization, negative,
  settlement, and pedantic differentials pass.
- All three precedent probes compile and their supplied assertions pass.
- Book II and Book III constants in the prototype match the governed
  Specification Anchors.

## Findings

### [P1] Any record can hide from Book III selection by carrying a borrowed wave reason

WRT-001 defines R0 as:

```text
settlement_active_for(J) minus wave-citation records
```

but neither the ADR nor the reason schema defines an authenticated
“wave-citation record” role. The prototype classifies a record solely by finding
any `sigma-glyph.wave@v1` reason in `body.because`. `verify_citation` receives
the reason-bearing WarrantID but never binds that Warrant's subject to
`check.entry`.

I filed a settlement-active, higher-epoch rival assertion under the same
jurisdiction, gave it the already-valid check reason from the happy citation,
and claimed the same `pass` verdict. The record's subject is the rival assertion,
not the precedent entry:

```text
rival active                         True
classified as wave citation          True
original reason                      pass
borrowed reason on rival              pass
public verify_store                   (0, 0)
```

If included, the rival wins Book III `select()` at epoch 99. Instead, the mere
presence of the borrowed reason removes it from the candidate universe, and
both reasons verify cleanly. This is a zero-error semantic bypass.

Do not define exclusion by reason presence. The smallest safe R0 rule is:

1. validate the exact reason-bearing citation record;
2. require its `body.subject.hash == check.entry` and the profile's required
   lifecycle/decision fields;
3. exclude only the current reason-bearing WarrantID from its own snapshot.

Other wave-bearing records must not disappear merely because of their reasons.
Add a negative vector where an assertion/projection/decision Warrant borrows a
valid wave check; it must be included in the index or rejected, never silently
retyped as a citation.

### [P1] R0 is a live store head, not a checkpoint

The runtime recomputes the view commitment from the current settlement-active
set. The citation does not name a historical settlement checkpoint or a
settlement epoch that resolves to one.

Starting from the clean happy fixture, I appended one unrelated, valid,
settlement-active Warrant under the same root:

```text
before append                         verify_store -> (0, 0)
new unrelated record active           True
after append                          verify_store -> (1, 0)
runtime reason                        unverified:
                                      checkpoint != view commitment
```

Therefore every ordinary jurisdictional store growth invalidates every existing
R0 citation. Under a permissive root, any actor able to file one active record
can invalidate all prior citations even when no relevant projection or wave
assertion changed.

WRT-001 must choose and name one temporal contract:

- **live-head claim:** old citations are intentionally stale after any active-set
  change; callers need an explicit `stale`, re-index/re-cite workflow, and the
  availability consequence must be normative; or
- **historical checkpoint claim:** the view names a settlement-authorized
  checkpoint whose membership remains replayable. In that case R1 is not a
  later tightening; it is required before the runtime contract is structurally
  closed.

Calling the current construction a checkpoint implies the second while
implementing the first. Budget work should wait until this choice determines
which set is scanned.

### [P1] The reference prototype still uses two contexts and downgrades failed settlement verification

The wrapper constructs `_settlement_context` itself, then calls the original
`verify_store(..., settlement=settlement)`, which constructs it again. A counter
around `_settlement_context` records two calls for one public verification.
Passing identical inputs is not sharing one context object and retains both
TOCTOU and duplicate-work surfaces.

On construction failure, the wrapper calls the original verifier with
`settlement=None`. It fail-closes individual wave reasons, but silently
downgrades every other record to base verification. Removing the wave citation
from the fixture and deleting the trust file gives:

```text
verify_store(store, settlement=missing_trust) -> (0 errors, 4 warnings)
```

A caller using zero errors as WRT-001 explicitly anticipates can therefore miss
that the requested settlement verification never happened whenever no wave
reason is available to contribute the compensating error.

This needs a real Warrant implementation change, not another wrapper:

- construct the context once inside `verify_store`;
- make context-construction failure a global ERR for a requested settlement
  verification;
- pass the same context object to base checks and runtime dispatch;
- emit runtime findings through the same reporter before the one final summary.

The last point is also observable today: with `quiet=False`, a claimed-verdict
lie prints `verify: ... 0 errors` from the original verifier, while the wrapper
returns `(1, ...)`.

### [P1] §7 tunnel closure remains unspecified and unimplemented

WRT-001 gives a proposed fingerprint tuple, then says the runtime “also defines
its nested tunnel references (the entry's cited records)”. That is not a
closure rule. A wave outcome depends on at least:

- the check, entry, query assertion, and index view blobs;
- the projection, cited assertion, projection policy, vocabulary, selection
  policy, and ruleset blobs;
- the decision, projection, assertion, and checkpoint Warrant records;
- every checkpoint candidate examined by cardinality and `select()`, plus their
  subject blobs.

The document does not say which of these enter the tunnel, how unavailable
members behave, or how the checkpoint set is recovered during historical
novelty testing.

The prototype's `wave_fingerprint()` is only a standalone helper:

```text
prototype wave_fingerprint(...)       non-None
Warrant fingerprint(...)              None
Warrant tunnel_fingerprints(CW)        empty set
```

The proposed tuple also calls itself an “outcome” fingerprint but contains the
claimed verdict, not a recomputed verdict/coherence/result. Its result cannot be
recomputed from the check blob alone; it needs all nested blobs and settlement
state. Specify the exact executable fingerprint and recursive closure, including
unresolved and budget-exhausted behavior, before declaring §7 closed.

WRT-001 itself correctly says the runtime is not settlement-novelty-integrated
until this exists. Accordingly, ADR-008 must not claim that registration and
tunnel closure are already specified.

### [P1/P2] The profile member of the “governed” ruleset is stale and provisional

The Book II and III members are real anchors. The third member is:

```text
a9096dd245ab...  # sha256(ADR-008), provisional
```

It is absent from `spec/ANCHORS.txt`, and the current rev-8 ADR bytes hash to:

```text
909c7d3de871...
```

Thus even as a raw document digest it no longer names the current profile, and
it is not the repository's governed Specification Anchor construction. The
prototype accepts one exact hash, but exact comparison to a stale provisional
value is not governance.

Create an externally governed profile artifact/anchor and pin that stable
anchor in the ruleset. Avoid self-hashing changing ADR prose. The final runtime
registry/version also needs an adopted mapping from the version tag to WRT-001
semantics; the string alone is not a content anchor.

### [P2] The “0 warnings” fixture result does not demonstrate key binding

The fixture's trust config contains only `genesis_roots`; it does not bind
`fixture@sigma` to the signing key. The prototype invokes the verifier with
`quiet=True`, and the current Python verifier suppresses both printing and
counting the settlement-context “signature unbound” branch in quiet mode.

The same happy fixture under `quiet=False` reports five unbound-signature
warnings. Key-state binding is correctly listed as deferred, so the gate should
report the fixture as unbound instead of advertising `0 warnings`. This does not
invalidate the structural checks, but it prevents the output from being used as
settlement-grade evidence.

## Recommended order

The next step is not the four-counter budget yet:

1. bind the reason-bearing record to its entry and remove the reason-based
   universe exclusion bypass;
2. decide live-head versus historical-checkpoint semantics and add append-after-
   citation vectors;
3. refactor the actual Warrant verifier around one fail-closed context and one
   reporter;
4. specify and implement exact §7 fingerprint/tunnel closure;
5. replace the provisional profile digest with a governed anchor;
6. then meter the now-fixed computation with exact/one-over budget vectors;
7. continue with key-state, abstention, cross-implementation parity, and only
   then governance adoption.

The architectural split is accepted. WRT-001 is not yet ready for a budget gate
or production signatures.
