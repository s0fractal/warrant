"""Assessment (SPEC §4): one pure function of one view.

`assess()` returns a report: every duty's disposition and candidates, every
transition's results, grants, challenges, unowned questions and the view's
identity. `reliance()`, `frontier()`, `questions()` and `capsule()` read a report."""
from pathlib import Path

from . import jcs as C
from . import compute as P
from . import records as R
from . import triggers as TR

PROFILE_FIELDS = ("uses", "accept_by", "targets", "grant_roots", "challengers")
VERDICTS = ("ADMITTED", "PENDING", "OVERCLAIMED", "MISSING_EVIDENCE", "UNMET_CONDITION", "UNVERIFIED")
RELIANCE = ("ELIGIBLE", "STALE", "CHALLENGED", "SUPERSEDED", "UNASSESSED", "NOT_CLOSED", "CONTESTED", "MISSING")
START = (-1, "")
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
    except R.Invalid as e:
        return str(e)
    return None


def profile(uses=None, results_by=(), targets=(), grant_roots=(), challengers=()):
    return {"uses": dict(uses or {"act": {"requires_triggers": False}}), "accept_by": {"results": list(results_by)},
            "targets": list(targets), "grant_roots": list(grant_roots), "challengers": list(challengers)}


# ---------------------------------------------------------------- the view

class View:
    def __init__(self, snapshot, trust, as_of, prof, provider):
        self.snap, self.as_of, self.profile, self.provider = snapshot, as_of, prof, provider
        good, self.invalid = snapshot.authentic(trust)
        self.recs = {rid: r for rid, r in good.items() if r["at"] <= as_of}
        self.later = sorted(rid for rid, r in good.items() if r["at"] > as_of)
        self.by_type = {t: {} for t in R.TYPES}
        for rid, r in self.recs.items():
            self.by_type[r["type"]][rid] = r
        self.duties = self.by_type["duty"]
        self.transitions = self.by_type["transition"]
        self.missing = set()

    def pos(self, rid):
        return (self.recs[rid]["at"], rid)

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


def grant_state(view, gid, at, depth=0):
    rec = view.by_type["grant"].get(gid)
    if rec is None:
        return "BROKEN_CHAIN", "grant not in view"
    g = rec["body"]
    if rec["at"] > at:
        return "NOT_YET", "granted after this position"
    if g["expires"] is not None and at >= g["expires"]:
        return "EXPIRED", f"expired at {g['expires']}"
    if g["parent"] is None:
        return ("VALID", "root") if gid in view.profile["grant_roots"] else ("UNGROUNDED", "a root the recipient has not accepted")
    if depth >= MAX_CHAIN:
        return "BROKEN_CHAIN", "chain too long"
    pst, why = grant_state(view, g["parent"], rec["at"], depth + 1)      # the parent at the CHILD's position
    if pst != "VALID":
        return ("BROKEN_CHAIN" if pst in ("BROKEN_CHAIN", "UNGROUNDED", "NOT_YET") else pst, f"parent {g['parent'][:12]}: {why}")
    prec = view.by_type["grant"][g["parent"]]
    p = prec["body"]
    if rec["actor"] != p["grantee"]:
        return "NOT_ATTENUATED", "the grantor is not the parent's grantee"
    if not set(g["acts"]) <= set(p["delegable"]):
        return "NOT_ATTENUATED", "acts the parent did not make delegable"
    if not set(g["delegable"]) <= set(p["delegable"]):
        return "NOT_ATTENUATED", "delegable beyond the parent's"
    if not set(g["duties"]) <= set(p["duties"]):
        return "NOT_ATTENUATED", "duties beyond the parent's"
    if p["expires"] is not None and (g["expires"] is None or g["expires"] > p["expires"]):
        return "NOT_ATTENUATED", "expires later than the parent"
    return "VALID", "attenuated"


def authorized(view, actor, act, duty_id, at):
    reasons = []
    for gid, rec in sorted(view.by_type["grant"].items()):
        g = rec["body"]
        if g["grantee"] != actor or act not in g["acts"] or duty_id not in g["duties"]:
            continue
        st, why = grant_state(view, gid, at)
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


