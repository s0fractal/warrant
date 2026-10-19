"""Frozen receiver views (PROPOSAL §4, CONTRACT C.1-C.2).

A view owns copies of every operand that can change a verdict: the store's
record and blob bytes, the receiver's trust bytes and profile, as_of, current
revisions, the workspace commit and the accepted provider's module bytes. The
engine assesses that copy once, in a worker process with a deadline; every later
read of the view uses the stored report and the captured bytes, never the live
store. A view token selects a view; it grants nothing."""
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from warrant import compute as P
from warrant import jcs as C
from warrant import triggers as TR
from warrant.store import Snapshot, Trust

from .errors import AgentError, need

TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path, doc):
    _write(Path(path), json.dumps(doc, sort_keys=True, indent=1).encode())


def read_json(path):
    return json.loads(Path(path).read_bytes())


def live_digest(ws):
    return Snapshot.read(ws.store).digest


def incomplete_imports(ws):
    out = []
    for p in sorted((ws.state / "imports").glob("*.json")):
        doc = read_json(p)
        if doc.get("status") != "COMPLETE":
            out.append(p.stem)
    return out


def capture(ws, extra=None, delivery=None, as_of=None):
    """Freeze the operands, assess once, return the view meta. `extra` is
    {"records": {id: bytes}, "blobs": {hash: bytes}} added to the live store's
    bytes (an inspection of a staged package); live bytes are never replaced."""
    live = Snapshot.read(ws.store)
    records, blobs = dict(live.records), dict(live.blobs)
    for rid, data in (extra or {}).get("records", {}).items():
        records.setdefault(rid, bytes(data))
    for h, data in (extra or {}).get("blobs", {}).items():
        blobs.setdefault(h, bytes(data))
    frozen = Snapshot(records, blobs, live.misfiled)
    try:
        provider = P.Provider.capture()
        sources = {n: bytes(b) for n, b in provider.sources.items()}
    except P.ProviderError:
        sources = None
    commit = TR.resolve(*ws.repo) if ws.repo else None
    trust_bytes, profile = ws.trust_bytes(), ws.profile()   # each read once
    token = secrets.token_hex(16)
    vdir = ws.state / "views" / token
    for rid, data in records.items():
        _write(vdir / "records" / f"{rid}.json", data)
    for h, data in blobs.items():
        _write(vdir / "blobs" / h, data)
    for n, data in (sources or {}).items():
        _write(vdir / "provider" / f"{n}.py", data)
    now = int(time.time())
    meta = {"token": token, "workspace": ws.name, "created": now, "expires": now + int(ws.limits["view_ttl"]),
            "as_of": int(as_of if as_of is not None else now), "current": sorted(ws.current),
            "repo": [str(ws.repo[0]), commit] if ws.repo else None, "snapshot": frozen.digest,
            "live_snapshot": live.digest, "trust": base64.b64encode(trust_bytes).decode(),
            "profile": profile, "provider": bool(sources),
            "delivery": delivery or {"relation": "LOCAL_CAPTURE", "source_completeness": "UNATTESTED"}}
    write_json(vdir / "meta.json", meta)
    try:
        _assess(vdir, ws.limits["assess_seconds"])
    except AgentError:
        shutil.rmtree(vdir, ignore_errors=True)
        raise
    report = read_json(vdir / "report.json")
    assessed = report["view"]
    want_provider = P.identity_of(sources) if sources else None
    got_provider = (assessed["provider"] or {}).get("provider")
    if (assessed["snapshot"], assessed["trust"], got_provider) != (frozen.digest, Trust(C.loads(trust_bytes)).digest, want_provider):
        shutil.rmtree(vdir, ignore_errors=True)
        raise AgentError("NO_ASSESSMENT", "the assessed operands are not the captured ones")
    return meta


def _assess(vdir, deadline):
    paths = [str(Path(__file__).resolve().parents[1]), str(Path(P.__file__).resolve().parents[1])]
    code = ("import sys; sys.path[:0] = %r; from warrant_agent._assess_worker import main; main(%r)"
            % (paths, str(vdir)))
    try:
        p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, timeout=deadline, check=False)
    except subprocess.TimeoutExpired:
        raise AgentError("NO_ASSESSMENT", f"assessment exceeded the host deadline of {deadline}s") from None
    if p.returncode != 0 or not (vdir / "report.json").is_file():
        raise AgentError("NO_ASSESSMENT", "the assessment worker produced no report",
                         stderr=p.stderr.decode(errors="replace")[-400:])


def load(ws, token):
    need(isinstance(token, str) and TOKEN.match(token) is not None, "VIEW_UNKNOWN", "not a view token")
    vdir = ws.state / "views" / token
    if not (vdir / "meta.json").is_file() or not (vdir / "report.json").is_file():
        raise AgentError("VIEW_UNKNOWN", "no such view in this workspace; open a new context")
    meta = read_json(vdir / "meta.json")
    if meta["workspace"] != ws.name:
        raise AgentError("VIEW_UNKNOWN", "no such view in this workspace; open a new context")
    if int(time.time()) >= meta["expires"]:
        raise AgentError("VIEW_EXPIRED", "the view expired; open a new context")
    return meta, read_json(vdir / "report.json"), vdir


def observation(ws, meta):
    """What is known locally now, apart from the frozen report."""
    return {"newer_known": live_digest(ws) != meta["live_snapshot"], "incomplete_imports": incomplete_imports(ws)}
