# WRT-010: the binding enumeration

**Why this document exists.** Three gate rounds returned AMEND, and F1, F2, H1
and J1 are all one defect wearing four faces: *something claims to be about
something else, and nobody checked the claim.* Each round I bound the edge the
reviewer named and a later round found another. Patching one edge at a time is
not a method, and the repository's own stopping rule (WRT-007 §6) exists to
halt exactly that loop.

So this is a different kind of artifact. It enumerates **every** claim of
aboutness the profile relies on, says what checks each, and names the test.
A row with no check is a defect whether or not a reviewer has found it yet.

Writing it found two nobody had reported: **K1** and **K2** below.

**A check in the table is not a check on the path.** L1 was found *after* this
document existed, and it is the sharpest thing the document has taught: E1 was
listed, implemented and tested, and the new K1 walk still read `prior` out of
records without applying it. Listing an edge proves the check exists. It does
not prove the check runs at every site where that data is used as evidence.
So every row below names a **use site**, and a new path that consumes an
existing object owes its own row even when the check it needs is already
written. Correct addresses at the endpoints do not prove the edges between them.

**The honest limit of the method.** A complete-looking table proves the edges I
thought to list are checked. It cannot prove I listed them all. What it does
change is the failure mode: a future finding should either be a row here that is
wrong, or a row that is missing — and a missing row is an argument about the
model, which is a better argument than "here is another patch."

---

## 1. Objects

| Symbol | What it is |
|---|---|
| `R` | the record whose provenance is being checked (envelope + body) |
| `D` | a provenance document, a blob cited in `R.evidence` |
| `S` | the WPL source blob `D` names |
| `C` | the compiled `ski@v1` check blob `D` names |
| `W` | a warrant a derived fact names in its `from` clause |
| `Wr` | the `ski@v1` reason of `W` that supplies the value |
| `Wc` | the check blob `Wr` cites |
| `X` | a `supersede` record whose subject is `W` |
| `P` | an **intermediate record on a `prior` path** whose own `prior` the citation walk reads |

## 2. The edges

Every row is a claim of the form *"A claims to be about B"*.

| # | Claim | Checked by | Where | Test |
|---|---|---|---|---|
| E1 | a record file named `<wid>` claims its body is warrant `wid` | recompute `warrant_id(body)` and compare | `_record_at` | `test_address_integrity` |
| E2 | a blob file named `<h>` claims its bytes hash to `h` | `blob_intact` before any read | `_intact_blob`, `_provenance_docs_of` | `test_address_integrity` |
| E3 | a blob claims to be a profile document | `provenance == PROFILE` | `_provenance_docs_of` | — (identification, not a claim about anything else) |
| E4 | `D` claims a well-formed shape | closed schema, **before** any use | `_validate_doc_shape`, called first | `test_malformed_sidecar_is_a_typed_refusal` (J1) |
| E5 | `D` claims to describe check `C` | recompile `S`, require it yields `C` | `_recompile` | `test_completeness_and_tampering` |
| E6 | `D` claims to belong to record `R` | `D.check` ∈ `R`'s `ski@v1` reason checks | `_provenance_docs_of` | `test_sidecar_belongs_to_this_record` (H1) |
| E7 | `D`'s fact set claims to be `C`'s fact set | exact set equality, both directions | `_require_complete` | `test_completeness_and_tampering` |
| E8 | `D`'s per-fact value claims to be `S`'s literal | equality | `_require_complete` | `test_completeness_and_tampering` |
| E9 | `D`'s per-fact kind / `from` / selector claims to be `S`'s `from` clause | field-by-field comparison against `Fact.source` | `_require_complete` | `test_completeness_and_tampering` (F1) |
| **K1** | **a derived fact claims a dependency `R` also cites** | **`W` ∈ prior closure of `R`** | **`_citation_closure`** | **`test_derivation_must_also_be_cited`** |
| **L1** | **`P` claims, under its address, the `prior` this walk reads from it** | **E1 on every hop, before its `prior` is read; an unverified `P` is not traversed and is named** | **`_citation_closure`** | **`test_derivation_must_also_be_cited`** |
| L2 | the citation walk claims to have finished | record budget; a missing or unparsable intermediate is named, never swallowed | `_citation_closure` | `test_derivation_must_also_be_cited` |
| E10 | `entry.from` claims warrant `W` exists | `_record_at`, which re-checks E1 for `W` | `_check_derived` | `test_derived_states` |
| E11 | `entry.check` claims to select one of `W`'s reasons | filter, then require exactly one | `_check_derived` | `test_derived_states` |
| E12 | `Wr` claims a check blob `Wc` | `_is_hex64`, then loaded at its address | `_check_derived` → `warrant._load_ski_doc` | `test_derived_states` |
| E13 | `Wc` claims term / atp / expect | JCS-canonical, `validate_ski_blob`, budget bound | `warrant._load_ski_doc` (library) | warrant's own vectors |
| E14 | the reduction claims to reach `expect` | `run_ski_check` verdict must be `pass` | `_check_derived` | `test_derived_states` |
| E15 | the result claims to be a Church boolean | compare to the two canonical node hashes | `church_bool` | `test_derived_states` |
| E16 | that boolean claims to equal `entry.value` | equality → else `contradicted` | `_check_derived` | `test_derived_states` |
| E17 | `X` claims to supersede `W` | `subject.hash == W`, and `X` re-checks E1 | `_superseded_by` | `test_stale_propagation` |
| E18 | the walk claims to have finished | depth, record budget and cycle guard, each reported | `_source_health` | `test_transitive_staleness` |
| E19 | the term thunks the evaluator pulls claim their addresses | CAS adapter compares each fetch | `warrant.run_ski_check` (library) | warrant's own vectors |
| E20 | the evaluator claims to be the pinned one | digest check before load; unpinned raises | `warrant.load_sigma` (library) | `underived` on RuntimeError |
| **K2** | **`attested` claims an attestation** | **it does not: the name is bound to `R`'s identity and to nothing else** | **`Finding.actor`, narrowed** | **`test_profile_claims_no_attestation`** |

