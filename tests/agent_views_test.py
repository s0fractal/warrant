#!/usr/bin/env python3
"""Views as manifests over a workspace's content-addressed object store, and their collection (J).

A view pins records, blobs, provider modules, its tree, its report body and its manifest by the
SHA-256 of their bytes; a read hashes what it reads and never falls back to the live store; a
collection removes expired views and the objects no live view pins, under a lock that a capture
holds shared until its view is reachable. States are asserted by codes, object names and bytes,
never by wording.

    python3 tests/agent_views_test.py
"""
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from agent_world import ROOT, R, check, finish, reviewed_work, views, world
from warrant_agent import objects as O
from warrant_agent.config import Config
from warrant_agent.errors import AgentError

CTX = {"actor": "producer", "use": "continue", "targets": []}
IMPL = os.environ.get("WARRANT_IMPL") or str(ROOT)


def ok(r):
    assert "ok" in r, r
    return r["ok"]


def ctx(p, **kw):
    return ok(p.call("context", dict(CTX, workspace=p.name, **kw)))


def read(p, token, kind, target):
    """A read's result; an exception that is no typed refusal becomes {"error": "CRASH:<type>"} (a case, not a crash)."""
    try:
        return p.call("read", {"workspace": p.name, "view_token": token, "kind": kind, "target": target})
    except Exception as e:      # noqa: BLE001
        return {"error": f"CRASH:{type(e).__name__}"}


def data(r):
    return r.get("ok", {}).get("data", {})


def objs(p):
    return O.Objects(p.ws.state / "objects")


def names(p):
    return {n for n, _ in objs(p).names() if n is not None}


def manifest(p, token):
    return objs(p).get_doc(json.loads((p.ws.state / "views" / token / "view.json").read_bytes())["manifest"])


def pinned(p, token):
    """Every object name the view's manifest pins (the manifest included)."""
    m = manifest(p, token)
    tree = objs(p).get_doc(m["tree"])
    name = json.loads((p.ws.state / "views" / token / "view.json").read_bytes())["manifest"]
    return {name, m["tree"], m["report"]["body"], *(m["provider"] or {}).values(), *tree["records"].values(),
            *tree["blobs"]}


def overwrite(path, data):
    """Bytes changed under the same name (an object is read-only on disk)."""
    os.chmod(path, 0o644)
    path.write_bytes(data)


def obj_path(p, name):
    return objs(p).path(name)


def limits(p, **kw):
    p.doc["workspaces"][p.name]["limits"] = kw
    p.reload()


def tree_digest(root):
    """{relative path: sha256} of every file under root."""
    root = Path(root)
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()} if root.is_dir() else {}


def error(r):
    return (r.get("error"), (r.get("details") or {}).get("object"))


