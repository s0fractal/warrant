"""Assessment (SPEC §4): one pure function of one view.

`assess()` returns a report: every duty's disposition and candidates, every
transition's results, grants, challenges, unowned questions and the view's
identity. `reliance()`, `frontier()`, `questions()` and `capsule()` read a report."""
import heapq
from pathlib import Path

from . import jcs as C
from . import compute as P
from . import limits as L
from . import records as R
from . import store as S
from . import triggers as TR

PROFILE_FIELDS = ("uses", "accept_by", "targets", "grant_roots", "challengers", "providers")
VERDICTS = ("ADMITTED", "PENDING", "OVERCLAIMED", "MISSING_EVIDENCE", "UNMET_CONDITION", "UNVERIFIED")
RELIANCE = ("ELIGIBLE", "STALE", "CHALLENGED", "SUPERSEDED", "UNASSESSED", "NOT_CLOSED", "CONTESTED", "MISSING")
END_ID = "\U0010ffff"      # after every record id: (as_of, LAST, END_ID) is the end of the view
LAST = float("inf")        # after every rank
NEVER = (float("inf"), 0, "")
PACKAGE = Path(__file__).resolve().parent


def engine_identity():
    """Digest of every file of the evaluating code, by package-relative path: the
    same bytes installed elsewhere have the same identity."""
    files = sorted(p for p in PACKAGE.rglob("*") if p.is_file() and p.suffix in (".py", ".json")
                   and "__pycache__" not in p.parts)
    return C.doc_id({str(p.relative_to(PACKAGE)): C.digest(p.read_bytes()) for p in files})


def profile_problem(prof):
    try:
        R._fields(prof, PROFILE_FIELDS, what="profile")
        R._need(isinstance(prof["uses"], dict) and all(isinstance(k, str) and k for k in prof["uses"]), "uses")
        for need in prof["uses"].values():
            R._fields(need, ("requires_triggers",), what="use")
            R._need(type(need["requires_triggers"]) is bool, "requires_triggers")
        R._fields(prof["accept_by"], ("results",), what="profile accept_by")
        R._actors(prof["accept_by"]["results"], "accept_by.results")
        R._list(prof["targets"], "targets", R._text)
        R._hexes(prof["grant_roots"], "grant_roots")
        R._actors(prof["challengers"], "challengers")
        R._hexes(prof["providers"], "providers")
    except R.Invalid as e:
        return str(e)
    return None


def profile(uses=None, results_by=(), targets=(), grant_roots=(), challengers=(), providers=()):
    return {"uses": dict(uses or {"act": {"requires_triggers": False}}), "accept_by": {"results": list(results_by)},
            "targets": list(targets), "grant_roots": list(grant_roots), "challengers": list(challengers),
            "providers": list(providers)}


# ---------------------------------------------------------------- the view

class View:
    def __init__(self, snapshot, trust, as_of, prof, provider, cache=None, verdicts=None):
        self.snap, self.as_of, self.profile, self.provider = snapshot, as_of, prof, provider
        self.cache = cache      # the recipient's ReplayCache, or None: cost, never an answer
        good, self.invalid = snapshot.authentic(trust, verdicts)
        self.recs = {rid: r for rid, r in good.items() if r["at"] <= as_of}
        self.later = sorted(rid for rid, r in good.items() if r["at"] > as_of)
        self.by_type = {t: {} for t in R.TYPES}
        for rid, r in self.recs.items():
            self.by_type[r["type"]][rid] = r
        self.duties = self.by_type["duty"]
        self.transitions = self.by_type["transition"]
        self.missing = set()
        self.matched = {}       # (transition, item) -> window ends of the observations that met its condition
        self._chains(set(self.later))
        self._ranks()

    def _chains(self, later):
        """Each actor's chain (SPEC §3): `link` holds where a record's `prev` is in the view, by
        the same actor, and not dated after it; any other `prev` leaves the record unanchored.
        Two records of one actor naming the same `prev` are a fork: listed, neither excluded."""
        self.link, self.unanchored, self.unchained, groups = {}, {}, {}, {}
        for rid, r in sorted(self.recs.items()):
            if "prev" not in r:
                self.unchained[r["actor"]] = self.unchained.get(r["actor"], 0) + 1
                continue
            groups.setdefault((r["actor"], r["prev"] or ""), []).append(rid)
            if r["prev"] is None:                   # the actor's first record: a genesis
                continue
            q = self.recs.get(r["prev"])
            if q is None:
                self.unanchored[rid] = "its prev is dated after this view" if r["prev"] in later else "its prev is not in the view"
                if r["prev"] not in later:
                    self.missing.add(r["prev"])
            elif q["actor"] != r["actor"]:
                self.unanchored[rid] = "its prev was filed by another actor"
            elif q["at"] > r["at"]:
                self.unanchored[rid] = "it is dated before its prev"
            else:
                self.link[rid] = r["prev"]
        self.forks = [{"actor": a, "prev": p or None, "records": ids} for (a, p), ids in sorted(groups.items()) if len(ids) > 1]
        self.height = {}
        for start in self.recs:
            path, x = [], start
            while x not in self.height and x in self.link:
                path.append(x)
                x = self.link[x]
            h = self.height.setdefault(x, 0)
            for y in reversed(path):
                h += 1
                self.height[y] = h

    def _ranks(self):
        """The order of the records that share an `at` (SPEC §4): by id, except that a record
        chained to a predecessor with the same `at` follows it."""
        self.rank, groups = {}, {}
        for rid, r in self.recs.items():
            groups.setdefault(r["at"], []).append(rid)
        for at, ids in groups.items():
            kids, ready = {}, []
            for rid in ids:
                p = self.link.get(rid)
                if p is not None and self.recs[p]["at"] == at:
                    kids.setdefault(p, []).append(rid)
                else:
                    ready.append(rid)
            heapq.heapify(ready)
            while ready:
                x = heapq.heappop(ready)
                self.rank[x] = len(self.rank)
                for k in kids.get(x, ()):
                    heapq.heappush(ready, k)

    def pos(self, rid):
        return (self.recs[rid]["at"], self.rank[rid], rid)

    def before(self, a, b):
        """a is a chain ancestor of b: an order the records witness themselves (SPEC §3)."""
        if a == b or a not in self.height or b not in self.height or self.height[a] >= self.height[b]:
            return False
        while self.height[b] > self.height[a]:
            b = self.link[b]
        return a == b

    def ordered(self, a, b):
        """The chain orders a and b (same actor): one is the other or its ancestor."""
        return a == b or self.before(a, b) or self.before(b, a)

    def accepts_by(self, t_id, index, evidence, actor):
        """The acceptances by `actor` binding exactly (t_id, index, evidence)."""
        want = sorted(evidence)
        return sorted(rid for rid, r in self.by_type["accept"].items() if r["actor"] == actor
                      and r["body"]["transition"] == t_id and r["body"]["item"] == index and sorted(r["body"]["evidence"]) == want)

    def resolves(self, h):
        return h in self.snap.blobs or h in self.recs

    def accepted_at(self, t_id, index, evidence):
        """{actor: earliest position} of acceptances binding exactly (t_id, index, evidence)."""
        out = {}
        want = sorted(evidence)
        for rid, r in self.by_type["accept"].items():
            b = r["body"]
            if b["transition"] == t_id and b["item"] == index and sorted(b["evidence"]) == want:
                p = self.pos(rid)
                if r["actor"] not in out or p < out[r["actor"]]:
                    out[r["actor"]] = p
        return out

    def support(self, t_id, index):
        return {r["actor"]: r["body"]["support"] for r in self.by_type["accept"].values()
                if r["body"]["transition"] == t_id and r["body"]["item"] == index and r["body"]["support"]}


