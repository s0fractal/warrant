"""The resolution layer of the proof-space pilot (goal G9; contract docs/PILOT.md, warrant-pilot/contract@1).

A receiver gathers the objects one Sigma receipt needs from the local object stores it configured,
and nothing else: no network, no store an object names, no fallback past damage. An object is
named by a typed address `<kind>:<hex64>`, the hex64 being the SHA-256 of its exact bytes (SPEC §2).
Each address is checked in one order, every step before the next reads anything:

    shape (shapes.hex64)  ->  kind admitted by this receiver  ->  limits  ->  bytes from a store
    ->  digest  ->  the kind's tag  ->  its dependency fields  ->  each dependency, depth first

`Receiver.resolve` answers RESOLVED with the whole closure, or INCONCLUSIVE / REFUSED with one code
and no object at all; `Receiver.check` hands a closure to a verifier only when it is RESOLVED. A
verification profile (`profile`, `profile_problem`) is a content-addressed manifest of what a replay
of the receipt rests on. Nothing here verifies a computation, grants anything or is read by
`engine.assess`: RESOLVED says the named bytes are present and are what their addresses say, and
nothing about their truth, signatures, authority or the computation's result."""
import collections
import os
import stat
from pathlib import Path

from warrant import jcs as C
from warrant import shapes as S

from . import compute as P
from . import limits as L

MAX_TEXT = 4000                 # Warrant 2's bound of a text member (records.MAX_TEXT), kept for the contract

CONTRACT = "warrant-pilot/contract@1"
RESOLUTION = "warrant-pilot/resolution@1"
RECEIVER = "warrant-pilot/receiver@1"
ROOT_SCHEMA = "warrant-pilot/root@1"
PROFILE_SCHEMA = "warrant-pilot/profile@1"
CLOSURE_SCHEMA = "warrant-pilot/closure@1"
RULE = "warrant-pilot/sigma-replay@1"

RESOLVED, INCONCLUSIVE, REFUSED = "RESOLVED", "INCONCLUSIVE", "REFUSED"
# Each code has one result. INCONCLUSIVE: this receiver could not decide (bytes it has no store for,
# a kind it does not admit, its own limits). REFUSED: the objects as presented are not admissible.
# Neither is a statement about the computation.
CODES = {"MISSING": INCONCLUSIVE, "UNKNOWN_KIND": INCONCLUSIVE, "LIMIT": INCONCLUSIVE,
         "BAD_ADDRESS": REFUSED, "DIGEST_MISMATCH": REFUSED, "KIND_MISMATCH": REFUSED,
         "MALFORMED": REFUSED, "CYCLE": REFUSED}

# The receiver's resource bounds (limits.resolve with these defaults; the same LimitExceeded).
LIMITS = {
    "pilot_objects": 10_000,                 # distinct typed addresses resolved
    "pilot_bytes": 256 * 1024 * 1024,        # their bytes together, admitted before each object is read
    "pilot_depth": 64,                       # references on the longest chain from the root
    "pilot_edges": 100_000,                  # references followed, repeats included
}

NODE_TYPES = (0x00, 0x01, 0x02, 0xFF)         # Book I: literal, ref, apply, dissonance (sigma_glyph)
STATE_MAGIC = b"SGS1"                         # sigma_resume.STATE_MAGIC
CHECKPOINT_SCHEMA = "sigma-resume.checkpoint@draft-1"

# The execution-profile assumptions of the pilot's Sigma replay (SPEC §7, compute.Provider):
# declared in a profile as assumptions, never as pinned bytes.
ASSUMPTIONS = (
    "a host resource limit or timeout stops a run: the outcome is inconclusive, never an answer",
    "the provider runs as the captured module bytes in a separate CPython >= 3.10 interpreter "
    "(-I -B, bytes on stdin); the process boundary is not an OS sandbox",
)
AXIOMS = (
    "SHA-256 is collision resistant for every address the closure names",
    "the runtime's reduction is defined by the provider modules whose digests the profile pins",
)


class _Stop(Exception):
    """One code for one address: the walk ends there, and no object is returned."""

    def __init__(self, code, at, detail, **extra):
        super().__init__(detail)
        self.code, self.at, self.detail, self.extra = code, at, detail, extra


