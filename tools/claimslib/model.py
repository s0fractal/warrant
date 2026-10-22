"""The claim records of a snapshot, read under a trust: each claim transition with its blob (Node),
the lineages and current claims, what is malformed (Model.problems), and the accept records
indexed by exactly what they accept (accept_index, acceptors)."""
import unicodedata

from .base import CLAIM, CLAIM_FIELDS, ID_RE, norm, PREVIOUS_FIELDS, RETIRE, RETIRE_FIELDS, sha, statement_for


class Node:
    """One claim transition: its record, its claim (or retire) blob."""

    def __init__(self, tid, rec, doc):
        self.tid, self.rec, self.doc = tid, rec, doc
        self.id = doc["id"]
        self.retired = doc["schema"] == RETIRE
        self.kind = "retired" if self.retired else doc["kind"]

    @property
    def backed(self):
        return self.kind == "normative" and bool(self.doc["witnesses"]) and bool(self.doc["mutants"])

    @property
    def status(self):
        if self.retired:
            return "RETIRED"
        if self.kind == "informative":
            return "INFORMATIVE"
        return "BACKED" if self.backed else "UNBACKED"


def authentic(snap, trust):
    """Snapshot.authentic. One command builds many Models over the same records; the store
    remembers each verdict per (trust, record id, record bytes), so each signature is checked
    once (F44; this module kept its own memo before)."""
    return snap.authentic(trust)


