# Gate review: GOV-001 settlement at scale

Reviewer: Codex, independent adversarial reviewer  
Date: 2026-07-07  
Scope: `proposals/GOV-001-settlement-at-scale.md` as candidate SPEC v0.3 text for issues #5/#6/#7, checked against `SPEC.md`, Python/Go implementations, tests, and then existing `reviews/`.

## Verified state

Protocol was run before reading the proposal or existing reviews.

Command: `python3 impl/warrant.py selftest`

Observed:

```text
7e89c9d33bb361ce3efa0f95a7da0ce7f24550c6b6c86d81cc3f7eda7523d32e
9faed510b164a774a6c2d950acb81926cbefacb4908535c5dbde5df8f494d806
SELFTEST: ALL PASS
```

Command: `python3 impl/warrant.py conformance`

Observed final line:

```text
CONFORMANCE: ALL PASS (20/20)
```

Command: `(cd impl-go && go build -o warrant-go . 2>/dev/null || go build -o warrant-go main.go)`

Observed: no stdout/stderr; exit 0.

Command: `./impl-go/warrant-go selftest`

Observed:

```text
OK   unknown body field -> invalid
OK   ski@v1 runtime -> invalid
OK   reject with zero reasons -> invalid
OK   prose-only reject -> schema-valid
OK   prose-only reject -> unverifiable
OK   examples verify with unresolved blobs as warnings
OK   missing prior -> error

SELFTEST: ALL PASS (7/7)
```

Command: `python3 tests/differential.py`

Observed final line:

```text
DIFFERENTIAL: ALL AGREE (43/43)
```

Command: `python3 tests/negative.py`

Observed:

```text
OK    baseline valid store py=(0, 2) go=(0, 2)
OK    tampered signature py=(2, 1) go=(2, 1)
OK    signer actor != body.actor.id py=(1, 2) go=(1, 2)
OK    signatures stripped py=(1, 1) go=(1, 1)
OK    body tampered (id mismatch) py=(1, 1) go=(1, 1)
OK    dangling prior + supersede subject (SPEC s7 MUST) py=(2, 2) go=(2, 2)
OK    ski@v1 verdict lie (hand-crafted) -> re-run disagrees py=(0, 4) go=(0, 4)

NEGATIVE: ALL AGREE
```

Incidental: `./warrant-go selftest` from inside `impl-go/` failed because the binary defaults to `examples/` relative to the current directory. The protocol form from the repository root passed.

## Verdict

Do not adopt GOV-001 as SPEC v0.3 yet. I found no P0 in the current text because these rules are not implemented and the existing v0.2 verifier baseline agrees, but GOV-001 has P1 normative gaps: implementers would have to guess how to decide novelty, which roots count for settlement, and what authorizes key rotation under compromise. The compatibility claim is also too broad as written.

Section verdicts:

- §1 re-litigation: reject until novelty is defined by outcome/claim, not check bytes.
- §2 multi-root stores: reject until unadopted roots are excluded from settlement-grade indexes and adoption authority is quorum/policy-scoped.
- §3 keys/rotation/thresholds: reject until rotation authorization is explicitly current-policy quorum plus incoming proof-of-possession, not "both keys" as a sufficient condition.
- Compatibility: reject the blanket "additive" claim; replace with version/policy activation rules that preserve every v0.1/v0.2 verification result.

## Findings

### P1: §7(b) admits byte-new restatements because "new check" is not mechanically defined

GOV-001 says a re-litigation warrant may carry a "`check` reason ... that does not appear in the tunnel and whose re-run verdict contradicts or materially qualifies the settled claim." The first half is byte/hash identity. The second half is not machine-defined: "settled claim", "contradicts", and "materially qualifies" have no canonical representation in v0.2 records.

Executable probe against the current schema:

