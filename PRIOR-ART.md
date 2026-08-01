# Prior art record

This file records **what was publicly disclosed, when, and who else attests to
it**. It is defensive: it exists so that the formats and runtimes published here
cannot later be claimed as someone's invention, and so that a reader can check
that claim without trusting this repository.

It is not a patent filing, not legal advice, and not a claim that anything here
is patentable or unpatentable.

## What prior art actually requires

Two things, and they are routinely confused:

1. **Public availability.** The teaching had to be accessible to a person
   skilled in the art. A private file, however well timestamped, teaches nobody.
2. **A date that can be established.** Not asserted — established.

A blockchain timestamp addresses (2) alone. It says a document existed; it says
nothing about anyone being able to read it. Third-party archives address (1),
and this record uses both because either alone answers half the question.

**Git dates do not count.** `git commit --date=…` writes any date you like, and
the value is covered by the commit hash, so a forged date is internally
consistent. Every date in the manifests is labelled a *claim*. Only the
attestations below carry independent weight.

## Disclosure timeline

First public commit in both repositories: **2026-07-05**.

| Repository | Releases | Earliest | Manifest |
|---|---|---|---|
| `github.com/s0fractal/warrant` | v0.2.0 … v0.4.0 | 2026-07-05 | [`prior-art/warrant-disclosure-manifests.txt`](prior-art/warrant-disclosure-manifests.txt) |
| `github.com/s0fractal/sigma-glyph` | v0.5.0 … v0.6.6 | 2026-07-05 | [`prior-art/sigma-glyph-disclosure-manifests.txt`](prior-art/sigma-glyph-disclosure-manifests.txt) |

Each manifest lists, per release, the SHA-256 of every disclosed file, read from
git objects rather than a working tree, plus one `manifest_sha256` covering the
whole set. Regenerate and compare:

```bash
python3 tools/disclosure_manifest.py --all-tags
```

## Attestations by third parties

### Software Heritage — archival, and the public-availability half

