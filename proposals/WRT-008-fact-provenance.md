# WRT-008: Fact provenance — derived facts, and the chain of decisions

**Status:** DRAFT rev 1 (2026-09-09) — **design plus a reference profile.** No
SPEC edit and no change to `ski@v1` is made or proposed by this document. It
adds an OPTIONAL verification profile (`warrant.fact-provenance@v0`) and an
additive, term-preserving WPL clause. Adoption of the profile requires an
adversarial gate; nothing here is adopted, and no existing record changes
meaning.

**Invariant this proposal is built around:** *provenance never changes the
term.* A WPL source with `from` clauses compiles to byte-identical `term`,
`expect`, `atp` and check blob as the same source without them. Every shipped
pack keeps its hashes; nothing is re-signed. This is enforced by a test, not
by intent (§6).

---

## 1. The problem

`docs/authoring-checks.md` §8 states the position honestly:

> **Nothing about the facts is proven.** `fact retroactive: bool = true` is an
> assertion by whoever compiled it. Its trustworthiness comes from the
> signature on the record and the evidence blobs cited beside it, not from the
> check.

That is correct and it is the right default. But it flattens two things that
are not alike, and the flattening has a cost the format has not paid attention
to.

Some facts are **observations**: someone looked at the world and wrote a
number. No cryptography makes an observation true. The strongest honest thing a
record can say is *who* asserted it and *when it entered the record*.

Other facts are **consequences of what is already in the store**. `files_changed`
is a consequence of a pinned diff. And — the case this proposal exists for —
*the answer of a previous decision* is a consequence of a term that is already
content-addressed, budget-bounded and re-runnable by anyone.

For the second class, **trust is the wrong instrument**. The value does not need
to be believed; it needs to be *re-derived*. Today WPL has no way to say so, so
an author who wants to build on a prior decision retypes its answer as a
literal, and a re-typed literal is indistinguishable from an invention.

**Consequence: decisions do not compose.** Each warrant is an island. A policy
cannot cite another policy's outcome mechanically, so the "chain of reasons"
the format is for stops at one link. This is the single blocker to the format
demonstrating what it is actually for.

## 2. Two fact kinds

| Kind | What it is | What binds it | What a verifier can say |
|---|---|---|---|
| **observed** | someone measured the world | a signature and an actor | *attested by X at t* — never "verified" |
| **derived** | a consequence of store contents | a re-runnable derivation | *derived*, *contradicted*, *underived*, or *stale* |

