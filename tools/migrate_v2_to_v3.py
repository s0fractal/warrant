#!/usr/bin/env python3
"""Migrate a Warrant 2 store (.warrant/store) into a Warrant 3 store (docs/V3.md §9), deterministically.

    python3 tools/migrate_v2_to_v3.py identity                      # the migrator checker's actor id
    python3 tools/migrate_v2_to_v3.py keygen --out SEED             # a migrator seed, outside the repository
    python3 tools/migrate_v2_to_v3.py run --out DIR --claude-key SEED --migrator-key SEED
    python3 tools/migrate_v2_to_v3.py verify --out DIR             # replay: refuse any difference

The classification reads records and blobs only (never tools/), so a parity test against the v2
tools is a differential. Every v2 record lands in the map of exactly the v3 records it was derived
from; a v2 field the migration would lose without a declared rule (DROPPED) is refused. A v3 record
is derived from records of one actor only. Migrated records carry `sig: null`; their authenticity
is the migration attest of the checker `checker sha256:<identity()>`, whose identity is the digest
of its whole import closure (this file, warrant3/, warrant/), checked at run time.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from warrant import jcs as C                                     # noqa: E402
from warrant import keys as K                                    # noqa: E402
from warrant.bindings import admit_bindings, read_roles, trust_of  # noqa: E402
from warrant.store import Snapshot as V2Snapshot                 # noqa: E402
from warrant3 import bootstrap as B                              # noqa: E402
from warrant3 import records as R                                # noqa: E402
from warrant3.store import Store                                 # noqa: E402

HASHED = ("tools/migrate_v2_to_v3.py", "warrant3", "warrant")
CLAUDE_SEED = Path.home() / "Projects/.worktrees/claims-pilot/claude-claims.seed"
MIGRATOR_SEED = Path.home() / ".config/warrant/migrator-v3.seed"
CARRIER = {"name": "v2-transition@1", "fields": {"state": "str", "body": "obj"}, "states": {"carried": None},
           "closed": [], "successors": []}
CARRIED = ("established", "residual", "opened", "subject")       # transition members kept verbatim when present
# What the migration does not carry, and why each loss is safe (checked per record, else refused).
DROPPED = {
    "transition.basis": "every live transition is ATTESTED; what an attestation is worth is its actor's role",
    "transition.relied_on, triggers": "empty in every live record",
    "transition.supersedes, closes": "become the version's lineage and state",
    "transition.evidence": "inlined domain blobs become the body; other evidence is in refs",
    "duty.owed_to, accept_by, release_by, condition, schedule": "the schema's guard roles, bound by the receiver's profile",
    "duty.statement, subject of a claim": "derived from the claim's id and text (the subject blob is the text)",
    "accept.evidence, item": "an attest names the exact version, whose id covers its evidence",
    "observation.target, raw, probe": "the replay or merge facts are the attest's body",
    "blob schema, duty, pr, head, previous": "said by the envelope (schema, lineage, target)",
}
# Where the v3 record says more than the v2 records did, by a declared rule (listed in the map blob).
DECLARED = {
    "parallel closures": "closures of one obligation that name no earlier closure (no supersedes) are chained in "
                         "filing order: v2 kept them as independent candidates, v3 would read them as a FORK",
}
STATEMENT = re.compile(r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<pr>[1-9][0-9]{0,6}) is fit to merge: (?P<title>\S(?:.*\S)?)\Z")
REPLAY = {"FAIL": "reproduces", "PASS": "does_not_reproduce", "NO_RESULT": "no_result", "DOES_NOT_APPLY": "does_not_apply"}
CLAIM, RETIRE = "warrant-claims/claim@1", "warrant-claims/retire@1"
HEAD, FINDING = "warrant-review/head@1", "warrant-review/finding@1"
EVIDENCE, REVISION, SOURCE = "warrant-roadmap/evidence@1", "warrant-roadmap/revision@1", "warrant-roadmap/source@1"


class Refused(Exception):
    pass


def need(ok, why):
    if not ok:
        raise Refused(why)


# ---------------------------------------------------------------- identity

def _files():
    for name in HASHED:
        p = ROOT / name
        yield from ([p] if p.is_file() else sorted(q for q in p.rglob("*") if q.is_file() and "__pycache__" not in q.parts))


def identity():
    """The digest of everything that decides the output: every file of HASHED, the Python version
    and the signature library's version."""
    import cryptography
    files = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in _files()}
    return C.doc_id({"migrator": "warrant3/migrate-v2@1", "files": files, "python": list(sys.version_info[:2]),
                     "cryptography": cryptography.__version__})


