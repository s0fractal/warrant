"""Frozen receiver views (PROPOSAL §4, CONTRACT C.1-C.2).

A view pins every operand that can change a verdict: the store's record and blob
bytes, the receiver's trust bytes and profile, as_of, current revisions, the
workspace commit and the accepted provider's module bytes. The bytes live once in
the workspace's object store (objects.py), each under its SHA-256; a view is a
manifest object naming them, reached from views/<token>/view.json. The engine
assesses the pinned bytes once, in a worker process with a deadline, which reads
the view directory, the objects it names and, for cost only, the workspace's
replay cache (`<state>/replay-cache`): the receiver's own earlier verified replays
by the same provider over the same bytes (SPEC §7). Every later read of the view
uses the stored report and the pinned objects, each hashed as it is read, never
the live store. A view token selects a view; it grants nothing. collect removes
expired views and the objects no live view pins."""
import base64
import json
import math
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
from warrant import limits as L
from warrant import shapes as S
from warrant import triggers as TR
from warrant.store import Snapshot, Trust

from . import objects as O
from .errors import AgentError, need

TOKEN = S.HEX32
ADDRESS = S.HEX64
SOURCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def _addr(name, pattern=ADDRESS):
    """A file name inside a view is a content address (or a provider module name), never a path."""
    need(pattern.match(name) is not None, "BAD_REQUEST", "not a content address")
    return name


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path, doc):
    _write(Path(path), json.dumps(doc, sort_keys=True, indent=1).encode())


def read_json(path):
    return json.loads(Path(path).read_bytes())


def refusal(e):
    """An engine admission limit as the typed refusal: never a semantic result."""
    return AgentError("RESOURCE_LIMIT", str(e), limit=e.limit, value=e.value, bound=e.bound)


def read_snapshot(ws, root):
    """Snapshot.read under the workspace's admission limits."""
    try:
        return Snapshot.read(root, limits=ws.assessment_limits())
    except L.LimitExceeded as e:
        raise refusal(e) from None


def live_digest(ws):
    return read_snapshot(ws, ws.store).digest


def _landed(ws, journal):
    """An unfinished import whose every DECLARED object (record envelope digests and
    blob hashes of its manifest) is now in the live store with those exact bytes,
    for example through a later, larger import, leaves nothing half-promoted. The
    staging directory is not consulted for the set: it may have been cleaned."""
    spath = ws.state / "staging" / journal.get("staged_id", "") / "staged.json"
    if not journal.get("staged_id") or not spath.is_file():
        return False
    manifest = read_json(spath)["manifest"]
    for r in manifest["records"]:
        dst = ws.store / "records" / f"{_addr(r['id'])}.json"
        if not dst.is_file() or C.digest(dst.read_bytes()) != r["envelope"]:
            return False
    for h in manifest["blobs"]:
        dst = ws.store / "blobs" / _addr(h)
        if not dst.is_file() or C.digest(dst.read_bytes()) != h:
            return False
    return True


def incomplete_imports(ws):
    out = []
    for p in sorted((ws.state / "imports").glob("*.json")):
        doc = read_json(p)
        if doc.get("status") != "COMPLETE" and not _landed(ws, doc):
            out.append(p.stem)
    return out


VIEW = "warrant-agent/view@1"      # a manifest's format: the view it pins, by object names
VIEW_FILE = "view.json"             # views/<token>/view.json: {"manifest": the manifest's object name}
LEGACY = "a full copy"              # a view written before views were manifests (still read until it expires)


def objects_of(ws):
    return O.Objects(ws.state / "objects")


