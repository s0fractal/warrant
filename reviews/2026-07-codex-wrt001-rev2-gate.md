# WRT-001 rev 2 independent runtime gate

Date: 2026-07-26  
Scope: revised WRT-001, ADR-008 rev 9, the updated Sigma-side wrapper prototype,
and the current Warrant settlement semantics  
Verdict: **ROLE CONFUSION CLOSED; REAL VERIFIER PLUMBING MAY PROCEED AS A
GENERIC REFACTOR, BUT DO NOT ENABLE `wave@v1` UNTIL EFFECTIVE-LIFECYCLE AND
STALE/R1 SEMANTICS ARE CLOSED**

Rev 2 accepts the previous gate's architectural corrections:

- only the current citation WarrantID is excluded from its universe;
- the reason-bearing record is bound to `check.entry`;
- R0 is honestly named LIVE-HEAD rather than checkpoint;
- context failure contributes a global error even without a wave reason;
- the wrapper, §7 sketch, and profile digest are no longer presented as adopted
  Warrant mechanisms;
- key-state/R1 is ordered before budget.

The role-confusion bypass is closed in the runtime code. The remaining blocker
is that two different meanings of “active” are still conflated:
Warrant's `active_records` means settlement/root eligibility, while the profile
uses it as effective lifecycle state. Combined with active-`unverified` → ERR,
the LIVE-HEAD recitation workflow cannot converge.

## Reproduced baseline

- supplied happy fixture: `0` errors and 5 honestly reported unbound-signature
  warnings;
- all 14 supplied negatives return at least one error;
- missing trust on a non-wave store now returns `(1 error, 4 warnings)`, so the
  global fail-closed correction is real;
- role-confusion fixture keeps its rival in Book III selection and the cited
  assertion loses;
- `sigma-glyph/tools/test-all.sh`: `TEST-ALL: ALL GREEN`;
- Warrant `tests/agree_check.sh`: all current Python/Go/Rust differential,
  settlement, negative, and pedantic checks pass;
- all three precedent probes compile and their supplied assertions pass.

## Findings

### [P1] LIVE-HEAD recitation cannot restore a zero-error store

WRT-001 says store growth stales a citation and prescribes a re-index/re-cite
workflow. But stale is currently returned as `unverified`, and §5 makes an
unverified settlement-active reason an ERR. Warrant's `active_records` is an
append-only eligibility set; adding a newer citation does not remove the older
one from it.

I started with the happy citation, recomputed a correct new live-head view that
included the first citation, and filed a second correctly bound citation:

```text
one citation:
  public verify_store       (0, 0)

after correctly re-indexing and filing citation 2:
  citation 1               unverified: live-head set != view commitment
  citation 2               pass
  both in active_records    true
  public verify_store       (1, 0)
```

Filing citation 3 would stale citation 2 while citation 1 remains erroneous.
Therefore re-citation moves the one passing head but never clears the accumulated
errors. More generally, every new record permanently changes all prior
LIVE-HEAD reasons from clean to ERR. A jurisdiction cannot maintain multiple
clean citations in one growing store.

The current message also collapses:

```text
stale or tampered
```

Those cases cannot safely share a non-error outcome: treating every mismatch as
benign stale would let a filer submit an arbitrary commitment, while treating it
as ERR produces the permanent-poisoning behavior above.

Before registering the runtime, choose one:

1. make R0 explicitly ephemeral/non-settlement verification that does not live
   as an active reason in the growing store; or
2. define a trustworthy citation supersession/deactivation rule and a provable
   distinction between stale and tampered; or
3. require R1's authorized historical checkpoint for settlement-carried
   citations and keep R0 only as a research probe.

The third is the cleanest match for ADR-008's goal. In practical terms, R1 is
not merely required for replay; it is required for a usable multi-citation
Warrant store.

### [P1] `active_records` does not apply Warrant supersession lifecycle

`_settlement_context.active_records` contains every well-signed,
policy/root-eligible record. A `supersede` marks its target as replaced in
Warrant §7, but it does not remove the target from `active_records`.

The wave join uses that raw set for both C0 cardinality and Book III candidates:

