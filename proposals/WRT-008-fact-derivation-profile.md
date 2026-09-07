# WRT-008: Fact derivation profile — where a WPL constant came from

**Status:** DRAFT rev 1 (2026-09-07) — **design plus a running demonstration.**
No SPEC edit, no body schema change, no change to `warrant verify`, to the
`ski@v1` check blob or to WPL syntax. The profile is an additive blob cited in
`evidence`; `tools/fact_derivation_check.py` reads it, and
`tests/fact_derivation.py` burns each verdict with a mutation. Adoption
requires an adversarial gate; nothing here is adopted.

Written by Claude Fable 5.1 at the owner's decision of 2026-09-07 (\"роби\"),
after the experiment in §1. A gate verdict is evidence, not adoption
(AGENTS.md rules 3–4).

## 1. What was measured, and what it said

Reviewer models call WPL's poverty a defect for expressing the WHY of a
decision. Before extending the language, ten real decisions from this stack
were restated as *extractor + WPL* and compiled with the real compiler: a
reject for implementation divergence (b56c6ae8), the SPEC v0.3 implementation
gate (d675f8fe), a GOV-001 gate adjudication (8fa57925), sigma-glyph's v0.7.0
threshold adoption (0e634c17), TV-10 as a `ski@v1` reason (14d413f2), the Air
Canada refusal, the agent PR gate on a real report, the Book III implementation
gate (ac7596c6), Codex's merge of sigma-glyph PR #52, and a refund call under
`demos/mcp-commerce`. The run is local coordination evidence
(`.triad/experiments/wpl-decomposition-001/`, reproducible with its `run.py`),
not a repository artifact; its numbers are reproduced here.

| finding | number |
| --- | --- |
| rules that compile once derivation is pushed to an extractor | 10 of 10 |
| facts that carry any provenance today | 0 of 58 |
| facts deterministically derivable from cited evidence by a pinned extractor | 46 of 58 (80%) |
| … of which the derivation is `count` / `all` / `any` over a finite list | 15 |
| … of which the derivation is equality of two digests, which WPL refuses (>32 bytes) | 5 |
| decisions whose WHY includes a judgment no rule reaches (severity, adequacy) | 5 of 10 |

So the deficit reviewers see is mostly **provenance of operands**, not
expressiveness: every `fact` is an assertion baked into the term
(`docs/authoring-checks.md` §8), while four in five could have been read from
bytes the record already cites. Two constructs WPL lacks account for a third
of the derivations; they are a separate, smaller proposal (§7). Judgment is
outside any rule and stays there.

## 2. The profile

A blob, JCS-canonical, integers only, cited in the record's `evidence`:

```json
{ "profile": "warrant.fact-derivation@v0",
  "policy_source": "<hex64 WPL source blob>",
  "facts": {
    "<fact name>": { "from": "<hex64 evidence blob>",
                     "via":  <extractor>,
                     "value": <bool | int | string> } } }
```

`policy_source` is the WPL text the check was compiled from. Each listed fact
names the evidence blob its value was read from, the extractor that read it,
and the value — which MUST equal the literal in the source (the profile cannot
claim a derivation for a constant the term does not bake in; that is a
refusal, `PROFILE_VALUE_NOT_IN_TERM`). A fact absent from the profile is
simply **ASSERTED**, as every fact is today.

Extractors are a closed set. v0 has four:

| `via` | derives | trust |
| --- | --- | --- |
| `{"kind":"json","pointer":"/a/b"}` | the RFC 6901 pointer's value in a strict-JSON evidence blob | the tool's own reader; no execution |
| `{"kind":"json-len","pointer":"/items"}` | the length of the array at the pointer (an `int`) | same |
| `{"kind":"digest-eq","other":"<hex64>"}` | `from == other` (a `bool`); no bytes are read | none needed; identity of two addresses |
| `{"kind":"cmd","program":"<hex64>","args":[…]}` | `python3 <program> <evidence path> <args…>`, stdout one JSON literal | **container trust** (SPEC §14): executed only under `--execute-cmd`, otherwise `UNRUN` |

