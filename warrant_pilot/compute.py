"""The Sigma provider adapter (SPEC §7). Sigma owns evaluation, resume, replay and
cycles; this module maps Warrant's data to the installed `sigma_provider` and back.

The provider is the `sigma-glyph` distribution's three modules `sigma_glyph`,
`sigma_resume` and `sigma_provider`, found where the import system would find
them (never the current directory) and never imported into this process.
`Provider.capture()` reads their bytes once; `identity` is computed from those
bytes with the formula `sigma_provider.identity_of` documents. Every call starts
`python -I -B -c BOOT` and hands it the captured bytes on stdin, so the bytes
whose identity was computed are the bytes that run. The separate interpreter
keeps the kernel's module names out of the assessing process; it is not an OS
sandbox. Whether a recipient accepts this provider is its profile's choice
(`providers`), never the provider's own report."""
import base64
import hashlib
import importlib.machinery
import json
import os
import subprocess
import sys
import types
from pathlib import Path

from warrant import jcs as C
from warrant import shapes as S

MODULES = ("sigma_glyph", "sigma_resume", "sigma_provider")
PROTOCOL = 1
BOOK1 = "sigma-book1-0.6.0/hash-thunk/leftmost-outermost"
RICH = "sigma-resume-draft/ski+Y+M+W/hash-thunk/leftmost-outermost"

BOOT = (
    "import base64,json,sys,types\n"
    "req=json.loads(sys.stdin.buffer.read())\n"
    "for n in req['order']:\n"
    "    m=types.ModuleType(n); m.__file__='<captured '+n+'>'; sys.modules[n]=m\n"
    "    exec(compile(base64.b64decode(req['modules'][n]),m.__file__,'exec'),m.__dict__)\n"
    "sys.stdout.write(json.dumps(sys.modules['sigma_provider'].handle(req['call']),sort_keys=True))\n"
)


class ProviderError(Exception):
    """No provider, or one that did not answer: never an answer."""


def identity_of(sources):
    """sigma_provider.identity_of, computed here from the captured bytes."""
    return identity_of_files({f"{n}.py": hashlib.sha256(sources[n]).hexdigest() for n in MODULES})


def identity_of_files(files):
    """The same identity from the modules' digests ({"<module>.py": hex64}): a verification profile
    (warrant.pilot) names the provider by these digests without carrying the bytes."""
    doc = {"provider": "sigma-resume", "files": files}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _search_path():
    cwd = Path.cwd().resolve()
    return [p for p in sys.path if p and Path(p).resolve() != cwd]


def _locate(root):
    """{module: path}: one directory holding all three modules."""
    if root is not None:
        return {n: Path(root) / f"{n}.py" for n in MODULES}
    spec = importlib.machinery.PathFinder.find_spec("sigma_provider", _search_path())
    if spec is None or not spec.origin:
        raise ProviderError("no Sigma provider installed (pip install the sigma-glyph wheel that ships sigma_provider)")
    here = Path(spec.origin).parent
    return {n: here / f"{n}.py" for n in MODULES}


class Provider:
    def __init__(self, sources, where):
        # A private copy, exposed read-only: the identity, the acceptance check and
        # every execution read this one snapshot, so a caller who kept the dict it
        # passed in cannot change what runs under the accepted id (W140-01).
        own = {n: bytes(sources[n]) for n in MODULES}
        self.sources = types.MappingProxyType(own)
        self.where = str(where)
        self.id = identity_of(own)
        self.identity = {"provider": self.id, "boot": C.digest(BOOT.encode()),
                         "files": {f"{n}.py": C.digest(b) for n, b in sorted(sources.items())}}

    @classmethod
    def capture(cls, root=None):
        paths = _locate(root)
        sources = {}
        for n, p in paths.items():
            if p.is_symlink() or not p.is_file():
                raise ProviderError(f"provider module missing: {n}.py in {p.parent}")
            sources[n] = p.read_bytes()
        return cls(sources, paths["sigma_provider"].parent)

    def call(self, op, args, blobs=None, timeout=600):
        """One protocol request. Returns the provider's `ok` value, or
        {"refused": reason}; a crash or garbage is ProviderError."""
        req = {"order": list(MODULES), "modules": {n: base64.b64encode(self.sources[n]).decode() for n in MODULES},
               "call": {"sigma_provider": PROTOCOL, "op": op, "args": args,
                        "blobs": {h: base64.b64encode(b).decode() for h, b in (blobs or {}).items()}}}
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        try:
            p = subprocess.run([sys.executable, "-I", "-B", "-c", BOOT], input=json.dumps(req).encode(),
                               capture_output=True, timeout=timeout, check=False, env=env)
        except subprocess.TimeoutExpired:
            raise ProviderError("provider timed out") from None
        try:
            out = json.loads(p.stdout)
        except ValueError:
            raise ProviderError(f"provider failed (exit {p.returncode}): {p.stderr.decode(errors='replace')[-300:]}") from None
        if not (isinstance(out, dict) and out.get("sigma_provider") == PROTOCOL and ("ok" in out) != ("refused" in out)):
            raise ProviderError("provider answered outside its protocol")
        return {"refused": str(out["refused"])} if "refused" in out else out["ok"]