The full git history of both repositories is archived by
[Software Heritage](https://archive.softwareheritage.org), a UNESCO-backed
archive, under permanent identifiers:

| Repository | SWHID (snapshot) | Archived |
|---|---|---|
| warrant | `swh:1:snp:c7ba55837844b5ed7259780c63e7b332cf6d1089` | 2026-07-28 |
| sigma-glyph | `swh:1:snp:51b68178f8cef14fdf02bb98412a441c5fd536a8` | 2026-07-28 |

This is the load-bearing attestation. An independent institution holds a copy of
the whole graph, so the record survives this repository being rewritten, moved,
or deleted — and it is evidence that the material was publicly retrievable, not
merely that it existed.

### OpenTimestamps — the not-after half

The manifests are timestamped into the Bitcoin blockchain via OpenTimestamps:

```bash
python3 tools/tick.py verify prior-art/warrant-disclosure-manifests.txt.tick.json.ots
ots upgrade prior-art/*.ots      # after the attestation confirms
```

Submitted 2026-07-28 to four independent calendars. This proves the manifests
existed before the confirming block — which is the direction prior art needs.

### Bitcoin entanglement — the not-before half

Each `.tick.json` carries the chain tip at the moment of stamping (block
**960017**), fetched from two unrelated operators and required to agree. A block
hash cannot be predicted, so nothing carrying it was fixed earlier.

This does **not** make anything older. It makes it unable to *claim* to be
older, which is the point: it converts a writable git date into a checkable
floor.

### Accidental corroboration — a committed build cache

`impl-go/.gocache/` was committed by mistake at `9421f02` and removed in
`2de1d17`. It is worthless as code, but each of its 454 `-a` entries carries one
field the Go build system wrote and git never saw: unix nanoseconds.

```bash
python3 tools/cache_timestamps.py 9421f02
```

```
build earliest 2026-07-07T21:49:02+00:00
build latest   2026-07-07T21:59:54+00:00   (spread 10.9 min)
git claims     2026-07-07T22:59:08+00:00   (self-asserted, writable)
consistent: commit follows the build by 59.2 min
```

An eleven-minute compile, committed an hour later the same evening. Git dates
are writable and the commit hash covers the forgery, so it is internally
consistent; these stamps are not covered by it. Forging a commit date while
keeping hundreds of nanosecond build stamps consistent with it, at a plausible
compile spread, is a different and much easier thing to get wrong.

This is **corroboration, never proof** — the cache files are as writable as
anything else, and a careful forger fixes them too. It is one weak independent
signal, it costs nothing because the bytes are already archived, and it is listed
here rather than leaned on.

It is also the reason the history is not being rewritten to purge the cache.
Removing 56 MB of junk would change every commit hash after it, voiding the
manifests above, orphaning the Software Heritage snapshots, and breaking the
sibling-repository commit pins — to destroy evidence that happens to support us.
The cache is gone from every live branch and is gitignored; that is the whole of
the cleanup that was worth doing.

## Honest limits

- **Bitcoin time is not wall-clock time.** Block timestamps are asserted by
  miners, need only exceed the median of the previous eleven, and may run up to
  two hours ahead. Block *order* is solid; the mapping to a UTC instant carries
  hours of slack. Quote intervals in blocks.
- **This is not an eIDAS qualified timestamp.** The Article 41 presumption of
  accuracy attaches to a qualified trust service provider. Bitcoin is not one. A
  QTSP bridge is tracked separately and this record does not stand in for it.
- **Anchoring now does nothing against an earlier filing.** If someone's
  priority date precedes a disclosure listed here, that disclosure is not prior
  art against them, and no amount of anchoring reorders events. What anchoring
  protects is (a) the provability of what was already public, and (b) everything
  published from here on.
- **Prior art does not prevent a patent from issuing.** It supports invalidity,
  and it helps most when an examiner can find it — which is why archival and
  indexing matter more than cryptography here.
- **Coverage is what the manifests list.** Files excluded as build artefacts are
  excluded from the claim too; the manifest is the claim's boundary.

## Reproducing this record

```bash
python3 tools/disclosure_manifest.py --all-tags     # the bytes disclosed
python3 tools/tick.py fetch                         # a fresh chain tip
python3 tools/tick.py stamp <file>                  # entangle + submit to OTS
curl -s https://archive.softwareheritage.org/api/1/origin/\
save/git/url/https://github.com/s0fractal/warrant/ | jq .
```

Nothing above requires an account, a key, or a payment.

## IETF `draft-birkholz-verifiable-agent-conversations` (VAC)

The nearest active work, and one layer up. VAC is a **record format for what an
agent session was** — messages, tool calls, tool results, reasoning entries — signed
so that the transcript offered later can be shown to be the transcript that
happened. Its known `trace-format` values are the session-log formats coding
agents already write to disk (`claude-jsonl`, `gemini-json`, `codex-jsonl`,
`cursor-jsonl`), so its subject is normalising and signing those.

Warrant sits below it: not the transcript but the **decision**, with a reason that
re-executes. The two are complementary rather than competing — a conversation
record says what was said, a warrant says what was decided and lets a stranger
recompute whether the stated reason holds.

A nine-finding implementation review of -00 is in
[`reviews-outbound/2026-08-ietf-vac-draft-00.md`](reviews-outbound/2026-08-ietf-vac-draft-00.md).
It was never sent to the authors; the file says why. One of its findings —
that a specification can name a canonicalization while admitting a value domain
that canonicalization cannot carry — turned out to describe **this** repository
too, and was fixed here before the review was published (SPEC §2, integer domain).

## Pham & Hy, *Evaluating Agentic Bioinformatics through Function–Evidence–Validation* (arXiv:2607.27556, 2026-07-30)

**Read in full — 47 pages — and recorded here because it argues against this
project more than for it.** A survey mapping 109 agentic systems and 28
evaluation resources across 128 publications in genomics, single-cell omics,
protein science, drug discovery and computational pathology, proposing a
framework that separates three things a reader is otherwise tempted to conflate:
**Function** (which workflow operations a system demonstrably performs),
**Evidence** (traceable support for its actions and claims), and **Validation**
(what assurance has actually been established).

Its Validation ladder is cumulative: `V1` demonstrated execution, `V2`
*sufficient information for replay*, `V3` task-appropriate scientific evaluation,
`V4` prospective empirical testing. That decomposition is close enough to this
project's to be worth stating: a warrant's body is Function, its `because` and
`evidence` are Evidence, and its re-executable `check` is the mechanism a `V2`
claim would need.

**What it establishes.** The gap is real and measured rather than asserted:

> most systems implement multiple Function and Evidence dimensions, yet the
> majority remain at V3. Broader operational scope therefore does not imply
> stronger scientific assurance: additional agents, tools, databases, memory
> modules, or predictive models may expand a workflow without establishing
> replayability, verification, or empirical support for its principal claim.

That is this project's thesis, arrived at independently, in another discipline,
by people who have not heard of it.

**What it does not establish, and this is the part that matters.** Across 47
pages the words *tamper*, *malicious*, *forge*, *attack*, *threat model*,
*cryptographic*, *signature*, *integrity* and *immutable* do not appear once.
`adversarial` appears three times, each about adversarial *prompts* or fabricated
identifiers used to test an agent — never about altering a record after the fact.
No in-toto, no SLSA, no RO-Crate, no W3C PROV, no OpenTelemetry.

So their *provenance* means scientific traceability for an honest researcher.
The failure they are guarding against is sloppiness, hallucination and
irreproducibility, not forgery. For that threat model, RO-Crate or W3C PROV plus
a pinned container and a workflow engine is sufficient, and signatures are
overhead. A whole discipline reached a formal statement of the problem without
feeling the need for cryptography — which is the Antigravity objection to this
project, independently confirmed from the other side.

**And the honest further weakening:** their *largest* measured gaps are
prospective empirical testing and closed-loop refinement, i.e. `V4`. Replayability
lags execution, but it is not where the biggest hole is. Anyone tempted to cite
this paper as demand for what warrant does should read that sentence first.

**The one opening it leaves.** `V4` lives in regulated domains — drug discovery,
clinical pathology — where a record acquires legal and financial weight and the
honest researcher stops being the only party with an interest in what it says.
That is where a tamper-evident record starts to differ from a merely reproducible
one. It is a hypothesis about where to look next, not something this paper
demonstrates, and it is recorded as the former.