## 3. Edges the profile deliberately does not check

Named so that "unchecked" is never mistaken for "overlooked".

| Claim | Why not, and whose job it is |
|---|---|
| a signature is valid, and the key belongs to the actor | SPEC §5/§5.1 with a trust configuration, in `warrant verify`. This profile reads no keyring; **K2** exists so its output cannot imply otherwise |
| the actor had standing to decide | authority is not computable from a term. SPEC §12 |
| an **observed** fact is true | nothing can check this. It is the whole reason the two kinds are separate |
| `R`'s claimed `verdict` field | the profile uses the **re-run**, not the claim. A record claiming `fail` for a check that reduces to Church TRUE still supplies `true`, because the value is what the term computes. SPEC §6(7) reports the disagreement itself |
| `cmd@v1` reasons | their trust model is the container, per SPEC §3 |
| upstream derivation **values** in the walk | §5.5: the walk checks structure and supersession, not each ancestor's value. This is the boundary S1 named, open as §9.7 |

## 4. The envelope's edges

`tools/pack_pdf.py` is a separate artifact with its own aboutness claims.

| # | Claim | Checked by | Test |
|---|---|---|---|
| P1 | a member name claims a path inside the destination | resolve, require the prefix | `test_extraction_refusals` |
| P2 | a member claims to be a plain file | `isreg`, else refuse | `test_extraction_refusals` |
| P3 | two members claim distinct paths | exact target comparison | `test_extraction_refusals` |
| P4 | two members claim distinct **files** | case + NFC fold, because two strings can be one file | `test_extraction_refusals` (J2) |
| P5 | a member claims its parents are directories | order-independent ancestor scan, folded | `test_extraction_refusals` (H2) |
| P6 | a target claims not to collide with what is already there | parent-is-file, target-is-dir | `test_extraction_refusals` |
| P7 | nothing is written before every claim is checked | plan, then write | `test_extraction_refusals` (F5) |
| P8 | the xref offsets claim to address their objects | asserted at build time | `test_pdf_structure` |
| P9 | the file claims not to adjudicate itself | property test on the absence | `test_does_not_adjudicate` |

**P4's limit, stated rather than implied.** The fold covers case and Unicode
composition, which is the aliasing this host actually exhibits. It is not a
model of every filesystem's equivalence, and `os.path.normcase` alone would
have been a no-op on POSIX and caught nothing.

## 5. What the enumeration found

**K1 · a derivation was credited without being cited.** A record could derive a
fact from `W` while `W` sat outside its `prior` closure. SPEC §7 builds a
settlement tunnel from `prior`, so a dependency outside it is invisible to
re-litigation: superseding `W` would never reach this record through the
tunnel, and the propagation this profile exists for would silently not happen.
Using a decision now requires citing it. Reached transitively through `prior` is
enough, because the tunnel is the closure.

**K2 · `attested by <name>` implied an attestation nobody checked.** The name
comes from `body.actor.id`, which E1 binds to the record's identity and nothing
else. No signature is verified anywhere in this profile. The report now says
`record names X; this profile checks no signature`, and a test fails if the
profile ever grows a signature API or prints the old phrasing.

Both are the same species as F1/F2/H1/J1, which is the point: they were found by
walking the model rather than by waiting for the next round.

**L1 · an unverified bridge proved citation coverage.** The first K1 walk
delegated reachability to `warrant.tunnel`, which reads `body.prior` out of a
dict keyed by file name. Swapping an intermediate record's body under its old
name turned the refusal into `complete, derived` — the endpoints were both
correctly addressed, and the edge between them was a lie. The walk is now our
own, applies E1 on every hop before reading a `prior`, refuses to traverse what
it cannot verify, and reports the record it stopped at rather than letting a
broken path read as a plain miscitation. Found by a reviewer, not by this
table; the table's repair is the use-site rule above.

**One more, found while fixing K1.** Record status was derived from a *subset*
of the refusal list, so a record could report `complete` while a document it
cited had been refused. That is F3 one level up, and it is now derived from the
whole list.
