"""Overlay: a reader's assessment of records held in several stores, under the reader's own rules.

A publisher's store holds a claim; another store holds a challenge against it the publisher never took in; a third
holds a replay that reproduces it. Each store alone is assessed under its own receiver. A reader composes the stores
it chooses and assesses the union under its own receiver: the publisher cannot keep the reader from counting the
challenge, and no store's verdict is rewritten: there are two named results, each with its own identity,

    assess(A, T_A, P_A)   and   assess(A ∪ O_R, T_R, P_R),

O_R the records of the stores the reader chose, T_R and P_R the reader's trust and profile (Codex, 2026-11-11). It is
the general difference of views (view.py) with the receiver and the sources varied.

The reader's profile (who holds which role) is the reader's alone; no source's profile is merged in. Keys are where
an impostor would strike: a store can bind "claude" to its own key and sign "claude's" records. So a binding is
admitted only as the reader's own, or as one every chosen source that names that actor agrees on; a binding the
sources disagree on is not admitted and is named. An actor the reader's own profile gives a role is admitted only
from the reader's own trust: "every source agrees" can be one store, and a store that binds a role holder to its own
key would sign that holder's acceptances (Codex, 2026-11-12); such a binding is named, not admitted. What the reader cannot find is not counted: a challenge in a
store the reader did not choose does not exist for this assessment (the overlay is honest, not complete)."""
from warrant import engine as EN
from warrant import jcs as C
from warrant.store import Snapshot


def compose(snaps):
    """One snapshot holding every line of `snaps` ({store: Snapshot}) once, in canonical order, and all their blobs."""
    lines = sorted({raw for s in snaps.values() for raw in s.raw})
    blobs = {}
    for s in snaps.values():
        blobs.update(s.blobs)
    return Snapshot(lines, blobs)


def receiver(reader_trust, reader_profile, sources):
    """(trust, profile, held) of the reader composing `sources` ({store: trust}): the reader's own bindings, then each
    binding all the sources naming that actor agree on, unless the reader's profile gives that actor a role;
    [(actor, {store: keys}, why)] of those not admitted, why "role" (a role holder the reader does not bind itself)
    or "disagree" (the sources bind different keys)."""
    keys = {a: sorted(k) for a, k in reader_trust["keys"].items()}
    holders = {a for actors in reader_profile["roles"].values() for a in actors}
    named = {}
    for store, t in sorted(sources.items()):
        for actor, k in t["keys"].items():
            named.setdefault(actor, {})[store] = sorted(k)
    conflicts = []
    for actor, by in sorted(named.items()):
        if actor in keys:
            continue
        distinct = {tuple(k) for k in by.values()}
        if actor in holders:
            conflicts.append((actor, by, "role"))
        elif len(distinct) == 1:
            keys[actor] = list(distinct.pop())
        else:
            conflicts.append((actor, by, "disagree"))
    return dict(reader_trust, keys=dict(sorted(keys.items()))), reader_profile, conflicts


def assess(snaps, trust, profile):
    """The report of the union of `snaps` under (trust, profile), with its records."""
    v = EN.View(compose(snaps), trust, profile)
    rep = v.report()
    rep["_recs"], rep["_basis"] = v.recs, v.basis
    return rep


def identity(snaps, trust, profile, code):
    """The identity of an overlay assessment: each store's records (their ids), the trust, the profile and the engine:
    the same inputs give the same identity, another record set or another receiver another."""
    return C.doc_id({"stores": {n: C.doc_id(sorted(s.lines)) for n, s in sorted(snaps.items())},
                     "trust": C.doc_id(trust), "profile": C.doc_id(profile), "code": code})