# ---------------------------------------------------------------- grants (SPEC §4.5)

MAX_CHAIN = 16


def grant_state(view, gid, pos, depth=0):
    """The grant's state at position `pos` = (at, id), compared as positions (SPEC §4):
    a grant filed at the same `at` with a larger id is after `pos` (Gemini review, C)."""
    rec = view.by_type["grant"].get(gid)
    if rec is None:
        return "BROKEN_CHAIN", "grant not in view"
    g = rec["body"]
    if view.pos(gid) > pos:
        return "NOT_YET", "granted after this position"
    if g["expires"] is not None and pos[0] >= g["expires"]:
        return "EXPIRED", f"expired at {g['expires']}"
    if g["parent"] is None:
        return ("VALID", "root") if gid in view.profile["grant_roots"] else ("UNGROUNDED", "a root the recipient has not accepted")
    if depth >= MAX_CHAIN:
        return "BROKEN_CHAIN", "chain too long"
    pst, why = grant_state(view, g["parent"], view.pos(gid), depth + 1)      # the parent at the CHILD's position
    if pst != "VALID":
        return ("BROKEN_CHAIN" if pst in ("BROKEN_CHAIN", "UNGROUNDED", "NOT_YET") else pst, f"parent {g['parent'][:12]}: {why}")
    why = _attenuation_problem(rec["actor"], g, view.by_type["grant"][g["parent"]]["body"])
    return ("NOT_ATTENUATED", why) if why else ("VALID", "attenuated")


def _attenuation_problem(grantor, g, p):
    if grantor != p["grantee"]:
        return "the grantor is not the parent's grantee"
    if not set(g["acts"]) <= set(p["delegable"]):
        return "acts the parent did not make delegable"
    if not set(g["delegable"]) <= set(p["delegable"]):
        return "delegable beyond the parent's"
    if not set(g["duties"]) <= set(p["duties"]):
        return "duties beyond the parent's"
    if p["expires"] is not None and (g["expires"] is None or g["expires"] > p["expires"]):
        return "expires later than the parent"
    return None


def authorized(view, actor, act, duty_id, pos):
    reasons = []
    for gid, rec in sorted(view.by_type["grant"].items()):
        g = rec["body"]
        if g["grantee"] != actor or act not in g["acts"] or duty_id not in g["duties"]:
            continue
        st, why = grant_state(view, gid, pos)
        if st == "VALID":
            return gid, None
        reasons.append(f"{gid[:12]}: {st} ({why})")
    return None, "; ".join(reasons) if reasons else f"no grant gives {actor} {act} on this duty"


# ---------------------------------------------------------------- one duty

def _items(view, did):
    out = []
    for t_id, t in view.transitions.items():
        for i, m in enumerate(t["body"]["closes"]):
            if m["duty"] == did:
                out.append((t_id, t, i, m))
    return sorted(out, key=lambda x: (view.pos(x[0]), x[2]))


def _admission_pos(view, d, t_id, i, m):
    """The latest of the item's own position and the earliest acceptance by each
    required acceptor; None while one is missing (SPEC §4.2)."""
    pos = view.pos(t_id)
    got = view.accepted_at(t_id, i, m["evidence"])
    for actor in d["accept_by"]:
        if actor not in got:
            return None
        pos = max(pos, got[actor])
    return pos


def _awaited(groups):
    """The acceptances still missing, as actor sets: each group is one acceptance, given by
    any one actor in it. A group that contains another is dropped: whoever gives the
    smaller one gives it too (to = an owed_to actor; an acceptor who is also owed_to)."""
    gs = sorted({tuple(sorted(set(g))) for g in groups})
    return [list(g) for g in gs if not any(set(h) < set(g) for h in gs)]


def _waiting_why(groups):
    return "waiting for " + "; ".join(g[0] if len(g) == 1 else "one of " + ", ".join(g) for g in groups)


def _transfer_effect(view, d, t_id, i, m):
    """(effect position, None) once every required consent exists, else (None, missing):
    the missing consents as actor sets (_awaited), never as text (Gemini review, B)."""
    got = view.accepted_at(t_id, i, m["evidence"])
    missing = []
    pos = view.pos(t_id)
    if m["to"] not in got:
        missing.append([m["to"]])
    else:
        pos = max(pos, got[m["to"]])
    if m["act"] == "substitute":
        creditors = [got[a] for a in set(d["owed_to"]) | set(d["release_by"]) if a in got]
        if not creditors:
            missing.append(sorted(set(d["owed_to"]) | set(d["release_by"])))
        else:
            pos = max(pos, min(creditors))
    missing = _awaited(missing)
    return (None, missing) if missing else (pos, None)


