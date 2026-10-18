#!/usr/bin/env python3
"""The pinned Σ-GLYPH evaluator loader executes exactly the bytes it hashed.

    python3 tests/sigma_loader_read_once.py

_import_sigma used to hash an evaluator file and then import it by path, which
re-reads the file: a file replaced between the two ran under the digest that was
checked. The $SIGMA_GLYPH override had the same gap (its pinned/unpinned decision
was taken on one read, the import did another), and it decided "pinned" by
comparing with the bundled FILE rather than the pinned DIGEST. Each case below
replaces files at exactly those boundaries, in temporary copies only.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = Path(os.environ.get("WARRANT_IMPL") or ROOT / "impl")   # tests/sigma_loader_mutants.py
sys.path.insert(0, str(IMPL))
import warrant as W  # noqa: E402

results = {}
GENUINE = (IMPL / "sigma_glyph_v05.py").read_bytes()
EVIL = GENUINE + b"\nEVIL = True\n"
PIN = W.SKI_EVALUATORS["ski@v1"][1]


def check(cid, ok, what, detail=""):
    results[cid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{cid} {what}" + ("" if ok else f" | {detail}"))


def genuine(mod):
    return mod is not None and not hasattr(mod, "EVIL") and hasattr(mod, "term_hash")


def tmpfile(name, data):
    d = Path(tempfile.mkdtemp(prefix="sigma-loader-"))
    (d / name).write_bytes(data)
    return d / name


def main():
    os.environ.pop("SIGMA_GLYPH", None)
    real_path, real_hashlib, real_import = W.bundled_sigma_path, W.hashlib, W._import_sigma
    assert hashlib.sha256(GENUINE).hexdigest() == PIN, "the checkout's evaluator is not the pinned one"

    # R1: the bundled evaluator is replaced right after its bytes are hashed
    target = tmpfile("sigma_glyph_v05.py", GENUINE)

    def sha256_then_replace(data=b""):
        h = real_hashlib.sha256(data)
        target.write_bytes(EVIL)
        return h
    W.bundled_sigma_path = lambda tag="ski@v1": target
    W.hashlib = types.SimpleNamespace(sha256=sha256_then_replace)
    try:
        mod = W.load_bundled_sigma("ski@v1")
    finally:
        W.hashlib, W.bundled_sigma_path = real_hashlib, real_path
    check("R1", genuine(mod) and mod.WARRANT_SIGMA_UNPINNED is False,
          "a file replaced after the hash is not what runs", getattr(mod, "EVIL", mod))

    # R2: the $SIGMA_GLYPH override is replaced after its pinned/unpinned decision
    over = tmpfile("sigma_glyph.py", GENUINE)

    def replace_then_import(*a, **kw):
        over.write_bytes(EVIL)
        return real_import(*a, **kw)
    os.environ["SIGMA_GLYPH"] = str(over.parent)
    W._import_sigma = replace_then_import
    try:
        mod = W.load_sigma("ski@v1")
    finally:
        W._import_sigma = real_import
        os.environ.pop("SIGMA_GLYPH")
    check("R2", genuine(mod) and mod.WARRANT_SIGMA_UNPINNED is False,
          "an override replaced after the decision is not what runs", getattr(mod, "EVIL", mod))

    # R3: positive controls. A moved bundled evaluator is refused before it runs; an
    # override that differs from the pin from the start runs, flagged unpinned.
    moved = tmpfile("sigma_glyph_v05.py", EVIL)
    W.bundled_sigma_path = lambda tag="ski@v1": moved
    try:
        refused = W.load_bundled_sigma("ski@v1")
    finally:
        W.bundled_sigma_path = real_path
    over3 = tmpfile("sigma_glyph.py", EVIL)
    os.environ["SIGMA_GLYPH"] = str(over3.parent)
    try:
        flagged = W.load_sigma("ski@v1")
    finally:
        os.environ.pop("SIGMA_GLYPH")
    check("R3", refused is None and flagged is not None and getattr(flagged, "EVIL", False)
          and flagged.WARRANT_SIGMA_UNPINNED is True,
          "a moved pinned module never runs; a divergent override runs only as unpinned", (refused, flagged))

    # R4: "pinned" means the pinned DIGEST. If the bundled file itself has drifted,
    # an override with the same drifted bytes is still unpinned.
    drifted = tmpfile("sigma_glyph_v05.py", EVIL)
    over4 = tmpfile("sigma_glyph.py", EVIL)
    W.bundled_sigma_path = lambda tag="ski@v1": drifted
    os.environ["SIGMA_GLYPH"] = str(over4.parent)
    try:
        mod = W.load_sigma("ski@v1")
    finally:
        W.bundled_sigma_path = real_path
        os.environ.pop("SIGMA_GLYPH")
    check("R4", mod is not None and mod.WARRANT_SIGMA_UNPINNED is True,
          "an override equal to a drifted bundled file is not the pinned engine",
          getattr(mod, "WARRANT_SIGMA_UNPINNED", mod))

    for d in {target.parent, over.parent, moved.parent, over3.parent, drifted.parent, over4.parent}:
        shutil.rmtree(d, ignore_errors=True)
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"SIGMA LOADER: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("SIGMA_LOADER_RESULTS"):
        Path(os.environ["SIGMA_LOADER_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