# Sigma's own environment manifest: its canonical bytes hash to sigma_resume's
# environment_id, so one hash set has one identity on both sides.
ENV_SCHEMA = "sigma-resume.environment@draft-1"


def environment_doc(hashes):
    return {"schema": ENV_SCHEMA, "hashes": sorted(set(hashes))}


def environment_hashes(doc):
    return doc["hashes"]


def environment_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == {"schema", "hashes"} and doc["schema"] == ENV_SCHEMA
            and isinstance(doc["hashes"], list)
            and all(S.hex64(h) for h in doc["hashes"])
            and doc["hashes"] == sorted(set(doc["hashes"]))):
        return "not a sigma environment manifest"
    return None


RECEIPT_FIELDS = {"receipt", "target", "input", "environment", "checkpoint", "state", "claimed", "lost"}
CYCLE_FIELDS = {"cycle", "target", "input", "environment", "witness", "lost"}


def receipt_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == RECEIPT_FIELDS and doc["receipt"] == "sigma-resume"):
        return "not a sigma-resume receipt"
    # A hash member is lowercase hex64 (shapes.hex64): not any 64-character string (length only
    # before AMEND 1 of #164), and not 65 with a trailing newline (`$` before AMEND 2).
    if not all(S.hex64(doc[k]) for k in ("input", "environment", "checkpoint", "state", "claimed")):
        return "receipt hashes"
    if not (isinstance(doc["target"], str) and doc["target"] and isinstance(doc["lost"], list)
            and all(isinstance(x, str) for x in doc["lost"])):
        return "receipt target or lost"
    return None


def cycle_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == CYCLE_FIELDS and doc["cycle"] == "sigma-resume"):
        return "not a sigma-resume cycle"
    if not all(S.hex64(doc[k]) for k in ("input", "environment", "witness")):
        return "cycle hashes"
    if not (isinstance(doc["target"], str) and doc["target"] and isinstance(doc["lost"], list)
            and all(isinstance(x, str) for x in doc["lost"])):
        return "cycle target or lost"
    return None


class ReplayCache:
    """A receiver-local cache of the provider's own verified replays (SPEC §7).

    Keyed by the provider identity and the exact chain it verified (runtime,
    input, environment, checkpoint, state), it changes cost, never an answer:
    an entry is consulted only when every byte the uncached replay would read is
    in the view, and only REPLAYED results are kept, so a cached verdict equals
    the verdict the provider would give again on the same bytes. The directory
    is the receiver's own, like its keys and profile; it is never shipped."""
    SCHEMA = "warrant-replay-cache/1"
    FIELDS = ("provider", "runtime", "input", "environment", "checkpoint", "state")

    def __init__(self, root):
        self.root = Path(root)
        self.hits = 0

    @classmethod
    def key_of(cls, fields):
        return C.doc_id({k: fields[k] for k in cls.FIELDS})

    def _path(self, fields):
        return self.root / fields["provider"] / (self.key_of(fields) + ".json")

    def get(self, fields):
        path = self._path(fields)
        if not path.is_file():
            return None
        try:
            doc = json.loads(path.read_bytes())
        except ValueError:
            return None
        if not (isinstance(doc, dict) and doc.get("replay_cache") == self.SCHEMA
                and all(doc.get(k) == fields[k] for k in self.FIELDS)
                and isinstance(doc.get("result"), dict) and doc["result"].get("basis") == "REPLAYED"):
            return None
        self.hits += 1
        return doc["result"]

    def put(self, fields, result):
        if not (isinstance(result, dict) and result.get("basis") == "REPLAYED"):
            return
        path = self._path(fields)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps({"replay_cache": self.SCHEMA, **{k: fields[k] for k in self.FIELDS},
                                   "result": result}, sort_keys=True))
        os.replace(tmp, path)