class Holders:
    """Holder and delegates as a function of position (SPEC §4.1): the admitted transfers
    whose effect position is not after it, applied in effect order. For a filing, the
    filer's own records count in its chain's order, not by the `at` they claim (F43):
    a transfer to the filer counts only once an acceptance of it by the filer is a chain
    ancestor of the filing, and a transfer by the filer that the chain does not order
    against the filing counts as in effect, wherever its position is."""

    def __init__(self, view, holder):
        self.view, self.holder, self.transfers = view, holder, []

    def at(self, pos, filing=None):
        h, dl = self.holder, set()
        x = self.view.recs[filing]["actor"] if filing is not None else None
        for eff, t_id, act, frm, to, accepts in sorted(self.transfers, key=lambda e: e[0]):
            on = eff <= pos
            if x == to != frm:
                on = on and any(self.view.before(a, filing) for a in accepts)
            elif x == frm != to and not on:
                on = not self.view.ordered(t_id, filing)
            if on:
                h, dl = (h, dl | {to}) if act == "delegate" else (to, set())
        return h, frozenset(dl)

    def add(self, eff, t_id, m, accepts):
        self.transfers.append((eff, t_id, m["act"], self.view.recs[t_id]["actor"], m["to"], accepts))


def _observations(view, m, cond, filer, window):
    """The observation records cited by `m` that meet the observe condition."""
    good, why = [], "no cited observation meets the condition"
    for h in m["evidence"]:
        rec = view.by_type["observation"].get(h)
        if rec is None:
            continue
        o = rec["body"]
        if rec["actor"] not in cond["observers"]:
            why = f"observed by {rec['actor']}, who is not a named observer"
        elif rec["actor"] == filer:
            why = "the filer cannot observe its own closure"
        elif o["probe"] != cond["probe"]:
            why = "observed with another probe"
        elif o["result"] != cond["expect"]:
            why = f"observed {o['result']!r}, not {cond['expect']!r}"
        elif window and not (window[0] <= o["window"][0] and o["window"][1] < window[1]):
            why = "observed outside the period"
        else:
            good.append((h, rec))
    return good, why


def V(verdict, why="", label=None, waiting=None):
    """One candidate's verdict: always the same four fields. `waiting`, for PENDING, is the
    missing acceptances as actor sets (_awaited)."""
    return verdict, why, label, waiting


def _replayed(view, cond, m):
    want = "cycle" if m["act"] == "impossible" else "receipt"
    docs = [x for x in (view.snap.json_blob(h) for h in m["evidence"]) if isinstance(x, dict) and x.get(want) == "sigma-resume"]
    if len(docs) != 1:
        return V("MISSING_EVIDENCE", f"a REPLAYED item cites exactly one {want}")
    if view.provider is None:
        return V("UNVERIFIED", "no provider in this view")
    if view.provider.id not in view.profile["providers"]:
        return V("UNVERIFIED", f"provider {view.provider.id[:16]} is not one this recipient accepts")
    fn = P.replay_cycle if want == "cycle" else P.replay
    try:
        label, why = fn(view.provider, view.snap, cond, docs[0], view.profile["targets"], cache=view.cache)
    except P.ProviderError as e:
        return V("UNVERIFIED", str(e))
    return V("ADMITTED", label=label) if label else V("UNVERIFIED", why)


BASIS_OF = {"attest": "ATTESTED", "observe": "OBSERVED", "compute": "REPLAYED"}
WRONG_BASIS = {"attest": "{} is not the basis this condition admits",
               "observe": "this condition is met by an observation, not by the filer's word",
               "compute": "a computation is met by the recipient's own replay"}


def _basis(view, d, m, t, filer, window, key):
    """V("ADMITTED", label=...) if the item's basis meets the duty's condition."""
    basis = t["body"]["basis"]
    kind, cond = next(iter(d["condition"].items()))
    if m["act"] == "impossible" and kind != "compute":
        return V("ADMITTED", label=f"ATTESTED:{filer}") if basis == "ATTESTED" else \
            V("OVERCLAIMED", "an impossibility is attested")
    if basis != BASIS_OF[kind]:
        return V("OVERCLAIMED", WRONG_BASIS[kind].format(basis))
    if kind == "attest":
        return V("ADMITTED", label=f"ATTESTED:{filer}")
    if kind == "observe":
        good, why = _observations(view, m, cond, filer, window)
        view.matched[key] = [rec["body"]["window"][1] for _, rec in good]
        return V("ADMITTED", label="OBSERVED:" + ",".join(sorted({rec["actor"] for _, rec in good}))) if good \
            else V("UNMET_CONDITION", why)
    return _replayed(view, cond, m)


def _period_window(d, m):
    s = d["schedule"]
    if s is None:
        return None
    n = m["period"]
    return [s["start"] + n * s["every"], s["start"] + (n + 1) * s["every"]]


def _shape_problem(d, m, t, window, admitted):
    """A reason this item cannot close this duty whatever its evidence, or None."""
    sched = d["schedule"]
    if m["act"] == "discharge" and (sched is None) != ("period" not in m):
        return "a scheduled duty is discharged per period, and only a scheduled one"
    if m["act"] in ("impossible", "revalidate") and sched is not None:
        return f"{m['act']} is not defined for a scheduled duty here"
    if window and t["at"] < window[0]:
        return "a period cannot be discharged before it starts"
    if m["act"] == "revalidate" and not admitted:
        return "nothing admitted to revalidate"
    if m["act"] == "revalidate" and not set(m["revalidates"]) <= set(admitted):
        return "revalidates something that is not an admitted closure of this duty"
    return None


