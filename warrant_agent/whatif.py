"""What would follow, before an agent acts: the store assessed with records taken out or with acceptances added, and
which one act of the agent's would change the most. Nothing is filed; the engine assesses a candidate store.

  whatif {workspace, without?: [ids], accept?: [ids], actor?}
         the lineages whose state or reliance would change if the store held none of `without` and the actor
         (default: the workspace's signer) had accepted each of `accept`, from now to then
  next   {workspace, actor?, limit?}
         the versions waiting for the actor's acceptance (its frontier's `attest`), ranked first by how many lineages
         rest on each (the graph, at once), the first `limit` (default 5) then assessed with that acceptance alone:
         what it would change, the most first; where one act unblocks the most

An acceptance supposed here is signed by a key made for the call and bound to the actor in a copy of the trust, as
prepare's own check makes one (api._refusals); it counts only where the actor's roles let it, under the workspace's
own profile. The answer says what the engine would read, not that the act is right."""
import os
import time

from warrant import drift as D
from warrant import engine as E
from warrant import graph as G
from warrant import keys as K
from warrant import records as R
from warrant import shapes as S
from warrant.store import Snapshot, _line_id

from .errors import need
from . import changes as CH

NEXT_MAX = 12                     # candidates assessed exactly by one `next`: each is one more assessment of the store


def _rows(before, after):
    """[{lineage, schema, from: [state, reliance], to: [...]}] of every lineage whose state or reliance differs."""
    out = []
    for L in sorted(set(before["lineages"]) | set(after["lineages"])):
        a, b = before["lineages"].get(L), after["lineages"].get(L)
        was = [a["state"], a["reliance"]] if a else None
        now = [b["state"], b["reliance"]] if b else None
        if was != now:
            out.append({"lineage": L, "schema": (b or a)["schema"], "from": was, "to": now})
    return out


def _supposed(snap, trust, actor, targets, at):
    """(snapshot with the actor's acceptances of `targets` added, trust binding a key made for the call to it)."""
    key = K.Key.from_seed_hex(os.urandom(32).hex())
    trust = dict(trust, keys=dict(trust["keys"], **{actor: sorted(set(trust["keys"].get(actor, [])) | {key.public})}))
    prev, lines = E.head(snap, trust, actor)["id"], []
    for t in targets:
        r = R.record("attest", actor, at, {"target": t, "verdict": "accept"}, refs=[t], prev=prev)
        prev, line = R.line(r, key)
        lines.append(line)
    return Snapshot(sorted(set(snap.raw) | set(lines), key=_line_id), snap.blobs), trust


def _resting(rep, L):
    """The lineages resting on lineage L, transitively, from its root or any version (a requirement names the root)."""
    out = set()
    for x in rep["lineages"][L]["versions"]:
        out |= {G.lineage_of(rep, n["id"]) for n in G.why(rep, x)["nodes"]}
    return out - {None, L}


def _report(api, ws, snap, trust, profile):
    view = E.View(snap, trust, profile)
    rep = view.report()
    rep["_recs"], rep["_basis"] = view.recs, view.basis
    D.reading(rep, ws.repo)       # the gate beside a checkout, PINS_NOT_CHECKED for a store alone (Codex e91f50f1)
    return rep


def _actor(ws, req):
    actor = req.get("actor") or (ws.signer[0] if ws.signer else None)
    need(isinstance(actor, str) and S.is_actor(actor), "BAD_REQUEST", "an actor: the workspace's signer, or `actor`")
    return actor


def whatif(api, cfg, req):
    api._closed(req, ("workspace",), ("without", "accept", "actor"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    snap, view, trust, profile = api._assess(ws)
    without = [api._resolve(snap, x) for x in req.get("without") or []]
    accept = [api._resolve(snap, x) for x in req.get("accept") or []]
    need(without or accept, "BAD_REQUEST", "name records to take out (without) or versions to accept (accept)")
    need(len(without) + len(accept) <= 256, "BAD_REQUEST", "at most 256 records in one hypothesis")
    now = _report(api, ws, snap, trust, profile)
    hyp, htrust = CH.subset(snap, set(snap.lines) - set(without)), trust
    if accept:
        hyp, htrust = _supposed(hyp, trust, _actor(ws, req), accept, max(int(time.time()), view.as_of or 0))
    then = _report(api, ws, hyp, htrust, profile)
    rows = _rows(now, then)
    return api._budget({**api._header(now), "without": without, "accept": accept, "changes": rows,
                        "count": len(rows)}, ws.limits["context_bytes"])


def next_(api, cfg, req):
    api._closed(req, ("workspace",), ("actor", "limit"))
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    actor = _actor(ws, req)
    limit = req.get("limit", 5)
    need(isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= NEXT_MAX, "BAD_REQUEST",
         f"limit is 1 to {NEXT_MAX}")
    snap, view, trust, profile = api._assess(ws)
    now = _report(api, ws, snap, trust, profile)
    waiting = [x["version"] for x in G.frontier(now, profile, actor, view.recs)["attest"]]
    # first by what rests on each, transitively (the graph alone, at once); then the first `limit` assessed exactly
    reach = {v: _resting(now, G.lineage_of(now, v)) for v in waiting}
    order = sorted(waiting, key=lambda v: (-len(reach[v]), v))
    at, rows = max(int(time.time()), view.as_of or 0), []
    for v in order[:limit]:
        hyp, htrust = _supposed(snap, trust, actor, [v], at)
        ch = _rows(now, _report(api, ws, hyp, htrust, profile))
        rows.append({"version": v, "lineage": G.lineage_of(now, v), "rests_on_it": len(reach[v]), "changes": len(ch),
                     "lineages": [x["lineage"] for x in ch][:16]})
    rows.sort(key=lambda x: (-x["changes"], -x["rests_on_it"], x["version"]))
    return api._budget({**api._header(now), "actor": actor, "waiting": len(waiting), "next": rows},
                       ws.limits["context_bytes"])
