"""Deterministic cross-repository organism pulse & verified decision profile (`warrant.pulse`).

Read-only, offline, signature-verified sensorium across any set of Warrant 3 repositories:
  1. Evaluates each named repository strictly under its own `trust` and `profile` (receiver-local
     sovereignty — never merges trust roots across repositories) at a uniform optional `as_of`
     horizon (filtering out records dated after `as_of`).
  2. Reports per-repository integrity (`canonical`, `rejected_count`, `problem_count`, `record_count`),
     lineage frontier (`open_obligations`, `pending_done_obligations`, `open_goals`,
     `standing_challenges`), and `pact@1` counts (`active`, `settled`, `breached`).
  3. Aggregates a verified cross-repository actor decision profile (counts of verified `entity`,
     `attest`, `challenge`, `schema`, `accept` verdicts, and `finding@1` challenges per actor),
     strictly excluding unverified/rejected records.
  4. Emits a canonical, order-independent SHA-256 `digest` (`pulse/1`) over the whole snapshot.
"""
import hashlib
import json

from . import engine as E
from . import jcs as C
from . import pact as P
from . import records as R
from .store import Snapshot


def _snapshot_at(snap: Snapshot, as_of: int | None) -> Snapshot:
    """Return a Snapshot containing only lines dated `<= as_of` (when `as_of` is given)."""
    if as_of is None:
        return snap
    if not (R.is_int(as_of) and as_of >= 0):
        raise ValueError("as_of must be a non-negative integer")
    kept = []
    for raw in snap.raw:
        try:
            env = C.loads(raw.rstrip(b"\n"))
            rec = env.get("record") if isinstance(env, dict) else None
            at = rec.get("at") if isinstance(rec, dict) else None
        except Exception:
            kept.append(raw)  # keep malformed lines so integrity reporting never hides them
            continue
        if not R.is_int(at) or at <= as_of:
            kept.append(raw)
    return Snapshot(kept, snap.blobs, sort=False)


def pulse_repository(name: str, snap: Snapshot, trust: dict, profile: dict, *, as_of: int | None = None) -> dict:
    """Compute a deterministic verified pulse for one Warrant 3 repository under its own trust/profile."""
    if not isinstance(name, str) or not name or name != name.strip():
        raise ValueError("repository name must be a non-empty trimmed string")
    eff_snap = _snapshot_at(snap, as_of)
    view = E.View(eff_snap, trust, profile)
    rep = view.report()
    eff_as_of = as_of if as_of is not None else view.as_of

    # Frontier extraction from verified lineages
    open_obligations = []
    pending_done_obligations = []
    open_goals = []
    challenged_lineages = []
    for lid, lin in sorted(rep["lineages"].items()):
        schema = lin.get("schema")
        leaf_id = lin.get("leaf")
        leaf = view.recs.get(leaf_id) if leaf_id else None
        state = (leaf.get("body") or {}).get("state") if leaf else None
        if lin.get("reliance") == "CHALLENGED":
            challenged_lineages.append(lid)
        if schema == "obligation@1":
            if state == "open":
                open_obligations.append(lid)
            elif state == "done" and lin.get("effective") != leaf_id:
                pending_done_obligations.append(lid)
        elif schema == "goal@1" and state == "open":
            open_goals.append(lid)

    # Actor activity counts strictly from signature-verified records in view.recs
    actor_counts = {}
    for rid, rec in sorted(view.recs.items()):
        actor = rec["actor"]
        row = actor_counts.setdefault(actor, {
            "total": 0, "entity": 0, "attest": 0, "challenge": 0, "schema": 0,
            "accepts": 0, "findings": 0,
        })
        kind = rec["kind"]
        row["total"] += 1
        if kind in row:
            row[kind] += 1
        body = rec.get("body") or {}
        if kind == "attest" and body.get("verdict") == "accept":
            row["accepts"] += 1
        if rec.get("schema") == "finding@1":
            row["findings"] += 1

    # Resolve pact@1 status summary at eff_as_of
    pacts = P.resolve_pacts(eff_snap, trust, eff_as_of)
    pact_counts = {"proposed": 0, "active": 0, "settled": 0, "breached": 0, "expired": 0, "withdrawn": 0, "invalid": 0}
    for entry in pacts.values():
        st_key = str(entry.get("status", "")).lower()
        if st_key in pact_counts:
            pact_counts[st_key] += 1

    return {
        "name": name,
        "as_of": eff_as_of,
        "canonical": bool(eff_snap.canonical),
        "record_count": len(view.recs),
        "rejected_count": len(rep["rejected"]),
        "problem_count": len(view.problems),
        "lineage_count": len(rep["lineages"]),
        "open_goals": sorted(open_goals),
        "open_obligations": sorted(open_obligations),
        "pending_done_obligations": sorted(pending_done_obligations),
        "challenged_lineages": sorted(challenged_lineages),
        "pacts": pact_counts,
        "actors": dict(sorted(actor_counts.items())),
    }