def _judge_closure(view, d, t_id, t, i, m, holders, done, admitted):
    filer = t["actor"]
    holder, delegates = holders.at(view.pos(t_id), t_id)
    if filer != holder and filer not in delegates:
        return V("OVERCLAIMED", "filed by someone who did not hold the duty at that position")
    window = _period_window(d, m) if "period" in m else None
    why = _shape_problem(d, m, t, window, admitted)
    if why:
        return V("OVERCLAIMED", why)
    v = _basis(view, d, m, t, filer, window, (t_id, i))
    if v[0] != "ADMITTED":
        return v
    label = v[2]
    unmet = [c for c in d["requires"] if done.get(c) != "DISCHARGED"] if m["act"] in ("discharge", "revalidate") else []
    if unmet:
        return V("UNMET_CONDITION", "required duties not discharged: " + ", ".join(u[:12] for u in unmet))
    got = set(view.accepted_at(t_id, i, m["evidence"]))
    missing = [[a] for a in sorted(set(d["accept_by"]) - got)]
    # An attested impossibility also needs ONE owed_to actor (SPEC §4.2), not every one.
    if m["act"] == "impossible" and label.startswith("ATTESTED") and not set(d["owed_to"]) & got:
        missing.append(sorted(set(d["owed_to"])))
    missing = _awaited(missing)
    if missing:
        return V("PENDING", _waiting_why(missing), waiting=missing)
    return V("ADMITTED", label=label)


def _transfers(view, d, items, holders, verdicts):
    """Delegations and substitutions, applied in order of effect position: the filer
    must hold the duty both when it files and when the transfer takes effect."""
    transfers = []
    for t_id, t, i, m in items:
        if m["act"] in ("delegate", "substitute"):
            eff, missing = _transfer_effect(view, d, t_id, i, m)
            transfers.append((eff or NEVER, t_id, t, i, m, missing))
    for eff, t_id, t, i, m, missing in sorted(transfers, key=lambda x: (x[0], view.pos(x[1]), x[3])):
        verdicts[(t_id, i)] = _transfer(view, holders, eff, t_id, t, i, m, missing)


def _transfer(view, holders, eff, t_id, t, i, m, missing):
    h_file, _ = holders.at(view.pos(t_id), t_id)
    if t["actor"] != h_file:
        return V("OVERCLAIMED", "only the holder at that position transfers or delegates")
    if missing:
        return V("PENDING", _waiting_why(missing), waiting=missing)
    h_eff, _ = holders.at(eff, t_id)
    if h_eff != t["actor"]:
        return V("OVERCLAIMED", "the filer no longer held the duty when the transfer would take effect")
    holders.add(eff, t_id, m, view.accepts_by(t_id, i, m["evidence"], m["to"]))
    return V("ADMITTED")


def _release(view, did, d, t_id, t):
    # One statement per rule, so a counter blob's locality can tell them apart (AMEND 1 of #169).
    if t["actor"] in d["owed_to"]:
        return V("ADMITTED", label=f"RELEASE:{t['actor']}")
    if t["actor"] in d["release_by"]:
        return V("ADMITTED", label=f"RELEASE:{t['actor']}")
    gid, why = authorized(view, t["actor"], "release", did, view.pos(t_id))
    if gid:
        return V("ADMITTED", f"by grant {gid[:12]}", f"RELEASE_BY_GRANT:{gid[:12]}")
    return V("OVERCLAIMED", f"not authorized to release: {why}")


def _closures(view, did, d, items, holders, done, verdicts):
    """Releases and closures; revalidations last, in their own admission order (RV-01)."""
    admitted = {}           # transition id -> admission position, of admitted discharges/revalidations
    first = [x for x in items if x[3]["act"] not in ("delegate", "substitute", "revalidate")]
    reval = sorted((x for x in items if x[3]["act"] == "revalidate"),
                   key=lambda x: _admission_pos(view, d, x[0], x[2], x[3]) or (LAST, 0, x[0]))
    for t_id, t, i, m in first + reval:
        if not all(view.resolves(h) for h in m["evidence"]):
            verdicts[(t_id, i)] = V("MISSING_EVIDENCE", "cited evidence is not in the view")
        elif m["act"] == "release":
            verdicts[(t_id, i)] = _release(view, did, d, t_id, t)
        else:
            v = _judge_closure(view, d, t_id, t, i, m, holders, done, admitted)
            if v[0] == "ADMITTED" and m["act"] == "revalidate":
                v = _revalidation_order(view, d, t_id, i, m, admitted) or v
            if v[0] == "ADMITTED" and m["act"] in ("discharge", "revalidate"):
                admitted[t_id] = _admission_pos(view, d, t_id, i, m)
            verdicts[(t_id, i)] = v


def _revalidation_order(view, d, t_id, i, m, admitted):
    mine = _admission_pos(view, d, t_id, i, m)
    late = [x for x in m["revalidates"] if admitted[x] >= mine]
    if late:
        return V("OVERCLAIMED", "revalidates a closure not admitted before it (admission order): "
                 + ", ".join(x[:12] for x in late))
    return None


def _candidates(view, out, items, verdicts):
    """The report rows, and the admitted closures sorted by kind."""
    closures, periods, revals = [], {}, []
    for t_id, t, i, m in items:
        verdict, why, label, waiting = verdicts[(t_id, i)]
        cand = {"transition": t_id, "item": i, "act": m["act"], "filer": t["actor"], "basis": t["body"]["basis"],
                "verdict": verdict, "why": why}
        if waiting:
            # waiting_for: everyone whose acceptance could still be needed; awaiting: the
            # missing acceptances, each a list of actors any one of whom gives it.
            cand["waiting_for"] = sorted({a for g in waiting for a in g})
            cand["awaiting"] = waiting
        sup = view.support(t_id, i)
        if sup:
            cand["acceptor_support"] = sup
        out["candidates"].append(cand)
        if verdict != "ADMITTED":
            continue
        if m["act"] == "revalidate":
            revals.append((t_id, t, m, label, i))
        elif m["act"] in ("discharge", "impossible", "release") and "period" in m:
            periods.setdefault(m["period"], (t_id, label))
        elif m["act"] in ("discharge", "impossible", "release"):
            closures.append((m["act"], t_id, t, m, label, i))
    return closures, periods, revals