def _transfer_effect(view, d, t_id, i, m):
    """(effect position, None) once every required consent exists, else (None, missing)."""
    got = view.accepted_at(t_id, i, m["evidence"])
    missing = []
    pos = view.pos(t_id)
    if m["to"] not in got:
        missing.append(f"{m['to']} (incoming)")
    else:
        pos = max(pos, got[m["to"]])
    if m["act"] == "substitute":
        creditors = [got[a] for a in set(d["owed_to"]) | set(d["release_by"]) if a in got]
        if not creditors:
            missing.append("one of owed_to or release_by")
        else:
            pos = max(pos, min(creditors))
    return (None, missing) if missing else (pos, None)


class Holders:
    """Holder and delegates as a function of position (SPEC §4.1)."""

    def __init__(self, holder):
        self.timeline = [(START, holder, frozenset())]

    def at(self, pos):
        _, h, dl = max((e for e in self.timeline if e[0] <= pos), key=lambda e: e[0])
        return h, dl

    def add(self, pos, holder, delegates):
        self.timeline.append((pos, holder, frozenset(delegates)))


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


def _basis(view, did, d, t_id, t, m, filer, window):
    """(label, None) if the item's basis meets the duty's condition, else (None, verdict, why)."""
    basis = t["body"]["basis"]
    kind, cond = next(iter(d["condition"].items()))
    if m["act"] == "impossible" and kind != "compute":
        if basis != "ATTESTED":
            return None, "OVERCLAIMED", "an impossibility is attested"
        return f"ATTESTED:{filer}", None
    if kind == "attest":
        if basis != "ATTESTED":
            return None, "OVERCLAIMED", f"{basis} is not the basis this condition admits"
        return f"ATTESTED:{filer}", None
    if kind == "observe":
        if basis != "OBSERVED":
            return None, "OVERCLAIMED", "this condition is met by an observation, not by the filer's word"
        good, why = _observations(view, m, cond, filer, window)
        if not good:
            return None, "UNMET_CONDITION", why
        return "OBSERVED:" + ",".join(sorted({rec["actor"] for _, rec in good})), None
    if basis != "REPLAYED":
        return None, "OVERCLAIMED", "a computation is met by the recipient's own replay"
    docs = [view.snap.json_blob(h) for h in m["evidence"]]
    want = "cycle" if m["act"] == "impossible" else "receipt"
    docs = [x for x in docs if isinstance(x, dict) and x.get(want) == "sigma-resume"]
    if len(docs) != 1:
        return None, "MISSING_EVIDENCE", f"a REPLAYED item cites exactly one {want}"
    if view.provider is None:
        return None, "UNVERIFIED", "no provider in this view"
    fn = P.replay_cycle if want == "cycle" else P.replay
    try:
        label, why = fn(view.provider, view.snap, cond, docs[0], view.profile["targets"])
    except P.ProviderError as e:
        return None, "UNVERIFIED", str(e)
    if label is None:
        return None, "UNVERIFIED", why
    return label, None


def _period_window(d, m):
    s = d["schedule"]
    if s is None:
        return None
    n = m["period"]
    return [s["start"] + n * s["every"], s["start"] + (n + 1) * s["every"]]


def _judge_closure(view, did, d, t_id, t, i, m, holders, done, admitted):
    filer = t["actor"]
    holder, delegates = holders.at(view.pos(t_id))
    if filer != holder and filer not in delegates:
        return "OVERCLAIMED", "filed by someone who did not hold the duty at that position", None
    sched = d["schedule"]
    if m["act"] == "discharge" and (sched is None) != ("period" not in m):
        return "OVERCLAIMED", "a scheduled duty is discharged per period, and only a scheduled one", None
    if m["act"] in ("impossible", "revalidate") and sched is not None:
        return "OVERCLAIMED", f"{m['act']} is not defined for a scheduled duty here", None
    window = _period_window(d, m) if "period" in m else None
    if window and t["at"] < window[0]:
        return "OVERCLAIMED", "a period cannot be discharged before it starts", None
    if m["act"] == "revalidate":
        if not admitted:
            return "OVERCLAIMED", "nothing admitted to revalidate", None
        if not set(m["revalidates"]) <= set(admitted):
            return "OVERCLAIMED", "revalidates something that is not an admitted closure of this duty", None
    label, *rest = _basis(view, did, d, t_id, t, m, filer, window)
    if label is None:
        return rest[0], rest[1], None
    if m["act"] in ("discharge", "revalidate"):
        unmet = [c for c in d["requires"] if done.get(c) != "DISCHARGED"]
        if unmet:
            return "UNMET_CONDITION", "required duties not discharged: " + ", ".join(u[:12] for u in unmet), None
    got = set(view.accepted_at(t_id, i, m["evidence"]))
    missing = sorted(set(d["accept_by"]) - got)
    if m["act"] == "impossible" and label.startswith("ATTESTED") and not set(d["owed_to"]) & got:
        missing += [a for a in d["owed_to"] if a not in missing]
    if missing:
        return "PENDING", "waiting for " + ", ".join(missing), None, missing
    return "ADMITTED", "", label