def _env_and_blobs(snapshot, env_hash):
    doc = snapshot.json_blob(env_hash)
    if doc is None:
        return None, None, "environment manifest not in view"
    why = environment_problem(doc)
    if why:
        return None, None, why
    hashes = environment_hashes(doc)
    return hashes, {h: snapshot.blobs[h] for h in hashes if h in snapshot.blobs}, None


def replay(provider, snapshot, condition, doc, targets, cache=None):
    """(label, None) if the recipient's own replay admits receipt `doc` for the
    `compute` condition, else (None, reason). `cache` is a ReplayCache of this
    recipient's earlier replays by this provider, or None."""
    why = receipt_problem(doc) or _condition_problem(doc, condition, targets, "receipt")
    if why:
        return None, why
    hashes, blobs, why = _env_and_blobs(snapshot, doc["environment"])
    if why:
        return None, why
    ck, st = snapshot.blob(doc["checkpoint"]), snapshot.blob(doc["state"])
    if ck is None or st is None:
        return None, "receipt bytes not in view"
    fields = {"provider": provider.id, "runtime": condition["runtime"], "input": doc["input"],
              "environment": doc["environment"], "checkpoint": doc["checkpoint"], "state": doc["state"]}
    # The cache stands in for a replay only when that replay would have had every byte.
    complete = cache is not None and all(h in blobs for h in hashes)
    r = cache.get(fields) if complete else None
    if r is None:
        out = provider.call("verify", {"runtime": condition["runtime"], "input": doc["input"], "hashes": hashes,
                                       "chain": [[base64.b64encode(ck).decode(), base64.b64encode(st).decode()]]}, blobs)
        if "refused" in out:
            return None, f"not replayed: {out['refused']}"
        r = out["results"][0]
        if complete:
            cache.put(fields, r)
    why = _replayed_problem(r, doc, condition)
    if why:
        return None, why
    return f"REPLAYED:sigma-resume:{provider.id[:16]}", None


def _condition_problem(doc, condition, targets, what):
    """Why a receipt or a cycle (`what`) is no credit for the condition with this recipient, or None."""
    if doc["target"] not in targets:
        return f"a translation into {doc['target']!r} is not accepted by this recipient"
    if doc["lost"]:
        return f"the {what} reports something lost in translation: no credit"
    if (doc["input"], doc["environment"]) != (condition["input"], condition["environment"]):
        return f"the {what} is for another computation than the condition names"
    return None


def _replayed_problem(r, doc, condition):
    """Why the provider's replay result `r` does not admit the receipt for the condition, or None."""
    if r["basis"] != "REPLAYED":
        return f"not replayed: {r['code']}"
    if r["code"] != "NORMAL_FORM":
        return f"replayed, but {r['code']} is not an answer"
    if r["result"] != doc["claimed"]:
        return "the recipient's replay disagrees with the receipt"
    if r["result"] != condition["expect"]:
        return "the replayed result is not the one the condition requires"
    return None


def replay_cycle(provider, snapshot, condition, doc, targets, cache=None):
    # Cycle witnesses are verified every time; the cache covers receipts only.
    why = cycle_problem(doc) or _condition_problem(doc, condition, targets, "cycle")
    if why:
        return None, why
    hashes, blobs, why = _env_and_blobs(snapshot, doc["environment"])
    if why:
        return None, why
    w = snapshot.blob(doc["witness"])
    if w is None:
        return None, "cycle witness not in view"
    out = provider.call("verify_cycle", {"runtime": condition["runtime"], "input": doc["input"], "hashes": hashes,
                                         "witness": base64.b64encode(w).decode()}, blobs)
    if out.get("code") != "CYCLE_PROVEN":
        return None, f"cycle not proven: {out.get('code') or out.get('refused')}"
    return f"CYCLE:sigma-resume:{provider.id[:16]}", None
