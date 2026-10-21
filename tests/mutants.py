#!/usr/bin/env python3
"""Each mutant undoes one critical rule of the package and must make ITS case fail.

    python3 tests/mutants.py [ID ...]

KILLED only when a target case fails. A mutant that fails other cases only is
OFF_TARGET, one that fails nothing SURVIVED, one whose test run produced no
results CRASH, one whose text is not found exactly once BAD_MUTANT. Only KILLED
counts; the exit status is 0 only if every mutant is KILLED."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "warrant"

# (id, file, what the mutant breaks, [(old, new)], test file, target case ids)
MUTANTS = [
    ("M01", "engine.py", "a closure is judged against the final holder, not the holder at its position",
     [('    holder, delegates = holders.at(view.pos(t_id))\n    if filer != holder',
       '    holder, delegates = holders.at((float("inf"), ""))\n    if filer != holder')], "contract_test", ["H1", "H2"]),
    ("M02", "engine.py", "a transfer takes effect at its filing, not at its last consent",
     [('    return (None, missing) if missing else (pos, None)', '    return (None, missing) if missing else (view.pos(t_id), None)')],
     "contract_test", ["H4"]),
    ("M03", "engine.py", "anyone may transfer a duty",
     [('    if t["actor"] != h_file:\n', '    if False:\n')], "contract_test", ["U2"]),
    ("M04", "engine.py", "admission position ignores late acceptances (RV-01)",
     [('    for actor in d["accept_by"]:\n        if actor not in got:\n            return None\n        pos = max(pos, got[actor])',
       '    for actor in d["accept_by"]:\n        if actor not in got:\n            return None')], "contract_test", ["O1"]),
    ("M05", "engine.py", "an acceptance of another evidence set counts",
     [('b["item"] == index and sorted(b["evidence"]) == want:', 'b["item"] == index:')], "contract_test", ["X1"]),
    ("M06", "engine.py", "an acceptance of another item counts",
     [('if b["transition"] == t_id and b["item"] == index and', 'if b["transition"] == t_id and')], "contract_test", ["X1"]),
    ("M07", "engine.py", "named required children are not checked",
     [('    unmet = [c for c in d["requires"] if done.get(c) != "DISCHARGED"] if m["act"] in ("discharge", "revalidate") else []', '    unmet = []')], "contract_test", ["G1"]),
    ("M08", "records.py", "an attestation may be accepted by its own holder",
     [('        _need(set(b["accept_by"]) - {b["holder"]}, ', '        _need(True, ')], "contract_test", ["A3"]),
    ("M09", "engine.py", "a child grant may exceed its parent's delegable acts",
     [('    if not set(g["acts"]) <= set(p["delegable"]):\n        return "acts the parent did not make delegable"\n', '')],
     "contract_test", ["U4"]),
    ("M10", "engine.py", "any grant root is accepted",
     [('if gid in view.profile["grant_roots"] else', 'if True else')], "contract_test", ["U5"]),
    ("M11", "engine.py", "any authenticated actor may release",
     [('    if t["actor"] in set(d["owed_to"]) | set(d["release_by"]):', '    if True:')], "contract_test", ["U1"]),
    ("M12", "engine.py", "an UNEVALUABLE trigger does not block reliance",
     [('    unknown = [f"{t[\'kind\']}: {t[\'detail\']}" for t in cur if t["result"] == "UNEVALUABLE"]',
       '    unknown = []')], "contract_test", ["N1"]),
    ("M13", "engine.py", "a use that requires triggers is served by none",
     [('    if use_need and not cur:', '    if False:')], "contract_test", ["N2"]),
    ("M14", "engine.py", "no revision basis is needed",
     [('    if any(s in current for s in subjects):\n        return True', '    if True:\n        return True')], "contract_test", ["N3"]),
    ("M15", "engine.py", "an unaccepted transition supersedes",
     [('            elif out[t_id]["accepted"]:', '            else:')], "contract_test", ["S2"]),
    ("M16", "store.py", "the snapshot digest depends on the directory",
     [('        self.digest = C.digest("\\n".join(listing).encode())', '        self.digest = C.digest("\\n".join(listing).encode() + str(id(self)).encode())')],
     "contract_test", ["I1"]),
    ("M17", "engine.py", "the profile is not part of the assessment identity",
     [('"profile": C.doc_id(prof), ', '')], "contract_test", ["I1"]),
    ("M18", "engine.py", "a key bound to another actor authenticates",
     [], "contract_test", ["N5"]),
    ("M19", "compute.py", "a replay of another answer closes the condition",
     [('    if r["result"] != condition["expect"]:\n', '    if False:\n')], "compute_test", ["C2"]),
    ("M20", "compute.py", "a translation target the recipient did not accept counts",
     [('    if doc["target"] not in targets:\n        return None, f"a translation into {doc[\'target\']!r} is not accepted by this recipient"\n    if doc["lost"]:\n        return None, "the receipt',
       '    if doc["lost"]:\n        return None, "the receipt')], "compute_test", ["C3"]),
    ("M21", "compute.py", "the receipt's claim is believed",
     [('    if r["result"] != doc["claimed"]:\n', '    if False:\n')], "compute_test", ["C4"]),
    ("M22", "engine.py", "a provider the recipient did not accept is used",
     [('    if view.provider.id not in view.profile["providers"]:', '    if False:')], "compute_test", ["C11"]),
    ("M33", "compute.py", "the provider runs the files on disk, not the captured bytes",
     [("        req = {\"order\": list(MODULES), \"modules\": {n: base64.b64encode(self.sources[n]).decode() for n in MODULES},",
       "        req = {\"order\": list(MODULES), \"modules\": {n: base64.b64encode((Path(self.where) / f\"{n}.py\").read_bytes()).decode() for n in MODULES},")],
     "compute_test", ["C10"]),
    ("M23", "engine.py", "a computation may be closed on the filer's word",
     [('    if basis != BASIS_OF[kind]:', '    if basis != BASIS_OF[kind] and kind != "compute":'),
      ('    if kind == "attest":\n        return V("ADMITTED", label=f"ATTESTED:{filer}")',
       '    if kind == "attest" or basis == "ATTESTED":\n        return V("ADMITTED", label=f"ATTESTED:{filer}")')],
     "compute_test", ["C5"]),
    ("M24", "engine.py", "the filer may observe its own closure",
     [('        elif rec["actor"] == filer:\n', '        elif False:\n')], "conditions_test", ["B3"]),
    ("M25", "engine.py", "an observed condition is met by the filer's word",
     [('    if basis != BASIS_OF[kind]:', '    if basis != BASIS_OF[kind] and kind != "observe":'),
      ('    if kind == "attest":\n        return V("ADMITTED", label=f"ATTESTED:{filer}")',
       '    if kind == "attest" or basis == "ATTESTED":\n        return V("ADMITTED", label=f"ATTESTED:{filer}")')], "conditions_test", ["B1"]),
    ("M26", "engine.py", "freshness is not assessed",
     [('    if rep["view"]["as_of"] - r["observed_until"] <= r["fresh_for"]:\n        return None', '    if True:\n        return None')], "conditions_test", ["B4"]),
    ("M27", "engine.py", "a period may be discharged before it starts",
     [('    if window and t["at"] < window[0]:', '    if False:')], "conditions_test", ["Q2"]),
    ("M28", "engine.py", "an observation outside the period covers it",
     [('        elif window and not (window[0] <= o["window"][0] and o["window"][1] < window[1]):', '        elif False:')],
     "conditions_test", ["Q3"]),
    ("M29", "engine.py", "any actor's challenge counts",
     [('if c["target"] in closures and c["actor"] in counts)', 'if c["target"] in closures)')], "conditions_test", ["K2"]),
    ("M30", "engine.py", "a superseded closure still carries its challenges",
     [('    yield _challenged(rep, _counting_challenges(rep, set(r["current_closures"]), r))', '    yield _challenged(rep, _counting_challenges(rep, set(r["closed_by"]), r))')],
     "conditions_test", ["K3"]),
    ("M31", "engine.py", "freshness counts any observation cited by a closure (R138-01)",
     [('           for end in view.matched.get((tid, t["body"]["closes"].index(m)), [])]',
       '           for h in m["evidence"] if h in view.by_type["observation"]\n           for end in [view.by_type["observation"][h]["body"]["window"][1]]]')],
     "conditions_test", ["B5"]),
    ("M32", "store.py", "signature members are used before their types are checked (R138-02)",
     [('        R._hex(env["sig"]["key"], "sig key")            # types before lookup (R138-02)\n', '')],
     "contract_test", ["N6"]),
    ("M34", "cli.py", "`warrant file` files the body as given, without its structural members",
     [('    body = fill(a.type, _read_json(a.body))', '    body = _read_json(a.body)')], "cli_test", ["F1", "T1"]),
    ("M35", "cli.py", "a transition's evidence is not derived from its items",
     [('    if rtype == "transition" and "evidence" not in body and', '    if False and')], "cli_test", ["T1"]),
    ("M36", "engine.py", "a closure waiting for acceptance is shown as work to do",
     [("        need = f\"awaiting acceptance by {', '.join(waiting)}\" if waiting else \"close\"", '        need = "close"')],
     "contract_test", ["F1"]),
    ("M37", "engine.py", "actors without a key are not reported",
     [('            "unbound_actors": sorted(named - bound),', '            "unbound_actors": [],')], "contract_test", ["F2"]),
    ("M38", "compute.py", "the provider keeps the caller's dict (W140-01)",
     [("        self.sources = types.MappingProxyType(own)", "        self.sources = sources")], "compute_test", ["C14"]),
    ("M39", "engine.py", "superseded closures are still offered for acceptance",
     [('and actor in (c.get("waiting_for") or []) and not replaced:', 'and actor in (c.get("waiting_for") or []):')],
     "contract_test", ["F3"]),
    ("M40", "engine.py", "results supersession alone hides a pending closure (W141-01)",
     [('        replaced = set(rep["results"].get(c["transition"], {}).get("superseded_by", [])) & closed_by_admitted',
       '        replaced = set(rep["results"].get(c["transition"], {}).get("superseded_by", []))')],
     "contract_test", ["F4"]),
    ("M41", "compute.py", "an environment is addressed by Warrant's own manifest, not Sigma's environment_id",
     [('    return {"schema": ENV_SCHEMA, "hashes": sorted(set(hashes))}', '    return {"hashes": sorted(set(hashes)), "schema": "warrant"}')],
     "compute_test", ["C15"]),
    ("M42", "engine.py", "an acceptor is told its accept is the last one whoever else is still missing",
     [('"last_acceptance": c["waiting_for"] == [actor]}', '"last_acceptance": True}')], "contract_test", ["F5"]),
    ("M44", "compute.py", "a cached replay stands in for bytes the view lacks",
     [('    complete = cache is not None and all(h in blobs for h in hashes)', '    complete = cache is not None')],
     "compute_test", ["C17"]),
    ("M45", "compute.py", "the replay cache ignores the provider identity",
     [('    FIELDS = ("provider", "runtime", "input", "environment", "checkpoint", "state")',
       '    FIELDS = ("runtime", "input", "environment", "checkpoint", "state")'),
      ('        return self.root / fields["provider"] / (self.key_of(fields) + ".json")',
       '        return self.root / (self.key_of(fields) + ".json")')], "compute_test", ["C18"]),
    ("M46", "engine.py", "requires are followed by recursion, as at b64c007 (Codex F1)",
     [("""        busy = {root}
        stack = [(root, iter(view.duties[root]["body"]["requires"]))]
        while stack:
            did, children = stack[-1]
            for c in children:
                if c in view.duties and c not in report and c not in busy:
                    busy.add(c)
                    stack.append((c, iter(view.duties[c]["body"]["requires"])))
                    break
            else:
                stack.pop()
                busy.discard(did)
                report[did] = _assess_duty(view, did, view.duties[did], done)
                done[did] = report[did]["disposition"]
    return report""", """        _visit(view, root, report, done, set())
    return report