The first three cover D-field, the count part of D-quant, and D-hash from §1
without running anything the filer wrote. `cmd` covers the rest at exactly the
trust `cmd@v1` already has; it is never run by default because a program that
arrived in a record is not thereby safe to run.

## 3. Verdicts, per fact, never per document

| verdict | meaning |
| --- | --- |
| `DERIVED` | re-derived value equals the constant baked into the term |
| `DIVERGED` | re-derived value differs: **the term contradicts its own cited evidence**; the only verdict that fails the run |
| `ASSERTED` | no derivation listed |
| `UNRESOLVED` | evidence or program blob absent, or not hashing to its address, or the pointer names nothing |
| `UNRUN` | a `cmd` derivation not executed |
| `MALFORMED` | the evidence has the wrong shape for the fact's type (a float for an `int`, a string over 32 bytes, a duplicate JSON key) |

The summary line counts facts and ends `semantic-credit=none`. `DERIVED` binds
a constant to bytes and a pinned extractor; it does not make the bytes true.
Shape problems in the profile itself (unknown extractor, a fact the source
does not declare, a source that is not WPL) are typed refusals with no
per-fact report at all.

## 4. Relation to WRT-004 (reason-binding, on branch `papers/the-reason-runs-again`)

WRT-004's L2 binds each fact to an evidence *item* `{fact, type, value}`: a
named, hash-pinned assertion a disputant can point at. This profile binds a
fact to a *derivation* from a cited blob. They compose: a record may carry
both, WRT-004 answering "which evidence item does this constant stand on" and
this one "how was the constant read from it". Neither is a base-grade rule;
both are reports until a SPEC grade says otherwise. WRT-004's identifier
collision with the closed verify-report WRT-004 is noted in `MAP.md`; this
proposal takes a fresh number rather than adding to it.

## 5. What this does not establish

- **Truth.** A `DERIVED` fact is a constant read from bytes by a pinned
  reader. The bytes may be wrong; the format's answer to that is a
  counter-warrant against the evidence blob, which is now addressable per fact.
- **Container-free execution.** `cmd` derivations prove to whoever trusts the
  runner, exactly as `cmd@v1` reasons do.
- **The policy's merit** (NG-4) or the subject–fact relation (WRT-004 §4).
- **A second implementation.** The reader of `json` pointers and the
  comparison of literals live in one Python tool; parity is the same unmet
  independence gap the rest of the project names.

## 6. Falsifiers

1. A profile that reads `DERIVED` for a fact whose cited evidence does not
   contain that value (the three tool mutants in `tests/fact_derivation.py`
   §B each make the selftest fail; if one survives, this section is wrong).
2. A profile whose `value` differs from the term's literal and is not refused.
3. A `cmd` derivation executed without `--execute-cmd`.
4. A blob whose bytes do not hash to the cited address being read as evidence.
5. A repeat of §1 on a different corpus where D-field + D-quant + D-hash fall
   well below half of the facts: then provenance is not the deficit and this
   profile is the wrong lever.

## 7. Not decided here, and the stopping rule

- **`count` / `all` / `any` over a pinned finite list, and a digest fact kind
  compared by identity** inside WPL: 20 of 58 derivations in §1. A separate
  proposal, because it changes the compiler and its cost table; this profile
  changes neither.
- **Syntax.** `fact x: int from <blob> via json "/x"` in WPL source would be
  nicer than a sidecar. rev 1 keeps the compiler untouched so that the ski
  blob, its tests and every pinned `atp` stay exactly as they are; a later
  revision may fold the sidecar into syntax once the shape has survived a
  gate.
- **Stopping rule.** As WRT-007 §6: a second AMEND on the same layer closes
  this as deferred with §1's measurement retained. The measurement is the
  part worth keeping either way.
