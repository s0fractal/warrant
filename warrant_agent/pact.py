"""Agent interface for bilateral/multilateral pacts & computed-loss composition (`pact@1`, warrant.pact).

  pact {workspace, op: status | escrow | compose, as_of?, pact_ids?}
    status   every `pact@1` contract in the store resolved under this workspace's trust
    escrow   every `grant@1` bound to a pact, showing live escrow admissibility
    compose  compose ordered `pact_ids` under the default-deny computed-loss frame law

Read-only: nothing is filed; nothing alters the workspace's trust or profile."""
from warrant import dream as DR
from warrant import pact as P
from warrant import records as R
from warrant import shapes as S

from .errors import need

OPS = ("status", "escrow", "compose", "dream")


def pact(api, cfg, req):
    api._closed(
        req,
        ("workspace", "op"),
        ("as_of", "pact_ids", "goal_gives", "initial_gives", "required_witnesses",
         "boundary", "max_steps", "max_expansions"),
    )
    op = req["op"]
    need(op in OPS, "BAD_REQUEST", f"op is one of {list(OPS)}")
    as_of = req.get("as_of")
    need(as_of is None or (R.is_int(as_of) and as_of >= 0), "BAD_REQUEST", "as_of is a non-negative integer")
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    snap, view, trust, profile = api._assess(ws)
    eff_as_of = as_of if as_of is not None else view.as_of

    if op == "status":
        pacts = P.resolve_pacts(snap, trust, eff_as_of)
        out = {
            "warrant": "pact/1",
            "op": "status",
            "workspace": ws.name,
            "as_of": eff_as_of,
            "pacts": pacts,
            "count": len(pacts),
        }
        return api._budget(out, ws.limits["context_bytes"])

    if op == "escrow":
        res = P.resolve_escrow(snap, trust, profile, eff_as_of)
        out = {
            "warrant": "pact/1",
            "op": "escrow",
            "workspace": ws.name,
            "as_of": eff_as_of,
            "escrow": res["escrow"],
        }
        return api._budget(out, ws.limits["context_bytes"])

    if op == "dream":
        goal_gives = req.get("goal_gives")
        need(isinstance(goal_gives, list) and len(goal_gives) >= 1,
             "BAD_REQUEST", "dream requires a non-empty goal_gives list")
        try:
            dream_out = DR.dream_pacts(
                snap, trust, eff_as_of,
                goal_gives=goal_gives,
                initial_gives=req.get("initial_gives") or (),
                required_witnesses=req.get("required_witnesses"),
                boundary=req.get("boundary"),
                max_steps=req.get("max_steps", 4),
                max_expansions=req.get("max_expansions", 256),
            )
        except ValueError as exc:
            need(False, "BAD_REQUEST", str(exc))
        out = {
            "warrant": "pact/1",
            "op": "dream",
            "workspace": ws.name,
            "as_of": eff_as_of,
            "dream": dream_out,
        }
        return api._budget(out, ws.limits["context_bytes"])

    pact_ids = req.get("pact_ids")
    need(isinstance(pact_ids, list) and len(pact_ids) >= 1 and all(S.hex64(x) for x in pact_ids),
         "BAD_REQUEST", "compose requires a non-empty list of 64-hex pact_ids")
    try:
        comp = P.compose_pacts(snap, trust, pact_ids, eff_as_of)
    except ValueError as exc:
        need(False, "BAD_REQUEST", str(exc))
    out = {
        "warrant": "pact/1",
        "op": "compose",
        "workspace": ws.name,
        "as_of": eff_as_of,
        "composition": comp,
    }
    return api._budget(out, ws.limits["context_bytes"])