def actor():
    return "checker sha256:" + identity()


def closure_problem():
    """A module this process loaded from the repository outside HASHED, or None: the identity names
    the whole import closure or the run is refused."""
    hashed = {p.resolve() for p in _files()}
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and Path(f).resolve().is_relative_to(ROOT) and Path(f).resolve() not in hashed:
            return f"{Path(f).resolve().relative_to(ROOT)} is imported and not in the identity"
    return None


# ---------------------------------------------------------------- reading v2

def read_v2(root):
    root = Path(root)
    snap = V2Snapshot.read(root / ".warrant" / "store")
    need(not snap.misfiled, f"v2 store has misfiled entries: {snap.misfiled[:3]}")
    roles, why = read_roles(json.loads((root / ".warrant/roles.json").read_text()))
    admitted, why2 = admit_bindings(C.loads((root / ".warrant/trust.json").read_bytes()), roles=roles)
    need(not why and not why2, f"v2 bindings: {(why + why2)[:3]}")
    trust = trust_of(admitted)
    recs, bad = snap.authentic(trust)
    need(not bad, f"{len(bad)} v2 records are not authentic: {sorted(bad.items())[:2]}")
    cfg = {n: json.loads((root / ".warrant" / f"{n}.json").read_text()) for n in ("claims", "roadmap", "reviews")}
    return snap, trust, admitted, recs, cfg


