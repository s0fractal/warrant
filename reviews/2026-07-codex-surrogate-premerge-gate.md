# Codex pre-merge gate — lone-surrogate verifier hardening

**Date:** 2026-07-27  
**Reviewer:** Codex / OpenAI  
**Branch:** `verifier-hardening-surrogates`  
**Base:** `master` at `bca10bbac6bd5e4b094e013869ccfd0151772fdc`  
**Candidate:** `17ed19e5335629dd10decfee93d2e55331bde74a`  
**Scope:** production verifier hardening only; this review does not approve,
adopt, or activate WRT-001 / `wave@v1`.

## Verdict

**APPROVE TO MERGE.**

No P0, P1, or P2 finding remains in the candidate diff. The two commits are a
bounded maintenance fix for a real cross-implementation parser-domain defect in
published verifier paths:

1. `ff28f67` rejects unpaired UTF-16 surrogate escapes in record, trust, and
   hash-pinned genesis inputs in both Python and Go.
2. `17ed19e` closes the adjacent Python crash in policy, canonical-JSON/key-state,
   and `ski@v1` blob paths by making an unencodable decoded value a bounded
   non-canonical result.

The branch does not reinterpret existing valid bytes. Valid surrogate pairs
continue to produce the same WarrantID across implementations; escaped literal
text such as `\\uD800` remains legal and is not confused with a surrogate.

## Invariants attacked

### One byte domain

Identical authenticated JSON bytes must not decode to a Python surrogate string
but a Go `U+FFFD` replacement and then produce different identities or
authority. Lone high and low surrogates must be uniformly malformed.

### No over-rejection

Valid UTF-16 escape pairs and literal backslash-plus-`uXXXX` text must remain
accepted under the same public result in both implementations.

### Total blob paths

A surrogate-bearing JSON blob may be non-canonical or invalid, but it must not
raise through the public verifier. This includes policy parsing, canonical JSON
used by key-state/fingerprints, and `ski@v1` check parsing.

### Stable public observation

The important result is the public CLI verdict/count, not merely a helper return.
Malformed trust must fail closed; malformed record/blob inputs must produce a
bounded summary rather than a traceback.

## Independent countervectors

In addition to the committed regressions and the Kimi K3 review, this gate
exercised:

- lone `D800`, `DBFF`, `DC00`, and `DFFF`;
- valid boundary pairs and the emoji pair `D83D DE00`;
- non-surrogate neighbours `D7FF` and `E000`;
- high-surrogate followed by text, newline, a non-low `\u` escape, truncation,
  or reversed low/high order;
- lower/upper hex digits and invalid `\U`;
- two, three, and four consecutive backslashes;
- surrogate escapes embedded before/after ordinary text;
- actor keys in trust configuration;
- hash-pinned genesis input with an otherwise adoptable root;
- policy blobs, canonical JSON/key blobs, and `ski@v1` check blobs.

The focused raw-byte scanner sweep produced:

```text
SURROGATE-SCANNER: 23/23 byte-identical public results
```

Direct blob-path outcomes were bounded:

```text
ski@v1 check       → RuntimeError: malformed check blob (not JCS-canonical)
canonical JSON     → None
policy blob        → (None, invalid=True)
public PY / GO     → 1 record, 0 errors, 2 warnings; rc 0 in both
```

The warning wording differs for the malformed `ski@v1` blob, but the normative
classification, counts, and exit status agree. No contract currently requires
byte-identical prose for that warning.

## Regression results

Commands run from the candidate branch:

```text
python3 impl/warrant.py selftest
  SELFTEST: ALL PASS

./impl-go/warrant-go selftest examples
  SELFTEST: ALL PASS (7/7)

./tests/agree_check.sh
  DIFFERENTIAL: ALL AGREE (45/45)
  NEGATIVE: ALL AGREE
  SETTLEMENT: ALL AGREE
  RUNTIME-HOOK: ALL PASS
  PEDANTIC-EDGES: ALL AGREE (15/15)
```

`git diff --check master...verifier-hardening-surrogates` is clean.

## Non-blocking note

The strict record/trust/genesis paths reject lone surrogates at I-JSON decode,
while the plain JSON blob paths reject them through canonical round-trip
failure. That distinction is acceptable for this patch: both routes are total,
fail closed at the appropriate semantic layer, and agree observably. Routing
every JSON blob through one future shared strict decoder could simplify the
implementation, but is not required to merge this bugfix.

## Merge boundary

This verdict covers exactly `master..17ed19e` on
`verifier-hardening-surrogates`. It does not cover the untracked `scratchpad/`,
does not authorize merging `wrt-001-budget-spec` or
`adr-008-rev15-candidate`, and is not a substitute for any 2-of-3 governance
action required for a future runtime/specification adoption.

