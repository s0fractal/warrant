"""Agent interface for attenuating capability delegation (`grant@1`, warrant.delegate).

  delegate {workspace, op: grants | assess, as_of?}
    grants  every `grant@1` lineage in the store resolved under this workspace's trust and profile
    assess  scoped assessment with verified active delegations: admitted/refused delegated records,
            lineage changes vs static `assess`, and full provenance back to root trust anchors

Read-only: nothing is filed; nothing alters the workspace's static trust or profile."""
from warrant import delegate as D
from warrant import records as R

from .errors import need

OPS = ("grants", "assess")


def delegate(api, cfg, req):
    api._closed(req, ("workspace", "op"), ("as_of",))
    op = req["op"]
    need(op in OPS, "BAD_REQUEST", f"op is one of {list(OPS)}")
    as_of = req.get("as_of")
    need(as_of is None or (R.is_int(as_of) and as_of >= 0), "BAD_REQUEST", "as_of is a non-negative integer")
    ws = cfg.workspace(req["workspace"])
    ws.permit("context")
    snap, view, trust, profile = api._assess(ws)
    eff_as_of = as_of if as_of is not None else view.as_of
    if op == "grants":
        grants = D.resolve_grants(snap, trust, profile, eff_as_of)
        out = {
            "warrant": "delegation/1",
            "op": "grants",
            "workspace": ws.name,
            "as_of": eff_as_of,
            "grants": grants,
            "active": sum(1 for g in grants.values() if g["status"] == "ACTIVE"),
        }
        return api._budget(out, ws.limits["context_bytes"])
    res = D.assess_delegated(snap, trust, profile, eff_as_of)
    out = {
        "warrant": "delegation/1",
        "op": "assess",
        "workspace": ws.name,
        "as_of": res["as_of"],
        "grants": res["grants"],
        "admitted": res["admitted"],
        "refused": res["refused"],
        "changes": res["changes"],
        "provenance": res["provenance"],
    }
    return api._budget(out, ws.limits["context_bytes"])
