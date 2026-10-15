# WRT-014: Whose policy admits a root — the adopter's, or the jurisdiction's?

**Status:** DRAFT rev 1 (2026-10-15) — **finding and options only.** No SPEC
edit, no code change. Every implementation in this repository behaves as
described in §1; changing that is a settlement-semantics change that needs an
adversarial gate, an owner decision and a SPEC document-version bump. Nothing
here claims adoption.

## 1. The finding

SPEC §9 makes a non-genesis root settlement-active only if it is

> adopted by a settlement-active root through an `accept` warrant whose
> `subject.hash` is the WarrantID of the root to be adopted and whose
> signatures satisfy **the adopting root's current settlement policy,
> including any threshold rule**.

All three implementations evaluate instead the policies named in the
**adoption record's own `under`** (`_policies_satisfied` over
`record_policy(env["body"])` in Python, the same in Go and Rust). The filer of
the adoption chooses that list. So:

```
genesis root R   under: [2-of-2 threshold {a@x, b@x}]   signed by a@x and b@x
root X           under: [opaque]                         signed by a@x
adoption A       accept X, prior [R], under: [opaque]    signed by a@x ONLY
```

`verify --settlement` with R as the trusted genesis root: **X is adopted on one
signature, 0 errors, 0 warnings**, in Python, Go and Rust alike. Reproduce:

```bash
python3 proposals/wrt-014-model/reproduce.py
```

Nothing in the report hints that the jurisdiction's threshold was not the rule
applied. The same result follows if A cites R's threshold blob with one trailing
byte (it is then "not a policy" and therefore opaque), which is how this was
found: a threshold-encoding differential (`tests/go_findings_parity.py`) showed
all three implementations adopting under a mangled policy, and the question
"why does a mangled policy weaken the rule at all?" led here.

Scope, honestly: **no threshold has ever been exercised in this repository's
own governance store** (THREAT-MODEL SA-3), so this is not a live compromise of
anything here. It is a gap between what §9 says protects a jurisdiction and what
any verifier enforces, and it sits in the least-vectored layer of the format
(SA-7: §9 is vectored only as far as root admission).

## 2. What "the adopting root's current settlement policy" could mean

The SPEC does not define it, which is part of the defect. Three readings:

- **(R1) The root's own threshold policies.** The v0.3 threshold policies in
  the adopting root's `under`. Simple, static, decidable from one record.
- **(R2) The root's policy as amended.** R1, but a later settlement-active
  `supersede` of the root (or a dedicated policy-change record) can replace it.
  "Current" suggests this; nothing in §5.1/§7/§9 specifies the amendment path.
- **(R3) The adopter's choice (today's behaviour).** Whatever the adoption
  record cites. Then a threshold binds only if every member of a jurisdiction
  refuses to file adoptions under anything else — a social convention, not a
  verifier rule — and the SPEC sentence should say so.

## 3. Options

| | Rule | Cost | Breaks |
|---|---|---|---|
| **A** | Adoption must satisfy **R1** (the adopting root's threshold policies) **and** its own `under` | one more policy lookup per adoption; vectors for both | stores relying on unilateral adoption under a threshold root — none known |
| **B** | Adoption's `under` MUST include every threshold policy of the adopting root, else `ERR: adoption outside jurisdiction policy` | a new ERR string in three implementations | the same stores, loudly |
| **C** | Keep behaviour; rewrite §9 to R3 and state in THREAT-MODEL that thresholds are not a verifier-enforced boundary for adoption | documentation | nothing; the guarantee readers assumed is withdrawn in writing |
| **D** | A, plus R2's amendment path | a design for policy change | — (larger; separate proposal) |

A and B fail closed; C is honest about the current state; D is where "current"
would eventually have to go. This document does not choose.

## 4. What a decision must come with

- A vector per option in the conformance pack's settlement grade (the pack
  digest moves, SPEC §8.6) — today no vector distinguishes A/B from C.
- The same rule in Python, Go and Rust, held by `tests/go_findings_parity.py`
  and `tests/rs_parity.py`.
- THREAT-MODEL SA-7 updated from "assumed" to "vectored" for adoption policy.
- A transition note: fingerprints and activeness are computed, never stored, so
  any rule is retroactive; A/B can only make *fewer* roots active.

## 5. What this does not examine

Revocation of an adoption, adoption chains (X adopting Y under X's policy),
key-state conflicts inside an adoption threshold, and cross-jurisdiction
re-litigation. Each inherits whichever reading is chosen in §2.
