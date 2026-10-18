"""The Sigma provider (SPEC §7): one pinned sigma-resume kernel, executed from the
exact bytes whose digests were checked.

`Provider.capture()` reads the provider files once. The kernel files must match
PIN.json; the worker is Warrant's own code and is part of the engine identity.
Every call starts `python -I -B -c BOOT` and hands it those captured bytes on
stdin, so no file is reopened between the check and the execution. The separate
interpreter keeps the kernel's module names out of the assessing process; it is
not an OS sandbox."""
import base64
import json
import subprocess
import sys
from pathlib import Path

from . import jcs as C

HERE = Path(__file__).resolve().parent / "provider"
ORDER = ("sigma_glyph", "sigma_resume", "worker")
BOOK1 = "sigma-book1-0.6.0/hash-thunk/leftmost-outermost"
RICH = "sigma-resume-draft/ski+Y+M+W/hash-thunk/leftmost-outermost"

BOOT = (
    "import base64,json,sys,types\n"
    "req=json.loads(sys.stdin.buffer.read())\n"
    "for n in req['order']:\n"
    "    m=types.ModuleType(n); m.__file__='<pinned '+n+'>'; sys.modules[n]=m\n"
    "    exec(compile(base64.b64decode(req['modules'][n]),m.__file__,'exec'),m.__dict__)\n"
    "sys.stdout.write(json.dumps(sys.modules['worker'].main(req['call']),sort_keys=True))\n"
)


class ProviderError(Exception):
    """The provider could not be captured or did not answer; never an answer."""


class Provider:
    def __init__(self, sources, pin):
        self.sources = sources            # name -> bytes, exactly what will run
        self.pin = pin
        self.identity = {"pin": pin["commit"], "files": {n: C.digest(b) for n, b in sorted(sources.items())},
                         "boot": C.digest(BOOT.encode())}

    @classmethod
    def capture(cls, root=HERE):
        root = Path(root)
        pin = json.loads((root / "PIN.json").read_bytes())
        sources = {}
        for name in ORDER:
            p = root / f"{name}.py"
            if p.is_symlink() or not p.is_file():
                raise ProviderError(f"provider file missing: {name}.py")
            sources[name] = p.read_bytes()
        for fname, want in pin["files"].items():
            got = C.digest(sources[fname[:-3]])
            if got != want:
                raise ProviderError(f"provider not pinned: {fname}")
        return cls(sources, pin)

    def call(self, op, args, blobs=None, timeout=600):
        req = {"order": list(ORDER), "modules": {n: base64.b64encode(self.sources[n]).decode() for n in ORDER},
               "call": {"op": op, "args": args,
                        "blobs": {h: base64.b64encode(b).decode() for h, b in (blobs or {}).items()}}}
        try:
            p = subprocess.run([sys.executable, "-I", "-B", "-c", BOOT], input=json.dumps(req).encode(),
                               capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ProviderError("provider timed out") from None
        try:
            out = json.loads(p.stdout)
        except ValueError:
            raise ProviderError(f"provider failed (exit {p.returncode}): {p.stderr.decode(errors='replace')[-300:]}") from None
        return out


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
    return f"REPLAYED:sigma-resume:{provider.identity['files']['sigma_resume'][:16]}", None


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
    return f"CYCLE:sigma-resume:{provider.identity['files']['sigma_resume'][:16]}", None