class Migration:
    def __init__(self, root):
        self.snap, self.trust, self.admitted, self.recs, self.cfg = read_v2(root)
        self.out, self.src, self.memo, self.parent = {}, {}, {}, {}
        self.doc, self.declared = {}, []
        self.at = max(r["at"] for r in self.recs.values())
        self._classify()

    def blob(self, h):
        if h not in self.doc:
            d = self.snap.json_blob(h)
            self.doc[h] = d if isinstance(d, dict) else None
        return self.doc[h]

    def schema_of(self, h):
        d = self.blob(h)
        return d and (d.get("schema") or d.get("probe"))

    def docs(self, t, schema):
        return [h for h in self.recs[t]["body"]["evidence"] if self.schema_of(h) == schema]

    def _classify(self):
        R2 = self.recs
        self.claim_t = {t for t, r in R2.items() if r["type"] == "transition" and (self.docs(t, CLAIM) or self.docs(t, RETIRE))}
        self.claim_duty_t = {}
        for t in sorted(self.claim_t, key=lambda t: (R2[t]["at"], t)):
            d = self.blob(self.claim_doc(t)).get("duty")
            if d:
                self.claim_duty_t.setdefault(d, t)
        repo = self.cfg["reviews"]["repository"]
        self.review_d = {d for d, r in R2.items() if r["type"] == "duty" and (m := STATEMENT.match(r["body"]["statement"]))
                         and m.group("repo") == repo}
        self.goal_q = {}
        for t, r in R2.items():
            if r["type"] == "transition":
                for i, q in enumerate(r["body"]["opened"]):
                    if (q["scope"] or "").startswith("roadmap:"):
                        self.goal_q[f"{t}:{i}"] = (t, q["scope"][len("roadmap:"):], q["text"])
        self.vision_t = {q[0] for q in self.goal_q.values()}
        self.obl_d = {d for d, r in R2.items() if r["type"] == "duty" and r["body"]["answers"] in self.goal_q}
        self.head_t, self.obl_t = set(), set()
        for t, r in R2.items():
            ds = [m["duty"] for m in r["body"].get("closes", [])] if r["type"] == "transition" else []
            if ds and all(d in self.review_d for d in ds):
                self.head_t.add(t)
            elif ds and all(d in self.obl_d for d in ds):
                self.obl_t.add(t)

    def claim_doc(self, t):
        hs = self.docs(t, CLAIM) + self.docs(t, RETIRE)
        need(len(hs) == 1, f"transition {t[:12]} carries {len(hs)} claim blobs")
        return hs[0]

    # -- emitting

    def emit(self, kind, rec_actor, at, body, sources, inlined=(), schema=None, lineage=None, refs=(), guard=None):
        for s in sources:
            need(self.recs[s]["actor"] == rec_actor, f"v3 record of {rec_actor!r} derived from {s[:12]} by {self.recs[s]['actor']!r}")
        r = R.record(kind, rec_actor, at, body, schema, lineage, refs, guard)
        i = R.rid(r)
        self.out[i] = r
        srcs, inl = self.src.setdefault(i, (set(), set()))
        srcs.update(sources)
        inl.update(inlined)
        if lineage:
            self.parent[i] = lineage
        return i

    def root(self, v):
        while v in self.parent:
            v = self.parent[v]
        return v

    def once(self, key, fn):
        if key not in self.memo:
            self.memo[key] = fn()
        return self.memo[key]

    def carried(self, t):
        b = self.recs[t]["body"]
        need(b["basis"] == "ATTESTED" and not b["relied_on"] and not b["triggers"]
             and not any(m.get("triggers") for m in b["closes"]), f"transition {t[:12]} uses a dropped member with content")
        return {k: b[k] for k in CARRIED if b[k] not in (None, [])}

    # -- claims

    def claim(self, t):
        return self.once(("claim", t), lambda: self._claim(t))

    def _claim(self, t):
        r, h = self.recs[t], self.claim_doc(t)
        doc = self.blob(h)
        prev = self.claim(doc["previous"]["transition"]) if doc["previous"] else None
        sources, inlined, refs = {t}, {h}, []
        if doc["schema"] == RETIRE:
            body = {k: self.out[prev]["body"][k] for k in ("id", "source", "section", "text", "witnesses", "mutants")}
            body.update(state="retired", because=doc["because"], counter=doc["counter"], challenge=self.image(doc["challenge"]))
            refs = [body["counter"], body["challenge"]]
        else:
            d = doc["duty"]
            if d and self.claim_duty_t.get(d) == t:
                db = self.recs[d]["body"]
                need(not (db["requires"] or db["serves"] or db["answers"] or db["schedule"] or db["release_by"])
                     and db["condition"] == {"attest": {}}, f"claim duty {d[:12]} has members the migration does not carry")
                sources.add(d)
                if db["subject"]:
                    inlined.add(db["subject"])
            state = "informative" if doc["kind"] == "informative" else "backed" if doc["witnesses"] and doc["mutants"] else "unbacked"
            body = {"state": state, **{k: doc[k] for k in ("id", "source", "section", "text", "witnesses", "mutants")},
                    "reason": doc["reason"], "because": doc["because"]}
        other = sorted(x if x in self.snap.blobs else self.image(x) for x in set(r["body"]["evidence"]) - {h})
        if other:
            body["evidence"], refs = other, sorted(set(refs) | set(other))
        body.update(self.carried(t))
        g = B.SCHEMAS[0]["states"][body["state"]]
        return self.emit("entity", r["actor"], r["at"], body, sources, inlined, "claim@1", prev, refs, g)

    # -- goals and obligations

    def vision(self, t):
        """{key: v3 version} after vision transition t (its keys and those it supersedes)."""
        return self.once(("vision", t), lambda: self._vision(t))

    def _vision(self, t):
        r = self.recs[t]
        b = r["body"]
        prior = {}
        for s in b["supersedes"]:
            need(s in self.vision_t, f"vision {t[:12]} supersedes {s[:12]}, not a vision")
            prior.update(self.vision(s))
        revs = {self.blob(h)["goal"]: (h, self.blob(h)) for h in self.docs(t, REVISION)}
        srcs = [self.blob(h) for h in self.docs(t, SOURCE)]
        inlined = set(self.docs(t, REVISION) + self.docs(t, SOURCE))
        need(set(b["evidence"]) <= inlined | {s["blob"] for s in srcs}, f"vision {t[:12]} cites evidence it would lose")
        carry = {k: v for k, v in self.carried(t).items() if k != "opened"}
        need(all((q["scope"] or "").startswith("roadmap:") for q in b["opened"]), f"vision {t[:12]} opens other questions")
        out, made = dict(prior), []
        guard = B.SCHEMAS[1]["states"]["met"]
        for i, q in enumerate(b["opened"]):
            key = q["scope"][len("roadmap:"):]
            h, rev = revs.get(key, (None, None))
            if key not in prior:
                need(rev is None, f"vision {t[:12]} revises {key}, which it opens first")
                body = {"state": "open", "key": key, "text": q["text"], **carry}
                if srcs:
                    body["sources"] = [{"by": s["by"], "blob": s["blob"]} for s in srcs]
                v = self.emit("entity", r["actor"], r["at"], body, {t}, inlined, "goal@1", refs=[s["blob"] for s in srcs])
                made.append(v)
            elif rev is None:
                need(self.out[prior[key]]["body"]["text"] == q["text"], f"vision {t[:12]} changes {key} without a revision")
                v = prior[key]
            else:
                need(rev["act"] == "reformulate", f"vision {t[:12]} opens {key} again and says it is {rev['act']}")
                v = self.emit("entity", r["actor"], r["at"], {"state": "reformulated", "key": key, "text": q["text"],
                              "because": rev["because"], "refs": rev["refs"], **carry}, {t}, inlined | {h}, "goal@1",
                              prior[key], guard=guard)
                made.append(v)
            out[key] = v
            self.memo[("question", f"{t}:{i}")] = self.root(v)
        opened = {q["scope"][len("roadmap:"):] for q in b["opened"]}
        for key in sorted(set(prior) - opened):
            h, rev = revs.get(key, (None, None))
            if rev is None and self.out[prior[key]]["body"]["state"] in ("met", "withdrawn"):
                continue                                        # closed earlier: nothing to reopen
            need(rev is not None and rev["act"] in ("met", "withdraw"), f"vision {t[:12]} drops {key} without saying it is met or withdrawn")
            state = "met" if rev["act"] == "met" else "withdrawn"
            v = self.emit("entity", r["actor"], r["at"], {"state": state, "key": key, "text": self.out[prior[key]]["body"]["text"],
                          "because": rev["because"], "refs": rev["refs"], **carry}, {t}, inlined | {h}, "goal@1", prior[key], guard=guard)
            out[key] = v
            made.append(v)
        need(made, f"vision {t[:12]} creates no goal version")
        self.memo[("made", t)] = made
        return out

    def question(self, ref):
        self.vision(self.goal_q[ref][0])
        return self.memo[("question", ref)]

    def lineage_of_duty(self, d):
        if d in self.obl_d:
            return self.obligation(d)
        if d in self.review_d:
            return self.review(d)
        need(d in self.claim_duty_t, f"duty {d[:12]} is neither a claim's, an obligation nor a review")
        return self.root(self.claim(self.claim_duty_t[d]))

    def obligation(self, d):
        return self.once(("obl", d), lambda: self._obligation(d))

    def _obligation(self, d):
        r = self.recs[d]
        b = r["body"]
        cfg = self.cfg["roadmap"]
        need((b["owed_to"], b["accept_by"], b["release_by"], b["condition"], b["schedule"])
             == (cfg["owed_to"], cfg["accept_by"], [], {"attest": {}}, None), f"obligation {d[:12]} has other terms")
        serves = sorted({self.lineage_of_duty(x) for x in b["serves"]})
        req = sorted({self.lineage_of_duty(x) for x in b["requires"]})
        body = {"state": "open", "statement": b["statement"], "answers": self.question(b["answers"]), "serves": serves}
        if b["subject"]:
            body["subject"] = b["subject"]
        return self.emit("entity", r["actor"], r["at"], body, {d}, (), "obligation@1", refs=serves + [body["answers"]],
                         guard=R.guard(requires=req) if req else None)

    def done(self, t):
        return self.once(("done", t), lambda: self._done(t))

    def _done(self, t):
        r = self.recs[t]
        b = r["body"]
        need(len(b["closes"]) == 1 and b["closes"][0]["act"] == "discharge" and b["closes"][0]["evidence"] == b["evidence"],
             f"obligation closure {t[:12]} is not one discharge citing the transition's evidence")
        d = b["closes"][0]["duty"]
        root = self.obligation(d)
        earlier = [s for s in b["supersedes"] if s in self.obl_t and self.recs[s]["body"]["closes"][0]["duty"] == d]
        need(len(earlier) == len(b["supersedes"]) <= 1, f"closure {t[:12]} supersedes other records")
        if not earlier:                                         # DECLARED["parallel closures"]
            named = {x for c in self.obl_t for x in self.recs[c]["body"]["supersedes"]}
            before = sorted((self.recs[c]["at"], c) for c in self.obl_t if c != t and c not in named
                            and self.recs[c]["body"]["closes"][0]["duty"] == d and (self.recs[c]["at"], c) < (r["at"], t))
            if before:
                earlier = [before[-1][1]]
                self.declared.append(["parallel closures", t, earlier[0]])
        ev = self.docs(t, EVIDENCE)
        need(len(ev) == 1 and self.blob(ev[0])["duty"] == d, f"closure {t[:12]} has no evidence blob of its duty")
        other = sorted(set(b["evidence"]) - set(ev))
        rb = self.out[root]["body"]
        body = {"state": "done", "statement": rb["statement"], "answers": rb["answers"], "serves": rb["serves"],
                "refs": self.blob(ev[0])["refs"], **self.carried(t)}
        if other:
            body["evidence"] = other
        return self.emit("entity", r["actor"], r["at"], body, {t}, set(ev), "obligation@1",
                         self.done(earlier[0]) if earlier else root, rb["serves"] + [rb["answers"]] + other,
                         B.SCHEMAS[2]["states"]["done"])

    # -- reviews

    def review(self, d):
        return self.once(("review", d), lambda: self._review(d))

    def _review(self, d):
        r = self.recs[d]
        b = r["body"]
        cfg = self.cfg["reviews"]
        need((b["owed_to"], b["accept_by"], b["release_by"], b["condition"], b["requires"], b["answers"], b["subject"], b["schedule"])
             == (cfg["owed_to"], cfg["accept_by"], [], {"attest": {}}, [], None, None, None), f"review duty {d[:12]} has other terms")
        m = STATEMENT.match(b["statement"])
        serves = sorted({self.lineage_of_duty(x) for x in b["serves"]})
        body = {"state": "open", "repository": m.group("repo"), "pr": int(m.group("pr")), "title": m.group("title"), "serves": serves}
        return self.emit("entity", r["actor"], r["at"], body, {d}, (), "pr-head@1", refs=serves)

    def head(self, t):
        return self.once(("head", t), lambda: self._head(t))

    def _head(self, t):
        r = self.recs[t]
        b = r["body"]
        hs = self.docs(t, HEAD)
        need(len(b["closes"]) == 1 and b["closes"][0]["act"] in ("discharge", "revalidate") and len(hs) == 1
             and b["evidence"] == hs == b["closes"][0]["evidence"], f"head {t[:12]} is not one closure citing one head blob")
        doc = self.blob(hs[0])
        need(doc["duty"] == b["closes"][0]["duty"], f"head {t[:12]}'s blob names another duty")
        if b["closes"][0]["act"] == "revalidate":
            need(set(b["closes"][0]["revalidates"]) <= self.head_t, f"head {t[:12]} revalidates no head")
        answers = sorted(self.challenge(x) for x in doc["answers"])
        body = {"state": "head", "commit": doc["commit"], "tree": doc["tree"], "answers": answers, **self.carried(t)}
        prev = self.head(doc["previous"]) if doc["previous"] else self.review(doc["duty"])
        return self.emit("entity", r["actor"], r["at"], body, {t}, set(hs), "pr-head@1", prev, answers,
                         B.SCHEMAS[3]["states"]["head"])

    # -- documents and other transitions

    def carrier(self, t):
        return self.once(("carrier", t), lambda: self._carrier(t))

    def _carrier(self, t):
        r = self.recs[t]
        b = r["body"]
        sup = [s for s in b["supersedes"]]
        need(len(sup) <= 1 and not b["closes"] and all(s not in self.claim_t | self.vision_t for s in sup),
             f"transition {t[:12]} is of no class the migration knows")
        refs = [h for h in b["evidence"]]
        need(all(h in self.snap.blobs for h in refs), f"transition {t[:12]} cites records as evidence")
        return self.emit("entity", r["actor"], r["at"], {"state": "carried", "body": b}, {t}, (), CARRIER["name"],
                         self.carrier(sup[0]) if sup else None, refs)

    def image(self, x):
        """The v3 version a v2 transition became; a challenge's own image for a challenge."""
        r = self.recs.get(x)
        need(r is not None, f"{x[:12]} is not a v2 record in the store")
        if r["type"] == "challenge":
            return self.challenge(x)
        need(r["type"] == "transition", f"{x[:12]} is a {r['type']}, which nothing targets in v3")
        if x in self.claim_t:
            return self.claim(x)
        if x in self.head_t:
            return self.head(x)
        if x in self.obl_t:
            return self.done(x)
        need(x not in self.vision_t, f"{x[:12]} is a vision: name its goal versions")
        return self.carrier(x)

    # -- accept, challenge, observation

    def accept(self, a):
        r = self.recs[a]
        b = r["body"]
        t = self.recs[b["transition"]]
        want = t["body"]["evidence"] if b["item"] is None else t["body"]["closes"][b["item"]]["evidence"]
        need(sorted(b["evidence"]) == sorted(want), f"accept {a[:12]} names another evidence set (it never counted in v2)")
        if b["transition"] in self.vision_t:
            need(b["item"] is None, f"accept {a[:12]} accepts a vision item")
            self.vision(b["transition"])
            targets = self.memo[("made", b["transition"])]
        else:
            need(b["item"] == 0 or (b["item"] is None and not t["body"]["closes"]), f"accept {a[:12]}: item {b['item']}")
            targets = [self.image(b["transition"])]
        for v in targets:
            body = {"target": v, "verdict": "accept"}
            if b["support"]:
                body["support"] = b["support"]
            self.emit("attest", r["actor"], r["at"], body, {a}, (), refs=[v] + b["support"])

    def challenge(self, c):
        return self.once(("challenge", c), lambda: self._challenge(c))

    def _challenge(self, c):
        r = self.recs[c]
        b = r["body"]
        need(b["item"] == 0, f"challenge {c[:12]} of item {b['item']}")
        fs = [h for h in b["evidence"] if self.schema_of(h) == FINDING]
        if fs and b["target"] in self.head_t:
            need(len(fs) == len(b["evidence"]) == 1, f"finding {c[:12]} carries more than its finding blob")
            doc = self.blob(fs[0])
            target = self.head(b["target"])
            body = {"target": target, "statement": b["statement"], **{k: doc[k] for k in ("severity", "what", "where", "commit", "tree", "test")}}
            return self.emit("challenge", r["actor"], r["at"], body, {c}, set(fs), "finding@1", refs=[target])
        target = self.image(b["target"])
        body = {"target": target, "statement": b["statement"]}
        if b["evidence"]:
            body["evidence"] = b["evidence"]
        need(all(h in self.snap.blobs for h in b["evidence"]), f"challenge {c[:12]} cites records as evidence")
        return self.emit("challenge", r["actor"], r["at"], body, {c}, (), refs=[target] + b["evidence"])

    def observation(self, o):
        r = self.recs[o]
        b = r["body"]
        probe = self.blob(b["probe"]) or {}
        if probe.get("probe") == "warrant-review/replay@1":
            f = self.recs[probe["finding"]]
            duty = self.recs[f["body"]["target"]]["body"]["closes"][0]["duty"]
            at = [t for t in self.head_t if self.recs[t]["body"]["closes"][0]["duty"] == duty
                  and self.blob(self.recs[t]["body"]["evidence"][0])["commit"] == probe["commit"]]
            need(len(at) == 1 and b["raw"] == [], f"replay {o[:12]} names no single head of its finding's review")
            target, on = self.challenge(probe["finding"]), self.head(at[0])
            body = {"target": target, "verdict": REPLAY[b["result"]], "on": on, "commit": probe["commit"],
                    "tree": probe["tree"], "test": probe["test"], "window": b["window"]}
            return self.emit("attest", r["actor"], r["at"], body, {o}, {b["probe"]}, refs=[target, on])
        need(probe.get("probe") == "warrant-review/merge@1" and len(b["raw"]) == 1, f"observation {o[:12]} of an unknown probe")
        target = self.review(probe["duty"])
        body = {"target": target, "verdict": "merged", "merge": probe["merge"], "report": b["raw"][0],
                "result": b["result"], "window": b["window"]}
        return self.emit("attest", r["actor"], r["at"], body, {o}, {b["probe"]}, refs=[target, b["raw"][0]])

    # -- the whole store

    def run(self):
        R2 = self.recs
        for i, r in sorted(R2.items(), key=lambda kv: (kv[1]["at"], kv[0])):
            if r["type"] == "duty":
                if i in self.review_d:
                    self.review(i)
                elif i in self.obl_d:
                    self.obligation(i)
                else:
                    need(i in self.claim_duty_t, f"duty {i[:12]} is of no class")
            elif r["type"] == "transition":
                self.vision(i) if i in self.vision_t else self.image(i)
            elif r["type"] == "accept":
                self.accept(i)
            elif r["type"] == "challenge":
                self.challenge(i)
            elif r["type"] == "observation":
                self.observation(i)
            else:
                raise Refused(f"{r['type']} {i[:12]}: no v3 form (grants are dropped and none is live)")
        used = set().union(*(s for s, _ in self.src.values()))
        need(used == set(R2), f"{len(set(R2) - used)} v2 records land in no v3 record: {sorted(set(R2) - used)[:3]}")
        blobs = sorted({h for r in self.out.values() for h in r["refs"] if h in self.snap.blobs})
        rows = [[i, sorted(s), sorted(inl)] for i, (s, inl) in sorted(self.src.items())]
        lost = set(self.snap.blobs) - set(blobs) - {h for row in rows for h in row[2]}
        need(not lost, f"{len(lost)} v2 blobs are neither copied nor inlined: {sorted(lost)[:3]}")
        return blobs, rows

    def roles(self, migrator):
        c, rm, rv = self.cfg["claims"], self.cfg["roadmap"], self.cfg["reviews"]
        roles = {"schema/author": ["claude"], "claim/verifier": c["accept_by"] + c.get("checkers", []),
                 "roadmap/acceptor": rm["accept_by"] + rm["results_accept_by"], "roadmap/owner": rm["owed_to"],
                 "pr/acceptor": rv["accept_by"], "pr/owner": rv["owed_to"], "replayer": rv["replayers"], "migrator": [migrator]}
        return {k: sorted(set(v)) for k, v in sorted(roles.items())}