FLAG_OF = (("PENDING", "PENDING_ACCEPTANCE"), ("OVERCLAIMED", "OVERCLAIMED_CANDIDATE"),
           ("UNVERIFIED", "UNVERIFIED_CANDIDATE"), ("UNMET_CONDITION", "UNMET_CANDIDATE"))


def _assess_duty(view, did, rec, done):
    d = rec["body"]
    out = {"statement": d["statement"], "holder": d["holder"], "owed_to": d["owed_to"], "accept_by": d["accept_by"],
           "release_by": d["release_by"], "condition": next(iter(d["condition"])), "subject": d["subject"],
           "schedule": d["schedule"], "disposition": "OPEN", "closed_by": [], "assessed_basis": [],
           "candidates": [], "flags": [], "triggers": [], "revalidations": [],
           "requires": d["requires"], "serves": d["serves"],
           "fresh_for": d["condition"].get("observe", {}).get("fresh_for")}
    items = _items(view, did)
    holders = Holders(view, d["holder"])
    verdicts = {}
    _transfers(view, d, items, holders, verdicts)
    _closures(view, did, d, items, holders, done, verdicts)
    closures, periods, revals = _candidates(view, out, items, verdicts)
    h, dl = holders.at(NEVER)
    out["holder"], out["delegates"] = h, sorted(dl)
    _disposition(view, out, d, closures, revals, periods)
    out["flags"] += [flag for verdict, flag in FLAG_OF if any(c["verdict"] == verdict for c in out["candidates"])]
    return out


KIND_OF = {"discharge": "DISCHARGED", "impossible": "IMPOSSIBLE", "release": "RELEASED"}


def _disposition(view, out, d, closures, revals, periods):
    kinds = sorted({KIND_OF[c[0]] for c in closures})
    if d["schedule"] is not None:
        out["periods"] = _periods(view, d, periods, out)
        out["disposition"] = "RELEASED" if "RELEASED" in kinds else "SCHEDULED"
        out["closed_by"] = [c[1] for c in closures] + [v[0] for v in periods.values()]
        return
    out["closed_by"] = [c[1] for c in closures]
    if len(kinds) > 1:
        out["disposition"], out["dispositions"] = "CONTESTED", kinds
        out["flags"].append("CONTESTED")
        return
    if not kinds:
        return
    out["disposition"] = kinds[0]
    chosen = [c for c in closures if KIND_OF[c[0]] == kinds[0]]
    out["assessed_basis"] = sorted({c[4] for c in chosen})
    if kinds[0] != "DISCHARGED":
        revals = []
    superseded = {x for r in revals for x in r[2]["revalidates"]}
    rows = [(c[1], c[2], c[3]) for c in chosen] + [(r[0], r[1], r[2]) for r in revals]
    out["revalidations"] = [{"transition": r[0], "revalidates": r[2]["revalidates"], "assessed_basis": r[3]}
                            for r in revals]
    out["current_closures"] = [tid for tid, _, _ in rows if tid not in superseded]
    # A challenge targets one closure: a (transition, item) pair (SPEC §3.6, §4.4).
    items = [(c[1], c[5]) for c in chosen] + [(r[0], r[4]) for r in revals]
    out["current_items"] = [[tid, i] for tid, i in items if tid not in superseded]
    out["declared_triggers"] = [{"closure": tid, "trigger": tr, "current": tid not in superseded}
                                for tid, _, m in rows for tr in m.get("triggers", [])]
    out["closure_subjects"] = sorted({t["body"]["subject"] for tid, t, _ in rows
                                      if tid not in superseded and t["body"]["subject"]})
    # Freshness counts only the observations that met the condition (R138-01):
    # another observer's, the filer's own, another probe's or another result's
    # record cited alongside does not refresh a closure.
    obs = [end for tid, t, m in rows if tid not in superseded
           for end in view.matched.get((tid, t["body"]["closes"].index(m)), [])]
    out["observed_until"] = max(obs) if obs else None


def period_count(schedule, as_of):
    """Period entries of a schedule at as_of: every n with start + n·every ≤ as_of."""
    return 0 if as_of < schedule["start"] else (as_of - schedule["start"]) // schedule["every"] + 1


def _admit(view, lim):
    """Refuse a view whose assessment would exceed an admission limit, before the
    work: requires edges the traversal follows, period entries per duty and per
    report (SPEC §9). At b64c007 one duty with start 0, every 1 gave 100001 period
    entries at as_of 100000 (Codex F2)."""
    L.admit(lim, "requires_edges", sum(len(r["body"]["requires"]) for r in view.duties.values()))
    total = 0
    for rec in view.duties.values():
        if rec["body"]["schedule"] is not None:
            n = period_count(rec["body"]["schedule"], view.as_of)
            L.admit(lim, "duty_periods", n)
            total += n
    L.admit(lim, "report_periods", total)


def _periods(view, d, periods, out):
    s = d["schedule"]
    report = {}
    n = 0
    while s["start"] + n * s["every"] <= view.as_of:
        end = s["start"] + (n + 1) * s["every"]
        if n in periods:
            report[str(n)] = {"state": "COVERED", "by": periods[n][0], "basis": periods[n][1]}
        else:
            report[str(n)] = {"state": "LAPSED" if end <= view.as_of else "OPEN"}
        n += 1
    if any(p["state"] == "LAPSED" for p in report.values()):
        out["flags"].append("LAPSED")
    return report


# ---------------------------------------------------------------- whole view

def _assess_duties(view):
    """Every duty after the duties it requires, depth first in sorted order. A duty
    on the current path (a cycle) is not waited for: its dependant is assessed
    without it, so the requirement is unmet. An explicit stack, not recursion: a
    valid chain of 3000 requires overflowed Python's stack at b64c007 (Codex F1)."""
    report, done = {}, {}
    for root in sorted(view.duties):
        if root in report:
            continue
        busy = {root}
        stack = [(root, iter(view.duties[root]["body"]["requires"]))]
        while stack:
            did, children = stack[-1]
            for c in children:
                if c in view.duties and c not in report and c not in busy:
                    busy.add(c)
                    stack.append((c, iter(view.duties[c]["body"]["requires"])))
                    break
            else:
                stack.pop()
                busy.discard(did)
                report[did] = _assess_duty(view, did, view.duties[did], done)
                done[did] = report[did]["disposition"]
    return report