```text
Command: python3 - <<'PY'
import hashlib, importlib.util, json
spec = importlib.util.spec_from_file_location('W','impl/warrant.py')
W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)
check_a = hashlib.sha256(b'#!/bin/sh\nexit 0\n').hexdigest()
check_b = hashlib.sha256(b'#!/bin/sh\n# cosmetic comment\nexit 0\n').hexdigest()
base = {
  'warrant':'0.2','decision':'reject','subject':{'hash':'a'*64},'under':['b'*64],
  'because':[{'kind':'check','runtime':'cmd@v1','check':check_a,'verdict':'pass'}],
  'evidence':['c'*64],'actor':{'id':'reviewer'},'prior':['d'*64],'ts':1
}
alt = json.loads(json.dumps(base)); alt['because'][0]['check'] = check_b
print('check_a', check_a)
print('check_b', check_b)
print('same_verdict', base['because'][0]['verdict'] == alt['because'][0]['verdict'])
print('schema_errors_base', W.validate_body(base))
print('schema_errors_alt', W.validate_body(alt))
print('warrant_ids_equal', W.warrant_id(base) == W.warrant_id(alt))
PY

Output:
check_a 306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb
check_b 63217a6d2a0e6a254b84f04eb1dad9b0ea6c8b56519d0d555de8656288fd0616
same_verdict True
schema_errors_base []
schema_errors_alt []
warrant_ids_equal False
```

That does not prove the cosmetic check is substantively new; it proves the format currently cannot distinguish byte novelty from claim novelty. One verifier can treat the second check hash as "does not appear in tunnel"; another can reject it as a restatement. That is a P1 because settlement admissibility becomes a local policy guess.

Concrete amendment:

```text
Replace §7(b) with:

(b) a new demonstrable consequence of evidence already present. A consequence
is new only by outcome, not by check bytes. A re-litigation check qualifies
only if all referenced blobs needed to re-run it are resolvable and one of the
following holds:

  1. It re-runs to the opposite verdict for the same claim target as a check in
     the settling tunnel; or
  2. It re-runs to a previously absent outcome fingerprint and explicitly
     names the settled claim it qualifies.

For `ski@v1`, the outcome fingerprint is:
  {runtime, term, expect, verdict, result_node_hash}

For `cmd@v1`, the outcome fingerprint is:
  {runtime, sorted evidence hashes, verdict, transcript hash}
and `transcript` is REQUIRED for §7(b) use.

A check whose outcome fingerprint already appears in the tunnel is not new,
even if the check blob hash differs. Prose MAY explain why the consequence
matters, but prose is not part of the novelty test.
```

This admits the ADR-004 precedent if ADR-004 supplied a new executable witness/check result over the already-shipped artifact. It rejects cosmetic restatements with the same verdict and same observable outcome.

### P1: "Tunnel" follows record links and blob links without defining closure

The proposal defines a settling warrant's tunnel as the transitive closure of its `prior`, `under`, and `subject` links. In SPEC v0.2, `prior` entries are WarrantIDs, while `under` and `subject.hash` are blob hashes. The text does not define whether verifiers recursively parse blobs, whether a blob hash that also names a record is followed as a record, or whether `under`/`subject` are only included as terminal hashes.

Concrete amendment:

```text
Add to §7:

The tunnel's record set is the transitive closure of `prior` edges through
stored warrants. The tunnel's blob set is the union of `under`, `evidence`,
`subject.hash`, `check`, and `transcript` hashes cited by those records.
Verifiers MUST NOT recursively parse arbitrary blobs for additional tunnel
links unless a later runtime-specific rule explicitly says so. If a blob hash
is also the WarrantID of a stored record, it is still a blob reference unless
it appears in `prior` or in a field whose rule explicitly names WarrantIDs.
```

### P1: WARN-only unadopted roots are not enough for settlement

GOV-001 says unadopted roots get `WARN: unadopted root`. That is fine for local integrity verification, but not enough for settlement. A settlement engine that scans all roots and merely warns can still index decisions from unadopted roots as settled. Worse, the proposed adoption rule lets any existing legitimate root `accept` a new root's first record. A hostile or compromised legitimate actor can mass-adopt spam roots and force every verifier/UI to process them as settlement-relevant unless adoption is scoped and policy-authorized.

Per-tunnel foreclosure helps only after a verifier has decided which roots are settlement-active. It does not answer whether unadopted roots can settle anything.

Concrete amendment:

```text
Replace the first §9 paragraph with:

A store is a DAG. A root is a record with empty `prior`. A root is
settlement-active only if either:

  (1) it is listed in the verifier's local trust configuration as a genesis
      root for this store; or
  (2) it is adopted by a settlement-active root through an `accept` warrant
      whose subject is the new root's first WarrantID and whose signatures
      satisfy the adopting root's current settlement policy, including any
      threshold rule.

Verifiers MAY verify inactive roots for local integrity, but MUST exclude
inactive/unadopted roots from settlement and foreclosure calculations and MUST
report `WARN: unadopted root`.

Adoption is scoped: adopting root A makes root B settlement-active for A's
jurisdiction. It does not make B globally authoritative for unrelated roots.
```

