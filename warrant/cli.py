"""`warrant` — the one command-line interface of Warrant 2 (SPEC.md).

Writing:   init, key, trust, blob, file, accept, observe, manifest, compute
Reading:   assess, reliance, frontier, questions, capsule
Every reading command assesses one view: --store, --trust, --profile, --as-of,
and optionally --current and --workspace. Output is JSON."""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import jcs as C
from . import compute as P
from . import engine as E
from . import records as R
from . import triggers as TR
from .keys import Key
from .store import Store, Trust


def _out(doc):
    sys.stdout.write(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(arg):
    if arg == "-":
        return json.loads(sys.stdin.read())
    if arg.lstrip().startswith(("{", "[")):
        return json.loads(arg)
    return json.loads(Path(arg).read_text())


def _key(path):
    return Key.from_seed_hex(Path(path).read_text())


def _now(v):
    return int(time.time()) if v is None else v


# ---------------------------------------------------------------- writing

def cmd_init(a):
    Store(a.store).init()
    _out({"store": str(Path(a.store))})


def cmd_key(a):
    p = Path(a.out)
    if p.exists():
        raise SystemExit(f"refusing to overwrite {p}")
    k = Key.generate()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(k.seed_hex() + "\n")
    _out({"key_file": str(p), "public": k.public, "key_id": k.id})


def cmd_trust(a):
    p = Path(a.trust)
    doc = json.loads(p.read_text()) if p.exists() else Trust.document([])
    pub = _key(a.key).public if a.key else a.public
    doc["keys"].append({"actor": a.actor, "public": pub})
    Trust(doc)                                    # refuse a malformed or doubly bound file
    p.write_bytes(C.canon(doc))
    _out({"trust": str(p), "actor": a.actor, "public": pub})


def cmd_blob(a):
    s = Store(a.store).init()
    if a.json is not None:
        h = s.put_json(_read_json(a.json))
    else:
        h = s.put_blob(sys.stdin.buffer.read() if a.file == "-" else Path(a.file).read_bytes())
    _out({"blob": h})


def cmd_file(a):
    s = Store(a.store).init()
    body = _read_json(a.body)
    try:
        r = R.record(a.type, a.actor, _now(a.at), body)
    except R.Invalid as e:
        raise SystemExit(f"invalid {a.type}: {e}")
    _out({"record": s.put_record(r, _key(a.key)), "type": a.type})


def cmd_accept(a):
    """Accept one exact item (or a transition's results) as it is filed."""
    s = Store(a.store).init()
    snap = s.snapshot()
    env = C.loads(snap.records[a.transition])
    t = env["record"]["body"]
    ev = t["evidence"] if a.item is None else t["closes"][a.item]["evidence"]
    r = R.record("accept", a.actor, _now(a.at), R.accept(a.transition, a.item, ev, a.support or []))
    _out({"record": s.put_record(r, _key(a.key)), "type": "accept"})


def cmd_observe(a):
    """Run a probe once and file what was observed, when, and how."""
    s = Store(a.store).init()
    probe = _read_json(a.probe)
    if not (isinstance(probe, dict) and isinstance(probe.get("argv"), list) and probe["argv"]):
        raise SystemExit("a probe is {\"argv\": [...], ...}: the command this observer runs")
    probe_h = s.put_json(probe)
    t0 = int(time.time())
    try:
        p = subprocess.run(probe["argv"], capture_output=True, timeout=probe.get("timeout", 30), check=False)
        result = p.stdout.decode(errors="replace").strip()[:R.MAX_TEXT]
        raw = [s.put_blob(p.stdout), s.put_json({"exit": p.returncode, "stderr": p.stderr.decode(errors="replace")[-2000:]})]
    except (OSError, subprocess.TimeoutExpired) as e:
        result, raw = f"PROBE_FAILED: {type(e).__name__}", []
    t1 = max(t0, int(time.time()))
    body = R.observation(a.target, probe_h, [t0, t1], result, raw)
    r = R.record("observation", a.actor, _now(a.at) if a.at is not None else t1, body)
    _out({"record": s.put_record(r, _key(a.key)), "type": "observation", "result": result, "window": [t0, t1]})


def cmd_manifest(a):
    s = Store(a.store).init()
    try:
        doc = TR.manifest(a.repo, a.rev, sorted(a.paths))
    except TR.Refusal as e:
        raise SystemExit(f"manifest refused: {e}")
    _out({"blob": s.put_json(doc), "commit": TR.resolve(a.repo, a.rev)})


# ---------------------------------------------------------------- compute (producer side)

def _env_blobs(s, env_h):
    snap = s.snapshot()
    doc = snap.json_blob(env_h)
    if doc is None or P.environment_problem(doc):
        raise SystemExit("not a sigma environment manifest in this store")
    hashes = doc["sigma-environment"]
    return hashes, {h: snap.blobs[h] for h in hashes if h in snap.blobs}


def _call(op, args, blobs=None):
    out = P.Provider.capture().call(op, args, blobs)
    if "refused" in out:
        raise SystemExit(f"provider refused: {out['refused']}")
    return out


def cmd_compute(a):
    s = Store(a.store).init()
    runtime = {"book1": P.BOOK1, "rich": P.RICH}[a.runtime]
    if a.op == "term":
        out = _call("term", {"expr": a.expr})
        nodes = [s.put_blob(base64.b64decode(b)) for b in out["nodes"].values()]
        env_h = s.put_json(P.environment_doc(nodes))
        return _out({"input": out["term"], "environment": env_h, "runtime": runtime, "nodes": len(nodes)})
    hashes, blobs = _env_blobs(s, a.environment)
    base = {"runtime": runtime, "input": a.input, "hashes": hashes}
    if a.op == "start":
        out = _call("start", base, blobs)
    elif a.op == "advance":
        snap = s.snapshot()
        out = _call("advance", dict(base, checkpoint=base64.b64encode(snap.blobs[a.checkpoint]).decode(),
                                    state=base64.b64encode(snap.blobs[a.state]).decode(), credit=a.credit), blobs)
    elif a.op == "cycle":
        out = _call("find_cycle", dict(base, max_steps=a.max_steps), blobs)
        if out.get("witness") is None:
            return _out({"cycle": None, "outcome": out.get("outcome")})
        w = s.put_blob(base64.b64decode(out["witness"]))
        doc = {"cycle": "sigma-resume", "target": a.target, "input": a.input, "environment": a.environment,
               "witness": w, "lost": []}
        return _out({"cycle": s.put_json(doc), "witness": w})
    else:
        raise SystemExit(f"unknown compute op {a.op}")
    ck = s.put_blob(base64.b64decode(out["checkpoint"]))
    st = s.put_blob(base64.b64decode(out["state"]))
    res = {"outcome": out["outcome"], "checkpoint": ck, "state": st, "result": out.get("result")}
    if out["outcome"] == "NORMAL_FORM" and a.target:
        res["receipt"] = s.put_json({"receipt": "sigma-resume", "target": a.target, "input": a.input,
                                     "environment": a.environment, "checkpoint": ck, "state": st,
                                     "claimed": out["result"], "lost": []})
    _out(res)


# ---------------------------------------------------------------- reading

def _report(a):
    s = Store(a.store)
    snap = s.snapshot()
    trust = Trust.load(a.trust)
    prof = _read_json(a.profile) if a.profile else E.profile()
    ws = None
    if a.workspace:
        repo, _, rev = a.workspace.rpartition("@")
        ws = (repo, rev or "HEAD")
    try:
        provider = P.Provider.capture()
    except P.ProviderError as e:
        print(f"warning: provider unavailable, replays are UNVERIFIED: {e}", file=sys.stderr)
        provider = None
    return E.assess(snap, trust, _now(a.as_of), prof, current=a.current or [], workspace=ws, provider=provider)


def cmd_assess(a):
    _out(_report(a))


def cmd_reliance(a):
    _out(E.reliance(_report(a), a.target, a.use))


def cmd_frontier(a):
    rep = _report(a)
    _out({"assessment_id": rep["assessment_id"], "actor": a.actor, "frontier": E.frontier(rep, a.actor)})


def cmd_questions(a):
    rep = _report(a)
    _out({"assessment_id": rep["assessment_id"], "questions": E.questions(rep, a.scope, owned=a.all)})


def cmd_capsule(a):
    _out(E.capsule(_report(a), a.target, a.use))


def build_parser():
    ap = argparse.ArgumentParser(prog="warrant", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def store(p):
        p.add_argument("--store", required=True)

    def signer(p):
        store(p)
        p.add_argument("--key", required=True, help="file holding the signer's Ed25519 seed (hex)")
        p.add_argument("--actor", required=True)
        p.add_argument("--at", type=int, help="record time (default: now)")

    def view(p):
        store(p)
        p.add_argument("--trust", required=True)
        p.add_argument("--profile", help="the recipient's profile JSON (default: one use 'act', no acceptors)")
        p.add_argument("--as-of", type=int, help="end of the view (default: now)")
        p.add_argument("--current", action="append", help="a revision the recipient treats as current")
        p.add_argument("--workspace", help="REPO@REV for subject_changed triggers")

    p = sub.add_parser("init", help="create a store")
    store(p)
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("key", help="generate an Ed25519 key file (0600, never overwritten)")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_key)
    p = sub.add_parser("trust", help="bind a key to an actor in a trust file")
    p.add_argument("--trust", required=True)
    p.add_argument("--actor", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--key")
    g.add_argument("--public")
    p.set_defaults(fn=cmd_trust)
    p = sub.add_parser("blob", help="add bytes (FILE or -) or a JSON document (--json) to the store")
    store(p)
    p.add_argument("file", nargs="?", default="-")
    p.add_argument("--json")
    p.set_defaults(fn=cmd_blob)
    p = sub.add_parser("file", help="sign and file a record body (SPEC §3)")
    signer(p)
    p.add_argument("--type", required=True, choices=R.TYPES)
    p.add_argument("body", help="JSON body, a file, or -")
    p.set_defaults(fn=cmd_file)
    p = sub.add_parser("accept", help="accept one exact item of a transition, or its results")
    signer(p)
    p.add_argument("transition")
    p.add_argument("--item", type=int, help="item index; omit to accept the transition's results")
    p.add_argument("--support", action="append")
    p.set_defaults(fn=cmd_accept)
    p = sub.add_parser("observe", help="run a probe and file the observation")
    signer(p)
    p.add_argument("--target", required=True)
    p.add_argument("--probe", required=True, help='JSON {"argv": [...], "timeout": s}')
    p.set_defaults(fn=cmd_observe)
    p = sub.add_parser("manifest", help="store a subject_changed baseline for explicit paths at a revision")
    store(p)
    p.add_argument("--repo", required=True)
    p.add_argument("--rev", required=True)
    p.add_argument("paths", nargs="+")
    p.set_defaults(fn=cmd_manifest)
    p = sub.add_parser("compute", help="sigma-resume producer steps: term, start, advance, cycle")
    store(p)
    p.add_argument("op", choices=("term", "start", "advance", "cycle"))
    p.add_argument("--runtime", choices=("book1", "rich"), default="book1")
    p.add_argument("--expr")
    p.add_argument("--input")
    p.add_argument("--environment")
    p.add_argument("--checkpoint")
    p.add_argument("--state")
    p.add_argument("--credit", type=int, default=0)
    p.add_argument("--max-steps", type=int, default=10000)
    p.add_argument("--target", help="crossing target named in the receipt or cycle")
    p.set_defaults(fn=cmd_compute)
    for name, fn, extra in (("assess", cmd_assess, None), ("reliance", cmd_reliance, "target"),
                            ("frontier", cmd_frontier, "actor"), ("questions", cmd_questions, None),
                            ("capsule", cmd_capsule, "target")):
        p = sub.add_parser(name)
        view(p)
        if extra:
            p.add_argument(extra)
        if name in ("reliance", "capsule"):
            p.add_argument("--use", default="act")
        if name == "questions":
            p.add_argument("--scope")
            p.add_argument("--all", action="store_true", help="include questions a duty has taken")
        p.set_defaults(fn=fn)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
