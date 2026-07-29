# Names, and what may be called conformant

The code here is MIT and the specification texts are CC-BY-4.0. Fork them,
sell them, embed them, close your changes — all fine, and deliberately so: a
format that hopes to become a standard cannot be one people need permission to
implement.

Copyright, however, protects none of what actually matters to a standard. It
does not stop a vendor shipping a divergent implementation, calling it
"Warrant", and letting the difference propagate until two things called by one
name no longer agree on a verification outcome. That failure has a name —
embrace, extend, extinguish — and copyleft does not prevent it either; the
industry's working defence has always been the **name**, not the licence.

So the licences stay permissive and the names carry the obligation.

## The rule

**"Warrant", "Σ-GLYPH", "warrant-verify" and "ski@v1" may be used to describe an
implementation only while that implementation passes the published conformance
vectors it claims to implement.**

- `tests/spec_conformance/vectors.json` and the negative vectors, for Σ-GLYPH
  Book I;
- `warrant conformance` and `tests/negative.py`, for the Warrant format.

Passing is not an application to anyone. Run the vectors, publish which suite
and which revision you ran, and say so. Nobody grants this and nobody can
withhold it — the check is public, offline, and the same for everyone.

Everything else is unrestricted. Say your product "works with Warrant records",
"reads Evidence Packs", "is based on Σ-GLYPH" — those are statements of fact and
need no permission. Compatibility claims are welcome; conformance claims are the
one thing tied to running the vectors.

## Divergence is allowed. Quiet divergence is not.

Fork the format, change the hashing, define a different settlement rule. That is
legitimate and Book III already treats permanent jurisdictional divergence as
designed-for rather than pathological. Give it your own name, state the ancestor
by hash — `spec/ANCHORS.txt` exists so a fork can be precise about what it forked
— and the ecosystem stays legible.

What is not allowed is a divergent implementation wearing the original name,
because the whole promise of the format is that two independent verifiers reach
the same verdict on the same bytes. A name that no longer predicts that promise
has stopped being a name and become a liability for everyone still keeping it.

## Enforcement, honestly

No trademark is registered. This is a published usage policy, which is weaker
than a registration and stronger than nothing: it establishes the terms in
public, dated, and archived (`PRIOR-ART.md`), so a later claim of "we did not
know" is not available.

If the format is adopted anywhere that matters, registration in the relevant
jurisdictions becomes worth its cost, and the neutral holder should be a
foundation rather than an individual — the same reasoning that keeps the
specification CC-BY rather than proprietary.

## Licence boundaries in the wider stack

Deliberate, and worth stating because it decides whether an enterprise can adopt
this at all:

- **`warrant`** — MIT. One runtime dependency, `cryptography` (Apache-2.0 OR
  BSD-3-Clause), for Ed25519. The Go implementation declares no third-party
  modules and the Rust one no crates, so a reviewer who will not accept even a
  permissive dependency has two implementations that carry none. Nothing
  copyleft is reachable from any of the three. This is a requirement rather than
  a happy accident, and it is checked before it is claimed — an earlier draft of
  this file said "pure standard library", which was simply wrong.
- **`sigma-glyph`** — MIT for implementations, CC-BY-4.0 for the Books.
- **`trinity` / `agentseal`** — AGPL-3.0-or-later. That is the product layer and
  it stays there. AGPL in the verifier's dependency path would make the verifier
  unadoptable at most enterprises — many ban it by policy without discussion —
  and an unadoptable verifier defeats the purpose of publishing a format.

The rule that keeps this straight: **anything a third party must run in order to
check our claims is permissively licensed and free of copyleft, transitively.**
Anything that is a product built on top may be licensed however it is worth
licensing. "Dependency-free" is a stronger property that two of the three
implementations happen to have; it is not the rule, and stating it as the rule
would have made this file untrue about itself.
