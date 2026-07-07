# Gate review: GOV-001 settlement at scale (Rev 2)

Reviewer: Gemini 3.1 Pro, independent adversarial reviewer
Date: 2026-07-07
Scope: `proposals/GOV-001-settlement-at-scale.md` REV 2 as candidate SPEC v0.3 text, checked against `SPEC.md`, implementations, and existing reviews.

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

Command: `(cd impl-go && go build -o warrant-go . 2>/dev/null || go build -o warrant-go main.go) || true`
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
Observed final line:
```text
NEGATIVE: ALL AGREE
```

## Verdict

Do not adopt GOV-001 rev 2 as SPEC v0.3 yet. While it successfully patches the loopholes from rev 1, it introduces new mechanisms that are fundamentally unimplementable against the v0.2 record schema (P1). Furthermore, the fallback behavior for DAG key conflicts allows an attacker to paralyze key rotation, effectively immortalizing a compromised key (P1).

Section verdicts:
- §1 re-litigation: **Reject** (P1) - The text relies on "explicitly names the settled claim", which is structurally impossible in the v0.2 `check` reason schema without triggering fatal validation errors.
- §2 multi-root stores: **Revise** (P2) - Subjectivity is fine, but it needs an in-band default manifest (`genesis.json`).
- §3 keys/rotation/thresholds: **Reject** (P1) - Suspending conflicting key states reverts to the prior state, giving attackers a veto via conflict injection.
- Compatibility: **Accept** - The activation rules successfully preserve v0.2 state without breaking existing stores, though they highlight the schema limitations in §1.

## Findings

### P1: §7(b) outcome fingerprint logic is unimplementable against the v0.2 schema

Rev 2 attempts to constrain new checks by requiring them to either test the "same claim target" or to "explicitly name the settled claim it qualifies". 
However, under the v0.2 schema (SPEC §2 and §3), a `check` reason is rigidly defined as having only `{"kind", "check", "runtime", "verdict", "transcript"}`. 

Executable probe demonstrating that adding fields to name a target is rejected by the format:
```bash
Command: python3 - <<'PY'
import json, subprocess
with open("examples/propose.warrant.json", "r") as f: warrant = json.load(f)
warrant["body"]["because"].append({
    "kind": "check", "check": "05d234bec21803c6fa007d848c1773b9fd05cfdf852d6d09542ed3b127c02b6c",
    "runtime": "cmd@v1", "verdict": "pass", 
    "transcript": "ca3e94e735d9232f3a2621d9a79813de520bc792b5e011d4662967de867fdb56",
    "qualifies_claim": "some_hash"
})
with open("scratch.json", "w") as f: json.dump(warrant, f)
import impl.warrant as W
print("Errors:", W.validate_body(warrant["body"]))
PY

Output:
Errors: ['because[1]: check reason has unknown fields']
```

Because unknown fields MUST make the record invalid, there is no way for a check to "explicitly name" a settled claim. Furthermore, "same claim target" is meaningless: the only identity of a check is its `check` hash. The format layer cannot logically distinguish between a valid novel check and an attacker's strawman check, because it cannot know what *semantic* claim a blob tests. 

*Answer to Ask 1:* Yes, an attacker can mint an 'opposite verdict' check that tests something adjacent, and because the format lacks a canonical representation of a "claim target", the format cannot prevent this.

**Concrete amendment:**
We must decouple the format's definition of *novelty* from the policy's definition of *relevance*. The format can only verify if an outcome is novel. Re-litigation churn via strawman checks is a policy-layer problem, not a format-layer problem.

```text
Replace the list in §7(b) with:

A re-litigation check qualifies only if all blobs needed to re-run it are 
resolvable and it re-runs to a previously absent **outcome fingerprint** 
within the settling tunnel. 

Outcome fingerprints: for `ski@v1` —
`{runtime, term, expect, verdict, result_node_hash}`; for `cmd@v1` —
`{runtime, sorted evidence hashes, verdict, transcript hash}`, and
`transcript` is REQUIRED for §7(b) use. A check whose outcome
fingerprint already appears in the tunnel is not new, even if the
check blob hash differs.

Whether a novel check is actually relevant to the subject, or merely a 
"strawman" testing an adjacent claim, MUST be decided by the active settlement 
policy, not the core format layer.
```

### P1: DAG-order key conflict suspension enables Denial-of-Service on rotation

Rev 2 states: "When two key-state warrants are unordered by the DAG, verifiers MUST report `WARN: key-state conflict` and MUST NOT use either transition for settlement-grade verification until a later quorum-authorized warrant resolves the conflict."

If neither transition is used, the system falls back to the *previous* key state. If an attacker compromises an outgoing key, they can author a fraudulent rotation on a fork. When the honest quorum attempts a legitimate rotation, the DAG sees a conflict. By freezing both transitions, the attacker successfully keeps their compromised key fully valid in the active quorum! They can then indefinitely block the "later quorum-authorized warrant" by refusing to sign it, paralyzing the store.

*Answer to Ask 3:* No, it does not converge. Conflicting key states live forever because the attacker retains their veto power in the fallback state.

**Concrete amendment:**
A conflict must freeze the *conflicted key*, not just the transitions, so it cannot participate in the quorum to block resolution.

```text
Replace the ordering conflict text in §5 with:

When two key-state warrants are unordered by the DAG, verifiers MUST report
`WARN: key-state conflict`. To prevent an attacker from keeping a compromised 
key alive by injecting conflicts, the conflicted actor's key MUST NOT be 
counted toward any quorum until a later warrant—authorized by the 
unconflicted remainder of the quorum—resolves the conflict. If the policy 
requires consensus (e.g. 3 of 3), the threshold is temporarily reduced to 
exclude the conflicted actor (e.g. 2 of 2) strictly for the purpose of 
conflict resolution.
```

### P2: Divergent local genesis lists are too subjective for auditing

Rev 2 allows verifiers to define settlement-active roots via "local trust configuration". While subjective federation (like `git remote`) is useful, handing an auditor a `.warrants` directory currently gives them no standard way to know which root is genesis without out-of-band communication. 

*Answer to Ask 2:* The spec needs a store-level manifest so divergence is explicit. Pure subjectivity breaks portability.

**Concrete amendment:**
Make the subjectivity explicit and in-band by adding a store-level manifest.

```text
Add to §2:

Stores SHOULD contain a `genesis.json` in the store root: a map 
`{"roots": ["<WarrantID>"]}`. If present, verifiers MUST use these as the 
default genesis roots for settlement unless explicitly overridden by the 
verifier's local trust configuration. This ensures that sharing a blob store 
also shares the intended jurisdictional perspective.
```

## Relation to existing reviews

I read `reviews/2026-07-codex-gov001-gate.md` after forming the above findings.

**Agree:**
- Codex was entirely correct that novelty must be defined mechanically by outcome, not check bytes. 
- Codex correctly identified that "both keys" rotation under compromise is insecure and required a quorum-based fix.

**Disagree:**
- Codex proposed the text "explicitly names the settled claim it qualifies" and "same claim target" to fix the strawman issue. As proven above, this is fatally incompatible with the v0.2 strict schema constraints. We cannot regulate strawman claims at the format layer without introducing a v0.3 body schema, which GOV-001 avoids doing.

**New:**
- I discovered that the fallback state for Codex's DAG-conflict rule unintentionally grants an attacker a perpetual veto over key rotation.
- I identified the need for `genesis.json` to standardize multi-root context sharing.
- I verified that the outcome fingerprint logic is fundamentally incompatible with the existing v0.2 strict JSON schema limits.