def capture(ws, extra=None, delivery=None, as_of=None):
    """Freeze the operands, assess once, return the view's manifest. `extra` is
    {"records": {id: bytes}, "blobs": {hash: bytes}} added to the live store's
    bytes (an inspection of a staged package); live bytes are never replaced.

    Every byte goes into the workspace's object store (objects.py) under its hash; the view is a
    manifest object pinning them by name, reachable from views/<token>/view.json once it is ready.
    The shared lock is held from the first object written until view.json exists: a collection
    (collect) holds it exclusively, so it never takes an object a capture is about to pin."""
    live = read_snapshot(ws, ws.store)
    records, blobs, misfiled = dict(live.records), dict(live.blobs), list(live.misfiled)
    for rid, data in (extra or {}).get("records", {}).items():
        records.setdefault(_addr(rid), bytes(data))
    for h, data in (extra or {}).get("blobs", {}).items():
        if _addr(h) in blobs:
            continue
        if C.digest(bytes(data)) != h:      # as a store read files it (Snapshot.read): never under its name
            misfiled.append(f"blobs/{h}: name is not its hash")
        else:
            blobs[h] = bytes(data)
    for rid in records:
        _addr(rid)
    frozen = Snapshot(records, blobs, misfiled)
    try:
        provider = P.Provider.capture()
        sources = {_addr(n, SOURCE): bytes(b) for n, b in provider.sources.items()}
    except P.ProviderError:
        sources = None
    commit = TR.resolve(*ws.repo) if ws.repo else None
    trust_bytes, profile = ws.trust_bytes(), ws.profile()   # each read once
    token = secrets.token_hex(16)
    vdir = ws.state / "views" / token
    objs = objects_of(ws)
    with objs.lock(exclusive=False):
        try:
            tree = {"records": {rid: objs.put(data) for rid, data in sorted(records.items())},
                    "blobs": sorted(objs.put(data) for data in blobs.values()), "misfiled": sorted(misfiled)}
            now = int(time.time())
            meta = {"view": VIEW, "token": token, "workspace": ws.name, "created": now, "expires": None,
                    "as_of": int(as_of if as_of is not None else now), "current": sorted(ws.current),
                    "repo": [str(ws.repo[0]), commit] if ws.repo else None, "snapshot": frozen.digest,
                    "tree": objs.put(O.doc_bytes(tree)), "live_snapshot": live.digest,
                    "trust": base64.b64encode(trust_bytes).decode(), "profile": profile,
                    "provider": {n: objs.put(b) for n, b in sorted(sources.items())} if sources else None,
                    "limits": ws.assessment_limits(),
                    # The receiver's own verified replays, reused across views (cost only).
                    "replay_cache": str(ws.state / "replay-cache"),
                    # ... and its own authentication verdicts (store.Verdicts.at, F44; cost only).
                    "verdicts": str(ws.state / "verdicts"),
                    "delivery": delivery or {"relation": "LOCAL_CAPTURE", "source_completeness": "UNATTESTED"}}
        except O.Unreadable as e:
            raise damaged(e) from None
        vdir.mkdir()
        try:
            write_json(vdir / "meta.json", meta)
            _assess(vdir, ws.limits["assess_seconds"])
            report = read_json(vdir / "report.json")
            assessed = report["view"]
            want_provider = P.identity_of(sources) if sources else None
            got_provider = (assessed["provider"] or {}).get("provider")
            if (assessed["snapshot"], assessed["trust"], got_provider) != (frozen.digest, Trust(C.loads(trust_bytes)).digest, want_provider):
                raise AgentError("NO_ASSESSMENT", "the assessed operands are not the captured ones")
            # The handle's lifetime starts when the view is ready and is at least view_ttl whole seconds.
            meta["expires"] = math.ceil(time.time()) + int(ws.limits["view_ttl"])
            body = {k: v for k, v in report.items() if k not in REPORT_OWN}
            meta["report"] = {"body": objs.put(O.doc_bytes(body)), **{k: report[k] for k in REPORT_OWN}}
            write_json(vdir / VIEW_FILE, {"manifest": objs.put(O.doc_bytes(meta))})
        except AgentError:
            shutil.rmtree(vdir, ignore_errors=True)
            raise
        for transient in ("meta.json", "report.json"):
            (vdir / transient).unlink()
    collect_due(ws)
    return meta


REPORT_OWN = ("assessment_id", "view")      # what a view's own report has that its body does not: the manifest carries it


def damaged(e, expires=None):
    """An object a view pins that cannot be read as itself: VIEW_EXPIRED when the view has expired by now
    (a collection may have taken it), else VIEW_DAMAGED. Nothing is read from elsewhere."""
    if expires is not None and time.time() >= expires:
        return AgentError("VIEW_EXPIRED", "the view expired; open a new context")
    return AgentError("VIEW_DAMAGED", f"{e}; this view answers nothing from elsewhere: open a new context",
                      object=e.name, why=e.why)