def frozen_cases():
    src, _ = world()
    ids = reviewed_work(src)
    a = ctx(src)
    tok = a["view_token"]
    rid = ids["transition"]
    before = {"record": data(read(src, tok, "record", rid)), "blob": data(read(src, tok, "blob", ids["evidence"])),
              "objects": {n: obj_path(src, n).read_bytes() for n in names(src)}}
    # J01: the live store changes (a new record, an existing record file rewritten, another removed): the
    # earlier view answers from the bytes it pinned; objects are only added
    new = src.file("transition", "producer", 300, R.transition("ATTESTED", established=["newer"]))
    live = src.ws.store / "records" / f"{rid}.json"
    live.write_bytes(live.read_bytes().replace(b"abs is implemented", b"abs is IMPLEMENTED"))
    (src.ws.store / "records" / f"{ids['accept']}.json").unlink()
    b = ctx(src)
    later = ok(src.call("read", {"workspace": "src", "view_token": tok, "kind": "context"}))
    after = {"record": data(read(src, tok, "record", rid)), "blob": data(read(src, tok, "blob", ids["evidence"]))}
    kept = all(obj_path(src, n).read_bytes() == b for n, b in before["objects"].items())
    check("J01", later["assessment_id"] == a["assessment_id"] and after == {k: before[k] for k in ("record", "blob")}
          and read(src, tok, "record", new).get("error") == "NOT_FOUND"
          and data(read(src, tok, "record", ids["accept"])).get("total", 0) > 0
          and b["assessment_id"] != a["assessment_id"] and "ok" in read(src, b["view_token"], "record", new)
          and kept and set(before["objects"]) < names(src),
          "a view answers from the bytes it pinned after the live store changes; objects are only added",
          (later["assessment_id"] == a["assessment_id"], after == {k: before[k] for k in ("record", "blob")}, kept))

    # J02: bytes changed under an object's name are refused on read, never replaced by the live store's
    src2, _ = world()
    ids2 = reviewed_work(src2)
    v = ctx(src2)
    t2 = v["view_token"]
    m = manifest(src2, t2)
    tree = objs(src2).get_doc(m["tree"])
    rec_obj = tree["records"][ids2["duty"]]
    saved_rec = obj_path(src2, rec_obj).read_bytes()
    overwrite(obj_path(src2, rec_obj), b"{}")
    r_rec = read(src2, t2, "record", ids2["duty"])
    overwrite(obj_path(src2, rec_obj), saved_rec)
    body_obj = m["report"]["body"]
    saved_body = obj_path(src2, body_obj).read_bytes()
    overwrite(obj_path(src2, body_obj), saved_body + b" ")
    r_body = src2.call("read", {"workspace": "src", "view_token": t2, "kind": "context"})
    overwrite(obj_path(src2, body_obj), saved_body)
    # another view's manifest under this token: not this view
    w = ctx(src2)
    vj = src2.ws.state / "views" / t2 / "view.json"
    saved_vj = vj.read_bytes()
    vj.write_bytes((src2.ws.state / "views" / w["view_token"] / "view.json").read_bytes())
    r_swap = src2.call("read", {"workspace": "src", "view_token": t2, "kind": "context"})
    vj.write_bytes(saved_vj)
    # damaged while the worker reads it: a typed refusal and no view
    real_assess = views._assess

    def tamper_then_assess(vdir, deadline):
        meta = json.loads((vdir / "meta.json").read_bytes())
        overwrite(obj_path(src2, objs(src2).get_doc(meta["tree"])["records"][ids2["accept"]]), b"x")
        return real_assess(vdir, deadline)
    views._assess = tamper_then_assess
    try:
        r_worker = src2.call("context", dict(CTX, workspace="src"))
    finally:
        views._assess = real_assess
    views_left = sorted(d.name for d in (src2.ws.state / "views").iterdir())
    check("J02", error(r_rec) == ("VIEW_DAMAGED", rec_obj) and error(r_body) == ("VIEW_DAMAGED", body_obj)
          and r_swap.get("error") == "VIEW_UNKNOWN"
          and r_worker.get("error") == "VIEW_DAMAGED" and views_left == sorted([t2, w["view_token"]])
          and "ok" in src2.call("read", {"workspace": "src", "view_token": t2, "kind": "context"}),
          "changed bytes under an object's name, a report body or a manifest of another view are refused; "
          "damage under the worker is VIEW_DAMAGED with no view",
          (error(r_rec), error(r_body), r_swap.get("error"), r_worker.get("error"), views_left))

    # J03: a pinned object that is absent is refused, not read from the live store (which still holds it)
    blob_obj = ids2["evidence"]
    blob_bytes = obj_path(src2, blob_obj).read_bytes()
    obj_path(src2, blob_obj).unlink()
    r_missing = read(src2, t2, "blob", blob_obj)
    live_has = (src2.ws.store / "blobs" / blob_obj).read_bytes() == blob_bytes
    check("J03", error(r_missing) == ("VIEW_DAMAGED", blob_obj) and live_has,
          "an absent pinned object is VIEW_DAMAGED although the live store holds its bytes", error(r_missing))

    # J04: a new capture writes back exactly the bytes the name stands for; the earlier view answers again
    overwrite(obj_path(src2, rec_obj), b"{}")
    fresh = src2.call("context", dict(CTX, workspace="src"))
    repaired = data(read(src2, t2, "record", ids2["duty"]))
    check("J04", "ok" in fresh and hashlib.sha256(obj_path(src2, rec_obj).read_bytes()).hexdigest() == rec_obj
          and obj_path(src2, blob_obj).is_file() and repaired.get("digest") == hashlib.sha256(
              (src2.ws.store / "records" / f"{ids2['duty']}.json").read_bytes()).hexdigest(),
          "a capture restores damaged or absent objects to the bytes their names stand for", repaired.get("digest"))

    # J15: views of an unchanged store share every object but their manifests: three files per view
    src3, _ = world()
    reviewed_work(src3)
    ctx(src3)
    n0, f0 = names(src3), sum(1 for _ in (src3.ws.state / "views").rglob("*") if _.is_file())
    tokens = [ctx(src3)["view_token"] for _ in range(4)]
    added = names(src3) - n0
    files = sum(1 for _ in (src3.ws.state / "views").rglob("*") if _.is_file()) - f0
    mans = {json.loads((src3.ws.state / "views" / t / "view.json").read_bytes())["manifest"] for t in tokens}
    check("J15", added <= mans | {manifest(src3, t)["report"]["body"] for t in tokens} and mans <= added
          and len(mans) == 4 and files == 4 * 2,
          "views of an unchanged store add their manifests (and a report body only when as_of changes it)",
          (len(added), len(mans), files))