- projection cardinality counts every active-record subject that parses as a
  projection;
- assertion selection includes every active record whose own decision is
  `accept`;
- neither path checks whether another active `supersede` replaces that Warrant.

I filed a valid `supersede` whose subject is the cited assertion WarrantID,
recomputed the current live-head view, and filed a new bound citation:

```text
cited assertion in active_records      true
supersede in active_records             true
new citation of superseded assertion    pass
```

Thus a Warrant explicitly marked “replaced” remains the jurisdiction's effective
Book III wave. The projection side fails in the opposite direction: supersede
an old projection and file its replacement, and the runtime sees both old and
new projection subjects and returns `projection cardinality (2)`.

R1 must not merely commit raw `active_records`. WRT/profile need an exact
**effective-record** derivation covering at least:

- how `supersede` removes or shadows decision/projection/assertion Warrants;
- whether competing superseders form a conflict rather than a winner;
- which effective records enter C2/checkpoint commitment;
- whether Book III `select()` receives effective assertion accepts only;
- whether C0 cardinality is “one effective projection” rather than “one
  historically eligible projection”.

Add vectors for a superseded cited assertion, a superseded projection followed
by a replacement, competing superseders, and an unrelated supersede.

This semantic layer affects R1 membership and later budget counts, so it belongs
before both.

### [P2] The borrowed-reason vector does not carry a valid borrowed check

The new fixture labels its case “rival borrows a wave reason”, but builds:

```python
"check": H("borrowed")
```

That blob does not exist. Direct execution of the rival's reason returns:

```text
unverified: check: unresolved reference
```

not the documented:

```text
unverified: reason-bearing Warrant subject != check.entry
```

The vector does prove the most important half of the correction: carrying a wave
reason no longer removes the rival from the candidate set, so the original
citation loses selection. It does not yet prove the claimed valid-check binding
edge.

Add either a valid earlier citation check that the rival borrows, or a focused
fixture that invokes the runtime with a resolvable check/entry and a mismatched
reason-bearing subject. Assert the exact stable reason class, not only
`errors >= 1`.

### [P2] The probe still advertises a §7 outcome that WRT-001 explicitly defers

The probe's main output says:

```text
§7 fingerprint: wave@v1 has a recomputable outcome fingerprint
```

but the helper returns a tuple containing the **claimed** verdict and does not
re-execute against settlement state. WRT-001 now correctly requires the
recomputed verdict/coherence/selection result and says real Warrant
`fingerprint()` returns `None`.

Remove this supplied “pass” or label it only as an obsolete tuple sketch whose
failure to satisfy §7 is expected. Otherwise the executable output contradicts
the normative deferral.

### [P2/P3] A few document counters and claims remain stale

- WRT-001's prototype paragraph says it demonstrates “every rule below” and
  mentions `prior_closure`, although the document itself says the prototype does
  not implement the real context/reporter, R1, §7, or governed profile anchor,
  and LIVE-HEAD no longer uses prior closure.
- “item-1 cost model” now points to the verifier refactor; budget is item 5.
- the adoption checklist says deferred items 1–4, while the ordered list says
  governance follows completion of 1–7.
- ADR-008's budget open question still says “item 1 above”; budget is item 5.
- ADR design criterion 10 and the verified-probe paragraph say “governed
  anchor-set/ruleset” although the profile member is explicitly provisional.

These are editorial rather than algorithmic, but they affect a cross-repository
normative handoff and should be made exact before the implementation patch.

## Recommendation on the next patch

Proceed with point 1 only as a **generic Warrant verifier refactor**:

- one `_settlement_context` construction;
- one reporter/error accumulator;
- runtime dispatch receives that same context and reporter;
- context-construction failure is one global structured ERR;
- preserve current `0.1`/`0.2`, `cmd@v1`, and `ski@v1` behavior byte-for-byte and
  report-for-report;
- do not yet add `0.2+sigma-wave.1` to the real accepted-version/runtime registry.

That refactor has independent value and a stable contract. In parallel, move
effective lifecycle plus R1 ahead of wave activation. Once those vectors exist,
wire `wave@v1` into the prepared dispatcher and then define §7/anchor/budget.