def _assess_duty(view, did, rec, done):
    d = rec["body"]
    out = {"statement": d["statement"], "holder": d["holder"], "owed_to": d["owed_to"], "accept_by": d["accept_by"],
           "release_by": d["release_by"], "condition": next(iter(d["condition"])), "subject": d["subject"],
           "schedule": d["schedule"], "disposition": "OPEN", "closed_by": [], "assessed_basis": [],
           "candidates": [], "flags": [], "triggers": [], "revalidations": [],
           "fresh_for": d["condition"].get("observe", {}).get("fresh_for")}
    items = _items(view, did)
    holders = Holders(d["holder"])
    verdicts = {}
    # 1. Transfers, in order of their effect position: the filer must hold the duty
    #    both when it files and when the transfer takes effect.
    transfers = []
    for t_id, t, i, m in items:
        if m["act"] in ("delegate", "substitute"):
            eff, missing = _transfer_effect(view, d, t_id, i, m)
            transfers.append((eff or (float("inf"), ""), t_id, t, i, m, missing))
    for eff, t_id, t, i, m, missing in sorted(transfers, key=lambda x: (x[0], view.pos(x[1]), x[3])):
        h_file, _ = holders.at(view.pos(t_id))
        if t["actor"] != h_file:
            verdicts[(t_id, i)] = ("OVERCLAIMED", "only the holder at that position transfers or delegates", None)
            continue
        if missing:
            verdicts[(t_id, i)] = ("PENDING", "waiting for " + ", ".join(missing), None,
                                   [x.split(" (")[0] for x in missing if not x.startswith("one of")] or list(d["owed_to"]))
            continue
        h_eff, dl = holders.at(eff)
        if h_eff != t["actor"]:
            verdicts[(t_id, i)] = ("OVERCLAIMED", "the filer no longer held the duty when the transfer would take effect", None)
            continue
        if m["act"] == "delegate":
            holders.add(eff, h_eff, set(dl) | {m["to"]})
        else:
            holders.add(eff, m["to"], set())
        verdicts[(t_id, i)] = ("ADMITTED", "", None)
    # 2. Releases and closures; revalidations last, in their own admission order.
    admitted = {}           # transition id -> admission position, of admitted discharges/revalidations
    first = [x for x in items if x[3]["act"] not in ("delegate", "substitute", "revalidate")]
    reval = sorted((x for x in items if x[3]["act"] == "revalidate"),
                   key=lambda x: _admission_pos(view, d, x[0], x[2], x[3]) or (float("inf"), x[0]))
    for t_id, t, i, m in first + reval:
        if not all(view.resolves(h) for h in m["evidence"]):
            verdicts[(t_id, i)] = ("MISSING_EVIDENCE", "cited evidence is not in the view", None)
            continue
        if m["act"] == "release":
            if t["actor"] in set(d["owed_to"]) | set(d["release_by"]):
                verdicts[(t_id, i)] = ("ADMITTED", "", f"RELEASE:{t['actor']}")
            else:
                gid, why = authorized(view, t["actor"], "release", did, view.pos(t_id)[0])
                verdicts[(t_id, i)] = ("ADMITTED", f"by grant {gid[:12]}", f"RELEASE_BY_GRANT:{gid[:12]}") if gid \
                    else ("OVERCLAIMED", f"not authorized to release: {why}", None)
            continue
        v = _judge_closure(view, did, d, t_id, t, i, m, holders, done, admitted)
        if v[0] == "ADMITTED" and m["act"] == "revalidate":
            mine = _admission_pos(view, d, t_id, i, m)
            late = [x for x in m["revalidates"] if not admitted[x] < mine]
            if late:
                v = ("OVERCLAIMED", "revalidates a closure not admitted before it (admission order): "
                     + ", ".join(x[:12] for x in late), None)
        if v[0] == "ADMITTED" and m["act"] in ("discharge", "revalidate"):
            admitted[t_id] = _admission_pos(view, d, t_id, i, m)
        verdicts[(t_id, i)] = v
    # 3. Report.
    closures, periods, revals = [], {}, []
    for t_id, t, i, m in items:
        verdict, why, label, *waiting = verdicts[(t_id, i)]
        cand = {"transition": t_id, "item": i, "act": m["act"], "filer": t["actor"], "basis": t["body"]["basis"],
                "verdict": verdict, "why": why}
        if waiting:
            cand["waiting_for"] = waiting[0]
        sup = view.support(t_id, i)
        if sup:
            cand["acceptor_support"] = sup
        out["candidates"].append(cand)
        if verdict != "ADMITTED":
            continue
        if m["act"] == "revalidate":
            revals.append((t_id, t, m, label))
        elif m["act"] in ("discharge", "impossible", "release"):
            if "period" in m:
                periods.setdefault(m["period"], (t_id, label))
            else:
                closures.append((m["act"], t_id, t, m, label))
    h, dl = holders.at((float("inf"), ""))
    out["holder"], out["delegates"] = h, sorted(dl)
    _disposition(view, out, d, closures, revals, periods)
    for verdict, flag in (("PENDING", "PENDING_ACCEPTANCE"), ("OVERCLAIMED", "OVERCLAIMED_CANDIDATE"),
                          ("UNVERIFIED", "UNVERIFIED_CANDIDATE"), ("UNMET_CONDITION", "UNMET_CANDIDATE")):
        if any(c["verdict"] == verdict for c in out["candidates"]):
            out["flags"].append(flag)
    return out


