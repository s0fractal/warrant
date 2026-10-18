#!/usr/bin/env python3
"""Each mutant of impl/replay.py, impl/replay_sigma_worker.py or impl/loops.py undoes
one WRT-022 S2 rule and must make ITS case of tests/replay_test.py fail. Breaking
only another case is OFF_TARGET, a crash is CRASH; neither counts as killed.

    python3 tests/replay_mutants.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("replay.py", "replay_sigma_worker.py", "loops.py", "triggers.py")
SOURCES = {f: (ROOT / "impl" / f).read_text() for f in FILES}

MUTANTS = [
    ("X01", "loops.py", "a validated replay is not labelled REPLAYED",
     [('        view.labels[(t_id, i)] = label\n', '')]),
    ("X02", "replay.py", "a ski@v1 receipt the recipient's replay contradicts is believed",
     [('    if verdict != r["claimed"]["verdict"] or result != r["claimed"]["result_node_hash"]:', '    if False:')]),
    ("X03", "replay.py", "a ski@v1 receipt of another computation counts",
     [('    if r["check"] != comp["check"]:', '    if False:')]),
    ("X04", "replay.py", "a duty that names no computation takes the receipt's",
     [('    if computation is None:\n        return None, "the duty names no computation, so no replay can discharge it"',
       '    if computation is None:\n        computation = {"runtime": "ski@v1", "check": "", "expect": ""}')]),
    ("X05", "replay.py", "the duty binds the check's verdict, not its answer",
     [('    if result != comp["expect"]:\n        return None, "the replayed result is not the one the duty requires"\n    pin',
       '    if verdict != "pass":\n        return None, "the replayed result is not the one the duty requires"\n    pin')]),
    ("X07", "replay.py", "a verified PREFIX is taken as an answer",
     [('    if res["code"] != "NORMAL_FORM":', '    if False:')]),
    ("X08", "replay.py", "a sigma receipt's claimed result is not compared",
     [('    if res["result_term_hash"] != r["claimed"]["result_term_hash"]:', '    if False:')]),
    ("X09", "replay.py", "a sigma replay's result is not compared with what the duty requires",
     [('    if res["result_term_hash"] != comp["expect"]:', '    if False:')]),
    ("X10", "replay.py", "an unreplayed checkpoint is taken as replayed",
     [('    if res["basis"] != "REPLAYED":', '    if False:')]),
    ("X11", "replay_sigma_worker.py", "the worker imports moved bytes",
     [('        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:',
       '        if not p.is_file():')]),
    ("X12", "replay.py", "a BORROWED crossing gets credit",
     [('    if st != "TRANSLATED":', '    if st == "UNTRANSLATABLE":')]),
    ("X13", "replay.py", "UNTRANSLATABLE need not name its conflicts",
     [('    if (doc["outcome"] == "UNTRANSLATABLE") != bool(doc["conflicts"]):', '    if False:')]),
    ("X14", "replay.py", "receipt enums are tested for membership before type",
     [('    if not isinstance(r, dict) or not _enum(r.get("runtime"), RUNTIMES):\n        return "replay runtime"',
       '    if not isinstance(r, dict) or r.get("runtime") not in RUNTIMES:\n        return "replay runtime"')]),
    ("X15", "replay.py", "a non-canonical environment manifest is accepted",
     [('    if not (isinstance(hs, list) and hs and all(_hex(h) for h in hs) and hs == sorted(set(hs))):',
       '    if not (isinstance(hs, list) and hs and all(_hex(h) for h in hs)):')]),
    ("X16", "replay.py", "the first of several crossings is used",
     [('    if len(crossings) != 1:', '    if not crossings:')]),
    ("X17", "replay.py", "the assessing side does not bind the resume kernel",
     [('    "sigma_resume_c864d3e/sigma_resume.py": SIGMA_RESUME_PIN,\n', ''),
      ('    if res.get("verifier") != {"sigma_resume.py": SIGMA_RESUME_PIN, "sigma_glyph.py": SIGMA_GLYPH_PIN}:',
       '    if res.get("verifier", {}).get("sigma_glyph.py") != SIGMA_GLYPH_PIN:')]),
    ("X18", "replay.py", "a crossing into any target gets credit (S2-01)",
     [('    if doc["target_profile"] not in accepted_targets:', '    if False:')]),
    ("X19", "replay.py", "the assessing side does not bind the glyph kernel (S2-02)",
     [('    "sigma_resume_c864d3e/sigma_glyph.py": SIGMA_GLYPH_PIN,\n', ''),
      ('    if res.get("verifier") != {"sigma_resume.py": SIGMA_RESUME_PIN, "sigma_glyph.py": SIGMA_GLYPH_PIN}:',
       '    if res.get("verifier", {}).get("sigma_resume.py") != SIGMA_RESUME_PIN:')]),
    ("X20", "loops.py", "the verifier observation is not in the assessment identity (S2-03)",
     [('             "replay_evaluator": RP.EVALUATOR, "replay_verifiers": view.verifiers,',
       '             "replay_evaluator": RP.EVALUATOR,')]),
    ("X22", "replay.py", "the worker runs from the mutable original path, not the capture (S2-04)",
     [('str(Path(exec_dir) / "replay_sigma_worker.py")', 'str(WORKER)')]),
    ("X21", "replay.py", "the worker's own bytes are not bound (S2-02)",
     [('    "replay_sigma_worker.py": ', '    "_not_bound_": ')]),
]


def run(target, fname, pairs):
    srcs = dict(SOURCES)
    for old, new in pairs:
        if srcs[fname].count(old) != 1:
            return "BAD_MUTANT", f"pattern occurs {srcs[fname].count(old)} times: {old[:60]!r}"
        srcs[fname] = srcs[fname].replace(old, new)
    with tempfile.TemporaryDirectory() as tmp:
        for f, text in srcs.items():
            (Path(tmp) / f).write_text(text)
        shutil.copytree(ROOT / "impl" / "sigma_resume_c864d3e", Path(tmp) / "sigma_resume_c864d3e")
        res = Path(tmp) / "results.json"
        env = dict(os.environ, REPLAY_IMPL=tmp, REPLAY_RESULTS=str(res))
        subprocess.run([sys.executable, str(ROOT / "tests" / "replay_test.py")], env=env,
                       capture_output=True, text=True, check=False)
        if not res.exists():
            return "CRASH", ""
        results = json.loads(res.read_text())
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    if results.get(target) == "FAIL":
        return "KILLED", ",".join(failed)
    return ("OFF_TARGET" if failed else "SURVIVED"), ",".join(failed)


def main():
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        outcomes = list(pool.map(lambda mt: run(mt[0], mt[1], mt[3]), MUTANTS))
    verdicts = []
    for (target, fname, what, _), (v, detail) in zip(MUTANTS, outcomes):
        verdicts.append(v)
        print(f"{v:10} {target} {fname}: {what}" + (f"  [{detail}]" if detail else ""))
    killed = verdicts.count("KILLED")
    print(f"REPLAY MUTANTS: {killed}/{len(MUTANTS)} killed on target")
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
