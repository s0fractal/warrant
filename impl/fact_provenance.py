#!/usr/bin/env python3
"""fact_provenance — `warrant.fact-provenance@v0`, the WRT-008 reference profile.

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
class Finding:
    __slots__ = ("fact", "kind", "state", "detail")

    def __init__(self, fact, kind, state, detail=""):
        self.fact, self.kind, self.state, self.detail = fact, kind, state, detail

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


def _recompile(store, doc):
    """Recompile the cited source and require it to yield the cited check.

    This is what keeps the compiler untrusted: provenance is audited by
    re-running the compiler and comparing, never by believing it."""
    src_hex = doc["source"]
    if not store.has_blob(src_hex):
        raise ProvenanceError(f"source blob {src_hex[:12]}… is not in the store")
    src = (store.blobs / src_hex).read_bytes()
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
    """WarrantIDs of stored `supersede` records whose subject is `wid`."""
    out = []
    for other, env in recs.items():
        b = env.get("body", {})
        if b.get("decision") == "supersede" and \
                b.get("subject", {}).get("hash") == wid:
            out.append(other)
    return sorted(out)


def check_doc(store, doc, recs=None, sg=None):
    """Check one provenance document. Returns [Finding] for every fact.

    Raises ProvenanceError when the DOCUMENT is unusable (malformed, or it does
    not describe the check it names) — that is a refusal about the artifact,
    which must not be reported as a per-fact state."""
    _validate_doc_shape(doc)
    compiled = _recompile(store, doc)

    # Completeness (MUST): the described fact set is exactly the check's own.
    # A missing entry would otherwise turn a fact off while the status stayed
    # green; it is a refusal, never a default to `observed`.
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

    if recs is None:
        recs = store.all_records()

    findings = []
    for name in sorted(actual):
        entry = doc["facts"][name]
        fact = compiled.program.facts[name]
        if entry["value"] != fact.value:
            raise ProvenanceError(
                f"provenance document gives fact {name!r} the value "
                f"{entry['value']!r}, but the source pins {fact.value!r}")
        if entry["kind"] == "observed":
            findings.append(Finding(name, "observed", ATTESTED))
            continue
        findings.append(_check_derived(store, recs, name, entry, sg))
    return findings


def _check_derived(store, recs, name, entry, sg):
    wid = entry["from"]
    env = recs.get(wid)
    if env is None:
        return Finding(name, "derived", UNDERIVED,
                       f"cited warrant {wid[:12]}… is not in the store")
    body = env.get("body", {})
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
        return Finding(name, "derived", UNDERIVED,
                       f"cited warrant has {what}")
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
    sup = _superseded_by(recs, wid)
    if sup:
        return Finding(name, "derived", STALE,
                       f"cited warrant was superseded by {sup[0][:12]}…")
    return Finding(name, "derived", DERIVED, f"from {wid[:12]}…")


def check_record(store, wid, recs=None, sg=None):
    """Check every provenance document cited in a record's `evidence`.

    Returns (findings, errors) where `errors` are ProvenanceError messages for
    documents that could not be used at all."""
    if recs is None:
        recs = store.all_records()
    env = recs.get(wid)
    if env is None:
        return [], [f"record {wid[:12]}… is not in the store"]
    findings, errors = [], []
    for h in env.get("body", {}).get("evidence", []):
        if not store.has_blob(h):
            continue
        raw = (store.blobs / h).read_bytes()
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        if not isinstance(doc, dict) or doc.get("provenance") != PROFILE:
            continue
        try:
            findings.extend(check_doc(store, doc, recs, sg))
        except ProvenanceError as e:
            errors.append(f"{h[:12]}…: {e}")
    return findings, errors


def check_store(store, recs=None, sg=None):
    """Check every provenance document reachable from every record.

    Returns {wid: (findings, errors)} for records that cite at least one."""
    if recs is None:
        recs = store.all_records()
    out = {}
    for wid in sorted(recs):
        findings, errors = check_record(store, wid, recs, sg)
        if findings or errors:
            out[wid] = (findings, errors)
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
    for wid, (findings, errors) in results.items():
        print(f"\n{wid[:16]}…")
        for e in errors:
            print(f"  ERR   refused: {e}")
            bad += 1
        for f in findings:
            lvl = f.level(settlement)
            if lvl:
                bad += 1
            print(f"  {lvl or '   ':5} {f.fact}: {f.state}"
                  + (f" — {f.detail}" if f.detail else ""))
    grade = "settlement" if settlement else "base"
    print(f"\n{PROFILE} ({grade} grade): "
          + ("ALL DERIVATIONS HOLD" if not bad else f"{bad} finding(s)"))
    return 1 if bad else 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="fact_provenance",
        description=f"Check {PROFILE} documents in a warrant store (WRT-008).")
    ap.add_argument("--store", default=".warrants")
    ap.add_argument("--settlement", action="store_true",
                    help="settlement grade: `underived` and `stale` become ERR")
    a = ap.parse_args(argv)
    return _report(a.store, a.settlement)


if __name__ == "__main__":
    sys.exit(main())