KIND_OF = {"discharge": "DISCHARGED", "impossible": "IMPOSSIBLE", "release": "RELEASED"}


def _disposition(view, out, d, closures, revals, periods):
    kinds = sorted({KIND_OF[c[0]] for c in closures})
    if d["schedule"] is not None:
        out["periods"] = _periods(view, d, periods, out)
        if "RELEASED" in kinds:
            out["disposition"] = "RELEASED"
        else:
            out["disposition"] = "SCHEDULED"
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
    out["declared_triggers"] = [{"closure": tid, "trigger": tr, "current": tid not in superseded}
                                for tid, _, m in rows for tr in m.get("triggers", [])]
    out["closure_subjects"] = sorted({t["body"]["subject"] for tid, t, _ in rows
                                      if tid not in superseded and t["body"]["subject"]})
    obs = []
    for tid, _, m in rows:
        if tid in superseded:
            continue
        for h in m["evidence"]:
            rec = view.by_type["observation"].get(h)
            if rec is not None:
                obs.append(rec["body"]["window"][1])
    out["observed_until"] = max(obs) if obs else None


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
    report, done, busy = {}, {}, set()

    def visit(did):
        if did in report or did in busy:
            return
        busy.add(did)
        for c in view.duties[did]["body"]["requires"]:
            if c in view.duties:
                visit(c)
        report[did] = _assess_duty(view, did, view.duties[did], done)
        done[did] = report[did]["disposition"]
        busy.discard(did)

    for did in sorted(view.duties):
        visit(did)
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


def _challenges(view, duties, results):
    out = {}
    for cid, c in sorted(view.by_type["challenge"].items()):
        b = c["body"]
        if b["target"] not in view.transitions:
            view.missing.add(b["target"])
            continue
        out[cid] = {"actor": c["actor"], "at": c["at"], "target": b["target"], "item": b["item"],
                    "statement": b["statement"], "evidence": b["evidence"]}
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
        for item in r.pop("declared_triggers", []):
            result, detail = run(item["trigger"])
            r["triggers"].append({"closure": item["closure"], **item["trigger"], "result": result, "detail": detail,
                                  "current": item["current"]})
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


