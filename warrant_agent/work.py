"""The agent's work loop over warrant-agent/3: find a record, see what waits for you, and file a whole act at once.

  find   {workspace, schema?, kind?, actor?, where?, text?, state?, leaves?, limit?}
         records matching every filter given, newest first: `where` compares top-level body fields exactly, `text`
         is a case-insensitive substring of the body's JSON, `state` is the lineage's state, `leaves` keeps only the
         latest version of each lineage. Each row carries the full id, a title and its lineage's state and reliance.
  inbox  {actor?}
         over every workspace at once, what waits for the actor (default: each workspace's signer): versions it may
         attest, questions asked of it, challenges standing against its own records, its own versions still waiting
         and the schemas it may back. A workspace that cannot be read is named, never skipped silently.
  act    {workspace, act, ...; records?}
         the records an act files, built as the CLI builds them (warrant.review, warrant.roadmap) and checked as this
         receiver would read them, chained on the signer's head; with `records` (the list a preview returned,
         unchanged), signed and appended under one lock and one write, all or none. Acts:
           review-open  {pr, title, serves?}            a pull request's review lineage (pr-head@1 open)
           review-head  {pr, commit?, answers?}         its head version at a commit of the checkout (default HEAD)
           close        {obligation, established, evidence? | pr?, residual?, refs?, requires?}
                                                        an obligation's `done` version; `pr` names the evidence as that
                                                        pull request's review lineage
           accept       {target}                        an acceptance of a version, with what the signer saw of it
         A chain fork of the signer (a merge of the base after it filed there) is joined first, as the CLI does.

None of them chooses a signer, a key or a path: those stay the operator's configuration (warrant_agent.config)."""
import json
import os
import subprocess
import time
from types import SimpleNamespace

from warrant import chains as CH
from warrant import engine as E
from warrant import graph as G
from warrant import keys as K
from warrant import records as R
from warrant import review as RV
from warrant import roadmap as RM
from warrant import shapes as S
from warrant.repo import Failed, Repo
from warrant.store import Inadmissible, Refused, Snapshot

from .errors import AgentError, need

ACTS = ("review-open", "review-head", "close", "accept")
TITLE = ("title", "statement", "name", "text", "verdict")
FIND_MAX = 500


def title(r):
    """A short line naming a record: its body's title, statement, name, text or verdict, at most 160 characters."""
    b = r.get("body") or {}
    for k in TITLE:
        if isinstance(b.get(k), str) and b[k].strip():
            t = " ".join(b[k].split())
            return t if len(t) <= 160 else t[:159] + "…"
    return None


def _lineages(rep):
    return {v: root for root, lin in rep["lineages"].items() for v in lin["versions"]}


def _row(rep, lin_of, i, r):
    row = {"id": i, "kind": r["kind"], "schema": r.get("schema"), "actor": r["actor"], "at": r["at"], "title": title(r)}
    if isinstance((r.get("body") or {}).get("target"), str):
        row["target"] = r["body"]["target"]
    root = lin_of.get(i)
    if root is not None:
        lin = rep["lineages"][root]
        row["lineage"] = {"root": root, "state": lin["state"], "reliance": lin["reliance"], "leaf": lin["leaf"] == i}
    return row