def _assess(vdir, deadline):
    paths = [str(Path(__file__).resolve().parents[1]), str(Path(P.__file__).resolve().parents[1])]
    code = ("import sys; sys.path[:0] = %r; from warrant_agent._assess_worker import main; main(%r)"
            % (paths, str(vdir.resolve())))
    try:
        p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, timeout=deadline, check=False)
    except subprocess.TimeoutExpired:
        raise AgentError("NO_ASSESSMENT", f"assessment exceeded the host deadline of {deadline}s") from None
    if (vdir / "refusal.json").is_file():
        r = read_json(vdir / "refusal.json")
        raise refusal(L.LimitExceeded(r["limit"], r["value"], r["bound"]))
    if (vdir / "damaged.json").is_file():
        r = read_json(vdir / "damaged.json")
        raise damaged(O.Unreadable(r["object"], r["why"]))
    if p.returncode != 0 or not (vdir / "report.json").is_file():
        raise AgentError("NO_ASSESSMENT", "the assessment worker produced no report",
                         stderr=p.stderr.decode(errors="replace")[-400:])


class View:
    """The bytes of one view: through its manifest's tree and the object store, or (a view written
    before manifests) from its own directory. `dir` keeps what the call that made it wrote (context.json)."""

    def __init__(self, ws, vdir, meta):
        self.ws, self.dir, self.meta = ws, vdir, meta
        self.legacy = "tree" not in meta
        self._tree = None

    def _doc(self, name):
        try:
            return objects_of(self.ws).get_doc(name)
        except O.Unreadable as e:
            raise damaged(e, self.meta["expires"]) from None

    def tree(self):
        if self._tree is None:
            self._tree = self._doc(self.meta["tree"])
        return self._tree

    def _get(self, name):
        try:
            return objects_of(self.ws).get(name)
        except O.Unreadable as e:
            raise damaged(e, self.meta["expires"]) from None

    def record(self, rid):
        """The bytes this view holds under record id `rid`, or None if it holds none."""
        if self.legacy:
            p = self.dir / "records" / f"{_addr(rid)}.json"
            return p.read_bytes() if p.is_file() else None
        name = self.tree()["records"].get(rid)
        return None if name is None else self._get(name)

    def blob(self, h):
        if self.legacy:
            p = self.dir / "blobs" / _addr(h)
            return p.read_bytes() if p.is_file() else None
        return self._get(h) if h in set(self.tree()["blobs"]) else None

    def snapshot(self):
        """The view's whole snapshot, under the workspace's admission limits."""
        if self.legacy:
            return read_snapshot(self.ws, self.dir)
        try:
            return objects_of(self.ws).snapshot(self.tree(), self.ws.assessment_limits())
        except L.LimitExceeded as e:
            raise refusal(e) from None
        except O.Unreadable as e:
            raise damaged(e, self.meta["expires"]) from None


def _legacy(vdir):
    """The meta of a view directory written before manifests (meta.json with no tree beside its report), or None."""
    if not ((vdir / "meta.json").is_file() and (vdir / "report.json").is_file()):
        return None
    meta = read_json(vdir / "meta.json")
    return meta if isinstance(meta, dict) and "tree" not in meta else None


def load(ws, token):
    need(isinstance(token, str) and TOKEN.match(token) is not None, "VIEW_UNKNOWN", "not a view token")
    vdir = ws.state / "views" / token
    unknown = AgentError("VIEW_UNKNOWN", "no such view in this workspace; open a new context")
    if (vdir / VIEW_FILE).is_file():
        name = read_json(vdir / VIEW_FILE).get("manifest")
        try:
            meta = objects_of(ws).get_doc(name)
        except O.Unreadable as e:
            raise damaged(e) from None
        if meta.get("view") != VIEW or meta.get("token") != token:
            raise unknown
        report = None
    else:
        meta = _legacy(vdir)
        if meta is None:
            raise unknown
        report = read_json(vdir / "report.json")
    if meta["workspace"] != ws.name:
        raise unknown
    if meta["expires"] is None or time.time() >= meta["expires"]:
        raise AgentError("VIEW_EXPIRED", "the view expired; open a new context")
    view = View(ws, vdir, meta)
    if report is None:
        own = meta["report"]
        report = dict(view._doc(own["body"]), **{k: own[k] for k in REPORT_OWN})
    return meta, report, view


# ---------------------------------------------------------------- collection