# ---------------------------------------------------------------- kinds

def _json_tag(member, value):
    """Canonical JSON (jcs.loads: non-canonical bytes are refused, never normalized) whose `member` is `value`.
    Any ValueError of the parser is a refusal too: an integer past CPython's conversion limit raises one
    that is not NotCanonical (Codex finding b60e976acb54 on #193)."""
    def tag(data):
        try:
            doc = C.loads(data)
        except ValueError:
            return None
        return doc if isinstance(doc, dict) and doc.get(member) == value else None
    return tag


def _bytes_tag(ok):
    return lambda data: data if ok(data) else None


def _receipt_deps(doc):
    why = P.receipt_problem(doc)
    if why:
        raise ValueError(why)
    return [f"sigma-node:{doc['input']}", f"sigma-environment:{doc['environment']}",
            f"sigma-checkpoint:{doc['checkpoint']}", f"sigma-state:{doc['state']}"]


def _environment_deps(doc):
    why = P.environment_problem(doc)
    if why:
        raise ValueError(why)
    return [f"sigma-node:{h}" for h in doc["hashes"]]


def _root_deps(doc):
    if set(doc) != {"schema", "requires"}:
        raise ValueError("a root has exactly schema and requires")
    req = doc["requires"]
    if not (isinstance(req, list) and req and all(isinstance(a, str) for a in req)):
        raise ValueError("requires is a non-empty list of typed addresses")
    if len(set(req)) != len(req):
        raise ValueError("requires names an address twice")
    return list(req)


def _profile_deps(doc):
    why = profile_problem(doc)
    if why:
        raise ValueError(why)
    return []


def _leaf(_):
    return []


Kind = collections.namedtuple("Kind", "tag deps tag_doc deps_doc")
# The pilot's kinds: the tag is checked on the bytes before anything else reads them; the dependency
# fields are the kind's required references, every one resolved before verification starts.
KINDS = {
    "sigma-receipt": Kind(_json_tag("receipt", "sigma-resume"), _receipt_deps,
                          'canonical JSON, `receipt` = "sigma-resume" (SPEC §7, unchanged)',
                          "`input` (sigma-node), `environment`, `checkpoint`, `state`; `claimed` is a result "
                          "hash, not a dependency"),
    "sigma-environment": Kind(_json_tag("schema", P.ENV_SCHEMA), _environment_deps,
                              f'canonical JSON, `schema` = "{P.ENV_SCHEMA}"', "each of `hashes` (sigma-node)"),
    "sigma-checkpoint": Kind(_json_tag("schema", CHECKPOINT_SCHEMA), _leaf,
                             f'canonical JSON, `schema` = "{CHECKPOINT_SCHEMA}"',
                             "none: the provider replays its chain from the root"),
    "sigma-state": Kind(_bytes_tag(lambda d: d[:4] == STATE_MAGIC), _leaf, 'bytes beginning "SGS1"', "none"),
    "sigma-node": Kind(_bytes_tag(lambda d: len(d) in (34, 66) and d[0] in NODE_TYPES), _leaf,
                       "34 or 66 bytes, first byte 0x00, 0x01, 0x02 or 0xff (Book I)",
                       "none: the environment bounds a node's references (BLOCKED_REFERENCE is the kernel's answer)"),
    "pilot-root": Kind(_json_tag("schema", ROOT_SCHEMA), _root_deps, f'canonical JSON, `schema` = "{ROOT_SCHEMA}"',
                       "each of `requires` (a typed address of any admitted kind)"),
    "pilot-profile": Kind(_json_tag("schema", PROFILE_SCHEMA), _profile_deps,
                          f'canonical JSON, `schema` = "{PROFILE_SCHEMA}"', "none: its digests are identities"),
}