def assess(snapshot, trust, as_of, prof, current=(), workspace=None, provider=None):
    """Assess one view. `current` is the set of revisions the recipient treats as
    current; `workspace` is (repository path, commit) for subject_changed triggers;
    `provider` is a captured compute.Provider (None: replays are UNVERIFIED)."""
    why = profile_problem(prof)
    if why:
        raise ValueError(f"profile: {why}")
    ws = TR.Workspace(*workspace) if workspace is not None else None
    view = View(snapshot, trust, as_of, prof, provider)
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
    challenges = _challenges(view, duties, results)
    _evaluate_triggers(view, duties, results, ws)
    for r in duties.values():
        bad = {c["verdict"] for c in r["candidates"]} - set(VERDICTS)
        if bad:
            raise ValueError(f"verdict outside its vocabulary: {sorted(bad)}")
    ident = {"snapshot": snapshot.digest, "trust": trust.digest, "profile": C.doc_id(prof), "as_of": as_of,
             "current": sorted(current), "workspace": ws.identity() if ws else None,
             "engine": engine_identity(), "provider": provider.identity if provider else None}
    return {"warrant": "report/2", "assessment_id": C.doc_id(ident), "view": dict(ident, completeness="UNATTESTED"),
            "profile": prof, "duties": duties, "results": results, "challenges": challenges,
            "grants": {g: grant_state(view, g, as_of)[0] for g in sorted(view.by_type["grant"])},
            "questions": _questions(view, duties), "invalid_records": view.invalid,
            "later_records": view.later, "misfiled": snapshot.misfiled, "missing": sorted(view.missing)}


# ---------------------------------------------------------------- reading a report

def _counting_challenges(rep, closures, duty=None):
    """Challenges that count against these closures. A challenge against a closure
    that an admitted revalidation superseded no longer counts: that closure is not
    current any more, and the revalidation needed the same acceptances."""
    counts = set(rep["profile"]["challengers"])
    if duty is not None:
        counts |= set(duty["owed_to"]) | set(duty["accept_by"])
    return sorted(cid for cid, c in rep["challenges"].items() if c["target"] in closures and c["actor"] in counts)


def _revision_basis(subjects, triggers, current):
    if not subjects:
        return True
    if any(s in current for s in subjects):
        return True
    return any(t["kind"] == "subject_changed" and t["result"] == "NOT_FIRED" for t in triggers)


def _trigger_state(out, cur, use_need):
    if use_need and not cur:
        return dict(out, state="UNASSESSED", causes=["the use requires declared triggers; none are current"])
    fired = [f"{t['kind']}: {t['detail']}" for t in cur if t["result"] == "FIRED"]
    if fired:
        return dict(out, state="STALE", causes=fired)
    unknown = [f"{t['kind']}: {t['detail']}" for t in cur if t["result"] == "UNEVALUABLE"]
    if unknown:
        return dict(out, state="UNASSESSED", causes=unknown)
    return None