The design rule: **a policy cites an observed fact by its attestor, and a
derived fact by its derivation.** These MUST NOT be reported with the same
word. This is the same requirement SPEC §6(7) already imposes on reasons
("`Re-ran and matched` and `was not executed` MUST NOT be observationally
equivalent"), applied one level down, to the operands.

Observed facts remain exactly what they are today. This proposal adds nothing
to them and claims nothing about them. It gives the *other* kind a name and a
check.

## 3. The `from` clause (WPL, additive)

```
fact retroactive: bool = true                        # observed — unchanged
fact eligible:    bool = true from <WarrantID>       # derived
fact timely:      bool = true from <WarrantID> check <hex64>
```

Grammar: after a fact's literal, optionally `from` HEX64, optionally followed by
`check` HEX64. The second form disambiguates when the cited warrant carries more
than one `ski@v1` reason; without it, a cited warrant with more or fewer than
exactly one `ski@v1` reason is a compile-time refusal, by name, per WPL's
existing refusal discipline.

**Derived facts are `bool` only in v0.** A `ski@v1` check answers one Church
boolean (§3.1), so that is the only value shape a decision can hand to the next
policy. Deriving an `int` would require a check whose canonical outcome is a
numeral — a different outcome shape, and a different proposal. Predicate
chaining is what settlement needs, and predicate chaining is booleans.

**The clause does not enter the term.** Facts are still pinned as literals and
lowered exactly as before. `from` is provenance metadata, carried beside the
check, never inside it (§6).

## 4. The provenance document

One blob per check, JCS-canonical, cited in the filing warrant's `evidence`:

```json
{
  "provenance": "warrant.fact-provenance@v0",
  "check": "<hex64 — the ski@v1 check blob this describes>",
  "source": "<hex64 — the WPL source blob the check compiles from>",
  "facts": {
    "eligible":    {"kind": "derived",  "value": true,
                    "from": "<WarrantID>", "check": "<hex64>"},
    "retroactive": {"kind": "observed", "value": true}
  }
}
```

**Completeness (MUST).** The document MUST describe **every** fact of the check
it names, and a checker MUST refuse a document whose fact-name set differs from
the set recovered by recompiling `source`. Omission is the failure mode this
rule exists to stop: a provenance document that simply leaves a fact out would
otherwise turn a check off while the status stayed green. A missing entry is a
refusal, never a default to `observed`.

**The compiler stays untrusted.** The checker recompiles `source` and requires
it to yield `check`. Provenance is therefore auditable the same way the term
already is: by re-running the compiler and comparing, never by believing it.

## 5. What the profile checks

`warrant.fact-provenance@v0` is an OPTIONAL profile. A verifier asked for it
performs, for every derived fact:

1. Resolve the cited WarrantID among stored records.
2. Select its `ski@v1` reason (named by `check`, or the unique one).
3. Load the check blob; re-run `term` under its pinned `atp` (the same
   re-execution §6(7) already performs).
4. Require the result NodeHash to equal the reason's `expect`.
5. Map `expect` to a boolean by the canonical Church TRUE / Church FALSE node
   hashes. Any other normal form is **not a boolean outcome** and is a refusal,
   not a coerced value.
6. Compare that boolean to the fact's pinned literal.
7. Check whether the cited warrant has been superseded by a stored `supersede`.

Four terminal states per derived fact, which MUST be distinguishable in output:

| State | Meaning | Severity |
|---|---|---|
| `derived` | re-ran; the cited decision's answer equals the pinned value | — |
| `contradicted` | re-ran; the answer **differs** from the pinned value | ERR |
| `underived` | could not re-run: missing record or blob, over budget, ambiguous reason, non-boolean outcome | WARN, ERR under settlement grade |
| `stale` | derivation reproduces, but the cited warrant has been **superseded** | WARN, ERR under settlement grade |

Observed facts get one state, `attested`, carrying the actor of the citing
record. A checker MUST NOT print `verified` for an observed fact.

### 5.1. Why `stale` is the point

`stale` is the reason this proposal is worth more than tidiness.

When a leaf observation is later shown to be false, someone files a re-litigation
warrant under §7(b) and the affected decision is superseded. Every downstream
policy that derived a fact from it then reports `stale` — **mechanically,
offline, with no registry, no notification service and nobody remembering the
dependency existed.** Revocation propagates because the dependency is written
down in a form a machine re-walks, not because anyone maintained a list.

That is the honest version of the ambition: the format does not prevent a false
observation. It makes the discovery of one *propagate*.

## 6. The term-preservation invariant

`from` clauses MUST NOT change `term`, `expect`, `atp`, the emitted node set, or
the check blob hash. The reference implementation enforces this by compiling
each fixture twice — once with every `from` clause stripped — and asserting
byte-equality of the emitted document.

This is what keeps the change additive: `ski@v1` is a registered, immutable
runtime tag (§13.1), the shipped `demos/air-canada` pack keeps its published
hashes, and a verifier that does not know about provenance verifies exactly what
it verified before.

## 7. What this does not claim

- **It does not make an observed fact true.** Nothing can. It only stops an
  observation from being typeset like a derivation.
- **It does not change §6, §7, or `ski@v1`.** It is a profile plus an authoring
  clause. A base-grade verification is unaffected, and a verifier that ignores
  the provenance blob is still conformant.
- **It does not establish that a cited decision was *authorized*.** Re-running a
  term proves what the term computes, not that its author had standing. Authority
  remains §5/§12's problem, and the trust root remains the verifier's
  configuration.
- **It does not bound chain depth or cost.** A derived fact re-runs another
  check, which may itself carry derived facts. Implementations MUST bound
  recursion depth and total re-execution budget across a chain, and report the
  bound being hit as `underived` — never as success. The bound is local policy,
  as in §3.1.
- **It does not claim the profile has been reviewed.** rev 1 has had no
  adversarial gate. The design is filed to be attacked, and the most likely
  attack surfaces are named in §9.
- **It does not address cycles.** A store where W1's fact derives from W2 and
  W2's from W1 is possible to construct; §9(3) treats it as open.

## 8. Relation to the rest of the stack

- **Σ-GLYPH** owns the reduction; nothing here touches it. A derived fact is one
  more re-execution of an existing Book I term.
- **Aggregation (`all` / `any` / `count`) is downstream of this, not parallel to
  it.** Aggregation over a collection pinned into the term stays a closed ground
  check and costs only ATP. Aggregation over a collection that is *not* pinned
  requires knowing where the collection comes from — which is this proposal.
  Deciding quantifiers before binding is deciding the harder half first.
- **The manifesto's line about a network that remembers** gets a mechanism here:
  what the network remembers is not the value, it is the derivation.

## 9. Open questions (attack surface)

1. **Ambiguous reason selection.** v0 refuses a warrant with more than one
   `ski@v1` reason unless `check` names one. Is refusal right, or should the
   clause name a *reason index*? Index is fragile under re-filing; check-hash is
   stable but verbose.
2. **Non-boolean outcomes.** v0 refuses. A canonical DISSONANCE outcome is a
   real and meaningful answer ("this did not settle") that a downstream policy
   might legitimately want to branch on. Refusing it may be over-strict.
3. **Cycles and depth.** Cycle detection is unspecified. A malicious store can
   construct one; the bound in §7 stops non-termination but the reported state
   for a cycle member is undefined.
4. **`stale` and re-filing.** A superseded warrant whose successor reaches the
   *same* answer arguably should not make downstream facts stale. Distinguishing
   "superseded and changed" from "superseded and unchanged" needs the successor's
   outcome fingerprint compared to the predecessor's — cheap, but unspecified in
   rev 1.
5. **Does `contradicted` belong at ERR?** It is a genuine defect of the citing
   record, but §6's convention is that a false claim is a dispute answered by a
   counter-warrant, not a corruption of the record. rev 1 chooses ERR because the
   citing author pinned a value their own cited source refutes, which is a
   different thing from disagreeing with someone else. This is the finding most
   likely to be reversed by review.

## 10. Reference artifacts in this branch

| Artifact | What it is |
|---|---|
| `impl/policy_lang.py` | `from` clause: parser, `Fact.source`, provenance emission. Term-preserving. |
| `impl/fact_provenance.py` | Profile checker: the four states, completeness rule, recompile-and-compare. |
| `tests/fact_provenance.py` | Including the term-preservation invariant and one negative fixture per state. |
| `demos/refund-chain/` | Three policies, chained; rhetoric refused; a new consequence of old evidence reopens settlement, and the downstream derived fact goes `stale` on its own. |
| `tools/pack_pdf.py` | The envelope: a pack as one file that is both a readable PDF and its own deterministic archive. It does not verify itself, on purpose. |
| `tests/pack_pdf.py` | Including the xref walk, hostile-archive refusals, and a property test on the *absence* of self-adjudication. |
