# GOV-001: Settlement at scale — re-litigation, multi-root stores, keys

**Status:** PROPOSED (2026-07-07) — candidate normative text for SPEC v0.3; needs the standard adversarial review gate before adoption
**Origin:** Kimi k2.6 governance audit of the sigma-glyph warrant store (issues [#5](https://github.com/s0fractal/warrant/issues/5), [#6](https://github.com/s0fractal/warrant/issues/6), [#7](https://github.com/s0fractal/warrant/issues/7)) + Opus 4.8 review F3 (binding). Written by the maintainer; every rule below is stated so that a verifier can check it mechanically.

## Design stance

One principle resolves most of the open questions: **in this format, an
argument is admissible when it is executable.** Prose persuades; checks
settle. v0.2 already lives by this for decisions (`ski@v1`, filing-time
re-runs); v0.3 extends it to the *governance* of decisions.

## 1. Re-litigation standard (SPEC §7 replacement) — closes #5

Current text: re-opening a settled subject requires evidence "absent from
the entire prior tunnel." Two failure modes at scale: evidence
foreclosure by volume (dump blobs early, foreclose everything) and
interpretation lock-in (a new argument over an old blob is formally
inadmissible). Precedent already broke the strict reading: sigma-glyph
ADR-004 was opened over a settled point citing the already-shipped
artifact.

**Candidate §7 text:**

> A settling warrant's **tunnel** is the transitive closure of its
> `prior`, `under` and `subject` links. A blob **forecloses** only the
> claims that some reason in the tunnel actually makes about it: mere
> presence in an `evidence` array forecloses nothing.
>
> A re-litigation warrant MUST carry at least one of:
> (a) an evidence hash absent from the tunnel, or
> (b) a **new demonstrable consequence** of evidence already present: a
> `check` reason (any runtime) that does not appear in the tunnel and
> whose re-run verdict contradicts or materially qualifies the settled
> claim.
>
> Prose alone never re-opens settlement. Tools SHOULD refuse to file
> re-litigation warrants that carry neither (a) nor (b); verifiers
> SHOULD flag them `WARN: re-litigation cites nothing new`.

Rationale: (b) is the codified precedent — "new interpretation" is
admissible exactly when it compiles to something re-runnable. This also
dissolves foreclosure-by-volume: dumped-but-unreasoned blobs foreclose
nothing, and even reasoned blobs stay open to *new checks* over them.

Meta-rule (Kimi's ossification point): §7 itself is challengeable under
(b) — a check demonstrating that the rule produces a wrong settlement
(e.g. a divergence the rule forces verifiers to accept) is admissible
evidence against the rule. Constitutions that can only be amended from
outside die outside; this one accepts executable amendments.

## 2. Multi-root stores (new SPEC §9) — closes #6

The sigma-glyph store is already a two-root DAG. v0.2 neither forbids
nor governs this.

**Candidate §9 text:**

> A store is a DAG. A **root** is a record with empty `prior`. A root is
> **legitimate** iff its actor's key is bound in the store keyring (§5)
> at filing time, OR a warrant in an existing legitimate root `accept`s
> the new root's first record as `subject` (adoption). Verifiers MUST
> report roots that are neither: `WARN: unadopted root`.
>
> **Cross-root scope:** foreclosure and settlement are **per-tunnel**,
> never store-global. A record in root B is "in the tunnel" of a
> settlement in root A only if reachable from the settling warrant via
> `prior`/`under`/`subject` links. Two roots that never reference each
> other are separate jurisdictions sharing a blob store — by design.
>
> **Missing blobs, split by function:** for *verification*, an
> unresolvable referenced blob makes the warrant `unverifiable`
> (status-quo caution — an unverifiable warrant settles nothing new).
> For *foreclosure*, an unresolvable blob forecloses nothing (challenger
> fairness — what cannot be read cannot have been reasoned over). One
> fact, two consequences, no ambiguity.

## 3. Keys: binding, rotation, thresholds (SPEC §5 v0.3) — closes #7

v0.2 has one Ed25519 key and no keyring; F3 (Opus) added the honest
`binding unverified (no keyring)` warning. v0.3 gives the warning
something to resolve against.

**Candidate §5 additions:**

> A store MAY contain `keyring.json`: a map `actor id → [ {key,
> since_ts, until_ts?} ]`. With a keyring configured, verifiers MUST
> report each signature as `bound` (key listed and within window) or
> `unbound`; without one, the v0.2 warning stands.
>
> **Rotation is a warrant:** `accept` whose subject is the new key blob,
> signed by BOTH the outgoing and incoming key. **Revocation is a
> warrant:** `supersede` of the rotation warrant that introduced the
> key, signed by the outgoing key or by quorum (below). Keyring entries
> derive mechanically from these records — the keyring file is a cache,
> the warrants are the truth.
>
> **Thresholds are policy:** a policy blob MAY declare
> `min_sigs: M of [actor ids]`. Records filed `under` it MUST carry M
> valid bound signatures; verifiers MUST check this. Settlement-grade
> policies SHOULD require M ≥ 2 once more than one actor exists.

Single-key compromise (Kimi's scenario) under these rules: the attacker
can file, but cannot rotate silently (needs both keys' signatures on a
rotation), cannot foreclose (dumped blobs foreclose nothing per §7), and
every forged record dies retroactively when the true holder files a
quorum revocation — verifiers re-derive the keyring and every signature
after `until_ts` reports unbound.

## Compatibility

All three sections are additive: every v0.1/v0.2 record remains valid;
stores without keyrings keep today's behavior plus today's warnings. New
verifier obligations (unadopted-root WARN, per-tunnel scope, threshold
checks) activate only when the corresponding structures exist.

## Review gate asks

1. Attack §7(b): construct a "new check" that is a trivial restatement
   of a tunnel check (same verdict, cosmetic difference). Does the text
   as written admit it? Should novelty be defined as *different verdict
   or different claim*, not different bytes?
2. Attack §9 adoption: can a hostile legitimate root adopt a store's
   worth of spam roots? Is `WARN` enough, or should unadopted roots be
   excluded from settlement entirely?
3. Attack §5 rotation: outgoing key is compromised — the attacker can
   co-sign a rotation to a key they control. Is the both-keys rule
   strictly worse than quorum-only for stores with ≥2 actors?
