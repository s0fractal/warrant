#!/usr/bin/env python3
"""WRT-022 S2: verify ONE sigma-resume replay receipt, in its own interpreter.

Run by impl/replay.py as `python3 -I replay_sigma_worker.py`, with a JSON request on
stdin: {"store": <the assessment's private snapshot directory>, "receipt": {...}}.
It prints one JSON object. A process of its own keeps the vendored kernel's module
names (`sigma_glyph`, `sigma_resume`) out of the assessing process, where another
module of the same name could already be loaded.

The vendored files are hashed BEFORE import and refused if their bytes moved, as
warrant's own evaluators are (warrant.py, SKI_EVALUATORS). The verifier chooses the
root: it is derived here from the receipt's input term and environment manifest,
which impl/replay.py has already matched against the duty's own computation.
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "sigma_resume_c864d3e"
PINS = {"sigma_glyph.py": "f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4",
        "sigma_resume.py": "575a198d47519f56cb8cf75458d5d9754492433f98650d1ddf1f3580a363e858"}


def out(**kw):
    print(json.dumps(kw, sort_keys=True))
    return 0


def main():
    for name, digest in PINS.items():
        p = VENDOR / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            return out(refused=f"verifier not pinned: {name}")
    sys.path.insert(0, str(VENDOR))
    import sigma_glyph as G      # noqa: E402  (only after the pin check)
    import sigma_resume as R     # noqa: E402
    if Path(G.__file__).resolve().parent != VENDOR or Path(R.__file__).resolve().parent != VENDOR:
        return out(refused="verifier not pinned: another module was imported")
    req = json.loads(sys.stdin.read())
    blobs = Path(req["store"]) / "blobs"
    rc = req["receipt"]

    def blob(h):
        p = blobs / h
        if not p.is_file():
            return None
        b = p.read_bytes()
        return b if hashlib.sha256(b).hexdigest() == h else None

    class Delivered:
        def get(self, h):
            return blob(h.hex())

    manifest = blob(rc["environment"])
    ckpt, state = blob(rc["checkpoint"]), blob(rc["state"])
    if manifest is None or ckpt is None or state is None:
        return out(refused="receipt bytes not in view")
    try:
        hashes = json.loads(manifest)["hashes"]
        env = R.Environment([bytes.fromhex(h) for h in hashes], Delivered())
        root = R.root(bytes.fromhex(rc["input_term_hash"]), env)
        basis, code, _ = R.verify(root, env, ckpt, state)
        result = None
        if basis == R.REPLAYED and code == R.NORMAL_FORM:
            _, term = R.decode_state(state)
            result = G.term_hash(term).hex()
    except (R.InvalidEncoding, ValueError, KeyError, TypeError) as e:
        return out(refused=f"receipt not decodable: {type(e).__name__}")
    return out(basis=basis, code=code, result_term_hash=result, verifier=PINS["sigma_resume.py"])


if __name__ == "__main__":
    sys.exit(main())