def admission_cases():
    # J16: the worker admits the pinned snapshot under the workspace's limits (SPEC §9) as a store read does:
    # staged bytes that take the union past snapshot_bytes are RESOURCE_LIMIT with no view
    src, _ = world()
    reviewed_work(src)
    live = sum(f.stat().st_size for f in src.ws.store.rglob("*") if f.is_file())
    big = b"y" * 4096
    extra = {"records": {}, "blobs": {hashlib.sha256(big).hexdigest(): big}}
    outcomes = []
    for bound in (live + len(big) - 1, live + len(big)):
        limits(src, snapshot_bytes=bound, gc_interval=0)
        before = sorted(d.name for d in (src.ws.state / "views").iterdir())
        try:
            views.capture(src.ws, extra=extra)
            outcomes.append(("view", None))
        except AgentError as e:
            outcomes.append((e.code, e.details.get("limit"),
                             sorted(d.name for d in (src.ws.state / "views").iterdir()) == before))
    check("J16", outcomes == [("RESOURCE_LIMIT", "snapshot_bytes", True), ("view", None)],
          "staged bytes past snapshot_bytes are refused in the worker with no view; at the bound a view", outcomes)


def collection_cases():
    src, _ = world()
    ids = reviewed_work(src)
    limits(src, view_ttl=1, gc_interval=0)
    old = ctx(src)["view_token"]
    old_pins = pinned(src, old)
    loaded = views.load(src.ws, old)[2]
    src.file("transition", "producer", 300, R.transition("ATTESTED", established=["newer"]))
    limits(src, gc_interval=0)
    live = ctx(src)["view_token"]
    live_pins = pinned(src, live)
    stray = objs(src).put(b"no view pins this")
    tmp = obj_path(src, stray).parent / f"{O.TMP}123-dead"
    tmp.write_bytes(b"half")
    foreign = obj_path(src, stray).parent / "README"
    foreign.write_bytes(b"not an object")
    unfinished = src.ws.state / "views" / secrets.token_hex(16)
    unfinished.mkdir()
    (unfinished / "meta.json").write_text(json.dumps({"tree": stray}))
    time.sleep(2.1)
    expired_before_gc = read(src, old, "record", ids["duty"]).get("error")
    dry = views.collect(src.ws, dry_run=True)
    after_dry = names(src)
    rep = views.collect(src.ws)
    gone = old_pins - live_pins
    # J05: what a live view pins is kept, byte for byte; what only expired views, nothing or a dead capture
    # pinned is removed; a temporary is removed, a file that is not an object is left
    check("J05", dry["objects_removed"] == rep["objects_removed"] and after_dry >= live_pins | old_pins | {stray}
          and live_pins <= names(src) and not (gone & names(src)) and stray not in names(src)
          and names(src) == live_pins and not tmp.exists() and foreign.exists()
          and not (src.ws.state / "views" / old).exists() and not unfinished.exists()
          and all(hashlib.sha256(obj_path(src, n).read_bytes()).hexdigest() == n for n in live_pins)
          and "ok" in src.call("read", {"workspace": "src", "view_token": live, "kind": "context"})
          and rep["views"] == {"live": 1, "expired": 1, "unfinished": 1} and expired_before_gc == "VIEW_EXPIRED",
          "a collection keeps every object a live view pins and removes the rest",
          (rep, sorted(names(src) ^ live_pins)[:4], tmp.exists(), foreign.exists()))

    # J10: after expiry a token is VIEW_EXPIRED, after collection VIEW_UNKNOWN; a view loaded before it
    # expired whose objects were collected answers VIEW_EXPIRED, never DAMAGED or the live store's bytes
    try:
        loaded.record(ids["duty"])
        late = "read"
    except AgentError as e:
        late = e.code
    check("J10", read(src, old, "record", ids["duty"]).get("error") == "VIEW_UNKNOWN" and late == "VIEW_EXPIRED",
          "an expired view is VIEW_EXPIRED, a collected one VIEW_UNKNOWN; a loaded one whose objects went, VIEW_EXPIRED",
          late)

    # J06: a collection reads nothing but views/ and objects/ as roots and touches nothing else: drafts,
    # staging, imports, exports and the store keep their bytes, and a draft whose view was collected commits
    src2, rcv = world()
    ids2 = reviewed_work(src2)
    limits(src2, view_ttl=1, gc_interval=0)
    limits(rcv, view_ttl=1, gc_interval=0)
    base = ctx(src2)["view_token"]
    draft = ok(src2.call("prepare", {"workspace": "src", "based_on": base, "type": "accept",
                                     "body": {"transition": ids2["transition"], "item": 0}}))["data"]
    pkg = ok(src2.call("handoff", {"op": "export", "workspace": "src", "view_token": base}))["data"]
    rcv.expect("cut", pkg["manifest_digest"], source="src")
    staged = ok(rcv.call("handoff", {"op": "inspect", "workspace": "rcv", "package": pkg["package"],
                                     "expectation": "cut"}))["data"]["staged_id"]
    parts = {p: {d: tree_digest(p.ws.state / d) for d in ("drafts", "staging", "imports", "exports", "requests",
                                                           "verdicts", "replay-cache")} for p in (src2, rcv)}
    stores = {p: tree_digest(p.ws.store) for p in (src2, rcv)}
    time.sleep(2.1)
    swept = [views.collect(p.ws) for p in (src2, rcv)]
    same = all(parts[p] == {d: tree_digest(p.ws.state / d) for d in parts[p]} for p in (src2, rcv)) \
        and all(stores[p] == tree_digest(p.ws.store) for p in (src2, rcv))
    committed = src2.call("commit", {"workspace": "src", "draft_id": draft["draft_id"]})
    imported = rcv.call("handoff", {"op": "import", "workspace": "rcv", "staged_id": staged})
    check("J06", same and all(s["views_removed"] >= 1 and s["objects_removed"] > 0 for s in swept)
          and "ok" in committed and ok(imported)["data"]["status"] == "COMPLETE"
          and not list((src2.ws.state / "views").iterdir()),
          "a collection touches neither drafts, staging, imports, exports nor the store; a draft and an import "
          "whose views were collected still complete", (same, swept, committed, imported))


