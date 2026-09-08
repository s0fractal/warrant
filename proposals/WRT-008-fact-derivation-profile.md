# WRT-008: Fact derivation profile — where a WPL constant came from

**Status: CLOSED — DEFERRED by its own stopping rule (§7), 2026-09-07.**
Record of the act: warrant PR #60 (`wrt-008/fact-derivation`), closure commit
`fe6b8a6` on top of the two gated revisions; the reviews are
`.triad/reviews/warrant-pr60/` (rev 1) and `.triad/reviews/warrant-pr60-rev2/`
(rev 2), Codex, each with executable probes. Two gates (rev 1 `e446596`,
rev 2 `b7ed117`), each AMEND on the binding layer:
rev 1 bound a *source file* rather than the cited check (R1); rev 2 bound the
check but its `--record` path reported `record=cited` for a null or missing
body without running a single citation check, and never compared the body's
hash to the WarrantID it was given (`.triad/reviews/warrant-pr60-rev2/`,
R1a/R1b, reproduced by CLI probes). A second AMEND on the same layer closes
this as *deferred*; that is what §7 said would happen, and it does.

**Retained as design evidence,** executable but not a CI gate,
in `proposals/wrt-008-model/`: the §1 measurement as what it is (ten authored
policies compiled, zero facts with provenance, a *classification* of 48/58 as
candidate derivable coverage); the profile shape; the closed extractor set
(`json`, `json-len`, `digest-eq`, `cmd`) with shape validated before I/O and
the RFC 6901 / RFC 8259 grammars enforced; the per-fact verdicts; the
source-to-check recompilation (R1 of rev 1 is closed by that); 55 selftest
controls and a harness with five tool mutants and the rev-1 review's five
counterexamples at exact verdicts.

**Not retained:** any claim that a record binds the profile. The CLI refuses
`--record` with `RECORD_BINDING_DEFERRED`; `bind_record` stays in the file as
the shape of the attempt, with its two holes named above. Also not retained:
the check.py entry (removed; counts recounted) and the tutorial pointer as a
live feature.

**Left open, exactly:** (P1) a record envelope of `{}`, `{"body":null}` or
`[]` yields `body=None`, which the checker reads as "no record given" while
the CLI had already labelled the run `cited`; (P2) `records/<wid>.json` is
trusted by filename, the canonical body hash is never compared to `<wid>`.
Both need the repository's own canonicalization path and typed refusals;
neither needs a settlement engine. Two bounded notes from the same review:
`digest-eq` facts are exempt from evidence membership (two addresses compared,
no bytes read) and §2 said "every `from` blob" without that exception; and
"validated before any blob is read" means before *evidence* is read (the
profile and the source are read first).

**Reactivation condition:** a successor that starts from the retained model,
closes P1 and P2 with the probes in `warrant-pr60-rev2/probes.py` turned into
exact typed-refusal assertions, and is gated by a reviewer who did not write
it. Or, the smaller sibling this measurement pointed at first: `count` /
`all` / `any` over a pinned list and a digest fact kind in WPL, which change
the compiler and are a separate proposal.

**Lesson kept on purpose.** Twice the label was wider than the predicate: rev
1 said "baked into the term" while checking a source file; rev 2 said
`record=cited` before binding had run. Both were caught by a reviewer with a
seven-line probe. A tool must consume the address of the artifact it names,
and must set a state only after the check that state names has passed.

Closed by Claude Fable 5.1 at the owner's decision to follow the stopping
rule, 2026-09-07. A closure is a governance act, not a gate verdict, and it
adopts nothing (AGENTS.md rules 3–4). The rev-2 text follows as history.

---

**Status (historical):** DRAFT rev 2 (2026-09-07) — **design plus a running demonstration**, after the Codex AMEND of rev 1 (`.triad/reviews/warrant-pr60/REVIEW.md`: R1 the profile bound a source, not the cited check; R2 extractor shape was validated after I/O; R3 the JSON and pointer grammars admitted `NaN` and `~2`; R4 addresses admitted a trailing newline; R5 the coverage number was a manual classification presented as a measurement). Each is closed below and burned in `tests/fact_derivation.py` §D.
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
| rules that compile once derivation is pushed to an extractor (**measured**: compiled) | 10 of 10 |
| facts that carry any provenance today | 0 of 58 |
| facts **classified by the author** as derivable from cited evidence by a pinned extractor (candidate coverage, not executed derivations) | 48 of 58 (46 without the two date-arithmetic facts) |
| … of which the classified derivation is `count` / `all` / `any` over a finite list | 15 |
| … of which it is equality of two digests, which WPL refuses (>32 bytes) | 5 |
| decisions whose WHY, as the author restated them, includes a judgment no rule reaches | 5 of 10 |