def _visit(view, did, report, done, busy):
    if did in report or did in busy:
        return
    busy.add(did)
    for c in view.duties[did]["body"]["requires"]:
        if c in view.duties:
            _visit(view, c, report, done, busy)
    report[did] = _assess_duty(view, did, view.duties[did], done)
    done[did] = report[did]["disposition"]
    busy.discard(did)""")], "contract_test", ["D2"]),
    ("M47", "engine.py", "the requires traversal stops descending at a fixed depth",
     [('                if c in view.duties and c not in report and c not in busy:',
       '                if c in view.duties and c not in report and c not in busy and len(stack) < 500:')],
     "contract_test", ["D3"]),
    ("M48", "engine.py", "a scheduled duty's periods are not bounded (Codex F2)",
     [('            L.admit(lim, "duty_periods", n)\n', '')], "contract_test", ["L1"]),
    ("M49", "engine.py", "the periods of a whole report are not bounded",
     [('    L.admit(lim, "report_periods", total)\n', '')], "contract_test", ["L2"]),
    ("M50", "engine.py", "the requires traversal's work is not bounded",
     [('    L.admit(lim, "requires_edges", sum(len(r["body"]["requires"]) for r in view.duties.values()))\n', '')],
     "contract_test", ["L6"]),
    ("M51", "store.py", "a store is read whole whatever its total size (Codex F2)",
     [('                    L.admit(lim, "snapshot_bytes", size + p.stat().st_size)\n', ''),
      ('                    L.admit(lim, "snapshot_bytes", size)\n', '')], "contract_test", ["L3"]),
    ("M52", "store.py", "a file is read before its size is admitted",
     [('                    L.admit(lim, "snapshot_bytes", size + p.stat().st_size)\n', '')], "contract_test", ["L4"]),
    ("M53", "engine.py", "an in-memory snapshot is assessed whatever its size",
     [('    snapshot.admit(lim)\n', '')], "contract_test", ["L3", "L5"]),
    ("M54", "store.py", "the files of a store are not counted",
     [('                L.admit(lim, f"snapshot_{kind}", len(entries))\n', '')], "contract_test", ["L5"]),
    ("M55", "cli.py", "an admission limit escapes the command as a traceback",
     [('    except L.LimitExceeded as e:\n', '    except KeyboardInterrupt as e:\n')], "cli_test", ["L1"]),
    ("M43", "engine.py", "a duty capsule does not say whose acceptance a closure waits for",
     [('                   waiting_for=sorted({a for c in r["candidates"] if c["verdict"] == "PENDING"',
       '                   waiting_for=sorted({a for c in [] if c["verdict"] == "PENDING"')], "contract_test", ["F5"]),
]
# M18 edits store.py instead: authenticity must check the key's actor.
MUTANTS[17] = ("M18", "store.py", "a key bound to another actor authenticates",
               [('    if bound[0] != rec["actor"]:\n', '    if False:\n')], "contract_test", ["N5"])


def run_one(mid, fname, what, edits, test, targets):
    tmp = Path(tempfile.mkdtemp(prefix=f"warrant-{mid}-"))
    try:
        shutil.copytree(PKG, tmp / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
        p = tmp / "warrant" / fname
        src = p.read_text()
        for old, new in edits:
            if src.count(old) != 1:
                return "BAD_MUTANT", f"{old[:50]!r} found {src.count(old)} times"
            src = src.replace(old, new)
        p.write_text(src)
        res = tmp / "results.json"
        env = dict(os.environ, WARRANT_IMPL=str(tmp), WARRANT_RESULTS=str(res))
        subprocess.run([sys.executable, str(ROOT / "tests" / f"{test}.py")], env=env, capture_output=True,
                       cwd=ROOT / "tests", timeout=900, check=False)
        if not res.exists():
            return "CRASH", "no results"
        results = json.loads(res.read_text())
        failed = sorted(k for k, v in results.items() if v == "FAIL")
        if set(failed) & set(targets):
            return "KILLED", ",".join(failed)
        return ("OFF_TARGET", ",".join(failed)) if failed else ("SURVIVED", "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    pick = set(sys.argv[1:])
    killed = total = 0
    for m in MUTANTS:
        if pick and m[0] not in pick:
            continue
        total += 1
        outcome, detail = run_one(*m)
        killed += outcome == "KILLED"
        print(f"{outcome:<11} {m[0]} {m[1]}: {m[2]}  [{detail}]", flush=True)
    print(f"MUTANTS: {killed}/{total} killed on target")
    return 0 if killed == total else 1


if __name__ == "__main__":
    sys.exit(main())