def migrate(root, claude_key, migrator_key):
    """(lines, blobs {hash: bytes}, trust, profile, summary) of the v3 store migrated from `root`."""
    m = Migration(root)
    blobs, rows = m.run()
    me = actor()
    v2 = {"root": m.snap.digest, "trust": m.trust.digest, "records": len(m.recs), "blobs": len(m.snap.blobs)}
    mapdoc = C.canon({"migration": "warrant3/map@1", "v2": v2, "dropped": DROPPED, "declared": DECLARED,
                      "applied": sorted(m.declared), "map": rows})
    maph = hashlib.sha256(mapdoc).hexdigest()
    lines, prev = [R.line(r)[1] for r in m.out.values()], None
    for s in B.SCHEMAS + [CARRIER]:
        r = R.record("schema", "claude", m.at, s, prev=prev)
        prev, line = R.line(r, claude_key)
        lines.append(line)
    gen = R.record("attest", me, m.at, {"target": maph, "verdict": "migrated", "v2": v2, "code": identity(),
                                        "records": len(m.out)}, R.MIGRATION, refs=[maph])
    gid, line = R.line(gen, migrator_key)
    lines.append(line)
    keys = {}
    for a, p in m.admitted + [("claude", claude_key.public), (me, migrator_key.public)]:
        keys.setdefault(a, set()).add(p)
    trust = {"warrant": "trust/3", "keys": {a: sorted(v) for a, v in sorted(keys.items())}}
    profile = {"warrant": "profile/3", "roles": m.roles(me)}
    out_blobs = {h: m.snap.blobs[h] for h in blobs}
    out_blobs[maph] = mapdoc
    kinds = {}
    for r in m.out.values():
        k = f"{r['kind']} {r['schema']}"
        kinds[k] = kinds.get(k, 0) + 1
    summary = {"v2": v2, "v3": {"records": len(lines), "migrated": len(m.out), "blobs": len(out_blobs),
                                "inlined_v2_blobs": len(set().union(*(set(x[2]) for x in rows)))}, "genesis": gid,
               "declared": sorted(m.declared),
               "migrator": me, "kinds": dict(sorted(kinds.items()))}
    return lines, out_blobs, trust, profile, summary