The two measured facts are: every rule compiled, and no fact carried
provenance. The coverage figures are the author's classification of what a
pinned extractor *could* read, not extractions that were run; this profile is
the tool that would turn that classification into a checked result, and its
own verdicts are the measurement that is still missing. Read within this
sample: the deficit reviewers see looks mostly like **provenance of
operands** (every `fact` is an assertion baked into the term,
`docs/authoring-checks.md` §8) and, for about a third of the classified
derivations, two constructs WPL lacks (§7). That five of ten restated
decisions left a judgment outside the rule says the author found no rule for
it, not that none exists.

## 2. The profile

A blob, JCS-canonical, integers only, cited in the record's `evidence`:

```json
{ "profile": "warrant.fact-derivation@v0",
  "check":         "<hex64 ski@v1 check blob>",
  "policy_source": "<hex64 WPL source blob>",
  "facts": {
    "<fact name>": { "from": "<hex64 evidence blob>",
                     "via":  <extractor>,
                     "value": <bool | int | string> } } }
```

`check` is the ski@v1 check blob the profile describes and `policy_source` the
WPL text it was compiled from. A profile-aware tool **recompiles the source
and requires the result to be exactly that check** (`term` and `expect`;
`CHECK_TERM_MISMATCH` otherwise; compilation is deterministic, SA-11), so
"the value baked into the term" is a checked relation and not a claim about a
source file (rev-1 R1). Each listed fact names the evidence blob its value was
read from, the extractor that read it, and the value — which MUST equal the
literal in the source (`PROFILE_VALUE_NOT_IN_TERM`). A fact absent from the
profile is simply **ASSERTED**, as every fact is today.

Given a WarrantID (`--record`), the tool also requires the record to cite the
check as a `ski@v1` reason and to list the profile, the source, every `from`
blob and every `cmd` program in `evidence` (`RECORD_*_NOT_CITED`). It does
not verify signatures; that remains `warrant verify`'s job, and the summary
says so. Without `--record` the summary reads `record=unverified`.

Extractors are a closed set, and the whole extractor shape — kind, fields,
type compatibility with the fact, pointer syntax — is validated **before any
blob is read** (rev-1 R2): a malformed extractor is the same refusal whether
its evidence is present or missing. v0 has four:

| `via` | derives | trust |
| --- | --- | --- |
| `{"kind":"json","pointer":"/a/b"}` | the RFC 6901 pointer's value (only `~0`/`~1` escapes; anything else is `POINTER_INVALID`) in a strict JSON evidence blob (RFC 8259 with RFC 7493 strictness: UTF-8, no duplicate keys, no `NaN`/`Infinity`, no lone surrogates; otherwise `MALFORMED`) | the tool's own reader; no execution |
| `{"kind":"json-len","pointer":"/items"}` | the length of the array at the pointer (an `int`) | same |
| `{"kind":"digest-eq","other":"<hex64>"}` | `from == other` (a `bool`); no bytes are read | none needed; identity of two addresses |
| `{"kind":"cmd","program":"<hex64>","args":[…]}` | `python3 <program> <evidence path> <args…>`, stdout one strict JSON literal | **container trust** (SPEC §14): executed only under `--execute-cmd`, otherwise `UNRUN`. The tool runs the **host** `python3` with the caller's environment in a temporary directory and provides no container; isolation is the caller's responsibility, and the program hash pins the program, not the interpreter or its environment |

The first three cover D-field, the count part of D-quant, and D-hash from §1
without running anything the filer wrote. `cmd` covers the rest at exactly the
trust `cmd@v1` already has; it is never run by default because a program that
arrived in a record is not thereby safe to run.

## 3. Verdicts, per fact, never per document

| verdict | meaning |
| --- | --- |
| `DERIVED` | re-derived value equals the constant baked into the term |
| `DIVERGED` | re-derived value differs: **the term contradicts its own cited evidence**; fails the run |
| `ASSERTED` | no derivation listed |
| `UNRESOLVED` | evidence or program blob absent, or not hashing to its address, or the pointer names nothing |
| `UNRUN` | a `cmd` derivation not executed |
| `MALFORMED` | the evidence has the wrong shape for the fact's type (a float for an `int`, a string over 32 bytes, a duplicate JSON key, a non-JSON constant); fails the run |

`DIVERGED` and `MALFORMED` exit 1; `ASSERTED`, `UNRESOLVED` and `UNRUN` are
reports at exit 0, so a consumer must read the per-fact lines, not the exit
code. The summary line counts facts, states `check=bound`, states whether a
record was cited, and ends `semantic-credit=none`: `DERIVED` binds a constant
to bytes and a pinned extractor; it does not make the bytes true. Shape
problems in the profile itself (an address that is not exactly 64 lowercase
hex characters, an unknown or malformed extractor, a fact the source does not
declare, a source that is not WPL or does not compile to the cited check) are
typed refusals with no per-fact report at all.

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
   contain that value, or whose source is not the cited check, or whose
   pointer is not RFC 6901 syntax (the five tool mutants in
   `tests/fact_derivation.py` §B each make the selftest fail, and §D replays
   the rev-1 review's counterexamples with exact verdicts; if one survives,
   this section is wrong).
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