def _reach(ws, objs, vdir, now, trees):
    """(state, names): `live` with every object name the view pins, or why it is removed:
    `expired`, `unreadable` (its manifest, tree or report body cannot be read as itself) or
    `unfinished` (no view.json: a capture that is not in flight, since the caller holds the
    lock exclusively). A view written before manifests is `live` with no objects, or `expired`."""
    if not (vdir / VIEW_FILE).is_file():
        legacy = _legacy(vdir)
        if legacy is None:
            return "unfinished", set()
        return ("live" if legacy["expires"] is not None and now < legacy["expires"] else "expired"), set()
    try:
        name = read_json(vdir / VIEW_FILE).get("manifest")
        meta = objs.get_doc(name)
        if meta.get("token") != vdir.name or meta.get("workspace") != ws.name:
            return "unreadable", set()
        if meta["expires"] is None or now >= meta["expires"]:
            return "expired", set()
        if meta["tree"] not in trees:
            trees[meta["tree"]] = objs.get_doc(meta["tree"])
        objs.get(meta["report"]["body"])
    except (O.Unreadable, ValueError, KeyError, TypeError, AttributeError):
        return "unreadable", set()
    tree = trees[meta["tree"]]
    return "live", {name, meta["tree"], meta["report"]["body"], *(meta["provider"] or {}).values(),
                    *tree["records"].values(), *tree["blobs"]}


def _mark(ws, objs, now):
    """({state: count}, every object name a live view pins, the view directories to remove)."""
    views, marked, trees, gone = {}, set(), {}, []
    for vdir in sorted((ws.state / "views").iterdir()):
        if not (TOKEN.match(vdir.name) and vdir.is_dir() and not vdir.is_symlink()):
            continue                    # not a view: not this collection's to judge
        state, names = _reach(ws, objs, vdir, now, trees)
        views[state] = views.get(state, 0) + 1
        if state == "live":
            marked |= names
        else:
            gone.append(vdir)
    return views, marked, gone


def _sweep(objs, marked, dry_run):
    """(kept, removed, bytes removed): every object no live view pins, and writers' temporaries."""
    removed, freed, kept = 0, 0, 0
    for name, path in objs.names():
        if name is not None and name in marked:
            kept += 1
            continue
        if name is None and not path.name.startswith(O.TMP):
            continue                    # not an object or a writer's temporary: left as found
        removed += 1
        freed += path.lstat().st_size
        if not dry_run:
            path.unlink()
    return kept, removed, freed


def collect(ws, dry_run=False, wait=True):
    """Mark and sweep the workspace's views and objects under the exclusive lock: remove every view
    directory that is expired, unreadable or unfinished, then every object no live view pins.
    Nothing outside views/ and objects/ is read as a root or touched: drafts, staging, imports, exports
    and request status keep their own bytes, and the store is never touched. Returns what was (or,
    dry_run, would be) removed; None when wait=False and the lock is busy."""
    objs = objects_of(ws)
    with objs.lock(exclusive=True, wait=wait) as held:
        if not held:
            return None
        now = time.time()
        views, marked, gone = _mark(ws, objs, now)
        kept, removed, freed = _sweep(objs, marked, dry_run)
        if not dry_run:
            for vdir in gone:
                shutil.rmtree(vdir)
            write_json(objs.root / O.LAST, {"collected": int(now)})
        return {"workspace": ws.name, "dry_run": dry_run, "views": views, "views_removed": len(gone),
                "objects_kept": kept, "objects_removed": removed, "bytes_removed": freed}


def collect_due(ws):
    """A collection at the end of a capture when the last one is older than gc_interval (0: never), only if
    nobody holds the lock: it neither waits nor makes a context wait. A collection that fails here leaves
    the capture's view as it is (it removes only what no live view pins); `warrant-agent gc` reports it."""
    interval = ws.limits["gc_interval"]
    if not interval:
        return None
    try:
        last = read_json(objects_of(ws).root / O.LAST)["collected"]
    except (OSError, ValueError, KeyError, TypeError):
        last = 0
    try:
        return collect(ws, wait=False) if time.time() - last >= interval else None
    except OSError:
        return None


def expectation_now(ws, delivery):
    """The receiver's CURRENT definition of the expectation a delivery was inspected
    against: CURRENT, CHANGED or REMOVED (None when no expectation was used)."""
    handle = delivery.get("expectation")
    if handle is None:
        return None
    now = ws.expectation_digest(handle)
    state = "REMOVED" if now is None else "CURRENT" if now == delivery.get("expectation_definition") else "CHANGED"
    return {"handle": handle, "state": state, "definition": now}


def observation(ws, meta):
    """What is known locally now, apart from the frozen report."""
    return {"newer_known": live_digest(ws) != meta["live_snapshot"], "incomplete_imports": incomplete_imports(ws),
            "trust_current": base64.b64encode(ws.trust_bytes()).decode() == meta["trust"],
            "expectation": expectation_now(ws, meta["delivery"])}