def _results(view):
    """Each transition's results: who accepted them, and what supersedes them."""
    need = set(view.profile["accept_by"]["results"])
    out = {}
    for t_id, t in sorted(view.transitions.items()):
        got = view.accepted_at(t_id, None, t["body"]["evidence"])
        out[t_id] = {"actor": t["actor"], "at": t["at"], "basis": t["body"]["basis"],
                     "established": t["body"]["established"], "residual": t["body"]["residual"],
                     "subject": t["body"]["subject"], "evidence": t["body"]["evidence"], "accepted_by": sorted(got),
                     "accepted": bool(need) and need <= set(got), "superseded_by": [],
                     "triggers": [], "challenges": []}
    for t_id, t in view.transitions.items():
        for old in t["body"]["supersedes"]:
            if old not in out:
                view.missing.add(old)
            elif out[t_id]["accepted"]:
                out[old]["superseded_by"].append(t_id)
    return out


def _counter_observation(view, b):
    """An evidence-weighted challenge (SPEC §4.4): the challenge cites an observation of the
    duty's own probe, by anyone but the closure's filer, that saw something other than
    `expect`, no earlier than the latest observation that met the condition. Who filed the
    challenge does not matter: the probe ran again and disagreed. Only `observe` conditions
    have such counter-evidence; a compute closure is settled by the recipient's own replay,
    and an attested one has no mechanical counter."""
    t = view.transitions[b["target"]]
    items = t["body"]["closes"]
    if not (type(b["item"]) is int and 0 <= b["item"] < len(items)):
        return None
    d = view.duties.get(items[b["item"]]["duty"])
    if d is None or "observe" not in d["body"]["condition"]:
        return None
    cond = d["body"]["condition"]["observe"]
    latest = max(view.matched.get((b["target"], b["item"]), []), default=None)
    for h in b["evidence"]:
        rec = view.by_type["observation"].get(h)
        if rec is None or rec["actor"] == t["actor"]:
            continue
        o = rec["body"]
        if o["probe"] != cond["probe"] or o["result"] == cond["expect"]:
            continue
        if latest is not None and o["window"][1] < latest:
            continue
        return {"observation": h, "actor": rec["actor"], "result": o["result"], "window": o["window"]}
    return None


def _challenges(view, results):
    out = {}
    for cid, c in sorted(view.by_type["challenge"].items()):
        b = c["body"]
        if b["target"] not in view.transitions:
            view.missing.add(b["target"])
            continue
        out[cid] = {"actor": c["actor"], "at": c["at"], "target": b["target"], "item": b["item"],
                    "statement": b["statement"], "evidence": b["evidence"],
                    "counter_observation": _counter_observation(view, b) if b["item"] is not None else None}
        if b["item"] is None:
            results[b["target"]]["challenges"].append(cid)
    return out


def _evaluate_triggers(view, duties, results, workspace):
    dispositions = {did: r["disposition"] for did, r in duties.items()}

    def run(tr):
        result, detail = TR.evaluate(tr, view.snap.json_blob, workspace, dispositions)
        if result not in TR.RESULTS:
            raise ValueError(f"trigger result outside its vocabulary: {result}")
        return result, detail

    for r in duties.values():
        r["triggers"] += [dict({"closure": item["closure"]}, **item["trigger"], **dict(zip(("result", "detail"), run(item["trigger"]))),
                               current=item["current"]) for item in r.pop("declared_triggers", [])]
        if r["disposition"] == "DISCHARGED":
            cur = [t for t in r["triggers"] if t["current"]]
            r["trigger_coverage"] = "NONE_DECLARED" if not cur else {k: sum(t["result"] == k for t in cur) for k in TR.RESULTS}
    for t_id, r in results.items():
        for tr in view.transitions[t_id]["body"]["triggers"]:
            result, detail = run(tr)
            r["triggers"].append({**tr, "result": result, "detail": detail, "current": True})


def _questions(view, duties):
    taken = {view.duties[did]["body"]["answers"] for did in duties if view.duties[did]["body"]["answers"]}
    out = []
    for t_id, t in sorted(view.transitions.items()):
        for i, q in enumerate(t["body"]["opened"]):
            ref = f"{t_id}:{i}"
            out.append({"question": ref, "text": q["text"], "scope": q["scope"], "opened_by": t["actor"],
                        "taken_by": sorted(did for did in duties if view.duties[did]["body"]["answers"] == ref),
                        "owned": ref in taken})
    return out