def parse(address, kinds):
    """(kind, hex64) of a typed address, or _Stop: BAD_ADDRESS for anything but `<kind>:<hex64>`
    (before any path is built), UNKNOWN_KIND for a kind outside `kinds`."""
    kind, sep, h = address.partition(":") if isinstance(address, str) else ("", "", "")
    if not (sep and S.hex64(h)):
        raise _Stop("BAD_ADDRESS", address if isinstance(address, str) else None,
                    "not a typed address <kind>:<64 lowercase hex digits>")
    if kind not in kinds:
        raise _Stop("UNKNOWN_KIND", address, f"{kind!r} is not a kind this receiver admits")
    return kind, h


# ---------------------------------------------------------------- stores

class _Dir:
    """A local object store: a directory of objects named by the SHA-256 of their bytes."""
    layout = None

    def __init__(self, root):
        self.root = Path(root)
        # os.open refuses a NUL byte with ValueError, not OSError: refused here, before the store is used
        # (PC-26; Gemini review of 1a660a6)
        if "\x00" in str(self.root):
            raise ValueError("pilot receiver: a store path holds a NUL byte")

    def __repr__(self):
        return f"{self.layout}:{self.root}"

    def read(self, name, admit):
        """The bytes of the regular file this store holds under `name` (hex64), or None: an entry that is
        absent, not a regular file (a FIFO, a directory) or reached through a symlink is not an object of
        this store. Each component below the store's directory is opened relative to its parent's
        descriptor without following a symlink, so the directories checked are the ones read (Codex
        finding d8a510cd300e on #193), and the object without blocking, so a FIFO is seen as one before
        anything waits on it (19556ffa5a1c). `admit(size)` runs before a byte is read, and again on the
        bytes read: a file grown since fstat is read to its end, each part admitted as it is read, so
        its whole bytes are what the digest is checked on (971ca0938c3a, d564e974a47d)."""
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return None
        obj = -1
        try:
            *dirs, leaf = self.parts(name)
            for d in dirs:
                parent, fd = fd, -1
                try:
                    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                finally:
                    os.close(parent)
            obj = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except OSError:
            return None
        finally:
            if fd >= 0:
                os.close(fd)
        try:
            st = os.fstat(obj)
            if not stat.S_ISREG(st.st_mode):
                return None
            admit(st.st_size)
            with os.fdopen(obj, "rb") as f:
                obj = -1
                data = f.read(st.st_size + 1)   # one byte more than fstat said: a grown file is seen as grown
                while True:
                    admit(len(data))
                    more = f.read(1 << 16)
                    if not more:
                        return data
                    data += more
        finally:
            if obj >= 0:
                os.close(obj)


class BlobDir(_Dir):
    """`<dir>/<hex64>`: a Warrant store's blobs/ (store.Store). Its records/ is never read."""
    layout = "blobs"

    def parts(self, name):
        return (name,)


class FanoutDir(_Dir):
    """`<dir>/<2 hex>/<62 hex>`: a warrant-agent workspace's objects/ (git's loose objects, minds' cas/)."""
    layout = "fanout"

    def parts(self, name):
        return (name[:2], name[2:])


LAYOUTS = {c.layout: c for c in (BlobDir, FanoutDir)}


# ---------------------------------------------------------------- closure

def _result(root, stop):
    out = {"pilot": RESOLUTION, "result": CODES[stop.code], "code": stop.code, "root": root, "at": stop.at,
           "detail": stop.detail}
    out.update(stop.extra)
    return out