class Model:
    """The claims a snapshot holds under a trust, and what is wrong with them."""

    def __init__(self, snap, trust):
        self.snap = snap
        self.recs, self.bad = authentic(snap, trust)
        self.problems = []
        self.nodes = {}
        for rid, r in sorted(self.recs.items()):
            if r["type"] != "transition":
                continue
            heads = [(h, d) for h in r["body"]["evidence"] for d in [snap.json_blob(h)]
                     if isinstance(d, dict) and d.get("schema") in (CLAIM, RETIRE)]
            if not heads:
                continue
            if len(heads) > 1:
                self.problems.append(("STRUCTURE", f"transition {rid[:12]} carries {len(heads)} claim blobs"))
                continue
            h, doc = heads[0]
            why = self._shape(rid, r, h, doc)
            if why:
                self.problems.append(("STRUCTURE", f"transition {rid[:12]}: {why}"))
                continue
            self.nodes[rid] = Node(rid, r, doc)
        for n in list(self.nodes.values()):
            code, why = self._link(n)
            if why:
                self.problems.append((code, f"transition {n.tid[:12]} ({n.id}): {why}"))
                del self.nodes[n.tid]
        replaced = {s for n in self.nodes.values() for s in n.rec["body"]["supersedes"]}
        self.by_id = {}
        for n in self.nodes.values():
            self.by_id.setdefault(n.id, []).append(n)
        self.current = {}
        for cid, ns in sorted(self.by_id.items()):
            cur = [n for n in ns if n.tid not in replaced]
            if len(cur) != 1:
                self.problems.append(("FORK", f"{cid} has {len(cur)} current claims: "
                                      + ", ".join(n.tid[:12] for n in cur)))
            if cur:
                self.current[cid] = sorted(cur, key=lambda n: (n.rec["at"], n.tid))[-1]
        live = {n.tid: n for n in self.current.values()}
        self.challenges = {}
        for rid, r in sorted(self.recs.items()):
            if r["type"] == "challenge" and r["body"]["target"] in live:
                self.challenges.setdefault(live[r["body"]["target"]].id, []).append(rid)

    def _shape(self, rid, r, h, doc):
        """Why this transition is not a well-formed claim transition, or None."""
        b = r["body"]
        if b["basis"] != "ATTESTED":
            return "basis is not ATTESTED"
        if doc["schema"] == RETIRE:
            return self._retire_shape(r, h, doc)
        if set(doc) != set(CLAIM_FIELDS):
            return f"claim blob members are not {list(CLAIM_FIELDS)}"
        if not (isinstance(doc["id"], str) and ID_RE.match(doc["id"])):
            return f"claim id {doc['id']!r} is not SPEC-<section>-<n>"
        if doc["section"] != ID_RE.match(doc["id"]).group(1) or doc["source"] != "SPEC.md":
            return "section or source does not match the id"
        if not (isinstance(doc["text"], str) and doc["text"] and doc["text"] == norm(doc["text"])
                and not any(unicodedata.category(c) == "Cc" for c in doc["text"])):
            return "text must be a non-empty whitespace-normalized string with no control character"
        lists = all(isinstance(doc[k], list) and all(isinstance(x, str) for x in doc[k])
                    and doc[k] == sorted(set(doc[k])) for k in ("witnesses", "mutants"))
        if not lists:
            return "witnesses and mutants must be sorted lists of distinct strings"
        if doc["previous"] is not None and not (isinstance(doc["previous"], dict) and set(doc["previous"]) == set(PREVIOUS_FIELDS)):
            return "previous must be null or {transition, duty, statement_sha256}"
        if (doc["previous"] is None) != (doc["because"] is None) or (doc["because"] is not None and not (isinstance(doc["because"], str) and doc["because"])):
            return "a claim that replaces another says because, and only then"
        if doc["kind"] == "informative":
            if doc["duty"] is not None or not (isinstance(doc["reason"], str) and doc["reason"]) or doc["witnesses"] or doc["mutants"]:
                return "an informative claim has a reason and no duty, witnesses or mutants"
            return "an informative claim closes and establishes nothing" if b["closes"] or b["established"] else None
        if doc["kind"] != "normative":
            return "kind must be normative or informative"
        if doc["reason"] is not None and (doc["witnesses"] and doc["mutants"] or not (isinstance(doc["reason"], str) and doc["reason"])):
            return "a backed claim has no reason; an unbacked one says why it is open in a non-empty reason"
        d = self.recs.get(doc["duty"]) if isinstance(doc["duty"], str) else None
        if d is None or d["type"] != "duty":
            return "its duty is not an authentic duty record in the store"
        db = d["body"]
        if d["actor"] != r["actor"] or db["statement"] != statement_for(doc["id"], doc["text"]):
            return "the duty is not the author's duty for this sentence"
        if db["condition"] != {"attest": {}} or db["subject"] != sha(doc["text"]) or \
                self.snap.blob(db["subject"]) != doc["text"].encode():
            return "the duty's condition is not attest, or its subject is not the sentence's blob"
        if doc["witnesses"] and doc["mutants"]:
            want = [{"duty": doc["duty"], "act": "discharge", "evidence": [h]}]
            if b["closes"] != want or b["established"] != [doc["text"]]:
                return "a backed claim discharges its duty on the claim blob and establishes the sentence"
        elif b["closes"] or b["established"]:
            return "an unbacked claim closes and establishes nothing"
        return None

    def _retire_shape(self, r, h, doc):
        if set(doc) != set(RETIRE_FIELDS) or not (isinstance(doc["previous"], dict) and set(doc["previous"]) == set(PREVIOUS_FIELDS)):
            return f"retire blob members are not {list(RETIRE_FIELDS)}"
        if not (isinstance(doc["id"], str) and ID_RE.match(doc["id"]) and isinstance(doc["because"], str) and doc["because"]):
            return "a retirement names its claim and says because"
        b = r["body"]
        if b["closes"] or b["supersedes"] != [doc["previous"]["transition"]]:
            return "a retirement closes nothing and supersedes exactly the claim it retires"
        ch = self.recs.get(doc["challenge"]) if isinstance(doc["challenge"], str) else None
        if ch is None or ch["type"] != "challenge" or ch["body"]["target"] != doc["previous"]["transition"] \
                or doc["counter"] not in ch["body"]["evidence"]:
            return "its challenge is not in the store, or targets another claim, or lacks the counter-evidence"
        if not isinstance(doc["counter"], str) or not (self.snap.blob(doc["counter"]) is not None or doc["counter"] in self.recs):
            return "its counter-evidence does not resolve in the store"
        if not {doc["counter"], doc["challenge"], h} <= set(b["evidence"]):
            return "the transition does not carry its counter-evidence and challenge as evidence"
        return None

    def _link(self, n):
        """(code, why) unless a replacing claim names, in `previous` and `supersedes`, a claim of
        the same id by the same author; else (None, None)."""
        prev = n.doc["previous"]
        sup = n.rec["body"]["supersedes"]
        if prev is None:
            return ("STRUCTURE", "it supersedes something without saying what it replaces") if sup else (None, None)
        if sup != [prev["transition"]]:
            return "STRUCTURE", "supersedes does not name exactly its previous claim"
        p = self.nodes.get(prev["transition"])
        if p is None or p.id != n.id or p.retired:
            return "STRUCTURE", "its previous claim is not a live claim transition of the same id"
        if prev["duty"] != p.doc["duty"] or prev["statement_sha256"] != sha(p.doc["text"]):
            return "STRUCTURE", "previous does not repeat the replaced claim's duty and statement hash"
        # Open circle, part C: anyone may bind a key and file a counter, but a claim's lineage
        # (supersession, retirement) stays with its author: a counter lowers backing, never authorship.
        if n.rec["actor"] != p.rec["actor"]:
            return "LINEAGE_NOT_AUTHOR", (f"filed by {n.rec['actor']!r}, and the claim it replaces by {p.rec['actor']!r}: "
                                          "only a claim's author supersedes or retires it")
        return None, None

    def text_of(self, n):
        """The last sentence a claim chain stated (a retirement states none of its own)."""
        while n.retired:
            n = self.nodes[n.doc["previous"]["transition"]]
        return n.doc["text"]


def status_of(n, low):
    """A claim's status in the view: COUNTERED when a replaying counter lowers its backing (`low`)."""
    return "COUNTERED" if n.id in low else n.status


def accept_index(recs):
    """{(transition, item): {actor}} of authentic accept records, each under the evidence it
    names: an acceptance counts only for exactly that (transition, item, evidence set)."""
    out = {}
    for r in recs.values():
        if r["type"] == "accept":
            b = r["body"]
            out.setdefault((b["transition"], b["item"], tuple(sorted(b["evidence"]))), set()).add(r["actor"])
    return out


def acceptors(recs, index, tid, item):
    """The actors who accepted exactly (tid, item and that item's evidence); item None: the
    transition's results, its whole evidence (SPEC §3.3)."""
    t = recs.get(tid)
    if t is None or t["type"] != "transition":
        return []
    b = t["body"]
    if item is None:
        want = b["evidence"]
    elif 0 <= item < len(b["closes"]):
        want = b["closes"][item]["evidence"]
    else:
        return []
    want = tuple(sorted(want))
    return sorted({a for (t, i, ev), actors in index.items() if t == tid and i == item and ev == want for a in actors})