def assess(snapshot, trust, as_of, prof, current=(), workspace=None, provider=None, replay_cache=None, limits=None,
           verdicts=None):
    """Assess one view. `current` is the set of revisions the recipient treats as
    current; `workspace` is (repository path, commit) for subject_changed triggers;
    `provider` is a captured compute.Provider (None: replays are UNVERIFIED);
    `replay_cache` is a directory of this recipient's earlier verified replays
    (SPEC §7: it changes cost, never the answer or the task; not part of the
    assessment identity); `verdicts` is a directory of this recipient's earlier
    authentication verdicts (store.Verdicts.at, F44: cost only in the same way);
    `limits` overrides the admission limits (limits.DEFAULTS; operational, not an
    operand: exceeding one raises limits.LimitExceeded and nothing is assessed)."""
    why = profile_problem(prof)
    if why:
        raise ValueError(f"profile: {why}")
    lim = L.resolve(limits)
    snapshot.admit(lim)
    ws = TR.Workspace(*workspace) if workspace is not None else None
    index = S.Verdicts.at(verdicts) if verdicts is not None else None
    view = View(snapshot, trust, as_of, prof, provider,
                cache=P.ReplayCache(replay_cache) if replay_cache is not None else None, verdicts=index)
    if index is not None:
        index.flush(snapshot)
    _admit(view, lim)
    duties = _assess_duties(view)
    for did, r in duties.items():
        for x in view.duties[did]["body"]["requires"] + view.duties[did]["body"]["serves"]:
            if x not in view.duties:
                view.missing.add(x)
    for t in view.transitions.values():
        for m in t["body"]["closes"]:
            if m["duty"] not in view.duties:
                view.missing.add(m["duty"])
    results = _results(view)
    challenges = _challenges(view, results)
    _evaluate_triggers(view, duties, results, ws)
    for r in duties.values():
        bad = {c["verdict"] for c in r["candidates"]} - set(VERDICTS)
        if bad:
            raise ValueError(f"verdict outside its vocabulary: {sorted(bad)}")
    ident = {"snapshot": snapshot.digest, "trust": trust.digest, "profile": C.doc_id(prof), "as_of": as_of,
             "current": sorted(current), "workspace": ws.identity() if ws else None,
             "engine": engine_identity(), "provider": provider.identity if provider else None}
    named = {a for rec in view.duties.values() for f in ("holder", "owed_to", "accept_by", "release_by")
             for a in ([rec["body"][f]] if isinstance(rec["body"][f], str) else rec["body"][f])}
    bound = {actor for actor, _ in trust.keys.values()}
    return {"warrant": "report/2", "assessment_id": C.doc_id(ident), "view": dict(ident, completeness="UNATTESTED"),
            # Actors the duties name who have no key in this trust: nothing they
            # sign can count in this view (found in the 2026-10-18 handoff).
            "unbound_actors": sorted(named - bound),
            "profile": prof, "duties": duties, "results": results, "challenges": challenges,
            "grants": {g: grant_state(view, g, (as_of, LAST, END_ID))[0] for g in sorted(view.by_type["grant"])},
            "questions": _questions(view, duties), "invalid_records": view.invalid,
            "later_records": view.later, "misfiled": snapshot.misfiled, "missing": sorted(view.missing),
            # Each actor's chain (SPEC §3): what the records order themselves, and what they do not.
            "chains": {"forks": view.forks, "unanchored": view.unanchored, "unchained": view.unchained}}


# ---------------------------------------------------------------- reading a report

def _counting_challenges(rep, closures, duty=None):
    """Challenges that count against these closures, {(transition, item)}: a challenge
    names one closure, the item it gives; one with item null concerns the transition's
    results, not its closures (Gemini review, A). A challenge against a closure that an
    admitted revalidation superseded no longer counts: that closure is not current any
    more, and the revalidation needed the same acceptances."""
    counts = set(rep["profile"]["challengers"])
    if duty is not None:
        counts |= set(duty["owed_to"]) | set(duty["accept_by"])
    # One statement per rule, so a counter blob's locality can tell them apart (AMEND 1 of #169).
    out = []
    for cid, c in rep["challenges"].items():
        if (c["target"], c["item"]) not in closures:     # another closure, or the results (item null)
            continue
        weighted = bool(c.get("counter_observation"))   # evidence-weighted: whoever filed it (SPEC §4.4)
        counted = c["actor"] in counts                  # actor-weighted (SPEC §4.6)
        if weighted or counted:
            out.append(cid)
    return sorted(out)


def _revision_basis(subjects, triggers, current):
    if not subjects:
        return True
    if any(s in current for s in subjects):
        return True
    return any(t["kind"] == "subject_changed" and t["result"] == "NOT_FIRED" for t in triggers)


def _trigger_state(cur, use_need):
    if use_need and not cur:
        return "UNASSESSED", ["the use requires declared triggers; none are current"]
    fired = [f"{t['kind']}: {t['detail']}" for t in cur if t["result"] == "FIRED"]
    if fired:
        return "STALE", fired
    unknown = [f"{t['kind']}: {t['detail']}" for t in cur if t["result"] == "UNEVALUABLE"]
    if unknown:
        return "UNASSESSED", unknown
    return None


def _challenged(rep, ids):
    return ("CHALLENGED", [f"challenge {c[:12]}: {rep['challenges'][c]['statement']}" for c in ids]) if ids else None


def _duty_checks(rep, r, use):
    """The reliance checks of a duty, in order; each returns (state, causes) or None."""
    cur = [t for t in r["triggers"] if t["current"]]
    yield ("CONTESTED", []) if r["disposition"] == "CONTESTED" else None
    yield ("NOT_CLOSED", [f"disposition {r['disposition']}"]) if r["disposition"] != "DISCHARGED" else None
    yield _unknown_use(rep, use)
    yield _challenged(rep, _counting_challenges(rep, {tuple(x) for x in r["current_items"]}, r))
    yield _trigger_state(cur, rep["profile"]["uses"][use]["requires_triggers"])
    yield _freshness(rep, r)
    subjects = r["closure_subjects"] or ([r["subject"]] if r["subject"] else [])
    yield None if _revision_basis(subjects, cur, set(rep["view"]["current"])) else \
        ("UNASSESSED", ["no revision basis: not established on a current revision, "
                        "and no subject_changed trigger evaluated NOT_FIRED"])


def _result_checks(rep, r, use):
    """The reliance checks of a transition's results, in order."""
    need = set(rep["profile"]["accept_by"]["results"])
    yield ("SUPERSEDED", [f"superseded by {', '.join(x[:12] for x in r['superseded_by'])}"]) if r["superseded_by"] else None
    yield None if need else ("UNASSESSED", ["the profile names nobody whose acceptance closes results"])
    yield None if r["accepted"] else ("NOT_CLOSED", ["results not accepted by " + ", ".join(sorted(need - set(r["accepted_by"])))])
    yield _unknown_use(rep, use)
    counts = set(rep["profile"]["challengers"]) | need
    yield _challenged(rep, [c for c in r["challenges"] if rep["challenges"][c]["actor"] in counts])
    yield _trigger_state(r["triggers"], rep["profile"]["uses"][use]["requires_triggers"])
    yield None if _revision_basis([r["subject"]] if r["subject"] else [], r["triggers"], set(rep["view"]["current"])) \
        else ("UNASSESSED", ["no revision basis"])


