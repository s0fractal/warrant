#!/usr/bin/env python3
"""The resolution layer of the proof-space pilot (warrant/pilot.py; contract PILOT.md): G9 PS-02
typed addresses through two local object stores (A), PS-03 the dependency closure before verification
(D), PS-04 verification profiles as content-addressed manifests (F), PS-01 the contract (K).

    python3 tests/pilot_test.py

The objects are a real Sigma computation (the pinned provider, as compute_test uses it). Every case
is the target of a mutant in tests/mutants.py (K1 checks it), so CI's mutant baseline runs each one."""
import base64
import importlib.util
import json
import multiprocessing
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

from world import ROOT, P, World, check, finish, results
from warrant import jcs as C
from warrant import pilot as PL
from warrant_agent.objects import Objects

PROV = P.Provider.capture()
_impl = Path(os.environ["WARRANT_IMPL"]) / "tools" / "pilot.py" if os.environ.get("WARRANT_IMPL") else None
TOOL = _impl if _impl is not None and _impl.is_file() else ROOT / "tools" / "pilot.py"
_spec = importlib.util.spec_from_file_location("pilot_tool", TOOL)
PT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PT)

H = "ab" * 32


def outcome(res):
    """(result, code, at): what a resolution says, never its objects. Anything else, a RESOLVED one with a
    code, or another with objects, reads BROKEN."""
    if not isinstance(res, dict) or res.get("result") not in (PL.RESOLVED, PL.INCONCLUSIVE, PL.REFUSED):
        return ("BROKEN", None, None)
    if (res["result"] == PL.RESOLVED) == ("code" in res) or (res["result"] != PL.RESOLVED and "objects" in res):
        return ("BROKEN", res.get("code"), res.get("at"))
    return (res["result"], res.get("code"), res.get("at"))


class case:
    """One case: an exception inside it (a mutant can make the code under test raise) is that case's FAIL,
    never a crash of the file, so the mutant reads KILLED or OFF_TARGET by its cases."""

    def __init__(self, cid):
        self.cid = cid

    def __enter__(self):
        return self

    def __exit__(self, kind, err, tb):
        if kind is not None and issubclass(kind, Exception):
            check(self.cid, False, "raised", f"{kind.__name__}: {err}")
            return True
        return False


class Fixture:
    """A receipt of `S K K (K I)` run to its normal form, its environment, checkpoint, state and nodes, a
    profile of the installed provider and a root naming receipt, profile and environment: store A is
    the World's blobs/ (layout blobs), store B the same bytes in a warrant-agent object store (fanout)."""

    def __init__(self):
        self.w = World()
        out = PROV.call("term", {"expr": "S K K (K I)"})
        self.nodes = sorted({self.w.store.put_blob(base64.b64decode(b)) for b in out["nodes"].values()})
        self.inp = out["input"]
        self.env = self.w.blob(P.environment_doc(self.nodes))
        base = {"runtime": P.BOOK1, "input": self.inp, "hashes": self.nodes}
        snap = self.w.store.snapshot()
        blobs = {h: snap.blobs[h] for h in self.nodes}
        st = PROV.call("start", base, blobs)
        st = PROV.call("advance", dict(base, checkpoint=st["checkpoint"], state=st["state"], credit=100), blobs)
        self.ck = self.w.store.put_blob(base64.b64decode(st["checkpoint"]))
        self.st = self.w.store.put_blob(base64.b64decode(st["state"]))
        self.receipt_doc = {"receipt": "sigma-resume", "target": "warrant-test", "input": self.inp,
                            "environment": self.env, "checkpoint": self.ck, "state": self.st,
                            "claimed": st["result"], "lost": []}
        self.rc = self.w.blob(self.receipt_doc)
        self.profile_doc = PL.profile(PROV, P.BOOK1)
        self.prof = self.w.blob(self.profile_doc)
        self.root = self.put_root([f"sigma-receipt:{self.rc}", f"pilot-profile:{self.prof}",
                                   f"sigma-environment:{self.env}"])
        self.a = self.w.store.root / "blobs"
        self.b = self.w.dir / "objects"
        self.sync()

    def put_root(self, requires):
        return self.w.blob({"schema": PL.ROOT_SCHEMA, "requires": requires})

    def sync(self):
        """Store B holds every blob of store A."""
        objs = Objects(self.b)
        for f in sorted(self.a.iterdir()):
            objs.put(f.read_bytes())

    def fan(self, h):
        return self.b / h[:2] / h[2:]

    def receiver(self, *stores, **kw):
        return PL.Receiver([PL.BlobDir(self.a) if s == "A" else PL.FanoutDir(self.b) for s in (stores or "A")], **kw)

    @property
    def addr(self):
        return f"pilot-root:{self.root}"

    def all(self):
        return sorted([self.addr, f"sigma-receipt:{self.rc}", f"pilot-profile:{self.prof}",
                       f"sigma-environment:{self.env}", f"sigma-checkpoint:{self.ck}", f"sigma-state:{self.st}"]
                      + [f"sigma-node:{n}" for n in self.nodes])


class Counting:
    """A store that counts its reads per name."""

    def __init__(self, store):
        self.store, self.layout, self.reads = store, store.layout, {}

    def read(self, name, admit):
        self.reads[name] = self.reads.get(name, 0) + 1
        return self.store.read(name, admit)