def race_cases():
    # J08: a collection during a capture: the capture holds the lock shared from its first object until its
    # view is reachable, so a collection that does not wait gives up, one that waits runs after, and the
    # new view keeps every object it pinned
    src, _ = world()
    ids = reviewed_work(src)
    entered, release, out = threading.Event(), threading.Event(), {}
    real_assess = views._assess

    def held(vdir, deadline):
        entered.set()
        release.wait(30)
        return real_assess(vdir, deadline)

    def capture():
        try:
            out["capture"] = views.capture(src.ws)
        except AgentError as e:
            out["capture"] = e.code

    def collect():
        out["waited"] = views.collect(src.ws)

    views._assess = held
    try:
        t1 = threading.Thread(target=capture)
        t1.start()
        entered.wait(30)
        written = names(src)
        busy = views.collect(src.ws, wait=False)
        t2 = threading.Thread(target=collect)
        t2.start()
        time.sleep(0.5)
        blocked = t2.is_alive()
        release.set()
        t1.join(60)
        t2.join(60)
    finally:
        views._assess = real_assess
    token = out["capture"]["token"] if isinstance(out.get("capture"), dict) else None
    check("J08", busy is None and blocked and token is not None and written and written <= names(src)
          and pinned(src, token) <= names(src) and out["waited"]["objects_removed"] == 0
          and "ok" in read(src, token, "record", ids["duty"]),
          "a collection waits for a capture in flight and never takes an object it is pinning",
          (busy, blocked, out.get("capture") if token is None else token, out.get("waited")))

    # J07: a view directory a capture left without view.json (no capture is in flight under the exclusive
    # lock) is removed; one being written while the lock is held shared is not looked at
    unfinished = src.ws.state / "views" / secrets.token_hex(16)
    unfinished.mkdir()
    (unfinished / "meta.json").write_text("{}")
    with objs(src).lock(exclusive=False):
        meanwhile = views.collect(src.ws, wait=False)
    swept = views.collect(src.ws)
    check("J07", meanwhile is None and swept["views"].get("unfinished") == 1 and not unfinished.exists()
          and "ok" in read(src, token, "record", ids["duty"]),
          "an unfinished view directory is removed only under the exclusive lock", (meanwhile, swept))

    # J09: the collection at the end of a capture runs when the last is older than gc_interval, never waits
    # for the lock, and gc_interval 0 turns it off
    limits(src, view_ttl=1, gc_interval=0)
    ex = ctx(src)["view_token"]
    time.sleep(2.1)
    limits(src, gc_interval=0)
    ctx(src)
    off = (src.ws.state / "views" / ex).exists()
    limits(src, gc_interval=3600)
    views.write_json(objs(src).root / O.LAST, {"collected": int(time.time())})
    ctx(src)
    recent = (src.ws.state / "views" / ex).exists()
    with objs(src).lock(exclusive=False):
        views.write_json(objs(src).root / O.LAST, {"collected": 0})
        due_out = {}
        t = threading.Thread(target=lambda: due_out.setdefault("r", views.collect_due(src.ws)), daemon=True)
        t.start()
        t.join(2)
        quick, busy = not t.is_alive(), due_out.get("r", "WAITED")
    ctx(src)
    due = not (src.ws.state / "views" / ex).exists()
    check("J09", off and recent and busy is None and quick and due,
          "a capture collects when gc_interval has passed, not before, never waiting; 0 turns it off",
          (off, recent, busy, quick, due))


