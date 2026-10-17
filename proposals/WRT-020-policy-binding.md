# WRT-020: Does a decision follow from the policy it cites?

**Status:** DRAFT. This is a finding, a reference profile, and options for the
owner. Nothing here changes SPEC or any verdict of `warrant verify`. The
profile only reads stores and reports what it finds.

## 1. The finding: two gaps, both executable

Warrant pins the policy a record cites (`under`). It also re-runs the record's
`ski@v1` reasons. Nothing connects the two.

**Gap 1: policy → computation.** This is Monday's countermodel, already pinned by
`tests/countermodel_policy_binding.py`. The record cites a prose `DENY_ALL`
policy, gives a real `ski@v1` reason that computes something unrelated, and
accepts. Settlement grade with `--require-bound` reports 0 errors in Python, Go
and Rust. THREAT-MODEL A6 describes the same gap: "whatever the policy says."

**Gap 2: result → decision.** This one is new, and it is the sharper case. Here
the policy is machine-readable, and the reason really is its compilation:

```
under    examples/policies/1-threshold.wpl   (refund 65088 <= 50000: false)
because  ski@v1 check 8323aba3…  = exactly that policy, compiled; verdict pass
decision accept
```

`warrant verify` reports `ok: true, 0 errors`. The reason replays faithfully to
`65cd957f…`, which is Church FALSE: the policy says deny. `docs/authoring-checks.md`
already warns that `verdict pass` means "re-execution reproduced the pinned
answer", not "the policy said yes". No verifier connects that answer to the
decision.

To reproduce both gaps, and every other case below:

```sh
python3 tests/policy_binding.py
```

## 2. Where this sits among Monday's three links

Monday named three bindings that the format does not make:

| Link | What it means | Who owns it |
|---|---|---|
| policy → computation | the reason computes *this* policy | **this proposal** (UNBOUND) |
| evidence → facts | the facts a policy ran on are true | WRT-010, fact provenance |
| result → decision | the decision is the one the policy answered | **this proposal** (CONTRADICTED) |

WRT-014 is a different binding: whose *threshold* admits a root. It is decided
and implemented.

## 3. The profile: `impl/policy_binding.py`

The profile looks at every record and every policy blob in its `under`, and
gives each pair one status:

| Status | Meaning |
|---|---|
| **BOUND** | The policy is WPL. A `ski@v1` reason is exactly its compilation (same check hash, found by recompiling). The decision does not contradict the policy's answer. |
| **CONTRADICTED** | As BOUND, but the record **accepts** while the policy answers false. |
| **UNBOUND** | The policy is WPL, but no reason is its compilation, whatever the reasons compute. |
| **OPAQUE** | The policy is not machine-readable. Compliance is **not checked**, and the profile says so. |
| **SIGNATURES** | A v0.3 threshold policy. It governs who signs, and settlement already enforces that. |

Only `accept` is gated by the policy's answer:
- A `reject` where the policy would allow is discretion, not a contradiction.
- A `propose` or `supersede` decides nothing yet.

The profile compiles with a `put` that only hashes, so it never writes to the
store it reads, and a test holds it to that.

BOUND means the decision follows from the policy **given the facts pinned in it**.
Whether those facts are true is WRT-010's question, not this one.

### Tests (`tests/policy_binding.py`)

There are nine cases plus the read-only check. Each case is filed with the real
CLI and is also run through `warrant verify`, which today reports 0 errors in
all of them. That second column is the point of the proposal: if verify ever
refuses CONTRADICTED, the test fails on purpose and becomes the witness of that
rule. Two mutants of the profile were checked by hand, and each turns the test
red on the comparison:
- treat every gated case as consistent: the FALSE-accept case comes out BOUND;
- accept any reason as the policy's: the unrelated-reason case comes out BOUND.

## 4. Measured: what the repository's own records do

The four stores in the repository are `.warrants` and the air-canada,
refund-chain and cross-vendor demo packs. Across them:

| | pairs | BOUND | CONTRADICTED | UNBOUND | OPAQUE | SIGNATURES |
|---|---|---|---|---|---|---|
| all four stores | 24 | 0 | 0 | 0 | 23 | 1 |

No record cites a WPL source in `under`. The demos follow one pattern:
- a **prose** policy document in `under`;
- a WPL **compilation** in `because`;
- nothing linking the two.

Two further measurements on that pattern:

- **Compilation is reproducible.** Recompiling `demos/air-canada/policy.wpl` today
  gives exactly the check its record cites (`b423b6a8…`). So recompile-and-compare
  works on real records, not only on test fixtures.
- **The check does not name its source.** A compiled check blob holds `term`,
  `expect` and `atp`, and nothing else. Without recompiling a cited source, there
  is no way back from a check to the policy it came from.

## 5. Options

**A. Profile only.** Report, enforce nothing. No existing record changes. Both
gaps stay open at verify, and are visible to anyone who runs the profile.

**B. A, plus an authoring rule.** A record that relies on a WPL policy cites the
WPL source in `under`, next to the prose. The demos would file new records; none
is re-signed. Without this, the profile can only say OPAQUE about the demos.

**C. Normative, at settlement grade.** Three implementations, vectors, SPEC text.
- **CONTRADICTED is an error.** Measured breakage: **0** existing records. The
  rule fires only where a WPL source is cited, and none is.
- **UNBOUND is an error.** Also 0 existing records, for the same reason.
- **OPAQUE is reported but not a finding.** As a warning it would fire on 23 of
  24 existing pairs, which is noise that teaches readers to ignore warnings.

**What C does not close.** Monday's countermodel cites prose, and stays clean at
verify under C. It is reported OPAQUE ("not checked") by the profile. Under C the
gap closes for every author who cites a machine-readable policy. Nobody else gets
anything: a prose policy cannot be checked by any verifier, and a format that
claimed otherwise would be the larger defect.

**Recommendation: B now, C after one adversarial gate.** B costs nothing and makes
the demos checkable. C is a SPEC change and needs the gate.

## 6. What this does not claim

- **That a WPL policy faithfully formalizes a prose one.** The step from prose to
  WPL is the author's claim, signed with their record. No verifier can check it.
- **That the facts are true.** That is WRT-010.
- **Stability across compilers.** Recompile-and-compare assumes the compiler of
  WPL v1 still emits the same bytes. If a compiler change alters the emitted
  check, an old BOUND would read as UNBOUND (§7 Q1).

## 7. Open questions (attack surface)

1. **Compiler drift.** Should a WPL source name its compiler version, so that a
   verifier recompiles with the matching semantics? Or should a check blob name
   its source hash? The second makes the link explicit and costs one field, but
   the field must be inside the hashed check, so it changes check hashes.
2. **Policy versus instance.** A WPL file holds the rule *and* the facts, so the
   "policy" in `under` is per decision. A reusable policy needs a rule-only form,
   with the facts supplied by the record. That touches WRT-010's `from` clause.
3. **Gating `reject`.** Is "policy allows, record rejects" really never a
   contradiction? A jurisdiction might require acceptance when its rule is met.
   That needs a polarity the format does not have.
4. **Several WPL policies.** Every one is checked and the worst status is shown.
   Should a record with one BOUND and one UNBOUND policy be refused as a whole?

## 8. Artifacts

| Artifact | What |
|---|---|
| `impl/policy_binding.py` | The profile: the statuses above, read-only, plus a CLI over stores |
| `tests/policy_binding.py` | 9 cases + read-only check; also pins that `verify` says 0 errors in all of them |
| `tests/countermodel_policy_binding.py` | Unchanged: Monday's gap 1, still pinned at verify |