def pulse_ecosystem(repos: dict, *, as_of: int | None = None) -> dict:
    """Compute a deterministic, content-addressed pulse across named `{name: (snap, trust, profile)}` repos."""
    if not isinstance(repos, dict) or not repos:
        raise ValueError("repos must be a non-empty mapping of name -> (snap, trust, profile)")
    if as_of is not None and not (R.is_int(as_of) and as_of >= 0):
        raise ValueError("as_of must be a non-negative integer")

    per_repo = {}
    decision_profile = {}
    totals = {
        "repositories": 0,
        "records": 0,
        "rejected": 0,
        "problems": 0,
        "open_obligations": 0,
        "pending_done_obligations": 0,
        "challenged_lineages": 0,
        "active_pacts": 0,
        "settled_pacts": 0,
        "breached_pacts": 0,
    }

    for name in sorted(repos):
        item = repos[name]
        if not (isinstance(item, tuple) and len(item) == 3):
            raise ValueError(f"repo entry for {name!r} must be a 3-tuple (snap, trust, profile)")
        snap, trust, profile = item
        rp = pulse_repository(name, snap, trust, profile, as_of=as_of)
        per_repo[name] = rp
        totals["repositories"] += 1
        totals["records"] += rp["record_count"]
        totals["rejected"] += rp["rejected_count"]
        totals["problems"] += rp["problem_count"]
        totals["open_obligations"] += len(rp["open_obligations"])
        totals["pending_done_obligations"] += len(rp["pending_done_obligations"])
        totals["challenged_lineages"] += len(rp["challenged_lineages"])
        totals["active_pacts"] += rp["pacts"]["active"]
        totals["settled_pacts"] += rp["pacts"]["settled"]
        totals["breached_pacts"] += rp["pacts"]["breached"]

        for actor, counts in rp["actors"].items():
            agg = decision_profile.setdefault(actor, {
                "repositories": [], "total": 0, "entity": 0, "attest": 0,
                "challenge": 0, "schema": 0, "accepts": 0, "findings": 0,
            })
            agg["repositories"].append(name)
            for k in ("total", "entity", "attest", "challenge", "schema", "accepts", "findings"):
                agg[k] += counts[k]

    body = {
        "warrant": "pulse/1",
        "as_of": as_of,
        "totals": totals,
        "decision_profile": dict(sorted(decision_profile.items())),
        "repositories": per_repo,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"digest": hashlib.sha256(raw).hexdigest(), "pulse": body}


def main(argv=None):
    import argparse
    import sys

    from . import repo as RP

    ap = argparse.ArgumentParser(prog="warrant pulse", description="Deterministic cross-repository organism pulse.")
    ap.add_argument("--repo", action="append", required=True, help="Repository spec NAME=PATH (repeatable)")
    ap.add_argument("--as-of", type=int, default=None, help="Uniform Unix timestamp horizon")
    args = ap.parse_args(argv)

    repo_map = {}
    for spec in args.repo:
        if "=" not in spec:
            print(json.dumps({"error": f"expected NAME=PATH, got {spec!r}"}), file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        if name in repo_map:
            print(json.dumps({"error": f"duplicate repository name {name!r}"}), file=sys.stderr)
            return 2
        rp = RP.Repo(path)
        trust, profile, _ = rp.config()
        repo_map[name] = (rp.store.snapshot(), trust, profile)

    try:
        out = pulse_ecosystem(repo_map, as_of=args.as_of)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0
