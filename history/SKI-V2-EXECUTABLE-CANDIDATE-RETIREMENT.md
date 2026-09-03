# `ski@v2` executable candidate — retirement record

**Status:** EXECUTABLE_BYTES_WITHDRAWN  
**Protocol tag:** RESERVED, NOT ADMITTED  
**Last trunk revision shipping the candidate module:** `4cb3c8f6e1f2bb66524f3ce7df707e725b296781`

Warrant briefly shipped `impl/sigma_glyph_v06.py` as executable candidate bytes
for a future `ski@v2`. The specification admitted the tag in no body version,
so no valid record could invoke those bytes. Shipping and rebuilding the
candidate nevertheless enlarged the installed artifact and its provenance gate.

The active wheel now contains only the evaluator for admitted `ski@v1`.
`ski@v2` remains reserved in SPEC §3.2 and §13 so its name cannot be reused or
silently redefined. The removed candidate is still addressable in Git:

- path: `impl/sigma_glyph_v06.py`
- sha256: `55072bc02e63987898fd60125e8bb5b14a6233b081ba158e0253755652323825`
- source semantics: Σ-GLYPH Book I 0.6.0
- former provenance manifest: `trust/sigma-evaluator-provenance.json`

## Preserved invariants

- Every admitted runtime tag maps to exactly one evaluator digest.
- Evaluator bytes are hashed before import; mismatch or an unknown tag refuses
  without fallback.
- `ski@v1` stays byte-identical and replays offline.
- `ski@v2` remains invalid in all admitted body versions.

## Declared loss

Internal tooling can no longer load `ski@v2` ahead of its admission. That was a
candidate convenience, not an admitted Warrant function. A future body 0.3 must
bring its evaluator, negative vectors, fingerprint tuple and admission rule in
one explicit act.