def walk(fetch, root, kinds, limits):
    """The closure of typed address `root`: RESOLVED with every object, or the first code (CODES).

    `fetch(kind, hex64, address, admit)` returns the bytes, digest-checked, or raises _Stop. The walk
    is depth first and iterative; an address on the current path met again is CYCLE; an address
    already resolved is not fetched again, but the reference counts toward pilot_edges. The depth of an
    object is its longest chain of references below it, so pilot_depth bounds the longest chain from
    the root whatever the order of the walk. Limits raise L.LimitExceeded, read as LIMIT."""
    lim = dict(limits)
    objects, height, used = {}, {}, {"bytes": 0, "edges": 0}

    def admit_bytes(size):
        L.admit(lim, "pilot_bytes", used["bytes"] + size)

    def enter(address):
        kind, h = parse(address, kinds)
        L.admit(lim, "pilot_objects", len(objects) + 1)
        data = fetch(kind, h, address, admit_bytes)
        used["bytes"] += len(data)
        value = kinds[kind].tag(data)
        if value is None:
            raise _Stop("KIND_MISMATCH", address, f"the bytes of {h[:12]} are not a {kind}")
        try:
            deps = kinds[kind].deps(value)
        except ValueError as e:
            raise _Stop("MALFORMED", address, f"{kind}: {e}") from None
        objects[address] = data
        return [address, deps, 0]

    try:
        path = [enter(root)]
        on_path = {root}
        while path:
            frame = path[-1]
            address, deps, i = frame
            if i < len(deps):
                frame[2] += 1
                dep = deps[i]
                used["edges"] += 1
                L.admit(lim, "pilot_edges", used["edges"])
                if dep in on_path:
                    raise _Stop("CYCLE", dep, f"{dep} requires itself through the addresses above it")
                if dep in objects:
                    # resolved under another path: its chain from here counts now, before a later sibling
                    # is read (Gemini review of 1a660a6)
                    L.admit(lim, "pilot_depth", len(path) + height[dep])
                    continue
                L.admit(lim, "pilot_depth", len(path))
                path.append(enter(dep))
                on_path.add(dep)
                continue
            # every dependency is resolved by now (a cycle stopped the walk), so each has its height; every
            # chain below was admitted where it was entered or met again
            height[address] = max((1 + height.get(d, 0) for d in deps), default=0)
            path.pop()
            on_path.discard(address)
    except _Stop as stop:
        return _result(root, stop)
    except L.LimitExceeded as e:
        return _result(root, _Stop("LIMIT", None, str(e), limit=e.limit, value=e.value, bound=e.bound))
    closure = {"schema": CLOSURE_SCHEMA, "root": root, "objects": sorted(objects)}
    return {"pilot": RESOLUTION, "result": RESOLVED, "root": root, "closure": C.doc_id(closure),
            "manifest": closure, "objects": objects}


class Receiver:
    """A receiver's own configuration: its stores (in order), the kinds it admits and its limits.
    Nothing an object says adds a store, a kind or a limit."""

    def __init__(self, stores, kinds=None, limits=None):
        self.stores = tuple(stores)
        names = list(KINDS) if kinds is None else list(kinds)
        unknown = sorted(set(names) - set(KINDS))
        if unknown:
            raise ValueError(f"pilot receiver: unknown kinds {unknown}")
        self.kinds = {k: KINDS[k] for k in names}
        # A mapping or nothing: a false value is not "no limits given" (Codex finding b3887f01538c on #193)
        if limits is not None and not isinstance(limits, dict):
            raise ValueError("pilot receiver: limits is a mapping of limit names to positive integers")
        self.limits = L.resolve(limits, LIMITS)

    @classmethod
    def from_config(cls, doc, base="."):
        """A receiver from its configuration {"receiver": RECEIVER, "stores": [{"layout", "path"}], "kinds"?,
        "limits"?}; a relative path is under `base`. Anything else is a ValueError."""
        if not (isinstance(doc, dict) and doc.get("receiver") == RECEIVER
                and set(doc) <= {"receiver", "stores", "kinds", "limits"} and "stores" in doc):
            raise ValueError(f"pilot receiver: not a {RECEIVER} configuration")
        stores = []
        for s in doc["stores"] if isinstance(doc["stores"], list) else [None]:
            if not (isinstance(s, dict) and set(s) == {"layout", "path"} and isinstance(s["layout"], str) and s["layout"] in LAYOUTS
                    and isinstance(s["path"], str) and s["path"]):
                raise ValueError("pilot receiver: a store is {layout: blobs|fanout, path}")
            stores.append(LAYOUTS[s["layout"]](Path(base) / s["path"]))
        if not stores:
            raise ValueError("pilot receiver: at least one store")
        kinds = doc.get("kinds")
        if kinds is not None and not (isinstance(kinds, list) and all(isinstance(k, str) for k in kinds)):
            raise ValueError("pilot receiver: kinds is a list of kind names")
        return cls(stores, kinds, doc.get("limits"))

    def fetch(self, kind, h, address, admit):
        """The bytes of `h` from the first configured store holding an object under that name. Bytes
        that do not hash to it are DIGEST_MISMATCH, naming that store: never read further, and no
        other store is consulted past them."""
        for i, store in enumerate(self.stores):
            data = store.read(h, admit)
            if data is None:
                continue
            if C.digest(data) != h:
                raise _Stop("DIGEST_MISMATCH", address, f"store {i} ({store.layout}) holds other bytes under {h[:12]}",
                            store=i)
            return data
        raise _Stop("MISSING", address, f"no configured store holds {h[:12]}")

    def resolve(self, root):
        return walk(self.fetch, root, self.kinds, self.limits)

    def check(self, root, verify):
        """verify(resolution) on a RESOLVED closure, and its answer; otherwise the resolution itself,
        without calling verify: verification starts only after the whole closure is resolved."""
        res = self.resolve(root)
        return verify(res) if res["result"] == RESOLVED else res