def workspace_cases():
    # J11: two workspaces of one state directory over one store keep separate object stores: a collection of
    # one removes none of the other's objects, and a token of one is no view of the other
    src, _ = world()
    ids = reviewed_work(src)
    doc = json.loads(json.dumps(src.doc))
    doc["workspaces"]["twin"] = dict(doc["workspaces"]["src"], source_name="twin", limits={"view_ttl": 1, "gc_interval": 0})
    cfg = Config(doc)
    a, b = cfg.workspace("src"), cfg.workspace("twin")
    ta = ok(api_call(cfg, "context", dict(CTX, workspace="src")))["view_token"]
    tb = ok(api_call(cfg, "context", dict(CTX, workspace="twin")))["view_token"]
    before = tree_digest(a.state / "objects")
    time.sleep(2.1)
    rep = views.collect(b)
    check("J11", a.state / "objects" != b.state / "objects" and tree_digest(a.state / "objects") == before
          and rep["objects_removed"] > 0 and not [n for n, _ in O.Objects(b.state / "objects").names() if n]
          and api_call(cfg, "read", {"workspace": "twin", "view_token": ta, "kind": "context"}).get("error") == "VIEW_UNKNOWN"
          and "ok" in api_call(cfg, "read", {"workspace": "src", "view_token": ta, "kind": "record", "target": ids["duty"]})
          and api_call(cfg, "read", {"workspace": "src", "view_token": tb, "kind": "context"}).get("error") == "VIEW_UNKNOWN",
          "each workspace has its own objects; collecting one leaves the other's", rep)


def api_call(cfg, op, req):
    from warrant_agent import api
    return api.call(cfg, op, req)