def reliance(rep, target, use):
    """May a present action rely on duty or transition `target` for `use`? (SPEC §4.4)"""
    out = {"target": target, "use": use, "assessment_id": rep["assessment_id"], "causes": []}
    uses = rep["profile"]["uses"]
    current = set(rep["view"]["current"])
    if target in rep["duties"]:
        r = rep["duties"][target]
        if r["disposition"] == "CONTESTED":
            return dict(out, state="CONTESTED")
        if r["disposition"] != "DISCHARGED":
            return dict(out, state="NOT_CLOSED", causes=[f"disposition {r['disposition']}"])
        if use not in uses:
            return dict(out, state="UNASSESSED", causes=[f"use {use!r} is not in the recipient profile"])
        ch = _counting_challenges(rep, set(r["current_closures"]), r)
        if ch:
            return dict(out, state="CHALLENGED", causes=[f"challenge {c[:12]}: {rep['challenges'][c]['statement']}" for c in ch])
        cur = [t for t in r["triggers"] if t["current"]]
        st = _trigger_state(out, cur, uses[use]["requires_triggers"])
        if st:
            return st
        if r.get("observed_until") is not None and r.get("fresh_for"):
            if rep["view"]["as_of"] - r["observed_until"] > r["fresh_for"]:
                return dict(out, state="STALE", causes=[f"last observation ended at {r['observed_until']}, older than {r['fresh_for']}s"])
        subjects = r["closure_subjects"] or ([r["subject"]] if r["subject"] else [])
        if not _revision_basis(subjects, cur, current):
            return dict(out, state="UNASSESSED", causes=["no revision basis: not established on a current revision, "
                                                         "and no subject_changed trigger evaluated NOT_FIRED"])
        return dict(out, state="ELIGIBLE")
    if target in rep["results"]:
        r = rep["results"][target]
        if r["superseded_by"]:
            return dict(out, state="SUPERSEDED", causes=[f"superseded by {', '.join(x[:12] for x in r['superseded_by'])}"])
        if not rep["profile"]["accept_by"]["results"]:
            return dict(out, state="UNASSESSED", causes=["the profile names nobody whose acceptance closes results"])
        if not r["accepted"]:
            return dict(out, state="NOT_CLOSED", causes=["results not accepted by " +
                                                          ", ".join(sorted(set(rep["profile"]["accept_by"]["results"]) - set(r["accepted_by"])))])
        if use not in uses:
            return dict(out, state="UNASSESSED", causes=[f"use {use!r} is not in the recipient profile"])
        counts = set(rep["profile"]["challengers"]) | set(rep["profile"]["accept_by"]["results"])
        ch = [c for c in r["challenges"] if rep["challenges"][c]["actor"] in counts]
        if ch:
            return dict(out, state="CHALLENGED", causes=[f"challenge {c[:12]}: {rep['challenges'][c]['statement']}" for c in ch])
        st = _trigger_state(out, r["triggers"], uses[use]["requires_triggers"])
        if st:
            return st
        if not _revision_basis([r["subject"]] if r["subject"] else [], r["triggers"], current):
            return dict(out, state="UNASSESSED", causes=["no revision basis"])
        return dict(out, state="ELIGIBLE")
    return dict(out, state="MISSING")


def frontier(rep, actor):
    """What is open for `actor` in this view. Unowned questions are never in it."""
    out = []
    for did, r in sorted(rep["duties"].items()):
        holds = actor == r["holder"] or actor in r["delegates"]
        if holds and r["disposition"] == "OPEN":
            out.append({"duty": did, "need": "close", "statement": r["statement"]})
        if holds and r["disposition"] == "SCHEDULED":
            for n, p in sorted(r["periods"].items(), key=lambda kv: int(kv[0])):
                if p["state"] in ("OPEN", "LAPSED"):
                    out.append({"duty": did, "need": f"period {n} {p['state']}", "statement": r["statement"]})
        for c in r["candidates"]:
            if c["verdict"] == "PENDING" and actor in c.get("waiting_for", []):
                out.append({"duty": did, "need": "accept", "transition": c["transition"], "item": c["item"]})
        if holds and r["disposition"] == "DISCHARGED":
            for use in rep["profile"]["uses"]:
                rl = reliance(rep, did, use)
                if rl["state"] in ("STALE", "CHALLENGED", "UNASSESSED"):
                    out.append({"duty": did, "need": f"revalidate ({rl['state']} for {use})", "causes": rl["causes"]})
    for t_id, r in sorted(rep["results"].items()):
        if actor in rep["profile"]["accept_by"]["results"] and actor not in r["accepted_by"] and not r["superseded_by"] \
                and r["established"]:
            out.append({"transition": t_id, "need": "accept results"})
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
                   basis=r["assessed_basis"], closed_by=r["closed_by"], periods=r.get("periods"),
                   revalidate_when=[{k: t[k] for k in t if k != "closure"} for t in r["triggers"] if t["current"]],
                   challenges=_counting_challenges(rep, set(r.get("current_closures", [])), r),
                   evidence=sorted({h for tid in r["closed_by"] if tid in rep["results"] for h in rep["results"][tid]["evidence"]}),
                   limits=sorted({x for tid in r["closed_by"] if tid in rep["results"] for x in rep["results"][tid]["residual"]}))
    elif target in rep["results"]:
        r = rep["results"][target]
        cap.update(kind="transition", established=r["established"], limits=r["residual"], subject=r["subject"],
                   basis=r["basis"], accepted_by=r["accepted_by"], superseded_by=r["superseded_by"],
                   revalidate_when=r["triggers"], challenges=r["challenges"], evidence=r["evidence"])
    return cap
