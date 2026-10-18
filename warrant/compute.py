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

from . import jcs as C

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
    files = {f"{n}.py": hashlib.sha256(sources[n]).hexdigest() for n in MODULES}
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


def environment_doc(hashes):
    return {"sigma-environment": sorted(set(hashes))}


def environment_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == {"sigma-environment"} and isinstance(doc["sigma-environment"], list)
            and all(isinstance(h, str) and len(h) == 64 for h in doc["sigma-environment"])
            and doc["sigma-environment"] == sorted(set(doc["sigma-environment"]))):
        return "not a sigma environment manifest"
    return None


RECEIPT_FIELDS = {"receipt", "target", "input", "environment", "checkpoint", "state", "claimed", "lost"}
CYCLE_FIELDS = {"cycle", "target", "input", "environment", "witness", "lost"}


def receipt_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == RECEIPT_FIELDS and doc["receipt"] == "sigma-resume"):
        return "not a sigma-resume receipt"
    if not all(isinstance(doc[k], str) and len(doc[k]) == 64 for k in ("input", "environment", "checkpoint", "state", "claimed")):
        return "receipt hashes"
    if not (isinstance(doc["target"], str) and doc["target"] and isinstance(doc["lost"], list)
            and all(isinstance(x, str) for x in doc["lost"])):
        return "receipt target or lost"
    return None


def cycle_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == CYCLE_FIELDS and doc["cycle"] == "sigma-resume"):
        return "not a sigma-resume cycle"
    if not all(isinstance(doc[k], str) and len(doc[k]) == 64 for k in ("input", "environment", "witness")):
        return "cycle hashes"
    if not (isinstance(doc["target"], str) and doc["target"] and isinstance(doc["lost"], list)
            and all(isinstance(x, str) for x in doc["lost"])):
        return "cycle target or lost"
    return None


def _env_and_blobs(snapshot, env_hash):
    doc = snapshot.json_blob(env_hash)
    if doc is None:
        return None, None, "environment manifest not in view"
    why = environment_problem(doc)
    if why:
        return None, None, why
    hashes = doc["sigma-environment"]
    return hashes, {h: snapshot.blobs[h] for h in hashes if h in snapshot.blobs}, None


def replay(provider, snapshot, condition, doc, targets):
    """(label, None) if the recipient's own replay admits receipt `doc` for the
    `compute` condition, else (None, reason)."""
    why = receipt_problem(doc)
    if why:
        return None, why
    if doc["target"] not in targets:
        return None, f"a translation into {doc['target']!r} is not accepted by this recipient"
    if doc["lost"]:
        return None, "the receipt reports something lost in translation: no credit"
    if (doc["input"], doc["environment"]) != (condition["input"], condition["environment"]):
        return None, "the receipt is for another computation than the condition names"
    hashes, blobs, why = _env_and_blobs(snapshot, doc["environment"])
    if why:
        return None, why
    ck, st = snapshot.blob(doc["checkpoint"]), snapshot.blob(doc["state"])
    if ck is None or st is None:
        return None, "receipt bytes not in view"
    out = provider.call("verify", {"runtime": condition["runtime"], "input": doc["input"], "hashes": hashes,
                                   "chain": [[base64.b64encode(ck).decode(), base64.b64encode(st).decode()]]}, blobs)
    if "refused" in out:
        return None, f"not replayed: {out['refused']}"
    r = out["results"][0]
    if r["basis"] != "REPLAYED":
        return None, f"not replayed: {r['code']}"
    if r["code"] != "NORMAL_FORM":
        return None, f"replayed, but {r['code']} is not an answer"
    if r["result"] != doc["claimed"]:
        return None, "the recipient's replay disagrees with the receipt"
    if r["result"] != condition["expect"]:
        return None, "the replayed result is not the one the condition requires"
    return f"REPLAYED:sigma-resume:{provider.id[:16]}", None


def replay_cycle(provider, snapshot, condition, doc, targets):
    why = cycle_problem(doc)
    if why:
        return None, why
    if doc["target"] not in targets:
        return None, f"a translation into {doc['target']!r} is not accepted by this recipient"
    if doc["lost"]:
        return None, "the cycle reports something lost in translation: no credit"
    if (doc["input"], doc["environment"]) != (condition["input"], condition["environment"]):
        return None, "the cycle is for another computation than the condition names"
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