def spy(receiver):
    """Wrap each admitted kind's tag and deps: `seen` lists (kind, step, bytes or value) in call order."""
    seen = []

    def wrap(kind, k):
        def tag(data):
            seen.append((kind, "tag", data))
            return k.tag(data)

        def deps(value):
            seen.append((kind, "deps", value))
            return k.deps(value)
        return PL.Kind(tag, deps, k.tag_doc, k.deps_doc)
    receiver.kinds = {kind: wrap(kind, k) for kind, k in receiver.kinds.items()}
    return seen


def standin(graph, leaves=()):
    """A fetch over invented objects: `graph` {name: [names it requires]} as pilot-root objects under the
    names themselves (no digest: SHA-256 addresses cannot form a cycle, so the walker's guard is shown on
    a stand-in, as roadmap_test P19 does), `leaves` as sigma-state bytes."""
    def addr(n):
        return f"pilot-root:{n}" if n in graph else f"sigma-state:{n}"

    def fetch(kind, h, address, admit):
        if h in graph:
            data = C.canon({"schema": PL.ROOT_SCHEMA, "requires": [addr(x) for x in graph[h]]})
        elif h in leaves:
            data = PL.STATE_MAGIC + bytes(40)
        else:
            raise PL._Stop("MISSING", address, "not in the stand-in")
        admit(len(data))
        return data
    return fetch, addr


def _fifo_worker(root, layout, name, conn):
    conn.send(PL.Receiver([PL.LAYOUTS[layout](root)]).resolve("sigma-state:" + name))
    conn.close()


def fifo_resolves(layout, wait=5):
    """outcome() of resolving a FIFO named like an object, in a child process; ("BLOCKED",) when the child has
    not answered after `wait` seconds (it is then stopped)."""
    root, name = Path(tempfile.mkdtemp(prefix="warrant-pilot-fifo-")), "a" * 64
    target = root / name if layout == "blobs" else root / name[:2] / name[2:]
    target.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(target)
    ctx = multiprocessing.get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_fifo_worker, args=(root, layout, name, child))
    proc.start()
    child.close()
    try:
        return outcome(parent.recv()) if parent.poll(wait) else ("BLOCKED",)
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(5)
        parent.close()