def legacy_cases():
    # J12: a view written before manifests (a full copy in its directory) answers as before until it expires,
    # and a collection removes it only then; nothing is converted
    src, _ = world()
    ids = reviewed_work(src)
    v = ctx(src)
    meta, report, view = views.load(src.ws, v["view_token"])
    snap = view.snapshot()
    tok = secrets.token_hex(16)
    old = src.ws.state / "views" / tok
    for rid, b in snap.records.items():
        views._write(old / "records" / f"{rid}.json", b)
    for h, b in snap.blobs.items():
        views._write(old / "blobs" / h, b)
    legacy_meta = {k: x for k, x in meta.items() if k not in ("tree", "report", "view")}
    legacy_meta.update(token=tok, provider=meta["provider"] is not None)
    views.write_json(old / "meta.json", legacy_meta)
    views.write_json(old / "report.json", report)
    views.write_json(old / "context.json", {"actor": "producer", "targets": [], "use": "continue", "scope": None})
    page = src.call("read", {"workspace": "src", "view_token": tok, "kind": "context"})
    rec = read(src, tok, "record", ids["duty"])
    kept = views.collect(src.ws)
    still = (old / "records").is_dir()
    legacy_meta["expires"] = int(time.time()) - 1
    views.write_json(old / "meta.json", legacy_meta)
    removed = views.collect(src.ws)
    check("J12", page.get("ok", {}).get("assessment_id") == report["assessment_id"]
          and data(rec).get("digest") == hashlib.sha256(snap.records[ids["duty"]]).hexdigest()
          and kept["views"].get("live") == 2 and still and removed["views"].get("expired") == 1 and not old.exists(),
          "a full-copy view of an earlier version answers until it expires, then a collection removes it",
          (page.get("error"), kept, removed))

    # J13: a stray file in the store's records/ is reported by the view as a store read reports it (misfiled),
    # not refused: master refused every context of such a store as NO_ASSESSMENT
    (src.ws.store / "records" / "README").write_text("stray\n")
    r = src.call("context", dict(CTX, workspace="src"))
    tree = objs(src).get_doc(manifest(src, ok(r)["view_token"])["tree"]) if "ok" in r else {"misfiled": []}
    check("J13", "ok" in r and tree["misfiled"] == ["records/README: not a record file name"],
          "a misfiled store file is pinned in the tree's misfiled list and the store is assessed", r.get("error"))


def cli_cases():
    # J14: `warrant-agent gc`: --dry-run reports and removes nothing; without it, it removes
    src, _ = world()
    reviewed_work(src)
    limits(src, view_ttl=1, gc_interval=0)
    ctx(src)
    time.sleep(2.1)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([IMPL] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
    run = [sys.executable, "-m", "warrant_agent.cli", "--config", str(src.base / "config.json"), "gc"]
    before = names(src)
    d = subprocess.run(run + ["--dry-run"], capture_output=True, env=env, check=False)
    after_dry = names(src)
    g = subprocess.run(run + ["--workspace", "src"], capture_output=True, env=env, check=False)
    bad = subprocess.run(run[:-1] + ["context", "--dry-run"], capture_output=True, env=env, check=False)
    dout, gout = json.loads(d.stdout or b"{}"), json.loads(g.stdout or b"{}")
    check("J14", d.returncode == 0 and g.returncode == 0 and after_dry == before and before
          and dout["ok"]["gc"][0]["dry_run"] and dout["ok"]["gc"][0]["objects_removed"] == len(before)
          and gout["ok"]["gc"][0]["objects_removed"] == len(before) and not names(src) and bad.returncode == 2,
          "warrant-agent gc --dry-run removes nothing; gc removes what no live view pins",
          (d.returncode, g.returncode, d.stderr[-300:], dout, gout))


def main():
    for group in (frozen_cases, admission_cases, collection_cases, race_cases, workspace_cases, legacy_cases, cli_cases):
        try:
            group()
        except Exception as e:      # noqa: BLE001
            check(f"RAISED-{group.__name__}", False, f"{group.__name__} ran to its end", f"{type(e).__name__}: {e}")
    return finish("AGENT-VIEWS")


if __name__ == "__main__":
    sys.exit(main())