def write(out, lines, blobs, trust, profile, summary):
    out = Path(out)
    st = Store(out).init()
    st.write_lines(lines)
    for h, data in blobs.items():
        st.put_blob(data)
    for name, doc in (("trust.json", trust), ("profile.json", profile), ("summary.json", summary)):
        (out / name).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")


def load_key(path):
    p = Path(path).expanduser()
    need(p.is_file(), f"no seed at {p}")
    need(not p.resolve().is_relative_to(ROOT), "a seed must live outside the repository")
    return K.Key.from_seed_hex(p.read_text())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="migrate_v2_to_v3")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("identity")
    k = sub.add_parser("keygen")
    k.add_argument("--out", default=str(MIGRATOR_SEED))
    for name in ("run", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=str(ROOT))
        p.add_argument("--out", default=str(ROOT / "build" / "v3"))
    sub.choices["run"].add_argument("--claude-key", default=str(CLAUDE_SEED))
    sub.choices["run"].add_argument("--migrator-key", default=str(MIGRATOR_SEED))
    a = ap.parse_args(argv)
    try:
        why = closure_problem()
        need(why is None, f"IDENTITY: {why}")
        if a.cmd == "identity":
            print(actor())
        elif a.cmd == "keygen":
            p = Path(a.out).expanduser()
            need(not p.resolve().is_relative_to(ROOT), "a seed must live outside the repository")
            p.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            key = K.Key.generate()
            os.write(fd, key.seed_hex().encode())
            os.close(fd)
            print(json.dumps({"seed": str(p), "public": key.public, "actor": actor()}))
        elif a.cmd == "run":
            res = migrate(a.root, load_key(a.claude_key), load_key(a.migrator_key))
            write(a.out, *res)
            print(json.dumps(res[4], indent=1, sort_keys=True))
        else:
            print(json.dumps(verify(a.root, a.out), indent=1, sort_keys=True))
    except Refused as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 2
    return 0


def verify(root, out):
    """Replay (§9): re-derive the migrated records from the v2 store at `root` and compare ids with the
    store at `out`; the genesis must cite this v2 store's digest and this code's identity."""
    m = Migration(root)
    m.run()
    want = set(m.out)
    snap = Store(out).snapshot()
    have = {i for i, envs in snap.lines.items() if all(e["sig"] is None for e in envs)}
    gens = [e[0]["record"] for e in snap.lines.values() if e[0]["record"]["schema"] == R.MIGRATION]
    need(len(gens) == 1, f"{len(gens)} migration records")
    g = gens[0]["body"]
    need(g["v2"]["root"] == m.snap.digest, f"the genesis cites v2 root {g['v2']['root'][:12]}, this store is {m.snap.digest[:12]}")
    need(g["code"] == identity(), "the genesis names another migrator identity: run the code it names")
    need(have == want, f"REPLAY_DIFFERS: {len(want - have)} missing, {len(have - want)} extra")
    return {"replayed": len(want), "v2_root": m.snap.digest, "code": g["code"], "result": "IDENTICAL"}


if __name__ == "__main__":
    sys.exit(main())
