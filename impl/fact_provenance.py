#!/usr/bin/env python3
"""fact_provenance — `warrant.fact-provenance@v0`, the WRT-010 reference profile.

WHAT THIS IS FOR
----------------
A WPL fact is a literal, and `docs/authoring-checks.md` §8 says honestly that
nothing about it is proven. That is right for an **observation** — someone
looked at the world and wrote a number, and no cryptography makes an
observation true.

It is needlessly weak for the other kind. When a fact's value is the *answer of
a prior decision*, it does not need to be believed: it needs to be re-derived.
The term is already content-addressed, budget-bounded and re-runnable by
anyone, so the value can be recovered rather than trusted.

Without that distinction decisions do not compose: an author who builds on a
previous decision retypes its answer as a literal, and a retyped literal is
indistinguishable from an invention. This module makes the difference
mechanical.

WHAT IT IS NOT
--------------
* It does **not** make an observed fact true. Nothing can. It only stops an
  observation from being typeset like a derivation.
* It does **not** change SPEC §6, §7 or `ski@v1`. This is an OPTIONAL profile
  over blobs a base verifier ignores. A record verifies exactly as before.
* It does **not** establish that a cited decision was *authorized*. Re-running a
  term proves what the term computes, never that its author had standing.
* Provenance **never changes the term.** A source with `from` clauses compiles
  to byte-identical output. `tests/fact_provenance.py` enforces it.

THE FOUR STATES
---------------
Per SPEC §6(7)'s rule that "re-ran and matched" and "was not executed" must not
be observationally equivalent, a derived fact resolves to exactly one of:

    derived       re-ran; the cited decision's answer equals the pinned value
    contradicted  re-ran; the answer DIFFERS from the pinned value        (ERR)
    underived     could not re-run: missing record/blob, over budget,
                  ambiguous reason, non-boolean outcome        (WARN / settle ERR)
    stale         derivation reproduces, but the cited warrant has been
                  SUPERSEDED                                   (WARN / settle ERR)

`stale` is the reason the profile earns its keep. When a leaf observation is
later shown false and the affected decision is superseded under §7, every
downstream policy that derived a fact from it reports `stale` — offline, with
no registry, no notification service, and nobody remembering the dependency
existed. Revocation propagates because the dependency is written down in a form
a machine re-walks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import policy_lang as pl                      # noqa: E402
import warrant as w                           # noqa: E402

PROFILE = "warrant.fact-provenance@v0"

DERIVED = "derived"
CONTRADICTED = "contradicted"
UNDERIVED = "underived"
STALE = "stale"
ATTESTED = "attested"

#: Record-level completeness (§5.2). These are NOT fact states: they say
#: whether the profile could see all of a record's provenance, which is a
#: different question from whether each derivation holds.
COMPLETE = "complete"
NOT_APPLICABLE = "not-applicable"
INCOMPLETE = "incomplete"

#: States a checker MUST NOT report as success.
BAD_STATES = (CONTRADICTED, UNDERIVED, STALE)

#: `contradicted` is the citing record's own defect (it pinned a value its own
#: cited source refutes), not a disagreement with a third party, so it is an
#: ERR. The others are WARN in base grade and ERR under settlement grade.
ERR_STATES = (CONTRADICTED,)
SETTLEMENT_ERR_STATES = (CONTRADICTED, UNDERIVED, STALE)


class ProvenanceError(Exception):
    """The provenance document itself is malformed or does not describe the
    check it names. This is a refusal, never a finding about a fact."""


# --------------------------------------------------------------- Church pair
_CHURCH = None


def church_hashes():
    """(true_hex, false_hex) — the canonical Book I node hashes a WPL check
    reduces to. Derived by compiling two trivial sources through the real
    compiler and oracle rather than hard-coded, so they cannot drift from the
    evaluator this package is pinned to."""
    global _CHURCH
    if _CHURCH is None:
        t = pl.compile_source("check true")
        f = pl.compile_source("check false")
        assert t.result is True and f.result is False
        _CHURCH = (t.doc["expect"], f.doc["expect"])
    return _CHURCH


def church_bool(node_hex):
    """Map a result NodeHash to a Python bool, or None if it is not a Church
    boolean. `None` is a refusal (`underived`), never a coerced value."""
    t, f = church_hashes()
    return True if node_hex == t else False if node_hex == f else None


# ------------------------------------------------------------------ emission
def build_doc(compiled, check_hex, source_hex):
    """Build the provenance document for one compiled WPL check.

    Every fact of the check is described — omission is the failure mode the
    completeness rule exists to stop, so this function cannot produce a partial
    document."""
    facts = {}
    for name, f in compiled.program.facts.items():
        if f.source is None:
            facts[name] = {"kind": "observed", "value": f.value}
        else:
            wid, chk = f.source
            entry = {"kind": "derived", "value": f.value, "from": wid}
            if chk:
                entry["check"] = chk
            facts[name] = entry
    return {"provenance": PROFILE, "check": check_hex, "source": source_hex,
            "facts": facts}


def doc_bytes(doc):
    """JCS-canonical bytes, the same canonicalization every other blob uses."""
    return w.canon(doc)


def put_doc(store, compiled, check_hex, source_hex):
    """Store the provenance document; returns its blob hash."""
    return store.put_blob(doc_bytes(build_doc(compiled, check_hex, source_hex)))


def has_derived(compiled):
    return any(f.source is not None for f in compiled.program.facts.values())

# ------------------------------------------------------------------ checking
#: Bounds on transitive propagation (§5.1). Hitting either is reported as
#: `underived` with a reason, never as success — an unwalked dependency is not
#: a walked one.
MAX_DEPTH = 32
MAX_RECORDS_WALKED = 512


class Finding:
    __slots__ = ("fact", "kind", "state", "detail", "actor")

    def __init__(self, fact, kind, state, detail="", actor=None):
        self.fact, self.kind, self.state = fact, kind, state
        self.detail = detail
        # `actor` is the id the record NAMES for itself. It is bound to the
        # record's identity (the body recomputes to its WarrantID, §5.3) and to
        # nothing else: this profile verifies no signature and reads no
        # keyring, so it establishes neither that the record was signed by that
        # actor nor that the key is theirs. That is SPEC §5.1's bound/unbound
        # question and it belongs to `warrant verify` with a trust
        # configuration. Reporting a name as if it were an attestation is the
        # label this field must not be allowed to become.
        self.actor = actor

    @property
    def ok(self):
        return self.state not in BAD_STATES

    def level(self, settlement=False):
        bad = SETTLEMENT_ERR_STATES if settlement else ERR_STATES
        if self.state in bad:
            return "ERR"
        return "WARN" if self.state in BAD_STATES else None

    def __repr__(self):
        d = f" ({self.detail})" if self.detail else ""
        return f"{self.fact}: {self.state}{d}"


class RecordResult:
    """What the profile can say about ONE record.

    `status` distinguishes three things a single (findings, errors) pair used
    to conflate, which is how a vanished provenance document read as "nothing
    to check" (review F3):

        COMPLETE        every cited evidence blob resolved and was
                        address-intact; the provenance below is all of it
        NOT_APPLICABLE  everything resolved, and this record cites no
                        provenance document (a legacy record, legitimately)
        INCOMPLETE      some cited evidence is missing or its bytes do not
                        hash to the address citing them, so the ABSENCE of a
                        provenance document cannot be told from its LOSS
    """
    __slots__ = ("wid", "findings", "refusals", "status")

    def __init__(self, wid, findings, refusals, status):
        self.wid, self.findings = wid, findings
        self.refusals, self.status = refusals, status

    @property
    def ok(self):
        return (self.status != INCOMPLETE and not self.refusals
                and all(f.ok for f in self.findings))

    def __iter__(self):
        """Kept tuple-compatible for callers that unpack (findings, refusals);
        `status` is deliberately not in the tuple so a caller that ignores it
        cannot silently read INCOMPLETE as COMPLETE."""
        return iter((self.findings, self.refusals))


def _validate_doc_shape(doc):
    if not isinstance(doc, dict):
        raise ProvenanceError("provenance document is not an object")
    if doc.get("provenance") != PROFILE:
        raise ProvenanceError(
            f"not a {PROFILE} document (provenance={doc.get('provenance')!r})")
    for key in ("check", "source", "facts"):
        if key not in doc:
            raise ProvenanceError(f"provenance document has no {key!r}")
    if not w._is_hex64(doc["check"]) or not w._is_hex64(doc["source"]):
        raise ProvenanceError("`check` and `source` must be hex64 blob hashes")
    if not isinstance(doc["facts"], dict):
        raise ProvenanceError("`facts` must be an object")
    allowed = {"kind", "value", "from", "check"}
    for name, e in doc["facts"].items():
        if not isinstance(e, dict):
            raise ProvenanceError(f"fact {name!r} entry is not an object")
        extra = set(e) - allowed
        if extra:
            raise ProvenanceError(
                f"fact {name!r} carries unknown member(s) {sorted(extra)}; the "
                "document is a closed schema")
        if e.get("kind") not in ("observed", "derived"):
            raise ProvenanceError(
                f"fact {name!r} has kind {e.get('kind')!r}, expected "
                "'observed' or 'derived'")
        if "value" not in e:
            raise ProvenanceError(f"fact {name!r} has no value")
        if e["kind"] == "derived":
            if not w._is_hex64(e.get("from", "")):
                raise ProvenanceError(
                    f"derived fact {name!r} has no valid `from` WarrantID")
            if "check" in e and not w._is_hex64(e["check"]):
                raise ProvenanceError(
                    f"derived fact {name!r} has a malformed `check` selector")
            if not isinstance(e["value"], bool):
                raise ProvenanceError(
                    f"derived fact {name!r} is not a bool; a ski@v1 check "
                    "answers one Church boolean")
        elif "from" in e or "check" in e:
            raise ProvenanceError(
                f"observed fact {name!r} carries a derivation reference")


def _intact_blob(store, h, what):
    """Read a blob only after its bytes hash to the address citing them.

    `has_blob` checks the NAME shape and that a regular file is there; it does
    not check the address. Using bytes stored under an address they do not hash
    to would let a substituted file be credited as provenance (review F2), so
    every read on this path goes through here."""
    if not store.has_blob(h):
        raise ProvenanceError(f"{what} blob {h[:12]}… is not in the store")
    if not store.blob_intact(h):
        raise ProvenanceError(
            f"{what} blob {h[:12]}… does not hash to the address citing it; "
            "the store is not content-addressed at this entry")
    return (store.blobs / h).read_bytes()


def _record_at(recs, wid):
    """Return the record stored under `wid`, only if its canonical body really
    recomputes to `wid`.

    `all_records` keys records by FILE NAME. A body swapped under an existing
    name keeps that name and changes what it says, so a value derived from it
    would be credited to a decision that never made it (review F2; also the
    P2 left open by this proposal's earlier disposition, see §0)."""
    env = recs.get(wid)
    if env is None:
        return None, f"cited warrant {wid[:12]}… is not in the store"
    body = env.get("body")
    if not isinstance(body, dict):
        return None, f"cited record {wid[:12]}… has no body object"
    try:
        got = w.warrant_id(body)
    except Exception as e:
        return None, f"cited record {wid[:12]}… does not canonicalize: {e}"
    if got != wid:
        return None, (f"cited record is stored as {wid[:12]}… but its body "
                      f"recomputes to {got[:12]}…")
    return env, ""


def _recompile(store, doc):
    """Recompile the cited source and require it to yield the cited check.

    This is what keeps the compiler untrusted: provenance is audited by
    re-running the compiler and comparing, never by believing it."""
    src = _intact_blob(store, doc["source"], "source")
    try:
        compiled = pl.compile_source(src.decode("utf-8"))
    except UnicodeDecodeError:
        raise ProvenanceError("source blob is not valid UTF-8")
    except pl.PolicyError as e:
        raise ProvenanceError(f"source blob does not compile: {e}")
    got = w.blob_hash(pl._canon(compiled.doc))
    if got != doc["check"]:
        raise ProvenanceError(
            f"recompiling the cited source yields check {got[:12]}…, not the "
            f"{doc['check'][:12]}… this document describes")
    return compiled


def _ski_reasons(body):
    return [r for r in body.get("because", [])
            if isinstance(r, dict) and r.get("runtime") == "ski@v1"
            and r.get("kind") == "check"]


def _superseded_by(recs, wid):
    """WarrantIDs of stored `supersede` records whose subject is `wid`. Only
    records whose own body recomputes to their name are counted."""
    out = []
    for other in recs:
        env, _why = _record_at(recs, other)
        if env is None:
            continue
        b = env["body"]
        if b.get("decision") == "supersede" and \
                b.get("subject", {}).get("hash") == wid:
            out.append(other)
    return sorted(out)


#: Bound on the citation walk. Reaching it is reported, never assumed benign.
MAX_CITATION_RECORDS = 4096


def _citation_closure(wid, recs):
    """WarrantIDs reachable from `wid` through `prior`, **checking the address
    of every record whose `prior` this walk reads**, plus `wid` itself.

    A derived fact names a decision it USED. SPEC §7 builds a settlement tunnel
    from `prior`, so a dependency the record does not also CITE is invisible to
    re-litigation: superseding it would never reach this record through the
    tunnel. Using without citing is therefore refused, not merely noted.

    The first version delegated the walk to `warrant.tunnel`, which reads
    `body.prior` out of `Store.all_records` — a dict keyed by FILE NAME. An
    intermediate record whose body had been swapped under its old name was
    therefore trusted to prove reachability, and an off-address bridge turned
    the refusal into `complete, derived` (review L1). Correct addresses at the
    endpoints do not prove the edges between them, so E1 applies to every
    record on the path, not only to the two ends.

    Returns (reachable, broken) where `broken` maps a WarrantID this walk
    refused to traverse to the reason. Nothing is swallowed: a missing
    intermediate, an unparsable body and a hit bound are each named."""
    reachable, broken = {wid}, {}
    frontier, budget = [wid], MAX_CITATION_RECORDS
    while frontier:
        cur = frontier.pop()
        if budget <= 0:
            broken[cur] = (f"citation walk stopped after "
                           f"{MAX_CITATION_RECORDS} records")
            break
        budget -= 1
        env, why = _record_at(recs, cur)          # E1, on every hop
        if env is None:
            broken[cur] = why
            continue
        prior = env["body"].get("prior")
        if not isinstance(prior, list):
            broken[cur] = f"record {cur[:12]}… has no `prior` list"
            continue
        for nxt in prior:
            if not w._is_hex64(nxt if isinstance(nxt, str) else ""):
                broken[cur] = f"record {cur[:12]}… cites a malformed prior"
                continue
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    return reachable, broken


def _provenance_docs_of(store, body):
    """Provenance documents cited in a record's `evidence`, plus whether any
    cited evidence could not be resolved intact, plus any document that does
    not belong to this record.

    A sidecar is a document ABOUT one of this record's own `ski@v1` reasons
    (§4). Recompiling its source proves the document is internally consistent;
    it says nothing about whose reason it describes. Without this binding a
    correct sidecar for an unrelated check was accepted and the record reported
    `complete` — a result filed under one WarrantID that was about a different
    question entirely (review H1).

    Returns (docs, lost, foreign)."""
    mine = {r.get("check") for r in _ski_reasons(body)
            if isinstance(r.get("check"), str)}
    docs, lost, rejected = [], [], []
    for h in body.get("evidence", []):
        if not store.has_blob(h):
            lost.append(f"cited evidence {h[:12]}… is not in the store")
            continue
        if not store.blob_intact(h):
            lost.append(f"cited evidence {h[:12]}… does not hash to its address")
            continue
        raw = (store.blobs / h).read_bytes()
        try:
            doc = json.loads(raw)
        except Exception:
            continue                     # a non-JSON evidence blob is normal
        if not (isinstance(doc, dict) and doc.get("provenance") == PROFILE):
            continue                     # not claiming to be one of ours
        # SHAPE BEFORE BINDING. The binding test below is a set membership, so
        # an unhashable `check` (say `[]`) raised TypeError out of this
        # function and past `check_record`'s ProvenanceError handler, losing
        # the typed refusal AND the report for every other record in the store
        # (review J1). A blob that claims to be one of ours and is malformed is
        # a refusal, never an attachment to ignore.
        try:
            _validate_doc_shape(doc)
        except ProvenanceError as e:
            rejected.append(f"{h[:12]}…: malformed provenance document: {e}")
            continue
        if doc["check"] not in mine:
            rejected.append(
                f"{h[:12]}…: provenance document describes check "
                f"{doc['check'][:12]}…, which is not a ski@v1 reason "
                "of this record; a sidecar belongs to the reason it documents")
            continue
        docs.append((h, doc))
    return docs, lost, rejected


# ------------------------------------------------ transitive source health
def _source_health(store, recs, wid, sg, depth, seen, memo, budget):
    """Is `wid` still sound as a SOURCE of a derived value?

    Superseding the record a value came from is only the shallow case. If that
    record itself derived a fact from something that has since been replaced,
    its answer rests on the same moved ground, so the staleness has to travel
    (review F4). Returns (state, detail) with state in {None, STALE, UNDERIVED}
    where None means healthy.

    Bounded on purpose: depth, a global record budget and a cycle guard, each
    reported as UNDERIVED rather than assumed benign."""
    if wid in memo:
        return memo[wid]
    if wid in seen:
        return (UNDERIVED, f"provenance cycle through {wid[:12]}…")
    if depth > MAX_DEPTH:
        return (UNDERIVED,
                f"provenance chain deeper than {MAX_DEPTH}; not walked")
    if budget[0] <= 0:
        return (UNDERIVED,
                f"walked {MAX_RECORDS_WALKED} records without finishing")
    budget[0] -= 1

    sup = _superseded_by(recs, wid)
    if sup:
        result = (STALE, f"cited warrant was superseded by {sup[0][:12]}…")
        memo[wid] = result
        return result

    env, why = _record_at(recs, wid)
    if env is None:
        result = (UNDERIVED, why)
        memo[wid] = result
        return result

    seen = seen | {wid}
    docs, lost, rejected = _provenance_docs_of(store, env["body"])
    if lost or rejected:
        result = (UNDERIVED, f"upstream {wid[:12]}…: {(lost + rejected)[0]}")
        memo[wid] = result
        return result

    for _h, doc in docs:
        try:
            _validate_doc_shape(doc)
            compiled = _recompile(store, doc)
            _require_complete(doc, compiled)
        except ProvenanceError as e:
            result = (UNDERIVED,
                      f"upstream {wid[:12]}… has unusable provenance: {e}")
            memo[wid] = result
            return result
        for name, entry in sorted(doc["facts"].items()):
            if entry.get("kind") != "derived":
                continue
            state, detail = _source_health(
                store, recs, entry["from"], sg, depth + 1, seen, memo, budget)
            if state is not None:
                result = (state,
                          f"through {wid[:12]}….{name}: {detail}")
                memo[wid] = result
                return result

    memo[wid] = (None, "")
    return memo[wid]


def _require_complete(doc, compiled):
    """The described fact set is exactly the check's own, and each entry says
    exactly what the source says about that fact.

    Two separate rules, both refusals:
      * completeness — a missing entry would turn a fact off while the status
        stayed green, so it is never a default to `observed`;
      * agreement — the entry's kind, `from` and selector must match the
        source's own `from` clause. Without this a document could relabel a
        derived fact as observed, or point it at a different decision, and the
        term would not change because provenance is not semantics (review F1).
    """
    declared = set(doc["facts"])
    actual = set(compiled.program.facts)
    if declared != actual:
        missing = sorted(actual - declared)
        extra = sorted(declared - actual)
        bits = []
        if missing:
            bits.append(f"does not describe {missing}")
        if extra:
            bits.append(f"describes absent fact(s) {extra}")
        raise ProvenanceError(
            "provenance document " + " and ".join(bits) +
            "; it MUST describe exactly the facts of the check it names")

    for name in sorted(actual):
        entry = doc["facts"][name]
        fact = compiled.program.facts[name]
        if entry["value"] != fact.value:
            raise ProvenanceError(
                f"provenance document gives fact {name!r} the value "
                f"{entry['value']!r}, but the source pins {fact.value!r}")
        if fact.source is None:
            if entry["kind"] != "observed":
                raise ProvenanceError(
                    f"fact {name!r} is declared {entry['kind']} but its source "
                    "has no `from` clause: it is an observation")
            continue
        wid, sel = fact.source
        if entry["kind"] != "derived":
            raise ProvenanceError(
                f"fact {name!r} is declared {entry['kind']} but its source "
                f"derives it from {wid[:12]}…; a derivation may not be "
                "relabelled as an observation")
        if entry.get("from") != wid:
            raise ProvenanceError(
                f"fact {name!r} is declared to come from "
                f"{str(entry.get('from'))[:12]}…, but its source names "
                f"{wid[:12]}…")
        if entry.get("check") != sel:
            raise ProvenanceError(
                f"fact {name!r} disagrees with its source on which ski@v1 "
                f"reason to select ({entry.get('check')} vs {sel})")


def check_doc(store, doc, recs=None, sg=None, actor=None):
    """Check one provenance document. Returns [Finding] for every fact.

    Raises ProvenanceError when the DOCUMENT is unusable (malformed, not
    address-intact, or disagreeing with the source it names) — that is a
    refusal about the artifact, which must not be reported as a per-fact
    state."""
    _validate_doc_shape(doc)
    compiled = _recompile(store, doc)
    _require_complete(doc, compiled)

    if recs is None:
        recs = store.all_records()
    memo, budget = {}, [MAX_RECORDS_WALKED]

    findings = []
    for name in sorted(compiled.program.facts):
        entry = doc["facts"][name]
        if entry["kind"] == "observed":
            findings.append(Finding(name, "observed", ATTESTED, "", actor))
            continue
        findings.append(_check_derived(store, recs, name, entry, sg,
                                       memo, budget))
    return findings


def _check_derived(store, recs, name, entry, sg, memo=None, budget=None):
    memo = {} if memo is None else memo
    budget = [MAX_RECORDS_WALKED] if budget is None else budget
    wid = entry["from"]

    env, why = _record_at(recs, wid)
    if env is None:
        return Finding(name, "derived", UNDERIVED, why)
    body = env["body"]
    reasons = _ski_reasons(body)
    sel = entry.get("check")
    if sel is not None:
        reasons = [r for r in reasons if r.get("check") == sel]
        if not reasons:
            return Finding(name, "derived", UNDERIVED,
                           f"cited warrant has no ski@v1 reason {sel[:12]}…")
    if len(reasons) != 1:
        what = ("no ski@v1 reason" if not reasons
                else f"{len(reasons)} ski@v1 reasons and none is selected")
        return Finding(name, "derived", UNDERIVED, f"cited warrant has {what}")
    reason = reasons[0]
    check_hex = reason.get("check")
    if not w._is_hex64(check_hex or ""):
        return Finding(name, "derived", UNDERIVED,
                       "cited reason has a malformed check hash")
    try:
        verdict, result_hex, _spent = w.run_ski_check(store, check_hex, sg)
    except Exception as e:                       # unresolved, budget, oracle
        return Finding(name, "derived", UNDERIVED, f"could not re-run: {e}")
    if verdict != "pass":
        return Finding(
            name, "derived", UNDERIVED,
            "the cited reason does not re-run to its own `expect`; its verdict "
            "is disputed, so it cannot supply a value")
    value = church_bool(result_hex)
    if value is None:
        return Finding(name, "derived", UNDERIVED,
                       "the cited check does not reduce to a Church boolean")
    if value != entry["value"]:
        return Finding(
            name, "derived", CONTRADICTED,
            f"cited decision answers {str(value).lower()}, but this policy "
            f"pins {str(entry['value']).lower()}")
    state, detail = _source_health(store, recs, wid, sg, 0, frozenset(),
                                   memo, budget)
    if state is not None:
        return Finding(name, "derived", state, detail)
    return Finding(name, "derived", DERIVED, f"from {wid[:12]}…")


def check_record(store, wid, recs=None, sg=None):
    """Check every provenance document cited in a record's `evidence`.

    Returns a RecordResult. Cited evidence that cannot be resolved intact makes
    the result INCOMPLETE rather than silently reducing the work: with a blob
    gone, "this record cites no provenance" and "this record's provenance was
    removed" are the same observation, and they must not report the same."""
    if recs is None:
        recs = store.all_records()
    env, why = _record_at(recs, wid)
    if env is None:
        return RecordResult(wid, [], [why], INCOMPLETE)
    actor = (env["body"].get("actor") or {}).get("id")
    docs, lost, rejected = _provenance_docs_of(store, env["body"])
    findings, refusals = [], list(lost) + list(rejected)
    covered, broken = _citation_closure(wid, recs)
    kept = []
    for h, doc in docs:
        uncited = sorted({e["from"] for e in doc.get("facts", {}).values()
                          if isinstance(e, dict) and e.get("kind") == "derived"
                          and isinstance(e.get("from"), str)} - covered)
        if uncited:
            why = (f"{h[:12]}…: derives a fact from {uncited[0][:12]}…, which "
                   "is not in this record's prior closure. SPEC §7 builds a "
                   "settlement tunnel from `prior`, so a dependency outside it "
                   "is invisible to re-litigation: the derivation must be "
                   "cited as well as used")
            if broken:
                # Do not let a broken bridge read as a plain miscitation: the
                # source may well be cited THROUGH the record this walk could
                # not traverse, and saying "not cited" would be wider than what
                # was established.
                bad, reason = min(broken.items())
                why += (f". The walk also could not traverse {bad[:12]}…: "
                        f"{reason}; a path through it proves nothing")
            refusals.append(why)
            continue
        kept.append((h, doc))
    if broken and kept:
        # Coverage was established without needing the broken record, so the
        # documents stand — but the evidence path is not wholly walkable and
        # the report must not imply it was.
        bad, reason = min(broken.items())
        refusals.append(
            f"citation walk could not traverse {bad[:12]}…: {reason}")
    for h, doc in kept:
        try:
            findings.extend(check_doc(store, doc, recs, sg, actor))
        except ProvenanceError as e:
            refusals.append(f"{h[:12]}…: {e}")
    # Status is derived from `refusals`, not from a subset of them. Deriving it
    # from `lost or rejected` alone left a record COMPLETE while a document it
    # cited had been refused — the same shape as F3, one level up.
    if refusals:
        status = INCOMPLETE
    elif kept:
        status = COMPLETE
    else:
        status = NOT_APPLICABLE
    return RecordResult(wid, findings, refusals, status)


def check_store(store, recs=None, sg=None):
    """Check every record. Returns {wid: RecordResult} for every record that
    cites provenance OR whose evidence could not be resolved — a record that
    legitimately has none is omitted, one that lost its own is not."""
    if recs is None:
        recs = store.all_records()
    out = {}
    for wid in sorted(recs):
        r = check_record(store, wid, recs, sg)
        if r.status != NOT_APPLICABLE or r.refusals:
            out[wid] = r
    return out
# ----------------------------------------------------------------------- CLI
def _report(store_path, settlement=False):
    store = w.Store(store_path)
    store.require()
    results = check_store(store)
    if not results:
        print(f"{PROFILE}: no provenance documents in {store_path}")
        return 0
    bad = 0
    for wid, r in results.items():
        print(f"\n{wid[:16]}…  [{r.status}]")
        if r.status == INCOMPLETE:
            bad += 1
        for e in r.refusals:
            print(f"  ERR   refused: {e}")
            bad += 1
        for f in r.findings:
            lvl = f.level(settlement)
            if lvl:
                bad += 1
            who = (f" (record names {f.actor}; this profile checks no "
                   "signature)") if f.actor and not f.detail else ""
            print(f"  {lvl or '   ':5} {f.fact}: {f.state}{who}"
                  + (f" — {f.detail}" if f.detail else ""))
    grade = "settlement" if settlement else "base"
    print(f"\n{PROFILE} ({grade} grade): "
          + ("ALL DERIVATIONS HOLD" if not bad else f"{bad} finding(s)"))
    return 1 if bad else 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="fact_provenance",
        description=f"Check {PROFILE} documents in a warrant store (WRT-010).")
    ap.add_argument("--store", default=".warrants")
    ap.add_argument("--settlement", action="store_true",
                    help="settlement grade: `underived` and `stale` become ERR")
    a = ap.parse_args(argv)
    return _report(a.store, a.settlement)


if __name__ == "__main__":
    sys.exit(main())
