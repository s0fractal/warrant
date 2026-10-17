#!/usr/bin/env python3
"""Each mutant of impl/triggers.py or impl/loops.py undoes one WRT-022 S1 rule and
must make ITS case of tests/triggers_test.py fail. Breaking only another case is
OFF_TARGET, a crash is CRASH; neither counts as killed.

    python3 tests/triggers_mutants.py
"""
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {f: (ROOT / "impl" / f).read_text() for f in ("triggers.py", "loops.py")}

MUTANTS = [
    ("T01", "triggers.py", "an unchanged slice is reported FIRED",
     [('    return ("FIRED", "changed: " + ", ".join(changed)) if changed else ("NOT_FIRED", "unchanged")',
       '    return ("FIRED", "changed: none")')]),
    ("T02", "triggers.py", "any change in the commit fires, not only the slice",
     [('    changed = [p for p in base["selector"] if cur["entries"][p] != base["entries"][p]]',
       '    changed = [p for p in base["selector"] if cur["entries"][p] != base["entries"][p]] or '
       '(["(commit)"] if _git(workspace.repo, "diff", "--quiet", "HEAD~1", workspace.commit) is None else [])')]),
    ("T03", "triggers.py", "content changes are ignored",
     [('        entries[path] = {"mode": mode, "sha256": hashlib.sha256(data).hexdigest()}',
       '        entries[path] = {"mode": mode, "sha256": "0" * 64}')]),
    ("T03", "loops.py", "a fired trigger does not make reliance STALE",
     [('    if fired:\n        return dict(out, state="STALE", causes=fired)', '    if False:\n        pass')]),
    ("T05", "triggers.py", "the file mode is not part of an entry",
     [('        entries[path] = {"mode": mode, "sha256": hashlib.sha256(data).hexdigest()}',
       '        entries[path] = {"mode": "100644", "sha256": hashlib.sha256(data).hexdigest()}')]),
    ("T06", "triggers.py", "an unavailable revision reads as unchanged",
     [('    except Refusal as e:\n        return "UNEVALUABLE", str(e)\n',
       '    except Refusal as e:\n        return "NOT_FIRED", str(e)\n')]),
    ("T06", "loops.py", "an UNEVALUABLE trigger does not block eligibility",
     [('    if unknown:\n        return dict(out, state="UNASSESSED", causes=unknown)', '    if False:\n        pass')]),
    ("T07", "triggers.py", "a missing dependency reads as changed instead of UNEVALUABLE",
     [('        if not rows:\n            raise Refusal(f"missing dependency: {path}")',
       '        if not rows:\n            entries[path] = None\n            continue')]),
    ("T08", "triggers.py", "a missing baseline reads as unchanged",
     [('    if base is None:\n        return "UNEVALUABLE", "baseline manifest not in view"',
       '    if base is None:\n        return "NOT_FIRED", "baseline manifest not in view"')]),
    ("T08", "triggers.py", "no workspace reads as unchanged",
     [('    if workspace is None:\n        return "UNEVALUABLE", "no current workspace in view"',
       '    if workspace is None:\n        return "NOT_FIRED", "no current workspace in view"')]),
    ("T09", "triggers.py", "a missing duty reads as not discharged",
     [('    if d not in dispositions:\n            return "UNEVALUABLE", "duty not in view"',
       '    if d not in dispositions:\n            return "FIRED", "duty not in view"')]),
    ("T09", "triggers.py", "an open duty reads as discharged",
     [('            return "FIRED", f"duty is {disp}"', '            return "NOT_FIRED", f"duty is {disp}"')]),
    ("T10", "loops.py", "only the first trigger is kept",
     [('            r["triggers"].append({"closure": item["closure"], **item["trigger"], "result": result, "detail": detail})',
       '            if not r["triggers"]:\n                r["triggers"].append({"closure": item["closure"], **item["trigger"], "result": result, "detail": detail})')]),
    ("T11", "loops.py", "no declared triggers skips the revision basis",
     [('    if r["applicability"] != "CURRENT" and not scoped:', '    if r["applicability"] != "CURRENT" and not scoped and r["triggers"]:')]),
    ("T12", "loops.py", "an unknown use is allowed",
     [('        if use not in uses:\n            return dict(out, state="UNASSESSED", causes=[f"use {use!r} is not in the recipient profile"])',
       '        if use not in uses:\n            uses = dict(uses, **{use: {"requires_declared_triggers": False}})')]),
    ("T12", "loops.py", "a use's trigger requirement is ignored",
     [('        if uses[use]["requires_declared_triggers"] and not r["triggers"]:', '        if False:')]),
    ("T13", "loops.py", "the workspace is not part of the assessment identity",
     [('             "workspace": ws.identity() if ws is not None else None,', '             "workspace": None,')]),
    ("T13", "loops.py", "the profile is not part of the assessment identity",
     [('             "profile_sha256": hashlib.sha256(canon(profile)).hexdigest() if profile is not None else None,',
       '             "profile_sha256": None,')]),
    ("T13", "loops.py", "the current set is not part of the assessment identity",
     [('             "current": sorted(current) if current is not None else None,', '             "current": None,')]),
    ("T14", "triggers.py", "symlinks are hashed as if covered",
     [('        if mode not in FILE_MODES or kind != "blob":', '        if kind != "blob":')]),
    ("T14", "triggers.py", "unsafe paths are accepted",
     [('        if not p or p.startswith("/") or "\\\\" in p or any(x in ("", ".", "..") for x in parts):',
       '        if not p:')]),
    ("T15", "loops.py", "malformed triggers are not refused",
     [('        if "triggers" in m:\n            why = TR.triggers_problem(m["triggers"])', '        if False:\n            why = None')]),
    ("T16", "triggers.py", "a manifest mode is tested for membership before its type (S1-01)",
     [('isinstance(e["mode"], str)\n                and e["mode"] in FILE_MODES', 'e["mode"] in FILE_MODES')]),
    ("T17", "triggers.py", "any present non-discharged state fires, assessable or not (S1-02)",
     [('        if disp in KNOWN_NOT_DISCHARGED:', '        if True:')]),
    ("T18", "loops.py", "triggers on unsupported mapping shapes are accepted and dropped (S1-03)",
     [('            if m["triggers"] and (m["disposition"] not in TRIGGER_DISPOSITIONS or "instance" in m):', '            if False:')]),
    ("T15", "triggers.py", "duplicate triggers are accepted",
     [('    if len({json.dumps(t, sort_keys=True) for t in ts}) != len(ts):\n        return "duplicate trigger"\n', '')]),
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
        res = Path(tmp) / "results.json"
        env = dict(os.environ, TRIGGERS_IMPL=tmp, TRIGGERS_RESULTS=str(res))
        subprocess.run([sys.executable, str(ROOT / "tests" / "triggers_test.py")], env=env,
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
    print(f"TRIGGER MUTANTS: {killed}/{len(MUTANTS)} killed on target")
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