def find(api, cfg, req):
    api._closed(req, ("workspace",), ("schema", "kind", "actor", "where", "text", "state", "leaves", "limit"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    _, view, _, _ = api._assess(ws)
    rep = api._report(ws, view)
    where, text = req.get("where"), req.get("text")
    if where is None:
        where = {}
    need(isinstance(where, dict) and all(isinstance(k, str) and (v is None or isinstance(v, (str, int, bool)))
                                         for k, v in where.items()),
         "BAD_REQUEST", "where is an object of body fields to exact strings, integers, booleans or null")
    need(text is None or (isinstance(text, str) and 0 < len(text) <= 200), "BAD_REQUEST", "text is 1 to 200 characters")
    leaves = req.get("leaves")
    need(leaves is None or isinstance(leaves, bool), "BAD_REQUEST", "leaves is a boolean")
    limit = req.get("limit", 50)
    need(isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= FIND_MAX, "BAD_REQUEST",
         f"limit is 1 to {FIND_MAX}")
    for k in ("schema", "kind", "actor", "state"):
        need(req.get(k) is None or isinstance(req[k], str), "BAD_REQUEST", f"{k} is a string")
    needle, lin_of, rows = text.lower() if text else None, _lineages(rep), []
    for i, r in view.recs.items():
        b = r.get("body") or {}
        if any(req.get(k) is not None and r.get(k) != req[k] for k in ("schema", "kind", "actor")):
            continue
        if any(k not in b or type(b[k]) is not type(v) or b[k] != v for k, v in where.items()):
            continue
        if needle and needle not in json.dumps(b, ensure_ascii=False).lower():
            continue
        row = _row(rep, lin_of, i, r)
        lin = row.get("lineage")
        if (req.get("state") is not None and (lin is None or lin["state"] != req["state"])) or \
                (leaves and (lin is None or not lin["leaf"])):
            continue
        rows.append(row)
    rows.sort(key=lambda x: (-x["at"], x["id"]))
    out = {**api._header(rep), "count": len(rows), "records": rows[:limit], "more": len(rows) > limit}
    return api._budget(out, ws.limits["context_bytes"])


def _waiting_items(rep, recs, f, actor, lin_of):
    nodes, _, _ = G.index(rep)
    def show(i):                  # a version's title, else its lineage root's (a pr-head's head names no title)
        root = lin_of.get(i)
        t = title(recs.get(i) or {}) or (title(recs.get(root) or {}) if root else None)
        return {"id": i, "schema": nodes.get(i, {}).get("schema"), "title": t}
    items = [{"do": "attest", **show(x["version"]), "waiting": x["waiting"]} for x in f["attest"]]
    items += [{"do": "answer", **show(x["version"])} for x in f["asked"]]
    items += [{"do": "back schema", "id": x["version"], "schema": "schema", "title": x["name"]} for x in f["schemas"]]
    mine = {i for i, r in recs.items() if r["actor"] == actor}
    answered = _answered(recs)
    replaced = 0
    for c, x in sorted(rep["challenges"].items()):
        if x["target"] not in mine or not x["counted"] or not x.get("stands", True) or c in answered:
            continue
        root = lin_of.get(x["target"])
        if root is not None and rep["lineages"][root]["leaf"] != x["target"]:
            replaced += 1         # its lineage has a newer version since: that version is the answer, for the guard to judge
            continue
        items.append({"do": "answer challenge", **show(x["target"]), "challenge": c, "by": nodes.get(c, {}).get("actor"),
                      "says": title(recs.get(c) or {})})
    for v in f["pending"]:        # what the actor's own versions wait for; a pull request's head is the gate's affair
        if nodes.get(v, {}).get("schema") == RV.PR_HEAD:
            continue
        g = rep["versions"].get(v) or {}
        items.append({"do": "wait", **show(v), "waiting": g.get("waiting", []), "open": g.get("open", [])})
    return items, replaced


def _answered(recs):
    """The ids some record says it answers: a body's `answers`, one id or a list (a pull request head's --answers, an
    obligation answering a goal's question)."""
    out = set()
    for r in recs.values():
        a = (r.get("body") or {}).get("answers")
        out.update([a] if isinstance(a, str) else [x for x in a if isinstance(x, str)] if isinstance(a, list) else [])
    return out


def inbox(api, cfg, req):
    api._closed(req, (), ("actor",))
    need(req.get("actor") is None or S.is_actor(req["actor"]), "BAD_REQUEST", "actor is an actor id")
    out, unavailable, total = [], [], 0
    for n in sorted(cfg.workspaces):
        ws = cfg.workspace(n)
        actor = req.get("actor") or (ws.signer[0] if ws.signer else None)
        if actor is None:
            unavailable.append({"workspace": n, "why": "no signer here and no actor asked"})
            continue
        try:
            ws.permit("context")
            _, view, _, profile = api._assess(ws)
            rep = api._report(ws, view)
        except AgentError as e:
            unavailable.append({"workspace": n, "why": f"{e.code}: {e.message}"[:300]})
            continue
        f = G.frontier(rep, profile, actor, view.recs)
        items, replaced = _waiting_items(rep, view.recs, f, actor, _lineages(rep))
        total += sum(1 for x in items if x["do"] in ("attest", "answer", "back schema", "answer challenge"))
        out.append({"workspace": n, "actor": actor, "roles": f["roles"], "snapshot": rep["snapshot"], "items": items,
                    "challenges_on_replaced_versions": replaced})
    return {"due": total, "workspaces": out, "unavailable": unavailable}


# ---------------------------------------------------------------- act

def _git(root, *a):
    try:
        return subprocess.run(["git", "--no-replace-objects", "-C", str(root), *a], capture_output=True, check=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise AgentError("BAD_REQUEST", f"git {a[0]}: {getattr(e, 'stderr', '') or e}"[:300]) from None


def _built(api, ws, repo, rep, view, snap, actor, req):
    """The unsigned records `act` names, actor and chain left to _chained, as the CLI builds them."""
    act = req["act"]
    _, _, name = repo.config()
    try:
        if act in ("review-open", "review-head"):
            pr = req.get("pr")
            need(isinstance(pr, int) and not isinstance(pr, bool) and pr > 0, "BAD_REQUEST", "pr is a pull request number")
            if act == "review-open":
                need(isinstance(req.get("title"), str) and req["title"].strip(), "BAD_REQUEST", "title is the pull request's title")
                serves = [api._resolve(snap, s) for s in req.get("serves") or []]
                a = SimpleNamespace(cmd="open", actor=actor, pr=pr, title=req["title"], serves=serves)
            else:
                answers = [api._resolve(snap, s) for s in req.get("answers") or []]
                commit = req.get("commit") or "HEAD"
                need(isinstance(commit, str) and len(commit) <= 64 and not commit.startswith("-"), "BAD_REQUEST",
                     "commit is a revision of the checkout")
                a = SimpleNamespace(cmd="head", actor=actor, pr=pr, commit=_git(ws.repo, "rev-parse", "--verify",
                                                                                 "--end-of-options", f"{commit}^{{commit}}"),
                                    answers=answers)
            return [RV._pr_record(repo, rep, a, name)]
        if act == "close":
            ob = api._resolve(snap, req.get("obligation") or "")
            ob = G.lineage_of(rep, ob) if ob in rep["versions"] else ob      # any version names its lineage
            evidence = [api._resolve(snap, e) for e in req.get("evidence") or []]
            if req.get("pr") is not None:
                pr = req["pr"]
                need(isinstance(pr, int) and not isinstance(pr, bool) and pr > 0, "BAD_REQUEST", "pr is a pull request number")
                L = RV.lineage_of(rep, name, pr)
                need(L is not None, "NOT_FOUND", f"#{pr} has no review lineage here: act review-open first")
                evidence.append(L)
            need(evidence, "BAD_REQUEST", "a closure names its evidence: evidence ids, or pr")
            est = req.get("established")
            need(isinstance(est, list) and est and all(isinstance(x, str) and x.strip() for x in est), "BAD_REQUEST",
                 "established is a list of what the closure establishes")
            for k in ("residual", "refs"):
                need(req.get(k) is None or (isinstance(req[k], list) and all(isinstance(x, str) for x in req[k])),
                     "BAD_REQUEST", f"{k} is a list of strings")
            a = SimpleNamespace(actor=actor, obligation=ob, evidence=sorted(set(evidence)), ref=req.get("refs") or [],
                                established=est, residual=req.get("residual"),
                                requires=[api._resolve(snap, x) for x in req.get("requires") or []])
            return [RM._closure(rep, a)]
        t = api._resolve(snap, req.get("target") or "")
        return [R.record("attest", actor, 0, G.with_seen(view.report(), {"target": t, "verdict": "accept"}), refs=[t])]
    except Failed as e:
        raise AgentError("REFUSED", str(e)) from None
    except KeyError as e:
        raise AgentError("NOT_FOUND", f"not in this store: {e}") from None


def _chained(snap, trust, actor, records):
    """The records dated now (never before the actor's head) and chained on its head, as Repo.file files them."""
    h = E.head(snap, trust, actor)
    at, prev, out = max(int(time.time()), h["at"] or 0), h["id"], []
    for r in records:
        r = dict(r, actor=actor, at=at, prev=prev)
        R.check(r)
        out.append(r)
        prev = R.rid(r)
    return out


def _refusals_all(snap, view, trust, profile, records):
    """Why the engine would not take `records` as the actor's next records, all of them read together (api._refusals
    for one record, over a key made for this call and never kept)."""
    key = K.Key.from_seed_hex(os.urandom(32).hex())
    actor = records[0]["actor"]
    keys = dict(trust["keys"], **{actor: sorted(set(trust["keys"].get(actor, [])) | {key.public})})
    lines = [R.line(r, key)[1] for r in records]
    try:
        after = E.View(Snapshot(snap.raw + lines, snap.blobs), dict(trust, keys=keys), profile)
    except (Refused, R.Invalid) as e:
        return [f"the store with them would be refused: {e}"]
    out = [f"{w}" for h, w in sorted(after.snap.rejected.items()) if h not in snap.rejected]
    return out + [f"{c}: {d}" for c, x, d in after.problems if [c, x, d] not in view.problems]


def act(api, cfg, req):
    api._closed(req, ("workspace", "act"), ("records", "pr", "title", "serves", "commit", "answers", "obligation",
                                            "evidence", "established", "residual", "refs", "requires", "target"))
    need(req["act"] in ACTS, "BAD_REQUEST", f"act is one of {list(ACTS)}")
    ws = cfg.workspace(req["workspace"])
    ws.permit("prepare")
    need(ws.repo is not None, "BAD_REQUEST", f"workspace {ws.name!r} is a store alone: an act needs a repository checkout")
    actor = api._signer(ws)
    trust, profile = ws.receiver()
    repo = Repo(ws.repo)
    own = ws.open().snapshot()                      # the signer's chain is this store's (Repo.file)
    snap, view, _, _ = api._assess(ws)
    if req.get("records") is not None:
        return _file(api, ws, own, snap, view, trust, profile, actor, req["records"])
    rep = repo.report()
    joins = CH.join_records(repo.view(), actor)           # as the CLI does (warrant.review run)
    records = _chained(own, trust, actor, [*joins, *_built(api, ws, repo, rep, view, snap, actor, req)])
    why = _refusals_all(snap, view, trust, profile, records)
    need(not why, "INVALID_RECORD", "; ".join(why), problems=why)
    return {"act": req["act"], "records": records, "ids": [R.rid(r) for r in records], "joined": len(joins),
            "next": "act again with these records, unchanged, to sign and file them all at once"}


def _file(api, ws, own, snap, view, trust, profile, actor, records):
    ws.permit("commit")
    need(isinstance(records, list) and 1 <= len(records) <= 16, "BAD_REQUEST", "records is the list a preview returned")
    for r in records:
        try:
            R.check(r)
        except (R.Invalid, TypeError) as e:
            raise AgentError("INVALID_RECORD", str(e)) from None
        need(r["actor"] == actor, "NOT_PERMITTED", f"the signer of this workspace is {actor!r}, not {r['actor']!r}")
    for a, b in zip(records, records[1:]):
        need(b["prev"] == R.rid(a), "INVALID_RECORD", "the records are one chain, in order, as the preview returned them")
    why = _refusals_all(snap, view, trust, profile, records)
    need(not why, "INVALID_RECORD", "; ".join(why), problems=why)
    try:
        key = K.Key.from_seed_hex(ws.signer[1].read_text())
    except (OSError, ValueError) as e:
        raise AgentError("NO_SIGNER", f"the signer's seed cannot be read: {type(e).__name__}") from None
    need(key.public in trust["keys"].get(actor, []), "SIGNER_NOT_TRUSTED",
         f"the signer's key {key.id[:12]} is not one this workspace's trust binds to {actor!r}")

    def admit(now, recs):         # under the writers' lock, as commit does
        try:
            return _refusals_all(now, E.View(now, trust, profile), trust, profile, recs)
        except (Refused, R.Invalid) as e:
            return [f"the store cannot be assessed: {e}"]
    try:
        ids = ws.open().extend(records, key, trust, expect_head=records[0]["prev"] or "", admit=admit)
    except Inadmissible as e:
        raise AgentError("INVALID_RECORD", str(e), problems=e.why) from None
    except Refused as e:
        raise AgentError("CHAIN_MOVED" if "CHAIN_MOVED" in str(e) else "REFUSED", str(e)) from None
    _, view2, _, _ = api._assess(ws)
    rep = view2.report()
    nodes, _, _ = G.index(rep)
    return {"filed": ids, "records": [G.describe(rep, nodes, i) for i in ids]}