If the design wants any keyring-bound actor to create a new settlement-active root without adoption, say that explicitly and accept the spam/federation tradeoff. I would not make that the default.

### P1: Both-keys rotation is unsafe if read as sufficient authorization

The proposal says rotation is an `accept` signed by both outgoing and incoming keys. Under outgoing-key compromise, the attacker controls the outgoing key and can generate the incoming key, so "both keys" adds no security. For stores with two or more actors, quorum-only authorization is stronger than outgoing+incoming if the latter is sufficient.

The text can be read two ways:

- If threshold policy also applies to the rotation warrant, both-keys is only proof-of-possession plus quorum, and the rule can be safe.
- If both-keys is sufficient by itself, it is strictly worse than quorum-only for multi-actor stores.

That ambiguity is a P1. The rationale currently says the attacker "cannot rotate silently (needs both keys' signatures)", which is false in the outgoing-compromise scenario.

Concrete amendment:

```text
Replace the rotation paragraph with:

Rotation is a warrant: an `accept` whose subject is the new key blob. A
rotation MUST include a valid signature by the incoming key as proof of
possession and MUST be authorized under the actor/store's current key policy.
If that policy has a threshold, the rotation warrant MUST satisfy the
threshold using keys that were already bound before the rotation. The incoming
key's proof-of-possession signature does not count toward that threshold.

The outgoing key's signature MAY be required by policy for ordinary rotation,
but it MUST NOT be sufficient authorization when the store has a multi-actor
threshold policy. Emergency replacement of a suspected-compromised outgoing
key SHOULD be authorized by quorum without requiring the outgoing key.
```

Also replace the compromise analysis with:

```text
Single outgoing-key compromise: the attacker can sign as the outgoing key and
can generate an incoming key, so an outgoing+incoming pair is not evidence of
legitimate rotation. Protection comes from the current-policy quorum and from
excluding the incoming key from that quorum until the rotation is accepted.
```

### P1: Revocation/keyring derivation needs an ordering rule, not only timestamps

GOV-001 says keyring entries have `since_ts` and optional `until_ts`, and forged records die "after `until_ts`". Existing SPEC only warns on timestamp decreases along prior edges. If key validity is driven by body timestamps alone, a compromised key can backdate or choose convenient timestamps. If it is driven by DAG order, the proposal needs to say so.

Concrete amendment:

```text
Add to §5:

Key validity windows are derived from accepted rotation/revocation warrants in
DAG order, not from unauthenticated wall-clock trust in `ts` alone. A `ts`
outside the non-decreasing prior order remains a warning as in §6 and MUST NOT
by itself extend or resurrect a key. When two key-state warrants are unordered
by the DAG, verifiers MUST report `WARN: key-state conflict` and MUST NOT use
either unordered state transition for settlement-grade verification until a
later quorum-authorized warrant resolves the conflict.
```

### P1: Compatibility claim is too broad

The proposal says all three sections are additive and every v0.1/v0.2 record remains valid. Schema-validity is preserved, but verification and settlement consequences can change:

- SPEC v0.2 says unresolved `under`, `check`, `evidence`, and `subject.hash` references are warnings, not corruption. GOV-001 §9 says an unresolvable referenced blob makes the warrant `unverifiable` and "settles nothing new". That can change an old record's settlement effect.
- v0.1/v0.2 policy blobs are arbitrary blobs. If v0.3 verifiers scan any JSON policy blob for `min_sigs`, an old record filed under an old policy blob can suddenly fail threshold verification.
- A configured keyring can turn old signatures from "binding unverified" into "unbound". That may be a useful report, but the proposal must state whether it is an error, warning, or settlement-grade exclusion.

Concrete amendment:

```text
Replace Compatibility with:

Every v0.1/v0.2 body that was schema-valid remains schema-valid under its
declared version. v0.3 settlement rules MUST NOT turn a v0.1/v0.2 record into
a schema error.

Unresolved references in v0.1/v0.2 records remain verification warnings as in
SPEC §6. For v0.3 settlement indexes, a record with unresolved settlement-
critical references is settlement-inactive until the references resolve; this
does not change its WarrantID or base verification result.

Threshold checks activate only for policy blobs that explicitly declare the
v0.3 policy format, e.g. canonical JSON with `{"warrant_policy":"0.3", ...}`.
Opaque v0.1/v0.2 policy blobs MUST NOT be interpreted as threshold policies by
accident.

With a keyring configured, bound/unbound status is a report unless a v0.3
policy explicitly makes bound signatures required for settlement-grade
verification. Stores without keyrings keep the v0.2 `binding unverified`
warning.
```

### P2: "Legitimate root" conflates identity validity with settlement authority

"Legitimate iff actor's key is bound" is too strong. A bound key proves who filed the root. It does not prove the root should settle the jurisdiction's questions. Use separate names.

Concrete amendment:

```text
Use:

- `well-signed root`: root whose filing signature is valid and bound.
- `settlement-active root`: root admitted to settlement/foreclosure by local
  trust configuration or policy-authorized adoption.
```

### P2: Threshold policy grammar is underspecified

`min_sigs: M of [actor ids]` is readable prose, not enough for two implementations. It needs canonical JSON shape, actor uniqueness, unknown-field handling, and activation rules.

Concrete amendment:

```text
A v0.3 threshold policy blob, if present, MUST be JCS-canonical JSON:

{
  "warrant_policy": "0.3",
  "threshold": {
    "min_sigs": <positive integer>,
    "actors": [<nonempty unique actor id strings>]
  }
}

`min_sigs` MUST be <= len(actors). Unknown fields in `threshold` MUST make the
threshold policy invalid. Records filed under an invalid threshold policy are
settlement-inactive and MUST produce `ERR: invalid threshold policy` for
settlement-grade verification.
```

## Explicit answers to review-gate asks

1. Does §7(b) admit a trivially restated check as "new"?

Yes, as written it can. The check hash can be new while the verdict and observable result are the same, and there is no machine-readable claim identity to decide "materially qualifies." Tightest fix: novelty must be outcome/claim novelty, not byte novelty. For `ski@v1`, use term/expect/verdict/result NodeHash; for `cmd@v1`, require transcript for §7(b) and use evidence set/verdict/transcript. Same fingerprint means not new even if the check blob differs.

2. Can a hostile legitimate root adopt spam roots at scale? Is WARN enough?

Yes. A hostile settlement-active root can mass-adopt spam under the current wording, and a merely bound actor can create roots that the text calls legitimate. WARN is not enough for settlement. Unadopted roots should be verifiable but settlement-inactive. Adoption should require the adopting root's current settlement policy/threshold, and adoption should be scoped to the adopting jurisdiction.

3. Is both-keys rotation strictly worse than quorum-only under outgoing-key compromise?

If both-keys is sufficient authorization, yes for stores with at least two actors. The attacker with the outgoing key can also create/sign the incoming key. If threshold policy also applies, both-keys is not worse but is redundant as proof-of-possession. The spec must say rotation requires current-policy quorum using already-bound keys, with the incoming signature only proving possession.

## Relation to existing reviews

I read `reviews/2026-07-opus48-v0.2-review.md` and `reviews/2026-07-opus48-v0.2-response.md` after forming the above findings.

Agree:

- The prior review's design-rule concern was real: two implementations must agree on IDs and outcomes. The current checkout now has differential and negative tests that pass.
- The prior F3 key-binding warning is the right starting point for GOV-001 §5, but GOV-001 must now define when "bound" affects settlement authority.

Disagree:

- No disagreement with the prior v0.2 dispositions. They are mostly outside this GOV-001 gate.

New relative to those reviews:

- GOV-001 introduces new settlement semantics that are not yet mechanically decidable: novelty, root activation/adoption, rotation authorization, and compatibility gating. These are not implementation bugs yet; they are spec blockers before implementation.

## Final recommendation

Revise GOV-001 before adoption. The direction is sound: settlement should be executable, root scope should be explicit, and key binding should graduate from warning-only to policy-aware settlement checks. But the current candidate text leaves too much normative work to verifier authors. Under Warrant's own severity ladder, that is P1: not yet a P0 split, but enough ambiguity that two conforming v0.3 implementations would plausibly diverge on settlement outcomes.