# ---------------------------------------------------------------- verification profiles

PROFILE_FIELDS = {"schema", "rule", "verifier", "runtime", "axioms", "assumptions"}
VERIFIER_FIELDS = {"entry", "boot", "protocol", "provider", "modules"}
MODULE_FILES = {f"{n}.py" for n in P.MODULES}


def _texts(v):
    return (isinstance(v, list) and v and all(isinstance(x, str) and x and len(x) <= MAX_TEXT for x in v)
            and v == sorted(set(v)))


def profile_problem(doc):
    """None if `doc` is a pilot verification profile, else why not. Every semantic operand is a declared
    member: a closed member set, pinned bytes only as hex64 digests (no path, URL or ref), the provider
    identity the one its module digests give (compute.identity_of_files), free text only in `axioms` and
    `assumptions`, each a sorted list without repeats, so one profile has one encoding and one id."""
    if not (isinstance(doc, dict) and set(doc) == PROFILE_FIELDS and doc["schema"] == PROFILE_SCHEMA):
        return "a profile has exactly the members " + ", ".join(sorted(PROFILE_FIELDS))
    v = doc["verifier"]
    if not (isinstance(v, dict) and set(v) == VERIFIER_FIELDS):
        return "a verifier has exactly the members " + ", ".join(sorted(VERIFIER_FIELDS))
    if not (isinstance(doc["rule"], str) and doc["rule"] and isinstance(doc["runtime"], str) and doc["runtime"]
            and isinstance(v["entry"], str) and v["entry"] and type(v["protocol"]) is int and v["protocol"] > 0):
        return "rule, runtime and verifier entry are non-empty strings, protocol a positive integer"
    mods = v["modules"]
    if not (S.hex64(v["boot"]) and S.hex64(v["provider"]) and isinstance(mods, dict) and set(mods) == MODULE_FILES
            and all(S.hex64(x) for x in mods.values())):
        return "boot, provider and each provider module are pinned by a hex64 digest"
    if v["provider"] != P.identity_of_files(mods):
        return "the provider identity is not the one its module digests give"
    if not (_texts(doc["axioms"]) and _texts(doc["assumptions"])):
        return "axioms and assumptions are non-empty sorted lists of distinct non-empty strings"
    return None


def profile(provider, runtime, rule=RULE, axioms=AXIOMS, assumptions=ASSUMPTIONS):
    """The profile of an installed provider (compute.Provider), from the receiver's own captured bytes."""
    doc = {"schema": PROFILE_SCHEMA, "rule": rule, "runtime": runtime,
           "verifier": {"entry": "sigma_provider.handle", "boot": C.digest(P.BOOT.encode()), "protocol": P.PROTOCOL,
                        "provider": provider.id,
                        "modules": {f"{n}.py": C.digest(provider.sources[n]) for n in P.MODULES}},
           "axioms": sorted(set(axioms)), "assumptions": sorted(set(assumptions))}
    why = profile_problem(doc)
    if why:
        raise ValueError(why)
    return doc


def profile_id(doc):
    """A profile's id: the SHA-256 of its canonical bytes, which is its `pilot-profile` address."""
    return C.doc_id(doc)
