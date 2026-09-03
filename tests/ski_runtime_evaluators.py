#!/usr/bin/env python3
"""One bundled evaluator per ski runtime tag, pinned by digest, checked BEFORE import.

Regression surface for SKI_EVALUATORS (impl/warrant.py) and its human record
trust/ski-runtime-evaluators.json:
  - record and code name the same tags, files and digests (no drift);
  - each bundled module hashes to its pin;
  - load_sigma("ski@v1") loads its pinned module;
  - the reserved but unadmitted ski@v2 tag has no executable module;
  - an unregistered tag yields None (no fallback to another tag's module);
  - a module whose bytes moved is NOT imported: a side-effect marker proves no
    line of it ran, and the loader returns None;
  - the ski@v1 evaluator still re-executes this repository's shipped ski@v1
    specimen to its `expect`.
Writes only under a TemporaryDirectory. Exit status is the verdict.
"""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "impl"))
os.environ.pop("SIGMA_GLYPH", None)               # exercise the BUNDLED engines
import warrant as W                                # noqa: E402

_fail = []


def check(name, cond, detail=""):
    print(f"  {'ok ' if cond else 'BAD'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        _fail.append(name)


# ---- record == code --------------------------------------------------------
rec = json.loads((REPO / "trust/ski-runtime-evaluators.json").read_text())
check("record kind", rec.get("kind") == "warrant/ski-runtime-evaluators@v0")
check("record and code name the same tags", set(rec["tags"]) == set(W.SKI_EVALUATORS),
      detail=f"{sorted(rec['tags'])} vs {sorted(W.SKI_EVALUATORS)}")
for tag, (fname, sha) in W.SKI_EVALUATORS.items():
    ent = rec["tags"].get(tag, {})
    check(f"{tag}: record module/sha equal the code constant",
          ent.get("module") == f"impl/{fname}" and ent.get("sha256") == sha)
    path = REPO / "impl" / fname
    got = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    check(f"{tag}: bundled {fname} hashes to its pin", got == sha, detail=f"{str(got)[:16]}…")

# ---- loading: admitted tag present, reserved candidate inert ---------------
v1 = W.load_sigma("ski@v1")
check("ski@v1 loads", v1 is not None and v1.WARRANT_SIGMA_UNPINNED is False)
check("ski@v1 module is the v0.5-era API (no eval_receipt)", v1 is not None and not hasattr(v1, "eval_receipt"))
check("reserved ski@v2 has no shipped evaluator", W.load_sigma("ski@v2") is None)
check("default tag is ski@v1", W.load_sigma().__file__ == v1.__file__ if v1 else False)
check("unregistered tag -> None (no fallback)", W.load_sigma("ski@v9") is None)

# ---- a moved module is never executed -------------------------------------
with tempfile.TemporaryDirectory(prefix="ski-moved-") as td:
    marker = Path(td) / "executed.marker"
    evil = Path(td) / "sigma_glyph_evil.py"
    evil.write_text(f"open({str(marker)!r}, 'w').write('ran')\nraise RuntimeError('should never import')\n")
    saved = dict(W.SKI_EVALUATORS)
    try:
        # pin says one digest, file has another: the loader must refuse BEFORE import
        W.SKI_EVALUATORS["x-test@v1"] = (evil.name, "00" * 32)
        W.SKI_EVALUATORS["ski@v1"] = (saved["ski@v1"][0], "11" * 32)   # the real file, wrong pin
        orig = W.bundled_sigma_path

        def _bp(tag=W.DEFAULT_SKI_TAG):
            return evil if tag in ("x-test@v1", "ski@v1") else orig(tag)
        W.bundled_sigma_path = _bp
        check("moved module (wrong pin) is refused: returns None", W.load_sigma("x-test@v1") is None)
        check("moved module was NOT executed (no side-effect marker)", not marker.exists())
        check("default tag under a WRONG pin is refused too (no import on mismatch)",
              W.load_sigma("ski@v1") is None)
        for authoring in ("ski_policy.py", "policy_lang.py"):
            name = f"moved_{authoring[:-3]}"
            spec = importlib.util.spec_from_file_location(name, REPO / "impl" / authoring)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                refused = False
            except RuntimeError as ex:
                refused = "pinned ski@v1 evaluator unavailable" in str(ex)
            check(f"{authoring}: moved evaluator refused through shared loader", refused)
            check(f"{authoring}: moved evaluator was NOT executed", not marker.exists())
    finally:
        W.SKI_EVALUATORS.clear(); W.SKI_EVALUATORS.update(saved); W.bundled_sigma_path = orig

# ---- the shipped ski@v1 specimen still re-executes to `expect` -------------
skidir = REPO / "examples" / "ski"
chk = json.loads((skidir / "check.json").read_text())
st = v1.Store()
for fn in skidir.glob("*.bin"):
    st.put(fn.read_bytes())
r = v1.eval_hash(bytes.fromhex(chk["term"]), int(chk["atp"]), st)
got = v1.term_hash(r[0]).hex()
check("ski@v1 specimen re-executes to expect", got == chk["expect"] and int(r[1]) == 20,
      detail=f"{got[:12]} spent={r[1]}")

print(f"\n{'FAIL' if _fail else 'PASS'} — admitted evaluator pinned; reserved candidate inert; drift refused before import.")
raise SystemExit(1 if _fail else 0)