def _unknown_use(rep, use):
    return None if use in rep["profile"]["uses"] else ("UNASSESSED", [f"use {use!r} is not in the recipient profile"])


def _freshness(rep, r):
    if r.get("observed_until") is None or not r.get("fresh_for"):
        return None
    if rep["view"]["as_of"] - r["observed_until"] <= r["fresh_for"]:
        return None
    return "STALE", [f"last observation ended at {r['observed_until']}, older than {r['fresh_for']}s"]


def reliance(rep, target, use):
    """May a present action rely on duty or transition `target` for `use`? (SPEC §4.4)
    The first check that fails decides; checks run lazily, in the order of SPEC §4.4."""
    out = {"target": target, "use": use, "assessment_id": rep["assessment_id"], "causes": []}
    if target in rep["duties"]:
        checks = _duty_checks(rep, rep["duties"][target], use)
    elif target in rep["results"]:
        checks = _result_checks(rep, rep["results"][target], use)
    else:
        return dict(out, state="MISSING")
    for found in checks:
        if found:
            return dict(out, state=found[0], causes=found[1])
    return dict(out, state="ELIGIBLE")


def _duty_needs(rep, did, r, actor):
    holds = actor == r["holder"] or actor in r["delegates"]
    if holds and r["disposition"] == "OPEN":
        # A filed closure waiting only for acceptances is not work to redo: say
        # whom it waits for (found in the 2026-10-18 handoff experiment).
        waiting = sorted({a for c in r["candidates"] if c["verdict"] == "PENDING" for a in c.get("waiting_for") or []})
        need = f"awaiting acceptance by {', '.join(waiting)}" if waiting else "close"
        yield {"duty": did, "need": need, "statement": r["statement"]}
    if holds and r["disposition"] == "SCHEDULED":
        for n, p in sorted(r["periods"].items(), key=lambda kv: int(kv[0])):
            if p["state"] in ("OPEN", "LAPSED"):
                yield {"duty": did, "need": f"period {n} {p['state']}", "statement": r["statement"]}
    # A pending closure is no longer acceptance work only when THIS duty is closed
    # by an admitted item of a transition that superseded it. Results supersession
    # alone admits nothing on this duty (Codex W141-01).
    closed_by_admitted = {c["transition"] for c in r["candidates"] if c["verdict"] == "ADMITTED"} \
        if r["disposition"] in ("DISCHARGED", "IMPOSSIBLE", "RELEASED") else set()
    for c in r["candidates"]:
        replaced = set(rep["results"].get(c["transition"], {}).get("superseded_by", [])) & closed_by_admitted
        if c["verdict"] == "PENDING" and actor in (c.get("waiting_for") or []) and not replaced:
            # Whose acceptance this item still waits for, and whether this one is the
            # last: a reader must not have to guess that its own accept closes the duty
            # (found in the 2026-10-19 fresh-context run).
            yield {"duty": did, "need": "accept", "transition": c["transition"], "item": c["item"],
                   "waiting_for": list(c["waiting_for"]), "awaiting": c["awaiting"],
                   "last_acceptance": all(actor in g for g in c["awaiting"])}
    if holds and r["disposition"] == "DISCHARGED":
        for use in rep["profile"]["uses"]:
            rl = reliance(rep, did, use)
            if rl["state"] in ("STALE", "CHALLENGED", "UNASSESSED"):
                yield {"duty": did, "need": f"revalidate ({rl['state']} for {use})", "causes": rl["causes"]}


def frontier(rep, actor):
    """What is open for `actor` in this view. Unowned questions are never in it."""
    out = [n for did, r in sorted(rep["duties"].items()) for n in _duty_needs(rep, did, r, actor)]
    if actor in rep["profile"]["accept_by"]["results"]:
        out += [{"transition": t_id, "need": "accept results", "under": "profile accept_by.results"}
                for t_id, r in sorted(rep["results"].items())
                if actor not in r["accepted_by"] and not r["superseded_by"] and r["established"]]
    return out


def questions(rep, scope=None, owned=False):
    return [q for q in rep["questions"] if (owned or not q["owned"]) and (scope is None or q["scope"] == scope)]


def capsule(rep, target, use="act"):
    """What the next session needs about one duty or transition, evidence by id."""
    rl = reliance(rep, target, use)
    cap = {"capsule": "warrant/2", "assessment_id": rep["assessment_id"], "target": target, "use": use,
           "reliance": rl["state"], "revisit_because": rl["causes"], "completeness": "UNATTESTED"}
    if target in rep["duties"]:
        r = rep["duties"][target]
        cap.update(kind="duty", statement=r["statement"], disposition=r["disposition"], holder=r["holder"],
                   owed_to=r["owed_to"], accept_by=r["accept_by"],
                   waiting_for=sorted({a for c in r["candidates"] if c["verdict"] == "PENDING"
                                       for a in c.get("waiting_for") or []}),
                   basis=r["assessed_basis"], closed_by=r["closed_by"], periods=r.get("periods"),
                   revalidate_when=[{k: t[k] for k in t if k != "closure"} for t in r["triggers"] if t["current"]],
                   challenges=_counting_challenges(rep, {tuple(x) for x in r.get("current_items", [])}, r),
                   evidence=sorted({h for tid in r["closed_by"] if tid in rep["results"] for h in rep["results"][tid]["evidence"]}),
                   limits=sorted({x for tid in r["closed_by"] if tid in rep["results"] for x in rep["results"][tid]["residual"]}))
    elif target in rep["results"]:
        r = rep["results"][target]
        cap.update(kind="transition", established=r["established"], limits=r["residual"], subject=r["subject"],
                   basis=r["basis"], accepted_by=r["accepted_by"], superseded_by=r["superseded_by"],
                   revalidate_when=r["triggers"], challenges=r["challenges"], evidence=r["evidence"])
    return cap
