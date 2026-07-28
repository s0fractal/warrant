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