def damaged():
    """A fixture whose store A holds the receipt with one bit changed (store B keeps the good bytes), and those bytes."""
    g = Fixture()
    bad = bytearray((g.a / g.rc).read_bytes())
    bad[len(bad) // 2] ^= 0x01
    os.chmod(g.a / g.rc, 0o644)
    (g.a / g.rc).write_bytes(bytes(bad))
    return g, bytes(bad)


def edit_of(doc):
    """changed(**{"a__b": v}): a copy of profile `doc` with doc[a][b] = v; a changed module digest recomputes the provider."""
    def changed(**edit):
        d = json.loads(json.dumps(doc))
        for path, value in edit.items():
            node = d
            *head, last = path.split("__")
            for k in head:
                node = node[k]
            node[last] = value
        if "verifier__modules" in edit:
            d["verifier"]["provider"] = P.identity_of_files(d["verifier"]["modules"])
        return d
    return changed


def contract_inputs():
    """The contract source, PILOT.md, the mutant harness and the filed G9 cards, from this checkout."""
    return (json.loads((ROOT / PT.SOURCE).read_text()), (ROOT / PT.VIEW).read_text(), PT.mutant_list(ROOT),
            PT.filed_cards(ROOT))


def main():
    f = Fixture()

    # ---------------------------------------------------------------- PS-02: typed addresses, two stores
    # A1: one typed address resolves through store A (blobs/), store B (a warrant-agent object store),
    # both in either order, and stores that each hold only part of the closure: the same bytes for every
    # object and the same closure id. The manifest names no store.
    with case('A1'):
        runs = {s: f.receiver(*s).resolve(f.addr) for s in ("A", "B", "AB", "BA")}
        split = Fixture()
        names = sorted(p.name for p in split.a.iterdir())
        for n in names[::2]:
            split.fan(n).unlink()                   # even names only in A, odd names only in B
        for n in names[1::2]:
            (split.a / n).unlink()
        mixed = split.receiver("A", "B").resolve(split.addr)
        got1 = ({s: outcome(r) for s, r in runs.items()}, len({r.get("closure") for r in runs.values()}),
                all(r.get("objects") == runs["A"].get("objects") for r in runs.values()),
                all(C.digest(b) == a.split(":")[1] for a, b in runs["A"].get("objects", {}).items()),
                sorted(runs["A"].get("objects", ())) == f.all() == runs["A"].get("manifest", {}).get("objects"),
                outcome(mixed), mixed.get("closure") == runs["A"].get("closure"),
                outcome(split.receiver("A").resolve(split.addr))[:2], outcome(split.receiver("B").resolve(split.addr))[:2])
        check("A1", got1 == ({s: ("RESOLVED", None, None) for s in runs}, 1, True, True, True, ("RESOLVED", None, None),
                             True, ("INCONCLUSIVE", "MISSING"), ("INCONCLUSIVE", "MISSING")),
              "one typed address resolves to the same bytes and closure id through either store, both, either order",
              got1)

    # A2: one bit of the receipt changed in store A: DIGEST_MISMATCH naming store 0, refused before any
    # kind looks at the bytes, and store B is not consulted past the damage; with B first, B's bytes resolve.
    with case('A2'):
        g, bad = damaged()
        rx = g.receiver("A", "B")
        seen = spy(rx)
        refused = rx.resolve(g.addr)
        got2 = (outcome(refused), refused.get("store"), [s for s in seen if s[2] == bad],
                outcome(g.receiver("B", "A").resolve(g.addr)))
        check("A2", got2 == (("REFUSED", "DIGEST_MISMATCH", f"sigma-receipt:{g.rc}"), 0, [], ("RESOLVED", None, None)),
              "bytes that do not hash to their address are refused before interpretation, naming the store, "
              "with no fallback past them", got2)

    # A3: the address's kind is checked on the bytes before the kind's dependency fields are read: a
    # receipt named as an environment, a receipt whose `environment` is its checkpoint, a receipt in
    # non-canonical JSON (not normalized). The environment's deps never ran on the receipt.
    with case('A3'):
        rx = f.receiver()
        seen = spy(rx)
        as_env = rx.resolve(f"sigma-environment:{f.rc}")
        swapped = f.w.blob(dict(f.receipt_doc, environment=f.ck))
        pretty = f.w.store.put_blob(json.dumps(f.receipt_doc, indent=1).encode())
        got3 = (outcome(as_env), [s[:2] for s in seen], outcome(f.receiver().resolve(f"sigma-receipt:{swapped}")),
                outcome(f.receiver().resolve(f"sigma-receipt:{pretty}")))
        check("A3", got3 == (("REFUSED", "KIND_MISMATCH", f"sigma-environment:{f.rc}"), [("sigma-environment", "tag")],
                             ("REFUSED", "KIND_MISMATCH", f"sigma-environment:{f.ck}"),
                             ("REFUSED", "KIND_MISMATCH", f"sigma-receipt:{pretty}")),
              "an object of another kind than its address says is refused before its dependency fields are read", got3)

    # A4: anything but <kind>:<64 lowercase hex> is BAD_ADDRESS before a store is read: path traversal at
    # the right length, uppercase, 63 digits, a trailing newline or CRLF, non-ASCII digits, no kind, no string.
    with case('A4'):
        counting = Counting(PL.BlobDir(f.a))
        rx = PL.Receiver([counting])
        bad_addrs = {"traversal": "sigma-receipt:" + ("../" * 21 + "x"), "uppercase": "sigma-receipt:" + f.rc.upper(),
                     "63": "sigma-receipt:" + f.rc[:63], "\\n": f"sigma-receipt:{f.rc}\n",
                     "\\r\\n": f"sigma-receipt:{f.rc}\r\n", "arabic-indic": "sigma-receipt:" + "١" * 64,
                     "no kind": f.rc, "not a string": 7}
        got4 = ({k: outcome(rx.resolve(v))[:2] for k, v in bad_addrs.items()}, counting.reads)
        check("A4", got4 == ({k: ("REFUSED", "BAD_ADDRESS") for k in bad_addrs}, {}),
              "a malformed address (path traversal, case, length, newline) is refused before any store is read", got4)

    # A5: a record id is not an object address (records/ is never read), and a record envelope named by
    # its digest in an object store is not a receipt.
    with case('A5'):
        did = f.w.duty()
        env_bytes = f.w.store.snapshot().records[did]
        env_name = Objects(f.b).put(env_bytes)
        got5 = (outcome(f.receiver("A", "B").resolve(f"sigma-receipt:{did}")),
                outcome(f.receiver("B").resolve(f"sigma-receipt:{env_name}")))
        check("A5", got5 == (("INCONCLUSIVE", "MISSING", f"sigma-receipt:{did}"),
                             ("REFUSED", "KIND_MISMATCH", f"sigma-receipt:{env_name}")),
              "a record id resolves to nothing, and an envelope's digest names no receipt", got5)

    # A6: a store reads only regular files inside its real directory: a symlink to the right bytes, a
    # fan-out directory that is a symlink, a directory under the name: none is an object of that store.
    with case('A6'):
        s = Fixture()
        outside = Path(tempfile.mkdtemp(prefix="warrant-pilot-outside-"))
        (outside / s.ck).write_bytes((s.a / s.ck).read_bytes())
        (s.a / s.ck).unlink()
        (s.a / s.ck).symlink_to(outside / s.ck)
        link = s.receiver("A").resolve(s.addr)
        fan = s.fan(s.st).parent
        moved = outside / "fan"
        shutil.move(str(fan), str(moved))
        fan.symlink_to(moved)
        via_dir = s.receiver("B").resolve(f"sigma-state:{s.st}")
        (s.a / s.st).unlink()
        (s.a / s.st).mkdir()
        a_dir = s.receiver("A").resolve(f"sigma-state:{s.st}")
        got6 = (outcome(link), outcome(via_dir), outcome(a_dir))
        check("A6", got6 == (("INCONCLUSIVE", "MISSING", f"sigma-checkpoint:{s.ck}"),
                             ("INCONCLUSIVE", "MISSING", f"sigma-state:{s.st}"),
                             ("INCONCLUSIVE", "MISSING", f"sigma-state:{s.st}")),
              "a store reads nothing through a symlink or outside its directory, and a directory is no object", got6)

    # A7: a kind outside the receiver's admitted kinds is UNKNOWN_KIND (inconclusive), at the root and as a
    # dependency, also a kind the code knows: admission is the receiver's configuration.
    with case('A7'):
        no_prof = f.receiver(kinds=[k for k in PL.KINDS if k != "pilot-profile"])
        got7 = (outcome(f.receiver().resolve(f"sigma-proof:{f.rc}")), outcome(no_prof.resolve(f.addr)))
        check("A7", got7 == (("INCONCLUSIVE", "UNKNOWN_KIND", f"sigma-proof:{f.rc}"),
                             ("INCONCLUSIVE", "UNKNOWN_KIND", f"pilot-profile:{f.prof}")),
              "a kind the receiver does not admit is inconclusive, wherever it is named", got7)

    # A8: the receiver's configuration alone names stores, kinds and limits (from_config refuses anything
    # else), and no object can add one: a root with a `stores` member is MALFORMED.
    with case('A8'):
        cfg = {"receiver": PL.RECEIVER, "stores": [{"layout": "fanout", "path": "objects"},
                                                   {"layout": "blobs", "path": "store/blobs"}],
               "kinds": sorted(PL.KINDS), "limits": {"pilot_depth": 3}}
        rx = PL.Receiver.from_config(cfg, base=f.w.dir)
        refused = []
        for name, bad_cfg in {"member": dict(cfg, network="https://example.org"),
                              "layout": dict(cfg, stores=[{"layout": "http", "path": "x"}]),
                              "kind": dict(cfg, kinds=["sigma-proof"]), "limit": dict(cfg, limits={"snapshot_bytes": 9}),
                              "no store": dict(cfg, stores=[])}.items():
            try:
                PL.Receiver.from_config(bad_cfg, base=f.w.dir)
            except ValueError:
                refused.append(name)
        smuggle = f.w.blob({"schema": PL.ROOT_SCHEMA, "requires": [f"sigma-receipt:{f.rc}"],
                            "stores": [{"layout": "blobs", "path": "/"}]})
        got8 = ([type(x).__name__ for x in rx.stores], outcome(rx.resolve(f.addr)), rx.limits["pilot_depth"], refused,
                outcome(f.receiver().resolve(f"pilot-root:{smuggle}")))
        check("A8", got8 == (["FanoutDir", "BlobDir"], ("RESOLVED", None, None), 3,
                             ["member", "layout", "kind", "limit", "no store"],
                             ("REFUSED", "MALFORMED", f"pilot-root:{smuggle}")),
              "stores, kinds and limits come from the receiver's configuration only; an object cannot add a store", got8)

    # A9 (Codex finding 19556ffa5a1c on #193, observed at 228ed32: the open blocked on a FIFO before the
    # type check; expected MISSING): a FIFO under an object name, in either layout, is no object of that
    # store, and the resolver returns at once. The resolver runs in a child that the case stops after.
    with case('A9'):
        got_a9 = [fifo_resolves(layout) for layout in ("blobs", "fanout")]
        check("A9", got_a9 == [("INCONCLUSIVE", "MISSING", "sigma-state:" + "a" * 64)] * 2,
              "a FIFO under an object name is no object, and nothing waits on it", got_a9)

    # A10 (Codex finding d8a510cd300e on #193, observed at 228ed32: a fan-out directory replaced by a symlink
    # between the check and the open was read through; expected MISSING, no verifier call): the
    # replacement happens at the first open of the read, and the bytes exist only outside the store.
    with case('A10'):
        root = Path(tempfile.mkdtemp(prefix="warrant-pilot-swap-"))
        store, outside = root / "store", root / "outside"
        outside.mkdir()
        data = PL.STATE_MAGIC + b" bytes present only outside the configured store"
        name = C.digest(data)
        (outside / name[2:]).write_bytes(data)
        (store / name[:2]).mkdir(parents=True)
        real_open, swapped, calls = os.open, [], []

        def swap(path, *args, **kw):
            if not swapped:
                (store / name[:2]).rename(store / "was")
                (store / name[:2]).symlink_to(outside, target_is_directory=True)
                swapped.append(path)
            return real_open(path, *args, **kw)
        with mock.patch.object(PL.os, "open", side_effect=swap):
            res = PL.Receiver([PL.FanoutDir(store)]).check("sigma-state:" + name,
                                                           lambda r: calls.append(r) or {"verified": "stand-in"})
        got_a10 = (len(swapped), outcome(res), calls)
        check("A10", got_a10 == (1, ("INCONCLUSIVE", "MISSING", "sigma-state:" + name), []),
              "a directory swapped for a symlink between check and use is never read through", got_a10)

    # A11 (Codex finding b60e976acb54 on #193, observed at eca04cc: a digest-correct root holding a 5000-digit
    # integer made the parser raise a ValueError the tag did not catch, and the resolver raised; expected a
    # typed KIND_MISMATCH): bytes outside the canonical JSON domain are refused, whatever the parser raises.
    with case('A11'):
        root = Path(tempfile.mkdtemp(prefix="warrant-pilot-json-"))
        huge = b'{"requires":["sigma-state:' + b"a" * 64 + b'"],"schema":"warrant-pilot/root@1","x":' + b"1" * 5000 + b"}"
        (root / C.digest(huge)).write_bytes(huge)
        calls = []
        try:
            res = PL.Receiver([PL.BlobDir(root)]).check("pilot-root:" + C.digest(huge),
                                                        lambda r: calls.append(r) or {"verified": "stand-in"})
        except Exception as e:      # noqa: BLE001  (the defect: the resolver raised instead of answering)
            res = {"raised": f"{type(e).__name__}: {str(e)[:60]}"}
        got_a11 = (outcome(res), res.get("raised"), calls)
        check("A11", got_a11 == (("REFUSED", "KIND_MISMATCH", "pilot-root:" + C.digest(huge)), None, []),
              "an object the JSON parser rejects in any way is a typed refusal, never an exception", got_a11)

    # A12 (Codex finding b3887f01538c on #193, observed at 11e11c6: `limits` false, 0, "" or [] gave the
    # default budgets and resolved; true, 1, a string or a list, and a store layout that is a list or an
    # object, raised AttributeError or TypeError; expected ValueError): a malformed configuration is refused.
    with case('A12'):
        base = {"receiver": PL.RECEIVER, "stores": [{"layout": "blobs", "path": str(f.a)}]}
        controls = (outcome(PL.Receiver.from_config(base).resolve(f"sigma-state:{f.st}"))[0],
                    outcome(PL.Receiver.from_config(dict(base, limits={"pilot_bytes": 4})).resolve(f"sigma-state:{f.st}"))[:2])
        bad_cfgs = {f"limits {v!r}": dict(base, limits=v) for v in (False, 0, "", [], True, 1, "invalid", [1])}
        bad_cfgs.update({f"layout {v!r}": dict(base, stores=[{"layout": v, "path": str(f.a)}]) for v in ([], {})})
        got_a12 = {}
        for label, cfg in bad_cfgs.items():
            try:
                PL.Receiver.from_config(cfg)
                got_a12[label] = "accepted"
            except ValueError:
                got_a12[label] = "refused"
            except Exception as e:      # noqa: BLE001  (the defect: an unhandled error, not a refusal)
                got_a12[label] = f"raised {type(e).__name__}"
        check("A12", (controls, got_a12) == (("RESOLVED", ("INCONCLUSIVE", "LIMIT")), {k: "refused" for k in bad_cfgs}),
              "a receiver configuration with limits that are not a mapping or a layout that is not a name is refused",
              (controls, got_a12))

    # ---------------------------------------------------------------- PS-03: the closure before verification
    # D1: branching and shared dependencies: the environment (named by the root and the receipt) and the
    # input node (named by the receipt and the environment) are read once; every object of the closure is
    # read once, the walk is deterministic, and every reference counts, repeats included.
    with case('D1'):
        counting = Counting(PL.BlobDir(f.a))
        rx = PL.Receiver([counting])
        one, two = rx.resolve(f.addr), rx.resolve(f.addr)
        edges = 3 + 4 + len(f.nodes)
        got_d1 = (outcome(one), sorted(one.get("objects", ())) == f.all(), set(counting.reads.values()), one == two,
                  len(f.all()) - 1 < edges, outcome(f.receiver(limits={"pilot_edges": edges}).resolve(f.addr)))
        check("D1", got_d1 == (("RESOLVED", None, None), True, {2}, True, True, ("RESOLVED", None, None)),
              "a branching closure with shared dependencies is gathered whole, each object read once", got_d1)

    # D2: a missing leaf, checkpoint or state: INCONCLUSIVE MISSING at that address, and no object returned.
    with case('D2'):
        got_d2 = []
        for h, kind in ((f.nodes[-1], "sigma-node"), (f.ck, "sigma-checkpoint"), (f.st, "sigma-state")):
            m = Fixture.__new__(Fixture)
            m.__dict__.update(f.__dict__)
            m.a = Path(tempfile.mkdtemp(prefix="warrant-pilot-missing-"))
            for p in f.a.iterdir():
                if p.name != h:
                    (m.a / p.name).write_bytes(p.read_bytes())
            got_d2.append(outcome(m.receiver("A").resolve(m.addr)) == ("INCONCLUSIVE", "MISSING", f"{kind}:{h}"))
        check("D2", got_d2 == [True, True, True], "a missing required object is named, inconclusive", got_d2)

    # D3: the verifier runs only on a RESOLVED closure, once, with every object; on a missing, mistyped,
    # damaged, unknown-kind, over-limit or malformed closure it never runs and the resolution is the answer.
    with case('D3'):
        calls = []

        def verify(res):
            calls.append(sorted(res.get("objects", ())))
            return {"verified": "stand-in"}
        ok = f.receiver().check(f.addr, verify)
        gone = Fixture()
        (gone.a / gone.nodes[0]).unlink()
        broken = f.w.blob(dict(f.receipt_doc, lost="x"))
        g = damaged()[0]
        not_ok = [gone.receiver("A").check(gone.addr, verify), f.receiver().check(f"sigma-environment:{f.rc}", verify),
                  g.receiver("A").check(g.addr, verify), f.receiver().check(f"sigma-proof:{f.rc}", verify),
                  f.receiver(limits={"pilot_objects": 3}).check(f.addr, verify),
                  f.receiver().check(f"sigma-receipt:{broken}", verify)]
        got_d3 = (ok, calls, [outcome(r)[:2] for r in not_ok])
        check("D3", got_d3 == ({"verified": "stand-in"}, [f.all()],
                               [("INCONCLUSIVE", "MISSING"), ("REFUSED", "KIND_MISMATCH"), ("REFUSED", "DIGEST_MISMATCH"),
                                ("INCONCLUSIVE", "UNKNOWN_KIND"), ("INCONCLUSIVE", "LIMIT"), ("REFUSED", "MALFORMED")]),
              "verification starts only after the whole closure is resolved, and never on a partial one", got_d3)

    # D4: an unknown dependency kind inside a root, and a malformed address there.
    with case('D4'):
        r_unknown = f.put_root([f"sigma-receipt:{f.rc}", f"sigma-proof:{f.rc}"])
        traversal = "sigma-node:" + "../" * 21 + "x"
        r_bad = f.put_root([f"sigma-receipt:{f.rc}", traversal])
        got_d4 = (outcome(f.receiver().resolve(f"pilot-root:{r_unknown}")),
                  outcome(f.receiver().resolve(f"pilot-root:{r_bad}")))
        check("D4", got_d4 == (("INCONCLUSIVE", "UNKNOWN_KIND", f"sigma-proof:{f.rc}"),
                               ("REFUSED", "BAD_ADDRESS", traversal)),
              "an unknown dependency kind is inconclusive, a malformed dependency address refused", got_d4)

    # D5 (stand-in fetch): a two-object cycle and a self-reference are CYCLE; a diamond is not one.
    with case('D5'):
        kinds, lim = PL.KINDS, PL.L.resolve(None, PL.LIMITS)
        fetch, addr = standin({"a" * 64: ["b" * 64], "b" * 64: ["a" * 64]})
        two_cycle = PL.walk(fetch, addr("a" * 64), kinds, lim)
        fetch, addr = standin({"c" * 64: ["c" * 64]})
        self_cycle = PL.walk(fetch, addr("c" * 64), kinds, lim)
        fetch, addr = standin({"1" * 64: ["2" * 64, "3" * 64], "2" * 64: ["4" * 64], "3" * 64: ["4" * 64]}, ["4" * 64])
        diamond = PL.walk(fetch, addr("1" * 64), kinds, lim)
        got_d5 = (outcome(two_cycle), outcome(self_cycle), outcome(diamond), len(diamond.get("objects", ())))
        check("D5", got_d5 == (("REFUSED", "CYCLE", "pilot-root:" + "a" * 64), ("REFUSED", "CYCLE", "pilot-root:" + "c" * 64),
                               ("RESOLVED", None, None), 4),
              "a cycle is refused (shown on a stand-in: SHA-256 addresses cannot form one); a diamond resolves", got_d5)

    # D6: each limit at the closure's own size resolves, one below is LIMIT {limit, value, bound} with no
    # object: distinct objects, their bytes, references followed (repeats included), the longest chain.
    with case('D6'):
        edges = 3 + 4 + len(f.nodes)
        size = sum(len(b) for b in f.receiver().resolve(f.addr).get("objects", {}).values())
        need = {"pilot_objects": len(f.all()), "pilot_bytes": size, "pilot_edges": edges, "pilot_depth": 3}
        got_d6 = {}
        for name, n in need.items():
            at = f.receiver(limits={name: n}).resolve(f.addr)
            under = f.receiver(limits={name: n - 1}).resolve(f.addr)
            got_d6[name] = (outcome(at)[0], outcome(under)[:2], under.get("limit"), under.get("bound"),
                            under.get("value", 0) > n - 1)
        check("D6", got_d6 == {k: ("RESOLVED", ("INCONCLUSIVE", "LIMIT"), k, n - 1, True) for k, n in need.items()},
              "each receiver limit holds at its bound and gives an explicit LIMIT one below", got_d6)

    # D7 (stand-in): the depth is the longest chain whatever the order of the walk: the short path to x is
    # walked first, the long one (root -> b -> c -> x) after it, through x already resolved.
    with case('D7'):
        fetch, addr = standin({"0" * 64: ["a" * 64, "b" * 64], "a" * 64: ["9" * 64], "b" * 64: ["c" * 64],
                               "c" * 64: ["9" * 64]}, ["9" * 64])
        deep = [PL.walk(fetch, addr("0" * 64), kinds, dict(lim, pilot_depth=d)) for d in (2, 3)]
        got_d7 = (outcome(deep[0])[:2], deep[0].get("value"), outcome(deep[1])[:2])
        check("D7", got_d7 == (("INCONCLUSIVE", "LIMIT"), 3, ("RESOLVED", None)),
              "pilot_depth bounds the longest chain from the root, also through a shared object", got_d7)

    # D8: dependency fields are read with the kind's exact shape: a receipt with another member, an
    # environment out of order, a root naming an address twice or nothing.
    with case('D8'):
        extra = f.w.blob(dict(f.receipt_doc, proof=f.ck))
        unsorted = f.w.blob({"schema": P.ENV_SCHEMA, "hashes": f.nodes[::-1]})
        twice = f.put_root([f"sigma-receipt:{f.rc}", f"sigma-receipt:{f.rc}"])
        empty = f.put_root([])
        got_d8 = [outcome(f.receiver().resolve(a))[:2] for a in (f"sigma-receipt:{extra}", f"sigma-environment:{unsorted}",
                                                                 f"pilot-root:{twice}", f"pilot-root:{empty}")]
        check("D8", got_d8 == [("REFUSED", "MALFORMED")] * 4,
              "an object whose dependency fields are not exactly its kind's shape is refused", got_d8)

    # D9: bytes are admitted before an object is read (an object over the bound is not read at all) and
    # again as read (Codex finding 971ca0938c3a on #193, observed at 228ed32: a file grown from 4 to 5 bytes
    # after fstat resolved under pilot_bytes 4 and reached the verifier; expected LIMIT, no verifier call).
    with case('D9'):
        root = Path(tempfile.mkdtemp(prefix="warrant-pilot-bytes-"))
        big = PL.STATE_MAGIC + bytes(6)
        (root / C.digest(big)).write_bytes(big)
        real_fdopen, opened = os.fdopen, []

        def fdopen(*args, **kw):
            opened.append(args[0])
            return real_fdopen(*args, **kw)
        with mock.patch.object(PL.os, "fdopen", side_effect=fdopen):
            over = PL.Receiver([PL.BlobDir(root)], limits={"pilot_bytes": 4}).resolve("sigma-state:" + C.digest(big))
        after = PL.STATE_MAGIC + b"x"
        target = root / C.digest(after)
        target.write_bytes(PL.STATE_MAGIC)
        real_fstat, grown, calls = os.fstat, [], []

        def grow(fd):
            info = real_fstat(fd)
            if not grown:
                with target.open("ab") as out:
                    out.write(b"x")
                grown.append(fd)
            return info
        with mock.patch.object(PL.os, "fstat", side_effect=grow):
            res = PL.Receiver([PL.BlobDir(root)], limits={"pilot_bytes": 4}).check(
                "sigma-state:" + C.digest(after), lambda r: calls.append(r) or {"verified": "stand-in"})
        got_d9 = (outcome(over)[:2], over.get("value"), opened, len(grown), outcome(res)[:2], res.get("value"), calls)
        check("D9", got_d9 == (("INCONCLUSIVE", "LIMIT"), 10, [], 1, ("INCONCLUSIVE", "LIMIT"), 5, []),
              "bytes are admitted before an object is read and again on the bytes read", got_d9)

    # D10 (Codex finding d564e974a47d on #193, observed at eca04cc: after fstat saw 4 bytes the file was
    # rewritten to 16, the store read 5, and that prefix hashed to the address and reached the verifier;
    # expected DIGEST_MISMATCH, no verifier call): a grown file is read to its end, in both layouts.
    with case('D10'):
        got_d10 = {}
        for layout, cls in PL.LAYOUTS.items():
            root = Path(tempfile.mkdtemp(prefix="warrant-pilot-grow-"))
            store, prefix = cls(root), PL.STATE_MAGIC + b"X"
            path = root.joinpath(*store.parts(C.digest(prefix)))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(PL.STATE_MAGIC)
            real_fstat, grown, calls = os.fstat, [], []

            def regrow(fd, path=path, grown=grown, prefix=prefix):
                info = real_fstat(fd)
                if not grown:
                    path.write_bytes(prefix + b"UNREAD-TAIL")
                    grown.append(fd)
                return info
            with mock.patch.object(PL.os, "fstat", side_effect=regrow):
                res = PL.Receiver([store]).check("sigma-state:" + C.digest(prefix),
                                                 lambda r, calls=calls: calls.append(r) or {"verified": "stand-in"})
            got_d10[layout] = (len(grown), outcome(res)[:2], calls)
        check("D10", got_d10 == {k: (1, ("REFUSED", "DIGEST_MISMATCH"), []) for k in PL.LAYOUTS},
              "a file grown past its size is read whole, so no prefix of it passes for the object", got_d10)

    # ---------------------------------------------------------------- PS-04: verification profiles
    # F1: the profile of the installed provider pins its modules and boot by digest, its id is the SHA-256
    # of its canonical bytes and the address it resolves under, recomputed by the receiver from the bytes.
    with case('F1'):
        res = f.receiver().resolve(f"pilot-profile:{f.prof}")
        got_f1 = (PL.profile_problem(f.profile_doc), f.profile_doc["verifier"]["provider"] == PROV.id,
                  f.profile_doc["verifier"]["modules"] == {f"{n}.py": C.digest(PROV.sources[n]) for n in P.MODULES},
                  PL.profile_id(f.profile_doc) == f.prof, outcome(res),
                  C.doc_id(C.loads(res.get("objects", {}).get(f"pilot-profile:{f.prof}", b"{}"))) == f.prof,
                  set(PL.ASSUMPTIONS) <= set(f.profile_doc["assumptions"]))
        check("F1", got_f1 == (None, True, True, True, ("RESOLVED", None, None), True, True),
              "a profile is a content-addressed manifest whose id the receiver recomputes from its bytes", got_f1)

    # F2: each declared semantic operand changed alone gives a valid profile with its own id, and the
    # old profile stays addressable beside the new ones.
    with case('F2'):
        changed = edit_of(f.profile_doc)
        mods = dict(f.profile_doc["verifier"]["modules"], **{"sigma_glyph.py": "0" * 64})
        variants = {"entry": changed(verifier__entry="sigma_provider.other"), "boot": changed(verifier__boot="1" * 64),
                    "protocol": changed(verifier__protocol=2), "module": changed(verifier__modules=mods),
                    "rule": changed(rule="warrant-pilot/sigma-replay@2"), "runtime": changed(runtime=P.RICH),
                    "axiom added": changed(axioms=sorted(PL.AXIOMS + ("Book I is confluent",))),
                    "axiom changed": changed(axioms=sorted(["SHA-256 is a random oracle", PL.AXIOMS[1]])),
                    "assumption removed": changed(assumptions=[PL.ASSUMPTIONS[0]])}
        ids = {k: PL.profile_id(v) for k, v in variants.items()}
        stored = {k: f.w.blob(v) for k, v in variants.items()}
        f.sync()
        resolved = [outcome(f.receiver("B").resolve(f"pilot-profile:{h}"))[0] for h in [f.prof, *stored.values()]]
        got_f2 = ({k: PL.profile_problem(v) for k, v in variants.items()}, len(set(ids.values()) | {f.prof}),
                  ids == stored, set(resolved))
        check("F2", got_f2 == ({k: None for k in variants}, len(variants) + 1, True, {"RESOLVED"}),
              "changing any declared semantic operand changes the profile id; the old one stays addressable", got_f2)

    # F3: what a profile may not be: a member missing or added (an unpinned URL), a pin that is a path, a URL,
    # a ref or uppercase, a provider other than its modules give, a boolean protocol, axioms out of order,
    # an assumption twice, no axioms. Through resolution each is MALFORMED.
    with case('F3'):
        changed = edit_of(f.profile_doc)
        mods = dict(f.profile_doc["verifier"]["modules"], **{"sigma_glyph.py": "0" * 64})
        d0 = f.profile_doc
        bad_profiles = {f"no {k}": {m: v for m, v in d0.items() if m != k} for k in sorted(PL.PROFILE_FIELDS - {"schema"})}
        bad_profiles.update({
            "source url": dict(d0, source="https://example.org/sigma_provider.py"),
            "module path": changed(verifier__modules=dict(mods, **{"sigma_glyph.py": "../sigma_glyph.py"})),
            "module url": changed(verifier__modules=dict(mods, **{"sigma_glyph.py": "https://pypi.org/sigma-glyph"})),
            "module ref": changed(verifier__modules=dict(mods, **{"sigma_glyph.py": "refs/heads/master"})),
            "module uppercase": changed(verifier__modules=dict(mods, **{"sigma_glyph.py": "A" * 64})),
            "provider": changed(verifier__provider="0" * 64), "protocol bool": changed(verifier__protocol=True),
            "verifier member": changed(verifier__version="latest"),
            "axioms order": changed(axioms=sorted(PL.AXIOMS, reverse=True)),
            "assumption twice": changed(assumptions=[PL.ASSUMPTIONS[0]] * 2), "no axioms": changed(axioms=[])})
        via = {k: outcome(f.receiver().resolve(f"pilot-profile:{f.w.blob(v)}"))[:2] for k, v in bad_profiles.items()}
        got_f3 = ({k: PL.profile_problem(v) is not None for k, v in bad_profiles.items()}, set(via.values()))
        check("F3", got_f3 == ({k: True for k in bad_profiles}, {("REFUSED", "MALFORMED")}),
              "a profile missing an operand, with an unpinned or mismatched pin, or not in its one order is refused",
              got_f3)

    # F4: one profile has one encoding: its bytes indented are no pilot-profile (refused, not normalized).
    with case('F4'):
        loose = f.w.store.put_blob(json.dumps(f.profile_doc, indent=2).encode())
        got_f4 = outcome(f.receiver().resolve(f"pilot-profile:{loose}"))
        check("F4", got_f4 == ("REFUSED", "KIND_MISMATCH", f"pilot-profile:{loose}"),
              "a profile in non-canonical bytes is refused, so one profile has one id", got_f4)

    # ---------------------------------------------------------------- PS-01: the contract

    # K2: the contract check refuses each planted defect with its code.
    with case('K2'):
        contract, view, harness, cards = contract_inputs()
        row = {"id": "PC-99", "rule": "planted", "tests": ["A1"],
               "mutants": [next(m[0] for m in harness if m[4] == "pilot_test" and "A1" in m[5])]}
        planted = {"UNKNOWN_CASE": dict(row, tests=["Z9"]), "UNPASSED_CASE": dict(row, tests=["X0"]),
                   "UNKNOWN_MUTANT": dict(row, mutants=["M999"]),
                   "MUTANT_OFF_ROW": dict(row, mutants=[next(m[0] for m in harness if m[4] != "pilot_test")]),
                   "UNKNOWN_CARD": {"id": "PC-99", "rule": "planted", "deferred": "PS-12"},
                   "ROW_SHAPE": dict(row, deferred="PS-07")}
        got_k2 = {}
        for code, bad_row in planted.items():
            c = json.loads(json.dumps(contract))
            c["sections"][0]["rows"].append(bad_row)
            got_k2[code] = code in {p[0] for p in PT.problems(c, PT.render(c, cards), dict(results, X0="FAIL"), harness,
                                                              cards)}
        got_k2["STALE_VIEW"] = "STALE_VIEW" in {p[0] for p in PT.problems(contract, view + "\n", dict(results), harness, cards)}
        check("K2", got_k2 == {k: True for k in list(planted) + ["STALE_VIEW"]},
              "the contract check refuses a row citing what does not hold, a deferral to no filed card, a stale view",
              got_k2)

    # K1 (last): PILOT.md is the rendering of the contract source; every row is enforced by cases of this
    # file that passed and mutants that target them, deferred to a filed G9 obligation, or excluded; every
    # case of this file is some mutant's target.
    with case('K1'):
        contract, view, harness, cards = contract_inputs()
        probs = PT.problems(contract, view, dict(results, K1="PASS"), harness, cards)
        check("K1", probs == [], "the pilot contract: every rule enforced here or deferred to a named later card", probs)
    return finish("PILOT")


if __name__ == "__main__":
    sys.exit(main())
