#!/usr/bin/env python3
"""Each mutant undoes one critical rule of the package and must make ITS case fail.

    python3 tests/mutants.py [--jobs N] [ID ...]
    python3 tests/mutants.py --matrix FILE [--matrix-tests own|all|T1,T2] [--jobs N] [ID ...]
    python3 tests/mutants.py --shard K/N --matrix FILE [--jobs N]
    python3 tests/mutants.py --merge OUT FILE ...   # the parts of a sharded run, checked
    python3 tests/mutants.py --selftest     # the runner itself against fixture runners

--matrix FILE also writes, for every mutant, every case of every test file it ran
under that mutant with its result (PASS/FAIL), so `tools/claims.py audit` can ask
which cases notice a mutant besides its targets. By default each mutant runs its
own test file only (what the verdict needs, so the matrix costs no extra run);
--matrix-tests all runs every tests/*_test.py under every mutant, T1,T2 names
test files (without .py). The verdict is always taken from the own test file.

--shard K/N runs part K of a partition of all the mutants (shards(): by id, test file and
measured cost); --merge OUT joins the parts' matrices into one and refuses unless every
mutant of the list was run in exactly one of them and killed on target (see merge()).

Before any mutant, every test file the selected mutants target runs once unmutated, in the
copy the mutants use; a target case that fails there refuses the whole run as BASELINE_RED
(exit 2), since every mutant on it would read KILLED.

KILLED only when a target case fails. A mutant that fails other cases only is
OFF_TARGET, one that fails nothing SURVIVED, one whose test run produced no
results CRASH, one whose text is not found exactly once BAD_MUTANT. Only KILLED
counts; the exit status is 0 only if every mutant is KILLED."""
import collections
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
     [('    holder, delegates = holders.at(view.pos(t_id), t_id)\n    if filer != holder',
       '    holder, delegates = holders.at(NEVER)\n    if filer != holder')], "contract_test", ["H1", "H2"]),
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
     [('    if t["actor"] in d["owed_to"]:\n', '    return V("ADMITTED", label=f"RELEASE:{t[\'actor\']}")\n    if t["actor"] in d["owed_to"]:\n')],
     "contract_test", ["U1"]),
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
     [('        counted = c["actor"] in counts', '        counted = True')], "conditions_test", ["K2"]),
    ("M30", "engine.py", "a superseded closure still carries its challenges",
     [('    yield _challenged(rep, _counting_challenges(rep, {tuple(x) for x in r["current_items"]}, r))',
       '    yield _challenged(rep, _counting_challenges(rep, {(c["transition"], c["item"]) for c in r["candidates"]\n'
       '                                                      if c["verdict"] == "ADMITTED"}, r))')],
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
     [('    replaced_by_admitted = {old for t in closed_by_admitted for old in rep["results"][t]["supersedes"]}',
       '    replaced_by_admitted = {old for t in rep["results"] for old in rep["results"][t]["supersedes"]}')],
     "contract_test", ["F4"]),
    ("M41", "compute.py", "an environment is addressed by Warrant's own manifest, not Sigma's environment_id",
     [('    return {"schema": ENV_SCHEMA, "hashes": sorted(set(hashes))}', '    return {"hashes": sorted(set(hashes)), "schema": "warrant"}')],
     "compute_test", ["C15"]),
    ("M42", "engine.py", "an acceptor is told its accept is the last one whoever else is still missing",
     [('"last_acceptance": all(actor in g for g in c["awaiting"])}', '"last_acceptance": True}')], "contract_test", ["F5"]),
    ("M56", "engine.py", "an evidence-weighted challenge still needs a listed challenger",
     [('        weighted = bool(c.get("counter_observation"))', '        weighted = False')], "conditions_test", ["K4"]),
    ("M57", "engine.py", "any cited observation is counter-evidence, whatever its probe or result",
     [('        if o["probe"] != cond["probe"] or o["result"] == cond["expect"]:\n            continue\n', '')],
     "conditions_test", ["K5"]),
    ("M58", "engine.py", "a counter-observation older than the one that met the condition counts",
     [('        if latest is not None and o["window"][1] < latest:\n            continue\n', '')],
     "conditions_test", ["K5"]),
    ("M59", "engine.py", "an attested closure admits counter-evidence: any observation of another result counts against it",
     [('    if d is None or "observe" not in d["body"]["condition"]:\n        return None\n    cond = d["body"]["condition"]["observe"]',
       '    if d is None:\n        return None\n    cond = d["body"]["condition"].get("observe")'),
      ('        if o["probe"] != cond["probe"] or o["result"] == cond["expect"]:',
       '        if cond and (o["probe"] != cond["probe"] or o["result"] == cond["expect"]):')], "conditions_test", ["K5"]),
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
    # M60-M89 burn the witnesses of SPEC §4.1-§4.4 sentences that had no mutant before the
    # claim records (.warrant/store, tools/claims.py; SPEC-CLAIMS.md is their view).
    ("M60", "engine.py", "transfers are applied in filing order, not in order of effect position",
     [('in sorted(transfers, key=lambda x: (x[0], view.pos(x[1]), x[3])):', 'in sorted(transfers, key=lambda x: (view.pos(x[1]), x[3])):')],
     "assessment_test", ["R1"]),
    ("M61", "engine.py", "the filer need not hold the duty when its transfer takes effect",
     [('    if h_eff != t["actor"]:\n', '    if False:\n')], "assessment_test", ["R1"]),
    ("M62", "engine.py", "a transfer takes effect without the acceptance of `to`",
     [('    if m["to"] not in got:\n        missing.append([m["to"]])\n    else:\n        pos = max(pos, got[m["to"]])',
       '    if m["to"] in got:\n        pos = max(pos, got[m["to"]])')], "assessment_test", ["R2"]),
    ("M63", "engine.py", "a substitution needs no consent from owed_to or release_by",
     [('    if m["act"] == "substitute":\n        creditors', '    if False:\n        creditors')], "assessment_test", ["R2"]),
    ("M64", "engine.py", "an actor named in owed_to may close the duty",
     [('    if filer != holder and filer not in delegates:', '    if filer != holder and filer not in delegates and filer not in d["owed_to"]:')],
     "assessment_test", ["R3"]),
    ("M65", "engine.py", "evidence that does not resolve in the view is not checked",
     [('        if not all(view.resolves(h) for h in m["evidence"]):', '        if False:')], "assessment_test", ["R4"]),
    ("M66", "store.py", "a blob file counts under its name whatever its bytes",
     [('if kind == "blobs" and key != C.digest(data):', 'if False:')], "assessment_test", ["R4"]),
    ("M67", "engine.py", "an attest condition is met by any basis",
     [('    if basis != BASIS_OF[kind]:', '    if basis != BASIS_OF[kind] and kind != "attest":')], "assessment_test", ["R5"]),
    ("M68", "engine.py", "a revalidation may name closures of another duty",
     [('    if m["act"] == "revalidate" and not set(m["revalidates"]) <= set(admitted):\n'
       '        return "revalidates something that is not an admitted closure of this duty"\n', '')],
     "assessment_test", ["R6"]),
    ("M69", "engine.py", "a revalidation need not be admitted after what it revalidates",
     [('    late = [x for x in m["revalidates"] if admitted[x] >= mine]', '    late = []')], "contract_test", ["O1"]),
    ("M70", "engine.py", "an attested impossibility needs no owed_to acceptance",
     [('    if m["act"] == "impossible" and label.startswith("ATTESTED") and not set(d["owed_to"]) & got:', '    if False:')],
     "assessment_test", ["R7"]),
    ("M71", "engine.py", "an impossibility is admitted on any basis",
     [('label=f"ATTESTED:{filer}") if basis == "ATTESTED" else \\', 'label=f"ATTESTED:{filer}") if True else \\')],
     "assessment_test", ["R7"]),
    ("M72", "compute.py", "a cycle witness counts without the provider proving it",
     [('    if out.get("code") != "CYCLE_PROVEN":', '    if False:')], "compute_test", ["C8"]),
    ("M73", "engine.py", "impossible and revalidate are accepted for a scheduled duty",
     [('    if m["act"] in ("impossible", "revalidate") and sched is not None:', '    if False:')], "assessment_test", ["R8"]),
    ("M74", "engine.py", "a released scheduled duty stays SCHEDULED",
     [('        out["disposition"] = "RELEASED" if "RELEASED" in kinds else "SCHEDULED"', '        out["disposition"] = "SCHEDULED"')],
     "assessment_test", ["R8"]),
    ("M75", "engine.py", "admitted closures that disagree are not CONTESTED",
     [('    if len(kinds) > 1:', '    if False:')], "assessment_test", ["R9"]),
    ("M76", "engine.py", "reliance does not report a CONTESTED duty as CONTESTED",
     [('    yield ("CONTESTED", []) if r["disposition"] == "CONTESTED" else None', '    yield None')], "assessment_test", ["R9"]),
    ("M77", "engine.py", "an absent target reads as NOT_CLOSED, not MISSING",
     [('        return dict(out, state="MISSING")', '        return dict(out, state="NOT_CLOSED")')], "assessment_test", ["R9"]),
    ("M78", "engine.py", "an open duty reads as UNASSESSED, not NOT_CLOSED",
     [('    yield ("NOT_CLOSED", [f"disposition {r[\'disposition\']}"]) if', '    yield ("UNASSESSED", [f"disposition {r[\'disposition\']}"]) if')],
     "assessment_test", ["R9"]),
    ("M79", "engine.py", "a use the profile does not name is assessed",
     [('    return None if use in rep["profile"]["uses"] else', '    return None if True else')], "assessment_test", ["R10"]),
    ("M80", "engine.py", "a revalidation erases the closures it names from closed_by",
     [('    out["closed_by"] = [c[1] for c in closures]\n',
       '    out["closed_by"] = [c[1] for c in closures if c[1] not in {x for r in revals for x in r[2]["revalidates"]}]\n')],
     "assessment_test", ["R11"]),
    ("M81", "engine.py", "a fired trigger reopens the duty",
     [('            r["trigger_coverage"] = "NONE_DECLARED" if not cur else',
       '            r["disposition"] = "OPEN" if any(t["result"] == "FIRED" for t in cur) else r["disposition"]\n'
       '            r["trigger_coverage"] = "NONE_DECLARED" if not cur else')], "contract_test", ["O1"]),
    ("M82", "engine.py", "a challenge reopens the duty whose closure it targets",
     [('    challenges = _challenges(view, results)\n',
       '    challenges = _challenges(view, results)\n    for c in challenges.values():\n        for r in duties.values():\n'
       '            if c["target"] in r["closed_by"]:\n                r["disposition"] = "OPEN"\n')], "conditions_test", ["K1"]),
    ("M83", "engine.py", "a revalidated closure's triggers leave the report",
     [('                                for tid, _, m in rows for tr in m.get("triggers", [])]',
       '                                for tid, _, m in rows if tid not in superseded for tr in m.get("triggers", [])]')],
     "assessment_test", ["R12"]),
    ("M84", "engine.py", "an ended uncovered period is OPEN, not LAPSED",
     [('{"state": "LAPSED" if end <= view.as_of else "OPEN"}', '{"state": "OPEN"}')], "conditions_test", ["Q1"]),
    ("M85", "engine.py", "a discharge of one period covers every period",
     [('        if n in periods:\n            report[str(n)] = {"state": "COVERED", "by": periods[n][0], "basis": periods[n][1]}',
       '        if periods:\n            report[str(n)] = {"state": "COVERED", "by": next(iter(periods.values()))[0], "basis": "any"}')],
     "conditions_test", ["Q1"]),
    ("M86", "engine.py", "a pending closure closes the duty",
     [('        if verdict != "ADMITTED":\n            continue', '        if verdict not in ("ADMITTED", "PENDING"):\n            continue\n        label = label or verdict')],
     "assessment_test", ["R13"]),
    ("M87", "engine.py", "an observation by an actor not named in observers meets the condition",
     [('        if rec["actor"] not in cond["observers"]:', '        if False:')], "conditions_test", ["B2a"]),
    ("M88", "engine.py", "an observation with another probe meets the condition",
     [('        elif o["probe"] != cond["probe"]:', '        elif False:')], "conditions_test", ["B2b"]),
    ("M89", "engine.py", "an observation of another result meets the condition",
     [('        elif o["result"] != cond["expect"]:', '        elif False:')], "conditions_test", ["B2c"]),
    # M90-M120 burn the witnesses of SPEC §4.5-§6 sentences (pilot W2: claims SPEC-4.5-1 to SPEC-6-5).
    ("M90", "engine.py", "a grant authorizes acts filed before the grant itself",
     [('    if view.pos(gid) > pos:\n        return "NOT_YET", "granted after this position"\n', '')], "assessment_test", ["R14"]),
    ("M91", "engine.py", "a grant never expires",
     [('    if g["expires"] is not None and pos[0] >= g["expires"]:\n        return "EXPIRED", f"expired at {g[\'expires\']}"\n', '')],
     "assessment_test", ["R15"]),
    ("M92", "engine.py", "a parent grant is judged at the act's position, not at its child's",
     [('    pst, why = grant_state(view, g["parent"], view.pos(gid), depth + 1)', '    pst, why = grant_state(view, g["parent"], pos, depth + 1)')],
     "assessment_test", ["R16"]),
    ("M93", "engine.py", "anyone may attenuate a grant, not only its grantee",
     [('    if grantor != p["grantee"]:\n        return "the grantor is not the parent\'s grantee"\n', '')], "assessment_test", ["R17"]),
    ("M94", "engine.py", "a child grant may name duties its parent does not",
     [('    if not set(g["duties"]) <= set(p["duties"]):\n        return "duties beyond the parent\'s"\n', '')], "assessment_test", ["R17"]),
    ("M95", "engine.py", "a child grant may outlive its parent",
     [('    if p["expires"] is not None and (g["expires"] is None or g["expires"] > p["expires"]):\n'
       '        return "expires later than the parent"\n', '')], "assessment_test", ["R17"]),
    ("M96", "store.py", "a grant signed by a key bound to another actor counts as its grantor's",
     [('    if bound[0] != rec["actor"]:\n', '    if bound[0] != rec["actor"] and rec["type"] != "grant":\n')],
     "assessment_test", ["R18"]),
    ("M97", "engine.py", "anyone's acceptance closes a transition's results",
     [('"accepted": bool(need) and need <= set(got),', '"accepted": bool(got),')], "assessment_test", ["R19"]),
    ("M98", "engine.py", "the duty's owed_to actors do not count as challengers",
     [('        counts |= set(duty["owed_to"]) | set(duty["accept_by"])', '        counts |= set(duty["accept_by"])')],
     "assessment_test", ["R20"]),
    ("M99", "engine.py", "the duty's accept_by actors do not count as challengers",
     [('        counts |= set(duty["owed_to"]) | set(duty["accept_by"])', '        counts |= set(duty["owed_to"])')],
     "assessment_test", ["R20"]),
    ("M100", "engine.py", "a transition's supersedes is not read",
     [('        for old in t["body"]["supersedes"]:\n            if old not in out:',
       '        for old in []:\n            if old not in out:')], "contract_test", ["S1"]),
    ("M101", "engine.py", "reliance on superseded results is not SUPERSEDED",
     [('    yield ("SUPERSEDED", [f"superseded by {\', \'.join(x[:12] for x in r[\'superseded_by\'])}"]) if r["superseded_by"] else None',
       '    yield None')], "contract_test", ["S1"]),
    ("M102", "engine.py", "superseded results lose their acceptance",
     [('                out[old]["superseded_by"].append(t_id)\n',
       '                out[old]["superseded_by"].append(t_id)\n                out[old]["accepted"] = False\n')],
     "contract_test", ["S1"]),
    ("M103", "engine.py", "a supersession lapses once its superseding transition is itself superseded (A returns)",
     [('                out[old]["superseded_by"].append(t_id)\n    return out\n',
       '                out[old]["superseded_by"].append(t_id)\n'
       '    for r in out.values():\n        r["superseded_by"] = [x for x in r["superseded_by"] if not out[x]["superseded_by"]]\n'
       '    return out\n')], "assessment_test", ["R21"]),
    ("M104", "engine.py", "a supersession of a transition not in the view is not reported missing",
     [('            if old not in out:\n                view.missing.add(old)', '            if old not in out:\n                pass')],
     "contract_test", ["S3"]),
    ("M105", "triggers.py", "a duty state the trigger does not name is passed through as its result",
     [('        return "UNEVALUABLE", f"duty state not assessable here: {disp}"', '        return disp, f"duty state not assessable here: {disp}"')],
     "assessment_test", ["R22"]),
    ("M106", "triggers.py", "an unsorted selector is evaluated",
     [('    if sel != sorted(set(sel)):\n        return "selector must be sorted and without duplicates"\n', ''),
      ('    if not (isinstance(ents, dict) and sorted(ents) == doc["selector"]):',
       '    if not (isinstance(ents, dict) and sorted(ents) == sorted(doc["selector"])):')], "assessment_test", ["R23"]),
    ("M107", "triggers.py", "a directory path is read as the first file under it",
     [('        if len(rows) != 1 or not exact:\n            raise Refusal(f"unsupported input (directory): {path}")\n'
       '        mode, kind, oid = exact[0].split("\\t", 1)[0].split(" ")',
       '        mode, kind, oid = rows[0].split("\\t", 1)[0].split(" ")')], "assessment_test", ["R23"]),
    ("M108", "triggers.py", "a symlink or submodule entry is read like a file",
     [('        if mode not in FILE_MODES or kind != "blob":\n            raise Refusal(f"unsupported input (mode {mode}): {path}")\n', '')],
     "assessment_test", ["R23"]),
    ("M109", "triggers.py", "a changed file mode does not fire",
     [('    changed = [p for p in base["selector"] if cur["entries"][p] != base["entries"][p]]',
       '    changed = [p for p in base["selector"] if cur["entries"][p]["sha256"] != base["entries"][p]["sha256"]]')],
     "assessment_test", ["R24"]),
    ("M110", "triggers.py", "subject_changed never fires",
     [('    changed = [p for p in base["selector"] if cur["entries"][p] != base["entries"][p]]', '    changed = []')],
     "assessment_test", ["R24"]),
    ("M111", "triggers.py", "a missing workspace reads as NOT_FIRED",
     [('        return "UNEVALUABLE", "no current workspace in view"', '        return "NOT_FIRED", "no current workspace in view"')],
     "assessment_test", ["R24"]),
    ("M112", "triggers.py", "a revision or path that cannot be read reads as NOT_FIRED",
     [('    except Refusal as e:\n        return "UNEVALUABLE", str(e)', '    except Refusal as e:\n        return "NOT_FIRED", str(e)')],
     "assessment_test", ["R24"]),
    ("M113", "triggers.py", "a baseline that is not in the view reads as NOT_FIRED",
     [('        return "UNEVALUABLE", "baseline manifest not in view"', '        return "NOT_FIRED", "baseline manifest not in view"')],
     "assessment_test", ["R24"]),
    ("M114", "triggers.py", "only an OPEN duty fires duty_not_discharged",
     [('KNOWN_NOT_DISCHARGED = ("OPEN", "RELEASED", "IMPOSSIBLE")', 'KNOWN_NOT_DISCHARGED = ("OPEN",)')],
     "assessment_test", ["R25"]),
    ("M115", "triggers.py", "a duty state the trigger does not name reads as NOT_FIRED",
     [('        return "UNEVALUABLE", f"duty state not assessable here: {disp}"', '        return "NOT_FIRED", f"duty state not assessable here: {disp}"')],
     "assessment_test", ["R25"]),
    ("M116", "engine.py", "release_by does not authorize a release",
     [('    if t["actor"] in d["release_by"]:', '    if False:')], "assessment_test", ["R26"]),
    ("M117", "engine.py", "any actor's acceptance stands for the duty's accept_by",
     [('    missing = [[a] for a in sorted(set(d["accept_by"]) - got)]', '    missing = [] if got else [[a] for a in sorted(d["accept_by"])]')],
     "contract_test", ["A2"]),
    ("M118", "engine.py", "a filer's challenged record elsewhere weighs on its other closures",
     [('    yield _challenged(rep, _counting_challenges(rep, {tuple(x) for x in r["current_items"]}, r))\n',
       '    yield _challenged(rep, _counting_challenges(rep, {tuple(x) for x in r["current_items"]}, r))\n'
       '    mine = {rep["results"][x]["actor"] for x in r["current_closures"] if x in rep["results"]}\n'
       '    yield _challenged(rep, sorted(c for c, x in rep["challenges"].items()\n'
       '                                  if rep["results"].get(x["target"], {}).get("actor") in mine))\n')],
     "assessment_test", ["R27"]),
    ("M119", "engine.py", "a substitution keeps the old holder's delegates",
     [('                h, dl = (h, dl | {to}) if act == "delegate" else (to, set())',
       '                h, dl = (h, dl | {to}) if act == "delegate" else (to, dl)')], "assessment_test", ["R28"]),
    ("M120", "engine.py", "a delegate's closure is not admitted",
     [('    if filer != holder and filer not in delegates:', '    if filer != holder:')], "contract_test", ["U3"]),
    # M121-M168 burn the witnesses of SPEC §7-§9 sentences (pilot W3) and the revision
    # basis of SPEC-4.4-3 through a subject_changed trigger (R24).
    ("M121", "engine.py", "a NOT_FIRED subject_changed trigger gives no revision basis",
     [('    return any(t["kind"] == "subject_changed" and t["result"] == "NOT_FIRED" for t in triggers)', '    return False')],
     "assessment_test", ["R24"]),
    ("M122", "records.py", "the Book I runtime id is not the kernel's",
     [('RUNTIMES = ("sigma-book1-0.6.0/hash-thunk/leftmost-outermost",', 'RUNTIMES = ("sigma-book1-0.6.1/hash-thunk/leftmost-outermost",')],
     "assessment_test", ["R29"]),
    ("M123", "records.py", "the draft runtime id is not the kernel's",
     [('            "sigma-resume-draft/ski+Y+M+W/hash-thunk/leftmost-outermost")', '            "sigma-resume-draft/ski+Y+M/hash-thunk/leftmost-outermost")')],
     "assessment_test", ["R29"]),
    ("M124", "compute.py", "the provider identity is computed over another document than sigma_provider.identity_of",
     [('    doc = {"provider": "sigma-resume", "files": files}', '    doc = {"provider": "warrant", "files": files}')],
     "compute_test", ["C13"]),
    ("M125", "compute.py", "the provider is two modules, without sigma_glyph",
     [('MODULES = ("sigma_glyph", "sigma_resume", "sigma_provider")', 'MODULES = ("sigma_resume", "sigma_provider")')],
     "compute_test", ["C13"]),
    ("M126", "engine.py", "the provider is not part of the assessment identity",
     [('"provider": provider.identity if provider else None}', '"provider": None}')], "compute_test", ["C12"]),
    ("M127", "compute.py", "an answer outside the request protocol is taken",
     [('        if not (isinstance(out, dict) and out.get("sigma_provider") == PROTOCOL and ("ok" in out) != ("refused" in out)):',
       '        if not (isinstance(out, dict) and ("ok" in out) != ("refused" in out)):')], "compute_test", ["C19"]),
    ("M128", "compute.py", "the provider interpreter is not isolated (-I dropped)",
     [('[sys.executable, "-I", "-B", "-c", BOOT]', '[sys.executable, "-B", "-c", BOOT]')], "compute_test", ["C20"]),
    ("M129", "compute.py", "the provider is located by importing it into the assessing process",
     [('    spec = importlib.machinery.PathFinder.find_spec("sigma_provider", _search_path())',
       '    spec = __import__("importlib").import_module("sigma_provider").__spec__')], "compute_test", ["C21"]),
    ("M130", "engine.py", "without a provider a replay is not UNVERIFIED",
     [('        return V("UNVERIFIED", "no provider in this view")', '        return V("UNMET_CONDITION", "no provider in this view")')],
     "compute_test", ["C5"]),
    ("M131", "engine.py", "a REPLAYED item may cite more than one receipt",
     [('    if len(docs) != 1:\n        return V("MISSING_EVIDENCE", f"a REPLAYED item cites exactly one {want}")',
       '    if not docs:\n        return V("MISSING_EVIDENCE", f"a REPLAYED item cites exactly one {want}")')], "compute_test", ["C22"]),
    ("M132", "compute.py", "a receipt's member set is not checked",
     [('    if not (isinstance(doc, dict) and set(doc) == RECEIPT_FIELDS and doc["receipt"] == "sigma-resume"):',
       '    if not (isinstance(doc, dict) and doc["receipt"] == "sigma-resume"):')], "compute_test", ["C23"]),
    ("M133", "compute.py", "a receipt's hash members are checked for length only, as at 808c011 (Codex AMEND on #164)",
     [('    if not all(S.hex64(doc[k]) for k in ("input", "environment", "checkpoint", "state", "claimed")):',
       '    if not all(isinstance(doc[k], str) and len(doc[k]) == 64 for k in ("input", "environment", "checkpoint", "state", "claimed")):')],
     "compute_test", ["C23"]),
    ("M134", "compute.py", "a receipt that reports a loss counts",
     [('    if doc["lost"]:\n        return None, "the receipt reports', '    if False:\n        return None, "the receipt reports')],
     "compute_test", ["C3"]),
    ("M135", "compute.py", "a receipt for another (input, environment) counts",
     [('    if (doc["input"], doc["environment"]) != (condition["input"], condition["environment"]):\n        return None, "the receipt is for another',
       '    if False:\n        return None, "the receipt is for another')], "compute_test", ["C24"]),
    ("M136", "compute.py", "a receipt whose bytes are not in the view is replayed anyway",
     [('    if ck is None or st is None:\n        return None, "receipt bytes not in view"\n', '')], "compute_test", ["C24"]),
    ("M137", "compute.py", "a replay that did not reach a normal form is compared as an answer",
     [('    if r["code"] != "NORMAL_FORM":\n', '    if False:\n')], "compute_test", ["C4", "C29"]),
    ("M138", "compute.py", "the replay cache is never consulted",
     [('        self.hits += 1\n        return doc["result"]', '        return None')], "compute_test", ["C16"]),
    ("M139", "compute.py", "a cycle blob's member set is not checked",
     [('    if not (isinstance(doc, dict) and set(doc) == CYCLE_FIELDS and doc["cycle"] == "sigma-resume"):',
       '    if not (isinstance(doc, dict) and doc["cycle"] == "sigma-resume"):')], "compute_test", ["C25"]),
    ("M140", "compute.py", "a cycle for another (input, environment) counts",
     [('    if (doc["input"], doc["environment"]) != (condition["input"], condition["environment"]):\n        return None, "the cycle is for another',
       '    if False:\n        return None, "the cycle is for another')], "compute_test", ["C26"]),
    ("M141", "engine.py", "a provider that failed (a timeout) is an unmet condition, not UNVERIFIED",
     [('    except P.ProviderError as e:\n        return V("UNVERIFIED", str(e))', '    except P.ProviderError as e:\n        return V("UNMET_CONDITION", str(e))')],
     "compute_test", ["C27"]),
    ("M142", "engine.py", "a replay the provider could not complete is an unmet condition, not UNVERIFIED",
     [('    return V("ADMITTED", label=label) if label else V("UNVERIFIED", why)', '    return V("ADMITTED", label=label) if label else V("UNMET_CONDITION", why)')],
     "compute_test", ["C27"]),
    ("M143", "compute.py", "a kernel answer that is not a normal form reads as bytes not replayed",
     [('        return None, f"replayed, but {r[\'code\']} is not an answer"', '        return None, f"not replayed: {r[\'code\']}"')],
     "compute_test", ["C28"]),
    ("M144", "engine.py", "a duty capsule carries no evidence ids",
     [('                   evidence=sorted({h for tid in r["closed_by"] if tid in rep["results"] for h in rep["results"][tid]["evidence"]}),',
       '                   evidence=[],')], "assessment_test", ["R30"]),
    ("M145", "engine.py", "a duty capsule carries no limits",
     [('                   limits=sorted({x for tid in r["closed_by"] if tid in rep["results"] for x in rep["results"][tid]["residual"]}))',
       '                   limits=[])')], "assessment_test", ["R30"]),
    ("M146", "engine.py", "a transition capsule does not say which triggers to revisit it under",
     [('                   revalidate_when=r["triggers"], challenges=r["challenges"], evidence=r["evidence"])',
       '                   revalidate_when=[], challenges=r["challenges"], evidence=r["evidence"])')], "assessment_test", ["R30"]),
    ("M147", "engine.py", "a transition capsule does not name its challenges",
     [('                   revalidate_when=r["triggers"], challenges=r["challenges"], evidence=r["evidence"])',
       '                   revalidate_when=r["triggers"], challenges=[], evidence=r["evidence"])')], "assessment_test", ["R30"]),
    ("M148", "engine.py", "a delegate's frontier omits the duty delegated to it",
     [('    holds = actor == r["holder"] or actor in r["delegates"]', '    holds = actor == r["holder"]')],
     "assessment_test", ["R31"]),
    ("M149", "engine.py", "lapsed periods are not in the frontier",
     [('            if p["state"] in ("OPEN", "LAPSED"):', '            if p["state"] == "OPEN":')], "assessment_test", ["R31"]),
    ("M150", "engine.py", "results acceptances owed under accept_by.results are not in the frontier",
     [('    if actor in rep["profile"]["accept_by"]["results"]:', '    if False:')], "assessment_test", ["R31"]),
    ("M151", "engine.py", "a challenge against the actor's closure is not in its frontier",
     [('            if rl["state"] in ("STALE", "CHALLENGED", "UNASSESSED"):', '            if rl["state"] in ("STALE", "UNASSESSED"):')],
     "assessment_test", ["R31"]),
    ("M152", "engine.py", "unowned questions are not listed by questions()",
     [('if (owned or not q["owned"]) and', 'if (owned and not q["owned"]) and')], "contract_test", ["Q1"]),
    ("M153", "records.py", "cmd@v1 and ski@v1 conditions are approximated as attestations",
     [('    _enum(kind, ("attest", "observe", "compute"), "condition kind")\n    if kind == "attest":',
       '    _enum(kind, ("attest", "observe", "compute", "cmd@v1", "ski@v1"), "condition kind")\n    if kind in ("attest", "cmd@v1", "ski@v1"):')],
     "assessment_test", ["R32"]),
    ("M154", "records.py", "a grant may name an act other than release",
     [('GRANT_ACTS = ("release",)', 'GRANT_ACTS = ("discharge", "release")')], "assessment_test", ["R32"]),
    ("M155", "records.py", "a grant may carry a revocation member",
     [('    _fields(b, ("grantee", "acts", "delegable", "duties", "expires", "parent"), what="grant")',
       '    _fields(b, ("grantee", "acts", "delegable", "duties", "expires", "parent"), ("revoked",), what="grant")')],
     "assessment_test", ["R32"]),
    ("M156", "records.py", "a duty may carry a threshold member",
     [('                "requires", "serves", "answers", "subject"), what="duty")',
       '                "requires", "serves", "answers", "subject"), ("threshold",), what="duty")')], "assessment_test", ["R32"]),
    ("M157", "store.py", "a trust key need not be a 32-byte Ed25519 key",
     [('            R._hex(k["public"], "trust public key")', '            R._text(k["public"], "trust public key")')],
     "assessment_test", ["R32"]),
    ("M158", "store.py", "a trust key binding may carry an expiry",
     [('            R._fields(k, ("actor", "public"), what="trust key")', '            R._fields(k, ("actor", "public"), ("until",), what="trust key")')],
     "assessment_test", ["R32"]),
    ("M159", "limits.py", "a value equal to its bound is refused",
     [('    if value > limits[name]:', '    if value >= limits[name]:')], "assessment_test", ["R33"]),
    ("M160", "engine.py", "the admission limits are an operand of the assessment identity",
     [('"provider": provider.identity if provider else None}', '"provider": provider.identity if provider else None, "limits": lim}')],
     "contract_test", ["L7"]),
    ("M161", "limits.py", "snapshot_records defaults to another bound",
     [('    "snapshot_records": 100_000,', '    "snapshot_records": 99_999,')], "assessment_test", ["R34"]),
    ("M162", "limits.py", "snapshot_blobs defaults to another bound",
     [('    "snapshot_blobs": 100_000,', '    "snapshot_blobs": 99_999,')], "assessment_test", ["R34"]),
    ("M163", "limits.py", "snapshot_bytes defaults to another bound",
     [('    "snapshot_bytes": 1024 * 1024 * 1024,', '    "snapshot_bytes": 1000 * 1000 * 1000,')], "assessment_test", ["R34"]),
    ("M164", "limits.py", "requires_edges defaults to another bound",
     [('    "requires_edges": 1_000_000,', '    "requires_edges": 999_999,')], "assessment_test", ["R34"]),
    ("M165", "limits.py", "duty_periods defaults to another bound",
     [('    "duty_periods": 10_000,', '    "duty_periods": 9_999,')], "assessment_test", ["R34"]),
    ("M166", "limits.py", "report_periods defaults to another bound",
     [('    "report_periods": 100_000,', '    "report_periods": 99_999,')], "assessment_test", ["R34"]),
    ("M167", "limits.py", "the resource refusal is not a ValueError",
     [('class LimitExceeded(ValueError):', 'class LimitExceeded(Exception):')], "contract_test", ["L1"]),
    ("M168", "store.py", "a file over 64 MiB is read",
     [('    if p.stat().st_size > MAX_FILE:\n        return "larger than admitted"\n', '')], "assessment_test", ["R35"]),
    ("M169", "compute.py", "a cycle blob's hash members are checked for length only, as at 808c011 (the mirror of M133)",
     [('    if not all(S.hex64(doc[k]) for k in ("input", "environment", "witness")):',
       '    if not all(isinstance(doc[k], str) and len(doc[k]) == 64 for k in ("input", "environment", "witness")):')],
     "compute_test", ["C25"]),
    # M170-M174 restore the `$` anchors of AMEND 2 of #164: `$` matches before a final newline
    ("M170", "shapes.py", "a hex64 may end in a newline (`$` instead of \\Z in shapes.HEX64, the one definition)",
     [('HEX64 = re.compile(r"^[0-9a-f]{64}\\Z")', 'HEX64 = re.compile(r"^[0-9a-f]{64}$")')], "contract_test", ["N7"]),
    ("M171", "shapes.py", "a signature may end in a newline",
     [('HEX128 = re.compile(r"^[0-9a-f]{128}\\Z")', 'HEX128 = re.compile(r"^[0-9a-f]{128}$")')], "contract_test", ["N7"]),
    ("M172", "records.py", "a subject may end in a newline",
     [('SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\\Z")', 'SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")')],
     "contract_test", ["N7"]),
    ("M173", "shapes.py", "a question reference may end in a newline",
     [('QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})\\Z")', 'QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})$")')],
     "contract_test", ["N7"]),
    ("M174", "shapes.py", "the predicate receipt and cycle hash members use is `$`-anchored, as compute's own copy was at 1d67124",
     [('    return isinstance(v, str) and HEX64.match(v) is not None',
       '    return isinstance(v, str) and __import__("re").match(r"^[0-9a-f]{64}$", v) is not None')], "compute_test", ["C23", "C25"]),
    # M175-M259 burn the witnesses of SPEC §2-§3 sentences (pilot W4: claims SPEC-2-n to SPEC-3.6-n),
    # all in tests/records_test.py, which runs in a tenth of a second. Each one makes a refused
    # value accepted (or a listed invalid record a crash); none changes only a message.
    ("M175", "jcs.py", "integers one beyond ±(2^53-1) are admitted",
     [("        if not -MAX_INT <= v <= MAX_INT:", "        if not -MAX_INT - 1 <= v <= MAX_INT + 1:")], "records_test", ["E1"]),
    ("M176", "jcs.py", "object keys of any type are written as their text, as json.dumps does",
     [("    if not (isinstance(v, dict) and all(isinstance(k, str) for k in v)):", "    if not isinstance(v, dict):"),
      ('    keys = sorted(v, key=lambda k: k.encode("utf-16-be", "surrogatepass"))',
       '    keys = sorted(v, key=lambda k: str(k).encode("utf-16-be", "surrogatepass"))'),
      ("        _check_text(keys[i])\n", "        _check_text(str(keys[i]))\n"),
      ('("s", json.dumps(keys[i], ensure_ascii=False), 0)', '("s", json.dumps(str(keys[i]), ensure_ascii=False), 0)')],
     "records_test", ["E1"]),
    ("M177", "jcs.py", "floats are admitted, read and written",
     [("    if isinstance(v, int):\n", "    if isinstance(v, float):\n        return repr(v)\n    if isinstance(v, int):\n"),
      ("parse_constant=_constant, parse_float=_float)", "parse_constant=_constant)")], "records_test", ["E2"]),
    ("M178", "jcs.py", "lone surrogates pass through, written as WTF-8",
     [('        raise NotCanonical("lone surrogate")', "        pass"),
      ('    return "".join(out).encode("utf-8")', '    return "".join(out).encode("utf-8", "surrogatepass")')],
     "records_test", ["E3"]),
    ("M179", "records.py", "an object may carry members nobody named",
     [('    _need(not extra, f"{what} has unknown members {sorted(extra)}")', "    pass")], "records_test", ["E4"]),
    ("M180", "records.py", "a missing required member is not refused (the store then aborts, not lists it)",
     [('    _need(not missing, f"{what} lacks {sorted(missing)}")', "    pass")], "records_test", ["E4"]),
    ("M181", "records.py", "a boolean is an integer, as Python's bool is",
     [("    _need(type(v) is int and (low is None or v >= low)", "    _need(isinstance(v, int) and (low is None or v >= low)")],
     "records_test", ["E4", "E9"]),
    ("M182", "jcs.py", "members are ordered by code point, not by UTF-16 code units",
     [('    keys = sorted(v, key=lambda k: k.encode("utf-16-be", "surrogatepass"))', "    keys = sorted(v)")],
     "records_test", ["E6"]),
    ("M183", "jcs.py", "a space follows each member's colon",
     [('("s", ":", 0)', '("s", ": ", 0)')], "records_test", ["E6"]),
    ("M184", "jcs.py", "non-ASCII characters are written as \\u escapes",
     [("        return json.dumps(v, ensure_ascii=False)", "        return json.dumps(v, ensure_ascii=True)")],
     "records_test", ["E6"]),
    ("M185", "shapes.py", "a hex64 may be uppercase",
     [('HEX64 = re.compile(r"^[0-9a-f]{64}\\Z")', 'HEX64 = re.compile(r"^[0-9a-fA-F]{64}\\Z")')], "records_test", ["E7"]),
    ("M186", "shapes.py", "a hex64 digit is any Unicode digit (`\\d`)",
     [('HEX64 = re.compile(r"^[0-9a-f]{64}\\Z")', 'HEX64 = re.compile(r"^[\\da-f]{64}\\Z")')], "records_test", ["E7"]),
    ("M187", "records.py", "the record version is not checked",
     [('    _need(record["warrant"] == VERSION, "record version must be \\"2\\"")', "    pass")], "records_test", ["K1"]),
    ("M188", "records.py", "a record's id hashes non-canonical JSON (sorted keys, default separators)",
     [("    return C.doc_id(r)", '    return C.digest(__import__("json").dumps(r, sort_keys=True).encode())')],
     "records_test", ["K2"]),
    ("M189", "store.py", "a stored envelope may carry other members",
     [('R._fields(env, ("record", "sig"), what="stored record")', 'R._fields(env, ("record", "sig"), ("note",), what="stored record")')],
     "records_test", ["K3"]),
    ("M190", "store.py", "a stored signature object may carry other members",
     [('R._fields(env["sig"], ("key", "ed25519"), what="sig")', 'R._fields(env["sig"], ("key", "ed25519"), ("note",), what="sig")')],
     "records_test", ["K3"]),
    ("M191", "keys.py", "the signed message's domain has no colon",
     [('SIG_DOMAIN = b"warrant-sig-v1:"', 'SIG_DOMAIN = b"warrant-sig-v1"')], "records_test", ["K4"]),
    ("M192", "keys.py", "the signature covers the id's hex text, not its 32 raw bytes",
     [("    return SIG_DOMAIN + bytes.fromhex(record_id)", "    return SIG_DOMAIN + record_id.encode()")], "records_test", ["K4"]),
    ("M193", "keys.py", "small-order and non-canonical public keys are not rejected",
     [("    if weak_public_key(raw):\n        return False", "    if False:\n        return False")], "primitives_test", ["P-verify-sig", "P-edge"]),
    ("M194", "keys.py", "a key id hashes the key's hex text",
     [("    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()", "    return hashlib.sha256(public_hex.encode()).hexdigest()")],
     "records_test", ["K5"]),
    ("M195", "store.py", "stored bytes need not be canonical",
     [("        env = C.loads(data)", '        env = __import__("json").loads(data)')], "records_test", ["K6"]),
    ("M196", "store.py", "a record is authentic under any file name",
     [("    if R.record_id(rec) != rid:", "    if False:")], "records_test", ["K6"]),
    ("M197", "store.py", "the signature is not verified",
     [('    if not K.verify(bound[1], env["sig"]["ed25519"], K.sig_message(rid)):', "    if False:")], "records_test", ["K6"]),
    ("M198", "records.py", "a seventh type, `claim`, is read as a transition",
     [('TYPES = ("duty", "transition", "accept", "observation", "grant", "challenge")',
       'TYPES = ("duty", "transition", "accept", "observation", "grant", "challenge", "claim")'),
      ('          "grant": _grant, "challenge": _challenge}', '          "grant": _grant, "challenge": _challenge, "claim": _transition}')],
     "records_test", ["K8"]),
    ("M199", "records.py", "a body is valid when any type's shape admits it",
     [('    BODIES[record["type"]](record["body"], record["actor"])\n',
       '    errs = []\n    for f in BODIES.values():\n        try:\n            f(record["body"], record["actor"])\n            break\n'
       '        except Invalid as e:\n            errs.append(e)\n    else:\n        raise errs[0]\n')], "records_test", ["K9"]),
    ("M200", "records.py", "a record may carry a `prior` member",
     [('    _fields(record, ("warrant", "type", "actor", "at", "body"), ("prev",), what="record")',
       '    _fields(record, ("warrant", "type", "actor", "at", "body"), ("prev", "prior"), what="record")')], "records_test", ["K11"]),
    ("M201", "records.py", "a statement may have 401 code points",
     [('    _text(b["statement"], "statement", limit=400)', '    _text(b["statement"], "statement", limit=401)')],
     "records_test", ["D1"]),
    ("M202", "records.py", "a statement is measured in UTF-16 code units",
     [('    _text(b["statement"], "statement", limit=400)\n',
       '    _text(b["statement"], "statement", limit=400)\n    _need(len(b["statement"].encode("utf-16-le")) // 2 <= 400, "statement")\n')],
     "records_test", ["D1"]),
    ("M203", "records.py", "a duty may be filed by someone other than its holder",
     [('    _need(b["holder"] == actor, "a duty is filed by its holder")', "    pass")], "records_test", ["D2"]),
    ("M204", "records.py", "owed_to may be empty",
     [('    _actors(b["owed_to"], "owed_to", nonempty=True)', '    _actors(b["owed_to"], "owed_to")')], "records_test", ["D3"]),
    ("M205", "records.py", "accept_by is not checked",
     [('    _actors(b["accept_by"], "accept_by")\n', "")], "records_test", ["D4"]),
    ("M206", "records.py", "release_by is not checked",
     [('    _actors(b["release_by"], "release_by")\n', "")], "records_test", ["D5"]),
    ("M207", "engine.py", "owed_to may release only when it is also in release_by",
     [('    if t["actor"] in d["owed_to"]:\n        return V("ADMITTED", label=f"RELEASE:{t[\'actor\']}")\n', '')],
     "records_test", ["D5"]),
    ("M208", "records.py", "a condition may name several kinds; the first counts",
     [('    _need(isinstance(c, dict) and len(c) == 1, ', '    _need(isinstance(c, dict) and len(c) >= 1, ')], "records_test", ["D6"]),
    ("M209", "records.py", "attest may carry anything",
     [('        _fields(v, (), what="attest condition")', "        pass")], "records_test", ["D7"]),
    ("M210", "records.py", "an observe probe is any string",
     [('        _hex(v["probe"], "probe")', '        _text(v["probe"], "probe")')], "records_test", ["D8"]),
    ("M211", "records.py", "fresh_for may be a boolean",
     [('(type(v["fresh_for"]) is int and v["fresh_for"] > 0)', '(isinstance(v["fresh_for"], int) and v["fresh_for"] > 0)')],
     "records_test", ["D8"]),
    ("M212", "records.py", "an observe expect is not checked",
     [('        _text(v["expect"], "expect", empty=True)\n', "")], "records_test", ["D8"]),
    ("M213", "records.py", "compute hash members are checked for length only",
     [("            _hex(v[k], k)", "            _need(isinstance(v[k], str) and len(v[k]) == 64, k)")], "records_test", ["D9"]),
    ("M214", "records.py", "a schedule may repeat every 0 seconds",
     [('        _int(s["every"], "schedule.every", 1)', '        _int(s["every"], "schedule.every", 0)')], "records_test", ["D10"]),
    ("M215", "records.py", "requires names any strings",
     [('    _hexes(b["requires"], "requires")', '    _list(b["requires"], "requires", _text)')], "records_test", ["D11"]),
    ("M216", "records.py", "serves names any strings",
     [('    _hexes(b["serves"], "serves")', '    _list(b["serves"], "serves", _text)')], "records_test", ["D12"]),
    ("M217", "shapes.py", "a question index may have leading zeros",
     [('QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})\\Z")', 'QREF = re.compile(r"^[0-9a-f]{64}:([0-9]{1,4})\\Z")')],
     "records_test", ["D13"]),
    ("M218", "shapes.py", "a question index digit is any Unicode digit (`\\d`)",
     [('QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})\\Z")', 'QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9]\\d{0,3})\\Z")')],
     "records_test", ["D13"]),
    ("M219", "records.py", "a subject is any hex string of 40 to 64 characters",
     [('SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\\Z")', 'SUBJECT = re.compile(r"^[0-9a-f]{40,64}\\Z")')],
     "records_test", ["D14", "T9"]),
    ("M220", "records.py", "a basis is any string",
     [('    _enum(b["basis"], BASES, "basis")', '    _text(b["basis"], "basis")')], "records_test", ["T1"]),
    ("M221", "records.py", "a transition's evidence names any strings",
     [('    _enum(b["basis"], BASES, "basis")\n    _hexes(b["evidence"], "evidence")',
       '    _enum(b["basis"], BASES, "basis")\n    _list(b["evidence"], "evidence", _text)')], "records_test", ["T2"]),
    ("M222", "records.py", "established is any list",
     [('    _list(b["established"], "established", _text)', '    _need(isinstance(b["established"], list), "established")')],
     "records_test", ["T4"]),
    ("M223", "records.py", "residual is any list",
     [('    _list(b["residual"], "residual", _text)', '    _need(isinstance(b["residual"], list), "residual")')],
     "records_test", ["T5"]),
    ("M224", "records.py", "a question's scope is not checked",
     [('    _need(q["scope"] is None or (isinstance(q["scope"], str) and q["scope"]), "question scope")', "    pass")],
     "records_test", ["T6"]),
    ("M225", "records.py", "the items of closes are not checked",
     [('    for m in b["closes"]:\n        _item(m, b["evidence"])', '    for m in b["closes"]:\n        pass')], "records_test", ["T7"]),
    ("M226", "records.py", "supersedes names any strings",
     [('    _hexes(b["supersedes"], "supersedes")', '    _list(b["supersedes"], "supersedes", _text)')], "records_test", ["T10"]),
    ("M227", "records.py", "a transition's triggers are not checked",
     [('    _list(b["triggers"], "triggers", _trigger)', '    _list(b["triggers"], "triggers", lambda v, w: None)')],
     "records_test", ["T11"]),
    ("M228", "engine.py", "a question reference counts its index from 1",
     [('            ref = f"{t_id}:{i}"', '            ref = f"{t_id}:{i + 1}"')], "records_test", ["T12"]),
    ("M229", "records.py", "an item's duty is any string",
     [('    _hex(m["duty"], "item duty")', '    _text(m["duty"], "item duty")')], "records_test", ["I1"]),
    ("M230", "records.py", "an item may name an act outside the six",
     [('ACTS = ("discharge", "impossible", "release", "delegate", "substitute", "revalidate")',
       'ACTS = ("discharge", "impossible", "release", "delegate", "substitute", "revalidate", "close")'),
      ('"revalidate": ("triggers",)}[act]', '"revalidate": ("triggers",), "close": ()}[act]')], "records_test", ["I2"]),
    ("M231", "records.py", "an item may cite evidence its transition does not carry",
     [('    _need(set(m["evidence"]) <= set(evidence), "an item cites evidence its transition does not carry")', "    pass")],
     "records_test", ["I3"]),
    ("M232", "records.py", "a period may be filed on an impossible item",
     [('"impossible": ("triggers",), "release": (),', '"impossible": ("period", "triggers"), "release": (),')],
     "records_test", ["I4"]),
    ("M233", "engine.py", "a period is not matched against the duty's schedule",
     [('    if m["act"] == "discharge" and (sched is None) != ("period" not in m):', "    if False:")], "records_test", ["I4"]),
    ("M234", "records.py", "a discharge may name a `to`",
     [('optional = {"discharge": ("period", "triggers"),', 'optional = {"discharge": ("period", "triggers", "to"),')],
     "records_test", ["I5"]),
    ("M235", "records.py", "revalidates may be empty",
     [('        _hexes(m["revalidates"], "revalidates", nonempty=True)', '        _hexes(m["revalidates"], "revalidates")')],
     "records_test", ["I6"]),
    ("M236", "records.py", "a release item may carry triggers",
     [('"impossible": ("triggers",), "release": (),', '"impossible": ("triggers",), "release": ("triggers",),')],
     "records_test", ["I7"]),
    ("M237", "records.py", "an acceptance names any string as its transition",
     [('    _hex(b["transition"], "transition")', '    _text(b["transition"], "transition")')], "records_test", ["A1"]),
    ("M238", "records.py", "an acceptance's item may be a boolean",
     [('    _hex(b["transition"], "transition")\n    _need(b["item"] is None or (type(b["item"]) is int',
       '    _hex(b["transition"], "transition")\n    _need(b["item"] is None or (isinstance(b["item"], int)')], "records_test", ["A2"]),
    ("M239", "engine.py", "a results acceptance of any evidence set counts",
     [('b["item"] == index and sorted(b["evidence"]) == want:', 'b["item"] == index and (index is None or sorted(b["evidence"]) == want):')],
     "records_test", ["A3"]),
    ("M240", "records.py", "support names any strings",
     [('    _hexes(b["support"], "support")', '    _list(b["support"], "support", _text)')], "records_test", ["A4"]),
    ("M241", "engine.py", "an acceptance of another transition counts",
     [('            if b["transition"] == t_id and b["item"] == index and sorted(b["evidence"]) == want:',
       '            if b["item"] == index and sorted(b["evidence"]) == want:')], "records_test", ["A6"]),
    ("M242", "records.py", "an observation's target is not checked",
     [('    _text(b["target"], "target", limit=400)\n', "")], "records_test", ["O1"]),
    ("M243", "records.py", "an observation's probe is any string",
     [('    _hex(b["probe"], "probe")', '    _text(b["probe"], "probe")')], "records_test", ["O2"]),
    ("M244", "records.py", "a window may end before it starts",
     [(" and w[0] <= w[1],", ",")], "records_test", ["O3"]),
    ("M245", "records.py", "an observation may end after it was filed",
     [('        _need(record["body"]["window"][1] <= record["at"], "an observation cannot be filed before it ended")', "        pass")],
     "records_test", ["O3"]),
    ("M246", "records.py", "an observation's result is not checked",
     [('    _text(b["result"], "result", empty=True)\n', "")], "records_test", ["O4"]),
    ("M247", "engine.py", "an observed result matches its expectation up to surrounding whitespace",
     [('        elif o["result"] != cond["expect"]:', '        elif o["result"].strip() != cond["expect"].strip():')],
     "records_test", ["O4"]),
    ("M248", "records.py", "raw names any strings",
     [('    _hexes(b["raw"], "raw")', '    _list(b["raw"], "raw", _text)')], "records_test", ["O5"]),
    ("M249", "records.py", "a grantee is not checked",
     [('    _actor(b["grantee"], "grantee")\n', "")], "records_test", ["G2"]),
    ("M250", "records.py", "a grant may name no act",
     [('"acts", lambda v, w: _enum(v, GRANT_ACTS, w), nonempty=True, sorted_=True)', '"acts", lambda v, w: _enum(v, GRANT_ACTS, w), sorted_=True)')],
     "records_test", ["G3"]),
    ("M251", "records.py", "delegable may name any act",
     [('"delegable", lambda v, w: _enum(v, GRANT_ACTS, w), sorted_=True)', '"delegable", _text, sorted_=True)'),
      ('    _need(set(b["delegable"]) <= set(b["acts"]), "delegable must be a subset of acts")', "    pass")],
     "records_test", ["G4"]),
    ("M252", "records.py", "a grant's duties need not be sorted",
     [('    _hexes(b["duties"], "duties", nonempty=True, sorted_=True)', '    _hexes(b["duties"], "duties", nonempty=True)')],
     "records_test", ["G5"]),
    ("M253", "engine.py", "a grant still authorizes at its expiry (`expires` inclusive)",
     [('and pos[0] >= g["expires"]:', 'and pos[0] > g["expires"]:')], "assessment_test", ["R15"]),
    ("M254", "records.py", "expires may be a boolean",
     [('(type(b["expires"]) is int and b["expires"] >= 0)', '(isinstance(b["expires"], int) and b["expires"] >= 0)')],
     "records_test", ["G6"]),
    ("M255", "records.py", "a grant's parent is checked for length only",
     [('b["parent"] is None or S.hex64(b["parent"])', 'b["parent"] is None or (isinstance(b["parent"], str) and len(b["parent"]) == 64)')],
     "records_test", ["G7"]),
    ("M256", "records.py", "a challenge's target is any string",
     [('    _hex(b["target"], "target")', '    _text(b["target"], "target")')], "records_test", ["C1"]),
    ("M257", "records.py", "a challenge's item may be a boolean",
     [('    _hex(b["target"], "target")\n    _need(b["item"] is None or (type(b["item"]) is int',
       '    _hex(b["target"], "target")\n    _need(b["item"] is None or (isinstance(b["item"], int)')], "records_test", ["C2"]),
    ("M258", "records.py", "a challenge's statement is not checked",
     [('    _text(b["statement"], "statement")\n', "")], "records_test", ["C3"]),
    ("M259", "records.py", "a challenge's evidence names any strings",
     [('    _text(b["statement"], "statement")\n    _hexes(b["evidence"], "evidence")',
       '    _text(b["statement"], "statement")\n    _list(b["evidence"], "evidence", _text)')], "records_test", ["C4"]),
    # W5: SPEC §4's lead, and the actor id of SPEC §3
    ("M260", "engine.py", "records filed after as_of are in the view",
     [('        self.recs = {rid: r for rid, r in good.items() if r["at"] <= as_of}',
       '        self.recs = {rid: r for rid, r in good.items()}')], "assessment_test", ["R21"]),
    ("M261", "shapes.py", "an actor id need not be in NFC",
     [('    if not unicodedata.is_normalized("NFC", v):\n        return "must be in Unicode NFC"\n', '')], "records_test", ["K12"]),
    ("M262", "shapes.py", "an actor id may contain a control character",
     [('    if any(unicodedata.category(c) == "Cc" for c in v):\n        return "must not contain a control character"\n', '')],
     "records_test", ["K12"]),
    ("M263", "shapes.py", "an actor id may begin or end with white space",
     [('    if unicodedata.category(v[0]) in EDGE_SPACE or unicodedata.category(v[-1]) in EDGE_SPACE:\n'
       '        return "must not begin or end with white space"\n', '')], "records_test", ["K12"]),
    ("M264", "shapes.py", "only a space separator (Zs) counts as white space at an actor id's ends",
     [('EDGE_SPACE = ("Zs", "Zl", "Zp")', 'EDGE_SPACE = ("Zs",)')], "records_test", ["K12"]),
    ("M265", "shapes.py", "an actor id may be 201 code points long",
     [('MAX_ACTOR = 200\n', 'MAX_ACTOR = 201\n')], "records_test", ["K12"]),
    ("M266", "shapes.py", "an actor id's length is counted in UTF-16 code units, not code points",
     [('        return f"must be a string ≤ {MAX_ACTOR}"\n',
       '        return f"must be a string ≤ {MAX_ACTOR}"\n    if len(v.encode("utf-16-le")) > 2 * MAX_ACTOR:\n        return "is too long"\n')],
     "records_test", ["K12"]),
    ("M267", "shapes.py", "an actor must look like a name (letters, digits, - _ .): what it is gets assessed",
     [('        return f"must be a string ≤ {MAX_ACTOR}"\n',
       '        return f"must be a string ≤ {MAX_ACTOR}"\n    if re.fullmatch(r"[A-Za-z0-9_.-]+", v) is None:\n        return "is not a name"\n')],
     "records_test", ["K13"]),
    # Gemini deep review 2026-10-22: defects A (challenge scope), B (awaited acceptances), C (grant positions)
    ("M268", "engine.py", "a challenge counts against every closure of the transition it targets, whatever its item",
     [('        if (c["target"], c["item"]) not in closures:', '        if c["target"] not in {x[0] for x in closures}:')],
     "assessment_test", ["R36"]),
    ("M269", "engine.py", "a challenge of the results (item null) counts against the transition's closures",
     [('        if (c["target"], c["item"]) not in closures:',
       '        if (c["target"], c["item"]) not in closures and not (c["item"] is None and c["target"] in {x[0] for x in closures}):')],
     "assessment_test", ["R36"]),
    ("M270", "engine.py", "a substitution is shown waiting for `to` only, never for its creditor",
     [('transfers or delegates")\n    if missing:\n        return V("PENDING", _waiting_why(missing), waiting=missing)',
       'transfers or delegates")\n    if missing:\n        return V("PENDING", _waiting_why(missing), waiting=missing[:1])')],
     "assessment_test", ["R37"]),
    ("M271", "engine.py", "an acceptance is the last one only when its actor is the only one awaited",
     [('"last_acceptance": all(actor in g for g in c["awaiting"])}', '"last_acceptance": c["waiting_for"] == [actor]}')],
     "assessment_test", ["R37"]),
    ("M272", "engine.py", "an attested impossibility waits for every owed_to actor, not for one",
     [('        missing.append(sorted(set(d["owed_to"])))', '        missing += [[a] for a in sorted(set(d["owed_to"]))]')],
     "assessment_test", ["R38"]),
    ("M273", "engine.py", "an awaited actor's id is read up to its first ' ('",
     [('            cand["waiting_for"] = sorted({a for g in waiting for a in g})',
       '            cand["waiting_for"] = sorted({a.split(" (")[0] for g in waiting for a in g})')], "assessment_test", ["R38"]),
    ("M274", "engine.py", "an acceptance another missing one implies is still awaited",
     [('    return [list(g) for g in gs if not any(set(h) < set(g) for h in gs)]', '    return [list(g) for g in gs]')],
     "assessment_test", ["R38"]),
    ("M275", "engine.py", "a grant is valid from its `at`, not from its position (at, id)",
     [('    if view.pos(gid) > pos:', '    if view.pos(gid)[0] > pos[0]:')], "assessment_test", ["R39"]),
    ("M276", "engine.py", "a parent grant is judged at the end of its child's `at`, not at the child's position",
     [('grant_state(view, g["parent"], view.pos(gid), depth + 1)', 'grant_state(view, g["parent"], (view.pos(gid)[0], LAST, END_ID), depth + 1)')],
     "assessment_test", ["R39"]),
    ("M277", "engine.py", "positions are ordered by `at` alone (SPEC-4-7: the id breaks no tie)",
     [('        return (self.recs[rid]["at"], self.rank[rid], rid)', '        return (self.recs[rid]["at"], 0, "")')], "assessment_test", ["R39"]),
    # The six counters of the Gemini deep review (2026-10-22), as mutants. SPEC-4.1-5's counter is M116's
    # edit and SPEC-4.2-7's is M137's, byte for byte: those claims cite the existing mutant.
    ("M278", "engine.py", "a results acceptance is looked up as an acceptance of item 0 (counter against SPEC-3.3-8)",
     [('b["item"] == index and sorted(b["evidence"]) == want:', 'b["item"] == (0 if index is None else index) and sorted(b["evidence"]) == want:')],
     "records_test", ["A7"]),
    ("M279", "engine.py", "an acceptance of item 0 also accepts the transition's results",
     [('b["item"] == index and sorted(b["evidence"]) == want:', '(b["item"] == index or index is None and b["item"] == 0) and sorted(b["evidence"]) == want:')],
     "records_test", ["A7"]),
    ("M280", "engine.py", "an acceptance of the results also accepts item 0",
     [('b["item"] == index and sorted(b["evidence"]) == want:', '(b["item"] == index or index == 0 and b["item"] is None) and sorted(b["evidence"]) == want:')],
     "records_test", ["A7"]),
    ("M281", "engine.py", "only a revalidation must be filed by the holder or a delegate (counter against SPEC-4.1-2)",
     [('    if filer != holder and filer not in delegates:', '    if m["act"] == "revalidate" and filer != holder and filer not in delegates:')],
     "contract_test", ["G3"]),
    ("M282", "engine.py", "a standing challenge does not block reliance (counter against SPEC-4.4-3)",
     [('    yield _challenged(rep, _counting_challenges(rep, {tuple(x) for x in r["current_items"]}, r))', '    yield None')],
     "conditions_test", ["K1"]),
    ("M283", "engine.py", "a child grant is not checked for attenuation (counter against SPEC-6-2)",
     [('    why = _attenuation_problem(rec["actor"], g, view.by_type["grant"][g["parent"]]["body"])', '    why = None')],
     "contract_test", ["U4"]),
    # The roadmap as records (tools/roadmap.py, tests/roadmap_test.py). Ids from M300 leave
    # M268-M299 to the parallel claims work.
    ("M300", "../tools/roadmap.py", "the Forward Attack mark fires when any obligation is DISCHARGED, not all",
     [('obligations and all(m.rep["duties"][d]["disposition"] == "DISCHARGED"', 'obligations and any(m.rep["duties"][d]["disposition"] == "DISCHARGED"')],
     "roadmap_test", ["P9"]),
    ("M301", "../tools/roadmap.py", "the Forward Attack mark ignores whether the goal is still open (a met goal is marked)",
     [('    if state == "OPEN" and obligations and all(', '    if obligations and all(')], "roadmap_test", ["P9"]),
    ("M302", "../tools/roadmap.py", "a released (forgiven) obligation counts as met for the Forward Attack mark",
     [('["disposition"] == "DISCHARGED" for d in obligations', '["disposition"] in ("DISCHARGED", "RELEASED") for d in obligations')],
     "roadmap_test", ["P9"]),
    ("M303", "../tools/roadmap.py", "a reformulation nobody accepted is current next to the goal it supersedes",
     [('            elif self.recs[f.tid]["body"]["supersedes"] and not res["accepted"]:', '            elif False:')],
     "roadmap_test", ["P6"]),
    ("M304", "../tools/roadmap.py", "a reformulated goal loses the obligations that answer its earlier formulation",
     [('        refs = {f.ref for f in self.goals.get(key, [])}', '        refs = {f.ref for f in self.goals.get(key, []) if f.state == CURRENT}')],
     "roadmap_test", ["P6"]),
    ("M305", "../tools/roadmap.py", "path does not follow requires to the prerequisites",
     [('    out["children"] = [node(m, c, "requires", seen | {did}, shown) for c in r["requires"]]', '    out["children"] = []')],
     "roadmap_test", ["P3", "P7"]),
    ("M306", "../tools/roadmap.py", "ROADMAP.md is compared as text: read_text() turns \\r\\n into \\n",
     [('    elif rm.view.read_bytes() != render_view(m).encode():', '    elif rm.view.read_text() != render_view(m):')],
     "roadmap_test", ["P8"]),
    ("M307", "../tools/roadmap.py", "two current formulations of one goal key pass check",
     [('            if len(cur) > 1:\n', '            if False:\n')], "roadmap_test", ["P12"]),
    ("M308", "../tools/roadmap.py", "a supersession may drop a goal without saying it is met or withdrawn",
     [('                    elif key not in mine and act not in ("met", "withdraw"):', '                    elif False:')],
     "roadmap_test", ["P12"]),
    ("M309", "../tools/roadmap.py", "a goal may be called met without the transition establishing its text",
     [('                    elif act == "met" and f.text not in r["body"]["established"]:', '                    elif False:')],
     "roadmap_test", ["P12"]),
    ("M310", "../tools/roadmap.py", "an obligation may require or serve a duty that is not in the view",
     [('                    if x not in self.rep["duties"]:', '                    if False:')], "roadmap_test", ["P12"]),
    ("M311", "../tools/roadmap.py", "a goal key is anchored with $, which admits a trailing newline",
     [('KEY_RE = re.compile(r"^G[1-9][0-9]{0,3}\\Z")', 'KEY_RE = re.compile(r"^G[1-9][0-9]{0,3}$")')],
     "roadmap_test", ["P12", "P13"]),
    ("M312", "../tools/roadmap.py", "done discharges a duty its signer does not hold",
     [('        if r["holder"] != self.actor and self.actor not in r["delegates"]:', '        if False:')],
     "roadmap_test", ["P5"]),
    ("M313", "../tools/roadmap.py", "release is filed by an actor the duty is not owed to (the holder forgives itself)",
     [('        if self.actor not in set(b["owed_to"]) | set(b["release_by"]):', '        if False:')],
     "roadmap_test", ["P5"]),
    ("M314", "../tools/roadmap.py", "done discharges with no evidence named",
     [('        if not refs:\n', '        if False:\n')], "roadmap_test", ["P5"]),
    ("M315", "../tools/roadmap.py", "the roadmap view is written into SPEC.md",
     [('        self.view = self.root / "ROADMAP.md"', '        self.view = self.root / "SPEC.md"')], "roadmap_test", ["P10"]),
    ("M316", "../tools/roadmap.py", "a goal reads unowned although an obligation answers it (the engine's taken_by ignored)",
     [('            self.owned[q["question"]] = q["taken_by"]', '            self.owned[q["question"]] = []')],
     "roadmap_test", ["P2"]),
    ("M317", "../tools/roadmap.py", "a revision of one goal leaves out the other goals of the transition it supersedes",
     [('                  for q in old if act == "reformulate" or q["scope"] != SCOPE + key]',
       '                  for q in old if act == "reformulate" and q["scope"] == SCOPE + key]')],
     "roadmap_test", ["P6", "P11"]),
    ("M318", "../tools/roadmap.py", "path does not show the duties whose serves names a node",
     [('                          "goal": m.goal_of(s)} for s in m.served_by(did) if s not in seen and s in m.rep["duties"]],',
       '                          "goal": m.goal_of(s)} for s in [] if s not in seen and s in m.rep["duties"]],')],
     "roadmap_test", ["P7"]),
    # The open circle of witnesses (tools/claims.py, tools/roadmap.py; tests/circle_test.py): A bindings
    # (the admission rule is warrant/bindings.py, the rest tools/claimslib/bindings.py),
    # B acceptance, C lineage and counters from anyone, D the witness ledger.
    ("M319", "bindings.py", "a binding whose proof does not verify is admitted (forged proof)",
     [("    if not K.verify(k[\"public\"], k[\"proof\"], msg):\n", "    if False:\n")], "circle_test", ["B2", "B3", "B8"]),
    ("M320", "bindings.py", "a proof signed by another key is reported as forged (the refusal stays, its code is wrong)",
     [("        if other:\n            return \"BINDING_PROOF_OTHER_KEY\"", "        if False:\n            return \"BINDING_PROOF_OTHER_KEY\"")], "circle_test", ["B3"]),
    ("M321", "bindings.py", "a second key for an actor is admitted (the first binding does not win)",
     [("    if first is not None:\n", "    if False:\n")], "circle_test", ["B4"]),
    ("M322", "bindings.py", "a binding's actor id is not checked against SPEC-3-21",
     [("        R.check_actor(k[\"actor\"])\n    except R.Invalid as e:\n        return \"BINDING_ACTOR_SHAPE\"", "        pass\n    except R.Invalid as e:\n        return \"BINDING_ACTOR_SHAPE\"")], "circle_test", ["B5"]),
    ("M323", "bindings.py", "one key binds two actors",
     [("    if any(p == k[\"public\"] for _, p in admitted):\n", "    if False:\n")], "circle_test", ["B6"]),
    ("M324", "bindings.py", "a binding with no proof is admitted",
     [("    if \"proof\" not in k:\n        return \"BINDING_UNPROVEN\"", "    if \"proof\" not in k:\n        return None, None\n        return \"BINDING_UNPROVEN\"")], "circle_test", ["B7"]),
    ("M325", "bindings.py", "the proof signs {actor, public} without the purpose (no domain separation)",
     [("    return C.canon({\"actor\": actor, \"public\": public, \"purpose\": BINDING})", "    return C.canon({\"actor\": actor, \"public\": public})")], "circle_test", ["B8"]),
    ("M326", "bindings.py", "a trust/2 file without proofs is read as admitted bindings outside a base",
     [("    if legacy and isinstance(doc, dict) and doc.get(\"warrant\") == \"trust/2\":", "    if isinstance(doc, dict) and doc.get(\"warrant\") == \"trust/2\":")], "circle_test", ["B7"]),
    ("M327", "../tools/claimslib/bindings.py", "a binding admitted at the base may be dropped",
     [("            for a, p in was if (a, p) not in have]", "            for a, p in was if False]")], "circle_test", ["B10"]),
    ("M328", "../tools/claimslib/bindings.py", "bind writes a binding check would not admit (another actor's id)",
     [("    if (actor, key.public) not in admitted:\n", "    if False:\n")], "circle_test", ["B9"]),
    ("M329", "../tools/claimslib/check.py", "check does not refuse a binding it does not admit",
     [("    out += repo.bindings()[1]\n", "")], "circle_test", ["B11"]),
    ("M330", "../tools/claimslib/bindings.py", "a receiver's own trust file is ignored",
     [("    return [] if not path else [(a, p) for a, p in Trust.load(path).keys.values()]", "    return []")], "circle_test", ["B12"]),
    ("M331", "../tools/claimslib/author.py", "anyone may file a claim's acceptance (accept_by not checked)",
     [("        if actor not in accept_by:\n            raise not_acceptor(", "        if False:\n            raise not_acceptor(")], "circle_test", ["K2"]),
    ("M332", "../tools/claimslib/author.py", "an acceptor who accepted already files another acceptance",
     [("        if actor in acceptors(model.recs, index, n.tid, 0):\n", "        if False:\n")], "circle_test", ["K7"]),
    ("M333", "../tools/claimslib/author.py", "a claim a replaying counter lowers is accepted",
     [("        if low:\n            raise Refused(f\"{cid}: a counter that replays", "        if False:\n            raise Refused(f\"{cid}: a counter that replays")], "circle_test", ["K4"]),
    ("M334", "../tools/claimslib/author.py", "accept --all takes a countered claim too (and the batch is refused)",
     [('if status[n.id] == "BACKED" and n.id not in cids', 'if n.backed and not n.retired and n.id not in cids')],
     "circle_test", ["K4"]),     # AMEND 1 of #171: accept --all reads standing
    ("M335", "../tools/claimslib/author.py", "an UNBACKED claim's acceptance is filed (it closes nothing)",
     [("        if not n.backed:\n            raise Refused(f\"{cid} is {n.status}", "        if False:\n            raise Refused(f\"{cid} is {n.status}")], "circle_test", ["K2"]),
    ("M336", "../tools/claimslib/views.py", "the view does not name who accepted",
     [("    by = f\"accepted by {', '.join(acceptor_name(a, report) for a in accepted)}\" if accepted else \"\"", "    by = \"\"")],
     "circle_test", ["K1", "K7"]),
    ("M337", "../tools/claimslib/model.py", "an acceptance of another evidence set is shown as the claim's acceptor",
     [("if t == tid and i == item and ev == want for a in actors})", "if t == tid and i == item for a in actors})")], "circle_test", ["K1"]),
    ("M338", "../tools/roadmap.py", "roadmap accept files anyone's acceptance",
     [("        if self.actor not in r[\"accept_by\"] and self.actor not in r[\"owed_to\"]:", "        if False:")], "circle_test", ["K6"]),
    ("M339", "../tools/roadmap.py", "roadmap accept accepts a closure that is no longer pending (already admitted)",
     [("        cands = [c for c in CL.pending_for(self.m.rep, did, self.actor) if transition in (None, c[\"transition\"])]", "        cands = [c for c in self.m.rep[\"duties\"][did][\"candidates\"] if transition in (None, c[\"transition\"])]")], "circle_test", ["K6"]),
    ("M340", "../tools/roadmap.py", "roadmap accept takes a SPEC claim's duty",
     [("        if did not in self.m.obligations:\n", "        if False:\n")], "circle_test", ["K6"]),
    ("M341", "../tools/roadmap.py", "the path does not name who accepted an obligation's closure",
     [("\"accepted_by\": m.accepted_by(did),", "\"accepted_by\": [],")], "circle_test", ["K6"]),
    ("M342", "../tools/claimslib/model.py", "another actor than a claim's author may supersede or retire it",
     [("        if n.rec[\"actor\"] != p.rec[\"actor\"]:\n", "        if False:\n")], "circle_test", ["L1", "L2"]),
    ("M343", "../tools/claimslib/document.py", "another actor than the document's author files its next version",
     [("            elif p[0][\"actor\"] != r[\"actor\"]:\n", "            elif False:\n")], "circle_test", ["L3"]),
    ("M344", "../tools/claimslib/author.py", "the tool files another author's supersession",
     [("        if previous is not None and previous.rec[\"actor\"] != self.actor:\n", "        if False:\n")], "circle_test", ["L3"]),
    ("M345", "../tools/claimslib/author.py", "the tool files another author's retirement",
     [("        if cur.rec[\"actor\"] != self.actor:\n            raise Refused(", "        if False:\n            raise Refused(")], "circle_test", ["L3"]),
    ("M346", "../tools/claimslib/author.py", "retire stores the counter-evidence before refusing another author",
     [("    if cur.rec[\"actor\"] != a.actor:\n", "    if False:\n")], "circle_test", ["L11"]),
    ("M347", "../tools/claimslib/author.py", "the tool files another author's document version",
     [("        if doc.current is not None and doc.nodes[doc.tid][0][\"actor\"] != self.actor:\n", "        if False:\n")], "circle_test", ["L3"]),
    ("M348", "../tools/claimslib/author.py", "challenge files a counter that does not replay",
     [("        if why:\n            raise Refused(f\"{a.claim}: the counter does not replay", "        if False:\n            raise Refused(f\"{a.claim}: the counter does not replay")], "circle_test", ["L4"]),
    ("M349", "../tools/claimslib/counters.py", "a counter that does not replay lowers the backing",
     [("            kind = LOWERS if good else COUNTED", "            kind = LOWERS if counters else COUNTED")], "circle_test", ["L5"]),
    ("M350", "../tools/claimslib/counters.py", "a counter lowers a claim that has no backing (UNBACKED)",
     [("            whys = {c: replay(c, n) if n.backed else", "            whys = {c: replay(c, n) if True else")], "circle_test", ["L5"]),
    ("M351", "../tools/claimslib/counters.py", "the author's own challenge does not count",
     [("    if actor == n.rec[\"actor\"]:\n        return True\n", "")], "circle_test", ["L5", "L6"]),
    ("M352", "../tools/claimslib/counters.py", "the acceptor's (and owed_to's) challenge does not count",
     [("    return d is not None and actor in set(d[\"body\"][\"owed_to\"]) | set(d[\"body\"][\"accept_by\"])", "    return False")], "circle_test", ["L5", "L6"]),
    ("M353", "../tools/claimslib/counters.py", "anyone's challenge counts (a stranger's thesis blocks check)",
     [("    if actor == n.rec[\"actor\"]:\n        return True\n", "    if True:\n        return True\n")], "circle_test", ["L5", "L6"]),
    ("M354", "../tools/claimslib/check.py", "check refuses a thesis as a standing challenge",
     [("if x[\"claim\"] == cid and x[\"kind\"] == COUNTED]", "if x[\"claim\"] == cid and x[\"kind\"] in (COUNTED, THESIS)]")], "circle_test", ["L6"]),
    ("M355", "../tools/claimslib/check.py", "check refuses a lowering counter as a standing challenge",
     [("if x[\"claim\"] == cid and x[\"kind\"] == COUNTED]", "if x[\"claim\"] == cid and x[\"kind\"] in (COUNTED, LOWERS)]")], "circle_test", ["L6"]),
    ("M356", "../tools/claimslib/counters.py", "a challenge's counters are replayed again although it was at the base",
     [("        if r[\"type\"] != \"challenge\" or rid in before:\n", "        if r[\"type\"] != \"challenge\":\n")], "circle_test", ["L7"]),
    ("M357", "../tools/claimslib/counters.py", "a new challenge's counter that does not replay is admitted",
     [("            if why:\n                out.append((\"COUNTER_NOT_REPLAYED\"", "            if False:\n                out.append((\"COUNTER_NOT_REPLAYED\"")], "circle_test", ["L7"]),
    ("M358", "../tools/claimslib/model.py", "a countered claim reads BACKED in the view",
     [("    return \"COUNTERED\" if n.id in low else n.status", "    return n.status")], "circle_test", ["L8"]),
    ("M359", "../tools/claimslib/check.py", "a claim's duty terms are not compared with the pins",
     [("    if n.retired or n.kind != \"normative\":\n        return None\n    b = model.recs", "    if True:\n        return None\n    b = model.recs")], "circle_test", ["L9"]),
    ("M360", "../tools/claimslib/check.py", "check does not refuse a claim whose duty names another acceptor",
     [("        if terms:\n            out.append((\"CLAIM_DUTY_TERMS\"", "        if False:\n            out.append((\"CLAIM_DUTY_TERMS\"")], "circle_test", ["L9"]),
    ("M361", "../tools/roadmap.py", "an obligation may name its own acceptor",
     [("            if (b[\"owed_to\"], b[\"accept_by\"], b[\"release_by\"]) != (cfg[\"owed_to\"], cfg[\"accept_by\"], []):", "            if False:")], "circle_test", ["L10"]),
    ("M362", "../tools/claimslib/views.py", "a supersession counts as an authored claim",
     [("        if n.doc[\"previous\"] is None:\n            rows[n.rec[\"actor\"]][\"authored\"] += 1", "        if True:\n            rows[n.rec[\"actor\"]][\"authored\"] += 1")], "circle_test", ["W1"]),
    ("M363", "../tools/claimslib/views.py", "an acceptance is credited to the accepted transition's filer",
     [("            rows[r[\"actor\"]][\"accepts\"].append(rid)", "            rows[recs[b[\"transition\"]][\"actor\"]][\"accepts\"].append(rid)")], "circle_test", ["W2"]),
    ("M364", "../tools/claimslib/views.py", "every acceptance of a claim counts as refuted",
     [("            if b[\"transition\"] in refuting and b[\"transition\"] in model.nodes:", "            if b[\"transition\"] in model.nodes:")], "circle_test", ["W3"]),
    ("M365", "../tools/claimslib/views.py", "an acceptance whose claim a downgrade's counter refuted is not counted",
     [("    refuting = {against[c] for c in now | set(downs)}", "    refuting = {against[c] for c in now}")], "circle_test", ["W3"]),
    ("M366", "../tools/claimslib/views.py", "a challenged closure counts as refuted without a revalidation",
     [("            elif (b[\"transition\"], b[\"item\"]) in challenged and b[\"transition\"] in revalidated:", "            elif (b[\"transition\"], b[\"item\"]) in challenged:")], "circle_test", ["W3"]),
    ("M367", "../tools/claimslib/views.py", "a challenge without evidence is not counted",
     [("        if r[\"type\"] == \"challenge\":\n            rows[r[\"actor\"]][\"challenges\"] += 1", "        if r[\"type\"] == \"challenge\" and r[\"body\"][\"evidence\"]:\n            rows[r[\"actor\"]][\"challenges\"] += 1")], "circle_test", ["W4"]),
    ("M368", "../tools/claimslib/views.py", "a counter is credited to the last record citing it",
     [("        first = min(rids, key=lambda rid: (recs[rid][\"at\"], rid))", "        first = max(rids, key=lambda rid: (recs[rid][\"at\"], rid))")], "circle_test", ["W5"]),
    ("M369", "../tools/claimslib/views.py", "a standing counter that does not replay counts as lowering now",
     [("    now = {c for x in table.values() if x[\"kind\"] == LOWERS for c in x[\"replays\"]}", "    now = {c for x in table.values() for c in x[\"counters\"]}")], "circle_test", ["W6"]),
    ("M370", "../tools/claimslib/counters.py", "a counter a BACKED re-back cites counts as cited by a downgrade",
     [("        if q.retired or q.kind != \"normative\" or q.backed:\n", "        if q.retired or q.kind != \"normative\":\n")], "circle_test", ["W6"]),
    ("M371", "../tools/claimslib/views.py", "any BACKED supersession counts as a re-back",
     [("        if n.backed and prev and prev[\"transition\"] in countered:", "        if n.backed and prev:")], "circle_test", ["W7"]),
    ("M372", "../tools/claimslib/views.py", "WITNESSES.md swaps the lowering-now and downgrade columns",
     [("f\"| {len(row['now'])} | {len(row['downgrade'])} | {len(row['rebacks'])} \"", "f\"| {len(row['downgrade'])} | {len(row['now'])} | {len(row['rebacks'])} \"")], "circle_test", ["W8"]),
    ("M373", "../tools/claimslib/check.py", "WITNESSES.md is compared as text: read_text() turns \\r\\n into \\n",
     [("    elif repo.witnesses.read_bytes() != render_witnesses(repo, model, table).encode():", "    elif repo.witnesses.read_text() != render_witnesses(repo, model, table):")], "circle_test", ["W9"]),
    # AMEND 1 of #170: a name the configuration gives a role is pinned in .warrant/roles.json, not first-come.
    ("M376", "bindings.py", "a role (a pinned key, reserved or collective) admits a binding of another key",
     [("    if role != k[\"public\"]:", "    if False:")], "circle_test", ["R1", "R2b", "R7"]),
    ("M377", "../tools/claimslib/repo.py", "the repository's bindings are admitted without its roles",
     [("        return admit_bindings(doc, roles=self.roles()[0])", "        return admit_bindings(doc)")], "circle_test", ["R2b"]),
    ("M378", "../tools/claimslib/bindings.py", "bind writes a binding the roles refuse",
     [("    admitted, problems = admit_bindings(doc, roles=repo.roles()[0])", "    admitted, problems = admit_bindings(doc)")], "circle_test", ["R2"]),
    ("M379", "bindings.py", "a role may be pinned to anything",
     [("        if not (v is None or v == COLLECTIVE or S.hex64(v)):", "        if False:")], "circle_test", ["R3"]),
    ("M380", "../tools/claimslib/check.py", "check does not report a malformed roles file",
     [("    out += why + unpinned(roles, ", "    out += unpinned(roles, ")], "circle_test", ["R3"]),
    ("M381", "../tools/claimslib/bindings.py", "a name the configuration gives a role may be left unpinned (first-come)",
     [("            for a in sorted(set(names) - set(roles))]", "            for a in []]")], "circle_test", ["R4"]),
    ("M382", "../tools/roadmap.py", "roadmap check does not ask for the roadmap's roles to be pinned",
     [("        self.problems += CL.unpinned(", "        _ = CL.unpinned(")], "circle_test", ["R4"]),
    ("M532", "../tools/roadmap.py", "a source blob may name bytes its transition does not cite",
     [('                    and doc["blob"] in ev and self.snap.blob(', '                    and self.snap.blob(')],
     "roadmap_test", ["P16"]),
    ("M533", "../tools/roadmap.py", "goal --source reads a file outside $TMPDIR",
     [("(CL.confined(a.source).read_bytes(), a.source_by)", "(Path(a.source).read_bytes(), a.source_by)")],
     "roadmap_test", ["P16"]),
    ("M383", "../tools/claimslib/bindings.py", "a pin may take a name from the binding admitted at the base",
     [("            for a, p in was if a in roles and roles[a] != p]", "            for a, p in was if False]")], "circle_test", ["R5"]),
    ("M384", "../tools/claimslib/author.py", "pin makes a collective role bindable",
     [("    if roles.get(a.actor) == COLLECTIVE:\n", "    if False:\n")], "circle_test", ["R6"]),
    ("M385", "../tools/claimslib/author.py", "pin takes a role from its admitted binding",
     [("    if other:\n        raise Refused(f\"{a.actor} is bound to key", "    if False:\n        raise Refused(f\"{a.actor} is bound to key")], "circle_test", ["R6"]),
    ("M403", "../tools/roadmap.py", "a discharge filed and not admitted (prerequisite open) reads as no closure filed",
     [("                return f\"closure {filed[-1]['verdict']}: {filed[-1]['why']}\" if filed else \"no closure filed\"",
       "                return \"no closure filed\"")], "roadmap_test", ["P14"]),
    # `claims.py why` (tools/claims.py, tests/why_test.py): a statement -> mutants -> claims -> obligations -> goals.
    ('M386', '../tools/claimslib/why.py', 'a statement only an uncited mutant changes counts as covered',
     [('        return any(mid in self.cited for mid in self.changes.get((path, i), ()))', '        return any(True for mid in self.changes.get((path, i), ()))')], "why_test", ['Y8']),
    ('M387', '../tools/claimslib/why.py', "an UNBACKED claim's mutants cover statements",
     [('{"BACKED": self.cited, "COUNTERED": self.countering}.get(status[n.id])', '{"BACKED": self.cited, "UNBACKED": self.cited, "COUNTERED": self.countering}.get(status[n.id])')], "why_test", ['Y3']),
    ('M388', '../tools/claimslib/why.py', "a superseded claim's mutants cover statements",
     [('for n in sorted(model.current.values(), key=lambda n: id_key(n.id)):\n            index = {', 'for n in sorted(model.nodes.values(), key=lambda n: id_key(n.id)):\n            index = {')], "why_test", ['Y5']),
    ('M389', '../tools/claimslib/why.py', 'a mutant inserting before a statement counts as changing it',
     [('(self.changes if kind == "at" else self.inserts)', '(self.changes if kind in ("at", "insert") else self.inserts)')], "why_test", ['Y4']),
    ('M390', '../tools/claimslib/statements.py', 'a comment line is owned by the statement around it',
     [('        own = own & code or {first}\n', '        own = own or {first}\n')], "why_test", ['Y6']),
    ('M391', '../tools/claimslib/statements.py', "a compound statement's header owns its children's lines",
     [('                own -= set(range(a, b + 1))\n', '                own |= set()\n')], "why_test", ['Y1']),
    ('M392', '../tools/claimslib/statements.py', 'a statement owns only its first line (a continuation line is no statement)',
     [('[d.lineno for d in getattr(st, "decorator_list", [])]), st.end_lineno', '[d.lineno for d in getattr(st, "decorator_list", [])]), st.lineno')], "why_test", ['Y7']),
    ('M393', '../tools/claimslib/why.py', "an obligation that requires a claim's duty is not found (serves only)",
     [('        for rel in ("serves", "requires"):\n            for x in body[rel]:', '        for rel in ("serves",):\n            for x in body[rel]:')], "why_test", ['Y7']),
    ('M394', '../tools/claimslib/why.py', 'the goal an obligation answers is not reported',
     [('                if ln["goal"]:\n                    goals[', '                if False:\n                    goals[')], "why_test", ['Y1']),
    ('M395', '../tools/claimslib/why.py', "every obligation is reported, whichever claim's duty it names",
     [('            for ln in (x for d in sorted(self.lineage.get(c["claim"], {c["duty"]})) for x in self.links.get(d, [])):',
       '            for ln in [x for v in self.links.values() for x in v]:')], "why_test", ['Y2']),
    ('M396', '../tools/claimslib/why.py', '--uncovered lists the wholly uncovered functions smallest first',
     [('key=lambda f: (-f["statements"], f["file"], f["line"])', 'key=lambda f: (f["statements"], f["file"], f["line"])')], "why_test", ['Y8']),
    ('M397', '../tools/claimslib/why.py', '--uncovered lists a function with a covered statement as uncovered',
     [('(f for f in funcs.values() if not f["covered"])', '(f for f in funcs.values() if f["covered"] < f["statements"])')], "why_test", ['Y8']),
    ('M398', '../tools/claimslib/why.py', 'why reads a FILE outside the source roots as given',
     [('        if path not in self.files:\n            raise Refused(f"{path}: not a Python file under', '        if not (self.repo.root / path).is_file():\n            raise Refused(f"{path}: not a Python file under'), ('        src = self.files[path].read_text()\n        lines = src.splitlines()', '        src = (self.repo.root / path).read_text()\n        lines = src.splitlines()')], "why_test", ['Y9']),
    ('M399', '../tools/claimslib/why.py', 'FILE:LINE is anchored with $, which admits a trailing newline',
     [('WHY_LINE = re.compile(r"^(.+):([1-9][0-9]{0,6})\\Z")', 'WHY_LINE = re.compile(r"^(.+):([1-9][0-9]{0,6})$")')], "why_test", ['Y9']),
    ('M400', '../tools/claimslib/why.py', "a line beyond the file's end is answered, not refused",
     [('        if line > len(lines):\n            raise Refused', '        if False:\n            raise Refused')], "why_test", ['Y9']),
    ('M401', '../tools/claimslib/why.py', 'a mutant two claims cite maps to the first of them only',
     [('                index.setdefault(mid, []).append(n)', '                index.setdefault(mid, [n])')], "why_test", ['Y1']),
    ('M402', '../tools/claimslib/why.py', 'a statement some mutant changes reads CLAIMED although no BACKED claim cites that mutant',
     [('status = NOT_A_STATEMENT if not hits else CLAIMED if claims else NO_CLAIM', 'status = NOT_A_STATEMENT if not hits else CLAIMED if any(x["mutants"] for x in stmts) else NO_CLAIM')], "why_test", ['Y3']),
    # AMEND 1 of #171: what counts as backing is the view's standing (COUNTERED is not backing).
    ('M404', '../tools/claimslib/why.py', "why counts a COUNTERED claim as backing (Node.status, not the view's standing)",
     [('.get(status[n.id])\n', '.get(n.status)\n')], "why_test", ['Y12']),
    ('M405', '../tools/claimslib/why.py', 'why drops a COUNTERED claim silently instead of naming it with its counter',
     [('{"BACKED": self.cited, "COUNTERED": self.countering}', '{"BACKED": self.cited}')], "why_test", ['Y12']),
    ('M406', '../tools/claimslib/audit.py', 'audit hunts blind witnesses of a COUNTERED claim as if it were BACKED',
     [('if status[n.id] == "BACKED"), key=lambda n: id_key(n.id)):\n        _audit_claim', 'if n.backed and not n.retired), key=lambda n: id_key(n.id)):\n        _audit_claim')], "why_test", ['Y15']),
    ('M407', '../tools/claimslib/why.py', '--uncovered does not name the COUNTERED claim of an uncovered statement',
     [('                    low = sorted({n.id for mid in self.changes.get((path, i), ()) for n in self.countering.get(mid, [])},\n                                 key=id_key)', '                    low = []')], "why_test", ['Y13']),
    ('M408', '../tools/claimslib/why.py', "why follows a COUNTERED claim's duty to the obligations serving it",
     [('        for c in claims.values():\n            for ln in (x for d', '        for c in list(claims.values()) + list(countered.values()):\n            for ln in (x for d')],
     "why_test", ['Y12']),
    # F43: a record's position is witnessed by its actor's chain (SPEC §3, §4, §4.1).
    ("M409", "engine.py", "a delegate's acceptance authorizes its filing wherever the chain puts it (F43)",
     [('                on = on and any(self.view.before(a, filing) for a in accepts)\n', '                on = on\n')],
     "assessment_test", ["R40", "R41", "R44", "R45"]),
    ("M410", "engine.py", "a holder's own transfer counts for its filing only from the transfer's effect position",
     [('            elif x == frm != to and not on:\n                on = not self.view.ordered(t_id, filing)\n', '')],
     "assessment_test", ["R42"]),
    ("M411", "engine.py", "a prev filed by another actor chains a record",
     [('            elif q["actor"] != r["actor"]:\n', '            elif False:\n')], "assessment_test", ["R45"]),
    ("M412", "engine.py", "a record dated before its prev is chained to it",
     [('            elif q["at"] > r["at"]:\n', '            elif False:\n')], "assessment_test", ["R42"]),
    ("M413", "engine.py", "a prev not in the view is not reported missing",
     [('                if r["prev"] not in later:\n                    self.missing.add(r["prev"])\n', '')],
     "assessment_test", ["R44"]),
    ("M414", "engine.py", "a fork of two records is not listed",
     [('for (a, p), ids in sorted(groups.items()) if len(ids) > 1]', 'for (a, p), ids in sorted(groups.items()) if len(ids) > 2]')],
     "assessment_test", ["R43"]),
    ("M415", "engine.py", "both branches of a fork are excluded (the alternative F43's design rejects: a retraction button)",
     [('        self.forks = [{"actor": a, "prev": p or None, "records": ids} for (a, p), ids in sorted(groups.items()) if len(ids) > 1]\n',
       '        self.forks = [{"actor": a, "prev": p or None, "records": ids} for (a, p), ids in sorted(groups.items()) if len(ids) > 1]\n'
       '        for f in self.forks:\n            for x in f["records"]:\n                self.recs.pop(x, None)\n'
       '                for byt in self.by_type.values():\n                    byt.pop(x, None)\n'
       '        self.link = {k: v for k, v in self.link.items() if k in self.recs and v in self.recs}\n')],
     "assessment_test", ["R43"]),
    ("M416", "engine.py", "records with the same `at` are ordered by id alone, against the chain",
     [('                if p is not None and self.recs[p]["at"] == at:\n', '                if False:\n')], "assessment_test", ["R48"]),
    ("M417", "engine.py", "a record is before every record of greater height, ancestor or not",
     [('        while self.height[b] > self.height[a]:\n            b = self.link[b]\n        return a == b\n', '        return True\n')],
     "assessment_test", ["R41"]),
    ("M418", "records.py", "prev may be any string",
     [('record["prev"] is None or S.hex64(record["prev"])', 'record["prev"] is None or isinstance(record["prev"], str)')],
     "records_test", ["K14"]),
    ("M419", "records.py", "prev is required: every record before chains becomes invalid",
     [('    _fields(record, ("warrant", "type", "actor", "at", "body"), ("prev",), what="record")',
       '    _fields(record, ("warrant", "type", "actor", "at", "body", "prev"), what="record")')], "records_test", ["K14"]),
    ("M420", "store.py", "the head is the earliest tip of a forked chain",
     [('        return (max(tips)[1], max(tips)[0]) if tips else None', '        return (min(tips)[1], min(tips)[0]) if tips else None')],
     "records_test", ["K15"]),
    ("M421", "store.py", "a writer may date a record before its head",
     [('        if head is not None and r["at"] < head[1]:\n', '        if False:\n')], "records_test", ["K15"]),
    ("M422", "store.py", "a record is filed whatever head its prev names (no compare-and-swap)",
     [('        if "prev" not in r or r["prev"] != (head[0] if head else None):\n', '        if False:\n')],
     "records_test", ["K15"]),
    ("M423", "store.py", "the chain head is read and extended without the lock",
     [('            fcntl.flock(fd, fcntl.LOCK_EX)\n', '')], "records_test", ["K16"]),
    ("M424", "engine.py", "a delegate's acceptance authorizes its filing wherever the chain puts it, at a receiver (F43)",
     [('                on = on and any(self.view.before(a, filing) for a in accepts)\n', '                on = on\n')],
     "agent_handoff_test", ["H16"]),
    ("M425", "store.py", "an unchained record is a head",
     [('        mine = {rid: r for rid, r in good.items() if r["actor"] == actor and "prev" in r}',
       '        mine = {rid: r for rid, r in good.items() if r["actor"] == actor}'),
      ('                p = r["prev"]\n', '                p = r.get("prev")\n'),
      ('        named = {r["prev"] for r in chain.values()}', '        named = {r.get("prev") for r in chain.values()}')],
     "records_test", ["K15"]),
    ("M426", "engine.py", "a filing replayed under a new prev inherits the acceptances of the one it copies",
     [('            if b["transition"] == t_id and b["item"] == index and sorted(b["evidence"]) == want:',
       '            if b["item"] == index and sorted(b["evidence"]) == want:')], "assessment_test", ["R46"]),
    # AMEND 1 of #174 (Codex P2): a writer's head is only what the reader admits as the actor's own.
    ("M427", "store.py", "the writer's head is read from every envelope, authentic or not",
     [('        good, _ = snap.authentic(trust, index)\n',
       '        good = {rid: C.loads(b)["record"] for rid, b in snap.records.items()}\n')],
     "records_test", ["K17"]),
    ("M428", "store.py", "an unanchored record of the actor is a head",
     [('        chain = {rid: r for rid, r in mine.items() if anchored.get(rid)}\n', '        chain = mine\n')],
     "records_test", ["K17"]),
    ("M429", "store.py", "the writer's head is read from every envelope, authentic or not (warrant-agent)",
     [('        good, _ = snap.authentic(trust, index)\n',
       '        good = {rid: C.loads(b)["record"] for rid, b in snap.records.items()}\n')],
     "agent_write_test", ["W12"]),
    # F44: a remembered verdict stands in for _authenticate only for the same trust, name, bytes and code.
    ("M430", "store.py", "a verdict remembered under one trust stands in under another",
     [('    k = (trust.digest, rid, hashlib.sha256(data).hexdigest())', '    k = ("", rid, hashlib.sha256(data).hexdigest())')],
     "store_index_test", ["V6"]),
    ("M431", "store.py", "a verdict remembered for a file stands in after its bytes change",
     [('    k = (trust.digest, rid, hashlib.sha256(data).hexdigest())', '    k = (trust.digest, rid, "")')],
     "store_index_test", ["V7"]),
    ("M432", "store.py", "a verdict remembered for bytes stands in for the same bytes under another name",
     [('    k = (trust.digest, rid, hashlib.sha256(data).hexdigest())', '    k = (trust.digest, "", hashlib.sha256(data).hexdigest())')],
     "store_index_test", ["V8"]),
    ("M433", "store.py", "with an index, a file it has not seen counts as authentic",
     [('    if why is MISS:\n        why, rec = _authenticate(rid, data, trust)\n    else:\n',
       '    if why is MISS and not (index is not None and index._part(k[0])["entries"]):\n        why, rec = _authenticate(rid, data, trust)\n'
       '    else:\n        why = None if why is MISS else why\n')],
     "store_index_test", ["V9"]),
    ("M434", "store.py", "an index line counts whatever its MAC",
     [(' and hmac.compare_digest(x[6], self._mac(x[2:6]))', '')], "store_index_test", ["V11"]),
    ("M435", "store.py", "an index line's MAC does not cover its verdict",
     [('hmac.compare_digest(x[6], self._mac(x[2:6]))', 'hmac.compare_digest(x[6], self._mac(x[2:5]))'),
      ('*fields, self._mac(fields)]', '*fields, self._mac(fields[:3])]')], "store_index_test", ["V12"]),
    ("M436", "store.py", "an index line's MAC does not cover the code identity it was computed by",
     [('        msg = json.dumps([self.SCHEMA, self.code, *fields]', '        msg = json.dumps([self.SCHEMA, *fields]')],
     "store_index_test", ["V14"]),
    ("M437", "store.py", "a receiver's index secret is a constant, not random",
     [('                os.write(fd, os.urandom(32))', '                os.write(fd, bytes(32))')], "store_index_test", ["V17"]),
    # A blob found canonical is remembered by the sha256 of its bytes (Snapshot.json_blob, _CANONICAL): claims-selftest
    # re-read ~100 document versions of SPEC.md (37 KB each) in every case, 286 s -> 106 s locally.
    ("M482", "store.py", "a remembered canonical blob is keyed by its name, not by its bytes",
     [("        seen = hashlib.sha256(data).digest()\n", "        seen = h\n")], "store_index_test", ["V19"]),
    ("M483", "store.py", "bytes are remembered as canonical before C.loads has accepted them",
     [("        try:\n            value = C.loads(data)\n", "        _CANONICAL.add(seen)\n        try:\n            value = C.loads(data)\n")],
     "store_index_test", ["V19"]),
    # One module of shapes (warrant/shapes.py, tests/shapes_test.py): each predicate against the `$`,
    # CRLF, non-ASCII, case and length vectors, never raising; and no second definition anywhere.
    ("M438", "shapes.py", "hex64 assumes a string: a non-string raises instead of answering False",
     [('    return isinstance(v, str) and HEX64.match(v) is not None', '    return HEX64.match(v) is not None')],
     "shapes_test", ["S1"]),
    ("M439", "shapes.py", "hex128 assumes a string",
     [('    return isinstance(v, str) and HEX128.match(v) is not None', '    return HEX128.match(v) is not None')],
     "shapes_test", ["S2"]),
    ("M440", "shapes.py", "a 32-digit hex (a view token) may end in a newline",
     [('HEX32 = re.compile(r"^[0-9a-f]{32}\\Z")', 'HEX32 = re.compile(r"^[0-9a-f]{32}$")')], "shapes_test", ["S3"]),
    ("M441", "shapes.py", "qref assumes a string",
     [('    return isinstance(v, str) and QREF.match(v) is not None', '    return QREF.match(v) is not None')],
     "shapes_test", ["S4"]),
    ("M442", "shapes.py", "an actor id is not checked to be a string before its length and normalization",
     [('    if not (isinstance(v, str) and v and len(v) <= MAX_ACTOR):', '    if not (v and len(v) <= MAX_ACTOR):')],
     "shapes_test", ["S5"]),
    ("M443", "compute.py", "a module writes its own (correct) copy of the hex64 pattern again",
     [('            and all(S.hex64(h) for h in doc["hashes"])',
       '            and all(isinstance(h, str) and __import__("re").fullmatch(r"[0-9a-f]{64}", h) for h in doc["hashes"])')],
     "shapes_test", ["S6"]),
    # G4: the replay checker (tools/claimslib/replay.py) and acceptances by replay as check reads them
    # (by_replay.py; tests/replay_test.py R0-R14). One mutant per adversary case.
    ("M444", "../tools/claimslib/replay.py", "the checker accepts a claim one of whose witnesses fails",
     [('        failed = [w for w, v in wit.items() if v != "PASS"]', '        failed = []')], "replay_test", ["R1"]),
    ("M445", "../tools/claimslib/replay.py", "a mutant counts as killed when any case of its file fails, cited or not",
     [('                    outcome = "KILLED" if fails else "SURVIVED"',
       '                    outcome = "KILLED" if any(v == "FAIL" for v in (runs or {}).values()) else "SURVIVED"')],
     "replay_test", ["R2"]),
    ("M446", "../tools/claimslib/replay.py", "the checker replays a working tree that is not HEAD's",
     [('    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):', '    if False:')], "replay_test", ["R3"]),
    ("M447", "../tools/claimslib/replay.py", "the checker accepts a challenged claim",
     [('    if any(r["type"] == "challenge" and r["body"]["target"] == tid for r in recs.values()):', '    if False:')],
     "replay_test", ["R4"]),
    ("M448", "../tools/claimslib/replay.py", "the checker signs with whatever key it is given",
     [('    if trust.keys.get(key.id, (None,))[0] != me:', '    if False:')], "replay_test", ["R5"]),
    ("M449", "../tools/claimslib/check.py", "a checker the pins adopt need not be pinned in roles.json (first-come)",
     [(' + pins_.get("checkers", []),', ',')], "replay_test", ["R6"]),
    ("M450", "../tools/claimslib/by_replay.py", "a report showing a failing witness stands",
     [('    if sorted(w) != n.doc["witnesses"] or any(v != "PASS" for v in w.values()) or sorted(m) != n.doc["mutants"] \\',
       '    if sorted(w) != n.doc["witnesses"] or sorted(m) != n.doc["mutants"] \\')], "replay_test", ["R7"]),
    ("M451", "../tools/claimslib/by_replay.py", "a report's tree is not compared with its commit's",
     [('    if tree != rep["tree"]:', '    if False:')], "replay_test", ["R8", "R22"]),
    ("M452", "../tools/claimslib/by_replay.py", "a checker id is admitted for other code at the reported commit",
     [('    if code is None or RP.identity(code) != rep["checker"]:', '    if False:')], "replay_test", ["R9"]),
    ("M453", "../tools/claimslib/by_replay.py", "pins may name a checker this checkout's replay.py is not",
     [('    if adopted and adopted[-1] != current_checker(repo):', '    if False:')], "replay_test", ["R9"]),
    ("M454", "../tools/claimslib/by_replay.py", "an acceptance of a claim challenged in the replayed store stands",
     [('        if r["type"] == "challenge" and r["body"]["target"] == rep["transition"] \\',
       '        if False and r["type"] == "challenge" and r["body"]["target"] == rep["transition"] \\')],
     "replay_test", ["R10"]),
    ("M455", "../tools/claimslib/by_replay.py", "the re-execution compares nothing with the report",
     [('                if w != rep["witnesses"] or m != rep["mutants"]:', '                if False:')],
     "replay_test", ["R11"]),
    ("M456", "../tools/claimslib/check.py", "a duty may name the checker for an UNBACKED claim (a replay accepts a thesis)",
     [('([[c] for c in pins.get("checkers", [])] if n.backed else [])', '[[c] for c in pins.get("checkers", [])]')],
     "replay_test", ["R12"]),
    ("M457", "../tools/claimslib/author.py", "a supersession keeps its claim's duty whoever that duty names",
     [('            if previous is not None and previous.kind == "normative" and previous.doc["text"] == text \\\n'
       '                    and self.model().recs[previous.doc["duty"]]["body"]["accept_by"] == accept_by:',
       '            if previous is not None and previous.kind == "normative" and previous.doc["text"] == text:')],
     "replay_test", ["R13"]),
    ("M458", "../tools/roadmap.py", "an obligation serving a claim's earlier duty is not mapped to the claim",
     [('        self.claim_of = {n.doc["duty"]: n.id for n in cm.nodes.values() if not n.retired and n.doc["duty"]}',
       '        self.claim_of = {d: cid for cid, d in self.claim_duty.items()}')], "replay_test", ["R13"]),
    ("M459", "../tools/claimslib/why.py", "why knows only a claim's current duty, not its lineage's",
     [('        for n in model.nodes.values():\n            if not n.retired and n.doc["duty"]:',
       '        for n in model.current.values():\n            if not n.retired and n.doc["duty"]:')],
     "replay_test", ["R13"]),
    ("M460", "../tools/claimslib/views.py", "the view names a replay's acceptance by the checker's id, not by what it checked",
     [('    if not by_replay.is_checker(a):\n        return a\n', '    return a\n')], "replay_test", ["R14"]),
    ("M461", "../tools/claimslib/replay.py", "a mutant that crashed its test file counts as killed",
     [('        return ("RAN" if runs is not None else "CRASH"), runs', '        return "RAN", runs or {"T1": "FAIL", "T2": "FAIL"}')],
     "replay_test", ["R2"]),
    ("M462", "../tools/claimslib/replay.py", "the checker replays a claim's superseded transition",
     [('    if any(r["type"] == "transition" and tid in r["body"]["supersedes"] for r in recs.values()):', '    if False:')],
     "replay_test", ["R15"]),
    # AMEND 1 of #176: a reported commit is named by its canonical id (minds VARS-1 §3), never by a ref.
    ("M463", "../tools/claimslib/by_replay.py", "an acceptance's report may name its commit and tree any way",
     [('        if not (RP.is_object_id(rep["commit"], n) and RP.is_object_id(rep["tree"], n)):', '        if False:')],
     "replay_test", ["R16"]),
    ("M464", "../tools/claimslib/by_replay.py", "--verify extracts whatever the report's commit name resolves to now",
     [('            c, bad = resolved(repo, rep)', '            c, bad = rep["commit"], None')], "replay_test", ["R16"]),
    ("M465", "shapes.py", "an object id of another length (an abbreviation) has the shape of one",
     [('    return isinstance(v, str) and len(v) == n and HEX.match(v) is not None',
       '    return isinstance(v, str) and HEX.match(v) is not None')], "replay_test", ["R17"]),
    ("M466", "shapes.py", "any string of an object id's length has its shape (a ref, an expression)",
     [('    return isinstance(v, str) and len(v) == n and HEX.match(v) is not None',
       '    return isinstance(v, str) and len(v) == n')], "replay_test", ["R18"]),
    ("M467", "../tools/claimslib/replay.py", "a full hex id Git resolves to another commit (an annotated tag) is canonical",
     [('    if got != name:', '    if got is None:')], "replay_test", ["R19"]),
    ("M468", "shapes.py", "hex may be uppercase",
     [('HEX = re.compile(r"^[0-9a-f]*\\Z")', 'HEX = re.compile(r"^[0-9a-fA-F]*\\Z")')], "replay_test", ["R20"]),
    ("M469", "shapes.py", "hex may end in a newline (`$`, not \\Z)",
     [('HEX = re.compile(r"^[0-9a-f]*\\Z")', 'HEX = re.compile(r"^[0-9a-f]*$")')], "replay_test", ["R21"]),
    # The agent interface under the spec (SPEC §10): a directory for why --uncovered, a new section of the document
    ("M470", "../tools/claimslib/why.py", "--uncovered DIR takes every file whose path merely starts with DIR",
     [('[p for p in w.files if p.startswith(path + "/")]', '[p for p in w.files if p.startswith(path)]')],
     "why_test", ["Y17"]),
    ("M471", "../tools/claimslib/why.py", "--uncovered takes no directory, only one file",
     [('[p for p in w.files if p.startswith(path + "/")]', '[]')], "why_test", ["Y17"]),
    ("M472", "../tools/claimslib/author.py", "a new section's heading is appended at the end, after later sections",
     [("    if j is not None:\n        return parts[:j]", "    if False:\n        return parts[:j]")],
     "circle_test", ["E1"]),
    ("M473", "../tools/claimslib/author.py", "a sentence may be placed under the heading of another section",
     [("            if after != section:\n", "            if False:\n")], "circle_test", ["E2"]),
    ("M474", "../tools/claimslib/author.py", "--item after a sentence starts no list item",
     [('sep = ("\\n\\n" if paragraph else "\\n") + "- " if item', 'sep = ("\\n\\n" if paragraph else "\\n") + "" if item')],
     "circle_test", ["E1"]),
    # G7: survivors of the generated-mutant hunt (tests/generated_mutants.py), each closed by a
    # witness that kills it on an assertion; the curated twin is what a claim may cite.
    ("M475", "engine.py", "a child whose delegable equals its parent's is not an attenuation",
     [('    if not set(g["delegable"]) <= set(p["delegable"]):', '    if not set(g["delegable"]) < set(p["delegable"]):')],
     "assessment_test", ["R49"]),
    ("M476", "engine.py", "a child expiring exactly with its parent is not an attenuation",
     [('(g["expires"] is None or g["expires"] > p["expires"])', '(g["expires"] is None or g["expires"] >= p["expires"])')],
     "assessment_test", ["R49"]),
    ("M477", "jcs.py", "a value 256 containers deep is refused",
     [("        if depth > MAX_DEPTH:\n", "        if depth >= MAX_DEPTH:\n")], "records_test", ["E10"]),
    ("M478", "jcs.py", "a value 257 containers deep is canonical",
     [("MAX_DEPTH = 256\n", "MAX_DEPTH = 257\n")], "records_test", ["E10"]),
    ("M479", "jcs.py", "loads' depth scan counts brackets inside strings",
     [("        if in_str:\n            if esc:", "        if False:\n            if esc:")], "records_test", ["E10"]),
    ("M480", "store.py", "a trust file may bind one key twice",
     [('            R._need(kid not in self.keys, "a key is bound twice")\n', "")], "records_test", ["K18"]),
    ("M481", "store.py", "a trust file of another version is read",
     [('        R._need(doc["warrant"] == "trust/2", "trust version must be \\"trust/2\\"")\n', "")], "records_test", ["K18"]),
    # The pull request review loop as records (tools/claimslib/reviews.py, review_replay.py; tests/review*_test.py).
    ('M484', '../tools/claimslib/reviews.py', 'a review duty with other terms (an accomplice accepts) is a review',
     [('            if terms != (cfg["owed_to"], cfg["accept_by"], [], {"attest": {}}, [], None, None, None):', '            if False:')],
     "review_check_test", ['V18']),
    ('M485', '../tools/claimslib/reviews.py', 'a second review duty of one pull request replaces the first',
     [('            if pr in self.reviews:\n                self.problem("REVIEW_DUTY_FORK"', '            if False:\n                self.problem("REVIEW_DUTY_FORK"')],
     "review_check_test", ['V18']),
    ('M486', '../tools/claimslib/reviews.py', 'a head blob naming its commit by a ref is a head',
     [('        if not (is_commit(doc["commit"]) and is_commit(doc["tree"])):', '        if False:')],
     "reviews_test", ['V11']),
    ('M487', '../tools/claimslib/reviews.py', 'a finding naming its commit by a ref is refused as another head, not as a ref',
     [('        if not is_commit(doc["commit"]):\n            return "REVIEW_FINDING_COMMIT_NAME"', '        if False:\n            return "REVIEW_FINDING_COMMIT_NAME"')],
     "reviews_test", ['V11']),
    ('M488', '../tools/claimslib/reviews.py', 'a finding filed after the next head is a finding of the current head',
     [('        if later:\n            return "REVIEW_FINDING_SUPERSEDED"', '        if False:\n            return "REVIEW_FINDING_SUPERSEDED"')],
     "reviews_test", ['V12']),
    ('M489', '../tools/claimslib/reviews.py', 'a head may answer a finding nobody filed',
     [('                    if f is None or f.head.item["duty"] != rv.did or f.head.n >= h.n:\n                        self.problem(', '                    if f is None or f.head.item["duty"] != rv.did or f.head.n >= h.n:\n                        continue\n                        self.problem(')],
     "review_check_test", ['V21']),
    ('M490', '../tools/claimslib/reviews.py', 'a finding that passes at its head counts as reproduced',
     [('    return {"FAIL": "REPRODUCED", "PASS": "NOT_REPRODUCED", None: "NOT_REPLAYED"}', '    return {"FAIL": "NOT_REPRODUCED", "PASS": "REPRODUCED", None: "NOT_REPLAYED"}')],
     "reviews_test", ['V04']),
    ('M491', '../tools/claimslib/reviews.py', 'a finding without a test reads as not replayed, not as a thesis',
     [('    if f.test is None:\n        return "THESIS"\n', '')],
     "reviews_test", ['V09']),
    ('M492', '../tools/claimslib/reviews.py', "an observation by any actor counts as the replayer's",
     [('        if r["actor"] not in self.cfg["replayers"]:\n            self.problem("REVIEW_REPLAYER_UNPINNED"', '        if False:\n            self.problem("REVIEW_REPLAYER_UNPINNED"')],
     "review_replay_test", ['V28']),
    ('M493', '../tools/claimslib/reviews.py', "check accepts a current replayer that is not this checkout's review_replay.py",
     [('    if m.cfg["replayers"][-1] != RR.actor(', '    if False and m.cfg["replayers"][-1] != RR.actor(')],
     "review_replay_test", ['V28']),
    ('M494', '../tools/claimslib/reviews.py', "a merge report counts the records' own paths as changed code",
     [('        outside = sorted(p for p in names if not ledger_path(p))', '        outside = sorted(names)')],
     "review_merge_test", ['V13']),
    ('M495', '../tools/claimslib/reviews.py', 'REVIEWS.md is not a generated view in a merge report',
     [('LEDGER_FILES = ("REVIEWS.md", "ROADMAP.md", "SPEC-CLAIMS.md", "WITNESSES.md")', 'LEDGER_FILES = ("ROADMAP.md", "SPEC-CLAIMS.md", "WITNESSES.md")')],
     "review_merge_test", ['V13']),
    ('M496', '../tools/claimslib/reviews.py', 'a tip changed after its accepted head reads as merged at that head',
     [('    if rep["outside"]:\n        return TIP_CHANGED\n', '')],
     "review_merge_test", ['V15']),
    ('M497', '../tools/claimslib/reviews.py', "a merge report reads acceptances from the present store, not the tip's",
     [('    then = Model(store_at(root, tip), trust, cfg).by_duty.get(rv.did)', '    then = Model(Snapshot.read(Path(root) / ".warrant" / "store"), trust, cfg).by_duty.get(rv.did)')],
     "review_merge_test", ['V14']),
    ('M498', '../tools/claimslib/reviews.py', 'the tip of a merge is its first parent',
     [('    base, tip = parents[1], parents[2]', '    base, tip = parents[2], parents[1]')],
     "review_merge_test", ['V13']),
    ('M499', '../tools/claimslib/reviews.py', "check --base takes a new merge observation's report as it is",
     [('    if want != rep:', '    if False:')],
     "review_merge_test", ['V16']),
    ('M500', '../tools/claimslib/reviews.py', 'check --base admits a new head that is not an ancestor of HEAD',
     [('    if not is_ancestor(rv.root, h.commit):\n        return [("REVIEW_COMMIT_NOT_ANCESTOR", f"head', '    if False:\n        return [("REVIEW_COMMIT_NOT_ANCESTOR", f"head')],
     "review_check_test", ['V22']),
    ('M501', '../tools/claimslib/reviews.py', 'check --base admits a new head whose blob names another tree',
     [('    if tree != h.tree:\n        return [("REVIEW_COMMIT_NAME"', '    if False:\n        return [("REVIEW_COMMIT_NAME"')],
     "review_check_test", ['V23']),
    ('M502', '../tools/claimslib/reviews.py', 'check reads REVIEWS.md as text (\\r\\n line ends pass)',
     [('    elif rv.view.read_bytes() != render_view(m).encode():', '    elif rv.view.read_text() != render_view(m):')],
     "review_check_test", ['V17']),
    ('M503', '../tools/claimslib/reviews.py', 'a stale REVIEWS.md passes check',
     [('        out.append(("REVIEWS_STALE"', '        out.append(()) if False else None\n        (("REVIEWS_STALE"')],
     "review_check_test", ['V17']),
    ('M504', '../tools/claimslib/reviews.py', 'a head after an accepted one discharges again instead of revalidating',
     [('        item = R.item(rv.did, "revalidate", [h], revalidates=admitted) if admitted else R.item(rv.did, "discharge", [h])', '        item = R.item(rv.did, "discharge", [h])')],
     "reviews_test", ['V25']),
    ('M505', '../tools/claimslib/reviews.py', 'a finding or acceptance may name a superseded head',
     [('        if last.commit != commit:\n            old =', '        if last.commit != commit and not any(h.commit == commit for h in rv.heads):\n            old =')],
     "reviews_test", ['V12']),
    ('M506', '../tools/claimslib/reviews.py', "anyone may accept a pull request's head",
     [('        if self.actor not in rv.rec["body"]["accept_by"]:\n            raise Refused', '        if False:\n            raise Refused')],
     "reviews_test", ['V24']),
    ('M507', '../tools/claimslib/reviews.py', 'an acceptor may accept a head twice',
     [('        if h.verdict != "PENDING" or self.actor not in h.waiting:', '        if False:')],
     "reviews_test", ['V24']),
    ('M508', '../tools/claimslib/reviews.py', 'head files a closure of a commit that is not an ancestor of HEAD',
     [('        if not is_ancestor(self.rv.root, commit):\n            raise Refused(f"{commit[:12]} is not an ancestor of HEAD: a head', '        if False:\n            raise Refused(f"{commit[:12]} is not an ancestor of HEAD: a head')],
     "review_check_test", ['V22']),
    ('M509', '../tools/claimslib/reviews.py', 'finding files a test whose diff leaves tests/',
     [('        if test is not None and RR.test_problem(test):', '        if False:')],
     "review_replay_test", ['V26']),
    ('M510', '../tools/claimslib/reviews.py', 'open files a second review duty of a pull request',
     [('        if pr in self.m.reviews:\n            raise Refused', '        if False:\n            raise Refused')],
     "review_check_test", ['V18']),
    ('M511', '../tools/claimslib/reviews.py', 'head takes any name Git resolves, not a canonical commit id',
     [('        commit, tree = canonical(self.rv.root, commit)\n        if not is_ancestor', '        commit, tree = commit, _git(self.rv.root, "rev-parse", commit + "^{tree}").decode().strip()\n        if not is_ancestor')],
     "reviews_test", ['V11']),
    ('M512', '../tools/claimslib/reviews.py', "the ledger counts no acceptor's miss",
     [('                    row(a)["misses"] += 1', '                    row(a)["misses"] += 0')],
     "reviews_test", ['V25']),
    ('M513', '../tools/claimslib/reviews.py', 'the ledger counts no answered finding',
     [('        x["answered"] += f.answered_by is not None', '        x["answered"] += 0')],
     "reviews_test", ['V29']),
    ('M514', '../tools/claimslib/reviews.py', 'replay --verify takes an observation as it is',
     [('    if got != result:', '    if False:')],
     "review_replay_test", ['V27']),
    ('M515', '../tools/claimslib/reviews.py', 'two heads naming the same previous are not a fork',
     [('        if forks:\n            rv.fork = True', '        if False:\n            rv.fork = True')],
     "review_check_test", ['V19']),
    ('M522', '../tools/claimslib/reviews.py', "a reviewer's closure of the author's duty is a head",
     [('            if r["actor"] != rv.rec["actor"]:\n', '            if False:\n')],
     "review_check_test", ['V19']),
    ('M523', '../tools/claimslib/reviews.py', 'an acceptance filed after the next head accepts a superseded head unrefused',
     [('            if later:\n                self.problem("REVIEW_ACCEPT_SUPERSEDED"', '            if False:\n                self.problem("REVIEW_ACCEPT_SUPERSEDED"')],
     "reviews_test", ['V12']),
    ('M524', '../tools/claimslib/reviews.py', "a merge report never compares the merge's own tree",
     [('        integ = integration(root, base, last, tree)', '        integ = []')],
     "review_integration_test", ['V30']),
    ('M525', '../tools/claimslib/reviews.py', 'integration changes read as a reviewed merge',
     [('    return INTEGRATION_CHANGES if rep["integration"] else REVIEWED', '    return REVIEWED')],
     "review_integration_test", ['V30']),
    ('M526', '../tools/claimslib/reviews.py', 'a conflict resolved by keeping one side is an integration change',
     [('                  and not (p in conflicted and got.get(p) in (sides[0].get(p), sides[1].get(p))))', '                  )')],
     "review_integration_test", ['V33']),
    ('M527', '../tools/claimslib/reviews.py', "the merge's tree is compared with the accepted head alone, not Git's merge with the base",
     [('    want, got = _entries(root, rows[0]), _entries(root, tree)', '    want, got = _entries(root, head), _entries(root, tree)')],
     "review_integration_test", ['V32']),
    ('M528', '../tools/claimslib/reviews.py', 'an integration Git could not redo reads as reviewed',
     [('    if rep["integration"] is None:\n        return INTEGRATION_UNVERIFIED\n', '')],
     "review_integration_test", ['V30']),
    ('M529', '../tools/claimslib/reviews.py', "the records and their views count as the merge's integration changes",
     [('            if not ledger_path(path):\n                mode, _, oid', '            if True:\n                mode, _, oid')],
     "review_merge_test", ['V13']),
    ('M530', '../tools/roadmap.py', 'a second closure is filed while one waits, without naming it',
     [('        if r["disposition"] != "OPEN" or (pending and pending != [replaces]):', '        if r["disposition"] != "OPEN":')],
     "roadmap_test", ['P15']),
    ('M531', '../tools/roadmap.py', '--replaces may name a closure that is not waiting',
     [('        if replaces is not None and replaces not in pending:', '        if False:')],
     "roadmap_test", ['P15']),
    ('M516', '../tools/claimslib/review_replay.py', 'a test diff may reach outside tests/ through ..',
     [('        if p != "/dev/null" and (not PATCH_PATH.match(p) or ".." in p.split("/")):', '        if p != "/dev/null" and not PATCH_PATH.match(p):')],
     "review_replay_test", ['V26']),
    ('M517', '../tools/claimslib/review_replay.py', 'a test diff may make a symlink',
     [('    if LINK_MODE.match(line) or LINK_INDEX.match(line):\n', '    if False:\n')],
     "review_replay_test", ['V26']),
    ('M518', '../tools/claimslib/review_replay.py', 'a test diff may be binary',
     [('    if line.startswith(("GIT binary patch", "Binary files ")):', '    if False:')],
     "review_replay_test", ['V26']),
    ('M519', '../tools/claimslib/review_replay.py', "a rename's paths are not read",
     [('    if line.startswith(RENAME):\n', '    if False:\n')],
     "review_replay_test", ['V26']),
    ('M520', '../tools/claimslib/review_replay.py', 'a test file that wrote no results counts as a failure (a crash reproduces)',
     [('        except (OSError, ValueError):\n            return "NO_RESULT"', '        except (OSError, ValueError):\n            return "FAIL"')],
     "review_replay_test", ['V26']),
    ('M521', '../tools/claimslib/review_replay.py', 'a diff that does not apply counts as a failure',
     [('            if r.returncode:\n                return "DOES_NOT_APPLY"', '            if r.returncode:\n                return "FAIL"')],
     "review_replay_test", ['V26']),
    ('M534', '../tools/claimslib/eligibility.py', "an acceptance by the pull request's author or its head's filer counts",
     [('        elif a in (author, h.rec["actor"]):', '        elif False:')],
     'review_gate_test', ['G4']),
    ('M535', '../tools/claimslib/eligibility.py', 'the head an acceptance is read for is any accepted head, not the latest',
     [('    h = rv.latest()\n    if h is None:\n        sh.append(("NO_HEAD"', '    h = next((x for x in reversed(rv.heads) if x.accepted_by), rv.latest())\n    if h is None:\n        sh.append(("NO_HEAD"')],
     'review_gate_test', ['G5']),
    ('M536', '../tools/claimslib/eligibility.py', 'changes after the accepted head are not read',
     [('    extra = tail(root, x, head, added, blobs)', '    extra = []')],
     'review_gate_test', ['G11']),
    ('M537', '../tools/claimslib/eligibility.py', 'an entry added to the store after the accepted head may be a symlink',
     [('        if status == "A" and new_mode == REGULAR and record:', '        if status == "A" and record:')],
     'review_gate_test', ['G12']),
    ('M538', '../tools/claimslib/eligibility.py', 'a record or blob changed after the accepted head reads as added',
     [('        if status == "A" and new_mode == REGULAR and record:', '        if new_mode == REGULAR and record:')],
     'review_gate_test', ['G13']),
    ('M539', '../tools/claimslib/eligibility.py', 'any regular file may change after the accepted head, not only the views',
     [(' and old_mode in (REGULAR, "000000") and path in VIEWS:', ' and old_mode in (REGULAR, "000000"):')],
     'review_gate_test', ['G14']),
    ('M540', '../tools/claimslib/eligibility.py', "the configuration and the pins are read from the pull request's head, not the base",
     [('    b = base if isinstance(base, Base) else Base(root, base)', '    b = base if isinstance(base, Base) else Base(root, pr["head"])')],
     'review_gate_test', ['G6', 'G22']),
    ('M541', 'store.py', "a record's signature is not verified (the gate's forged acceptance)",
     [('    if not K.verify(bound[1], env["sig"]["ed25519"], K.sig_message(rid)):', '    if False:')],
     'review_gate_test', ['G7']),
    ('M542', '../tools/claimslib/eligibility.py', 'a finding against the accepted head does not refuse the merge',
     [('    if found:\n        a.reasons.append(("OPEN_FINDING"', '    if False:\n        a.reasons.append(("OPEN_FINDING"')],
     'review_gate_test', ['G8', 'G9']),
    ('M543', '../tools/claimslib/eligibility.py', 'a required check that concluded otherwise than success reads as green',
     [('        elif last.get("conclusion") != "success":', '        elif False:')],
     'review_gate_test', ['G17']),
    ('M544', '../tools/claimslib/eligibility.py', 'a check run of the required name from another workflow is not refused',
     [('        if other:\n', '        if False:\n')],
     'review_gate_test', ['G18']),
    ('M545', '../tools/claimslib/eligibility.py', 'a check run posted by any app counts as the required check',
     [(' and r.get("head_sha") == head and (r.get("app") or {}).get("slug") == ACTIONS_APP]', ' and r.get("head_sha") == head]')],
     'review_gate_test', ['G19']),
    ('M546', '../tools/claimslib/eligibility.py', 'the hold label holds nothing',
     [('    if b.gate["hold_label"] in pr["labels"]:', '    if False:')],
     'review_gate_test', ['G20']),
    ('M547', '../tools/claimslib/eligibility.py', 'the global hold holds nothing',
     [('    if hold:\n        out.append(("GATE_HOLD"', '    if False:\n        out.append(("GATE_HOLD"')],
     'review_gate_test', ['G21']),
    ('M548', '../tools/claimslib/eligibility.py', "the accepted commit need not be in the head's history",
     [('    if not is_ancestor(root, x, head):', '    if False:')],
     'review_gate_test', ['G16']),
    ('M549', '../tools/claimslib/eligibility.py', "a head with a reviewer's verdict is still due for review",
     [('        return not self.shared and not self.verdict', '        return not self.shared')],
     'review_gate_test', ['G3', 'G9']),
    ('M550', '../tools/claimslib/gate.py', 'the merge does not name the head it assessed',
     [('{"sha": _sha(sha), "merge_method": "merge",', '{"merge_method": "merge",')],
     'review_gate_test', ['G23']),
    ('M551', '../tools/claimslib/gate.py', 'a head that moved after the assessment is merged',
     [('    if now["head"] != head:', '    if False:')],
     'review_gate_test', ['G24']),
    ('M552', '../tools/claimslib/gate.py', 'no workflow is dispatched on the base after a merge (master CI would not run)',
     [('    for w in sorted({c["workflow"] for c in b.gate["required"]}):', '    for w in []:')],
     'review_gate_test', ['G23']),
    ('M553', '../tools/claimslib/eligibility.py', 'a store entry that is not a regular file is read',
     [('        if (mode, typ) != (REGULAR, "blob") or not named:', '        if not named:')],
     'review_gate_test', ['G12']),
    ('M554', '../tools/claimslib/eligibility.py', 'an acceptance by a pinned actor outside accept_by counts',
     [('        if a not in base.cfg["accept_by"]:', '        if False:')],
     'review_gate_test', ['G25']),
    ('M555', '../tools/claimslib/eligibility.py', "a problem in the head's review records does not refuse",
     [('    if model.problems:', '    if False:')],
     'review_gate_test', ['G26']),
    ('M556', '../tools/claimslib/eligibility.py', 'a pull request into another branch is merged',
     [('    if pr["base"] != b.gate["base"]:', '    if False:')],
     'review_gate_test', ['G27']),
    ('M557', '../tools/claimslib/eligibility.py', 'a blob not named by its hash is read under that name',
     [('        elif C.digest(data[oid]) == name:', '        elif True:')],
     'review_gate_test', ['G28']),
    ('M558', '../tools/claimslib/eligibility.py', 'a change to an owner path (what decides merging) is merged by the gate',
     [('    if owned is None or owned:', '    if False:')],
     'review_gate_test', ['G29', 'G30']),
    ('M559', '../tools/claimslib/eligibility.py', 'an owner path ending in / names no directory',
     [(' or (e.endswith("/") and p.startswith(e))', '')],
     'review_gate_test', ['G29']),
    ('M560', '../tools/claimslib/eligibility.py', 'a record added after the accepted head is merged whatever it is',
     [('    if stray:', '    if False:')],
     'review_gate_test', ['G31', 'G32']),
    ('M561', '../tools/claimslib/eligibility.py', "the pull request's own review records added after X count as unreviewed",
     [('    return sorted(r for r in added if r not in mine\n                  and (', '    return sorted(r for r in added if True\n                  and (')],
     'review_gate_test', ['G3']),
    ('M562', '../tools/claimslib/gate.py', "the pull request read again before the merge is not held to the predicate's own rules",
     [('    changed = EL.pr_reasons(b, now)', '    changed = []')],
     'review_gate_test', ['G33']),
    # ROADMAP.md: a shared prerequisite once per goal; a goal opened again unchanged (tools/roadmap.py).
    ('M563', '../tools/roadmap.py', "a duty's full line is printed again under each duty that requires it",
     [('    if did in shown:\n', '    if did in seen:\n')], 'roadmap_test', ['P17']),
    ('M564', '../tools/roadmap.py', "a goal another revision opens again unchanged reads REFORMULATED",
     [('((REOPENED if nxt.text == f.text else REFORMULATED), nxt.ref)', '(REFORMULATED, nxt.ref)')],
     'roadmap_test', ['P6', 'P18']),
    ('M565', '../tools/roadmap.py', "a goal opened again unchanged reads unowned although obligations answer its text",
     [('"answered_as": reopened_from(m, fs, f)}', '"answered_as": []}')], 'roadmap_test', ['P18']),
    ('M566', '../tools/roadmap.py', "a duty that requires itself through others is not marked as a cycle",
     [('        if did in seen:\n            out["cycle"] = True', '        if False:\n            out["cycle"] = True')],
     'roadmap_test', ['P19']),
    ('M567', '../tools/roadmap.py', "an obligation is printed before the obligations it requires",
     [('        out.append((ready or rest)[0])', '        out.append(rest[0])')], 'roadmap_test', ['P20']),
    # The proof-space pilot's resolution layer (G9 PS-02..PS-04; warrant/pilot.py) and its contract (PS-01; tools/pilot.py).
    ('M568', 'pilot.py', 'bytes a store holds under a name are not hashed before they are read as an object',
     [('            if C.digest(data) != h:\n', '            if False:\n')], 'pilot_test', ['A2']),
    ('M569', 'pilot.py', 'a store holding other bytes under a name is passed over for the next store',
     [('                raise _Stop("DIGEST_MISMATCH", address,', '                continue\n                raise _Stop("DIGEST_MISMATCH", address,')],
     'pilot_test', ['A2']),
    ('M570', 'pilot.py', "an object is not checked to be of its address's kind before its dependency fields are read",
     [('        if value is None:\n            raise _Stop("KIND_MISMATCH"', '        if False:\n            raise _Stop("KIND_MISMATCH"')],
     'pilot_test', ['A3', 'A5']),
    ('M571', 'pilot.py', 'an address is admitted on the length of its hash, not its shape',
     [('    if not (sep and S.hex64(h)):', '    if not (sep and len(h) == 64):')], 'pilot_test', ['A4', 'D4']),
    ('M572', 'pilot.py', "a store follows a symlinked directory below its root, outside its real directory",
     [('os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent', 'os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent')],
     'pilot_test', ['A6', 'A10']),
    ('M573', 'pilot.py', "the receiver admits every kind the code knows, not the kinds it configured",
     [('        self.kinds = {k: KINDS[k] for k in names}', '        self.kinds = dict(KINDS)')], 'pilot_test', ['A7']),
    ('M574', 'pilot.py', 'the verifier runs on a closure that did not resolve',
     [('        return verify(res) if res["result"] == RESOLVED else res', '        return verify(res)')], 'pilot_test', ['D3']),
    ('M575', 'pilot.py', 'an address met again on its own reference path is not a cycle',
     [('                if dep in on_path:\n', '                if False:\n')], 'pilot_test', ['D5']),
    ('M576', 'pilot.py', 'a reference to an object already resolved does not count toward pilot_edges',
     [('                if dep in objects:\n', '                if dep in objects:\n                    used["edges"] -= 1\n')],
     'pilot_test', ['D6']),
    ('M577', 'pilot.py', 'pilot_depth bounds only the path walked, not the longest chain through a shared object',
     [('                    L.admit(lim, "pilot_depth", len(path) + height[dep])\n', '')], 'pilot_test', ['D7', 'D11']),
    ('M578', 'pilot.py', "an object's bytes are read without being admitted against pilot_bytes",
     [('            admit(st.st_size)\n', '')], 'pilot_test', ['D9']),
    ('M579', 'pilot.py', 'the number of objects is not bounded',
     [('        L.admit(lim, "pilot_objects", len(objects) + 1)\n', '')], 'pilot_test', ['D6']),
    ('M580', 'pilot.py', "a receipt's checkpoint and state are not dependencies of its closure",
     [(',\n            f"sigma-checkpoint:{doc[\'checkpoint\']}", f"sigma-state:{doc[\'state\']}"]', ']')],
     'pilot_test', ['D1', 'D2']),
    ('M581', 'pilot.py', "a receipt's dependency fields are read without SPEC §7's receipt shape",
     [('    why = P.receipt_problem(doc)\n    if why:\n        raise ValueError(why)\n', '')], 'pilot_test', ['D8', 'D3']),
    ('M582', 'pilot.py', 'a root may carry members besides schema and requires',
     [('    if set(doc) != {"schema", "requires"}:', '    if False:')], 'pilot_test', ['A8']),
    ('M583', 'pilot.py', 'a missing object is a refusal, not inconclusive',
     [('"MISSING": INCONCLUSIVE', '"MISSING": REFUSED')], 'pilot_test', ['D2', 'A5', 'A6']),
    ('M584', 'pilot.py', "a profile's provider identity need not be the one its module digests give",
     [('    if v["provider"] != P.identity_of_files(mods):', '    if False:')], 'pilot_test', ['F3']),
    ('M585', 'pilot.py', 'a profile may carry members besides its declared operands',
     [('set(doc) == PROFILE_FIELDS and', 'PROFILE_FIELDS <= set(doc) and')], 'pilot_test', ['F3']),
    ('M586', 'pilot.py', 'a provider module may be pinned by any string, not a hex64 digest',
     [('all(S.hex64(x) for x in mods.values())', 'all(isinstance(x, str) for x in mods.values())')], 'pilot_test', ['F3']),
    ('M587', 'pilot.py', "a profile's axioms and assumptions need not be in their one order without repeats",
     [('\n            and v == sorted(set(v)))', ')')], 'pilot_test', ['F3']),
    ('M588', 'pilot.py', "a profile's id leaves out its axioms",
     [('    return C.doc_id(doc)\n', '    return C.doc_id({k: v for k, v in doc.items() if k != "axioms"})\n')],
     'pilot_test', ['F1', 'F2']),
    ('M589', 'pilot.py', "a profile's verifier may carry members besides its declared operands",
     [('set(v) == VERIFIER_FIELDS', 'VERIFIER_FIELDS <= set(v)')], 'pilot_test', ['F3']),
    ('M591', 'pilot.py', 'the fanout layout is read at another path than a warrant-agent object store writes',
     [('        return (name[:2], name[2:])', '        return (name[:2], name)')], 'pilot_test', ['A1']),
    ('M592', 'pilot.py', 'a shared dependency is read again at each reference',
     [('                if dep in objects:\n', '                if False:\n')], 'pilot_test', ['D1']),
    ('M593', 'pilot.py', "a JSON kind's bytes are normalized instead of refused when they are not canonical",
     [('            doc = C.loads(data)', '            doc = C.loads(C.canon(C.json.loads(data)))')], 'pilot_test', ['F4', 'A3']),
    ('M600', 'pilot.py', 'a kind the receiver does not admit is a refusal, not inconclusive',
     [('"UNKNOWN_KIND": INCONCLUSIVE', '"UNKNOWN_KIND": REFUSED')], 'pilot_test', ['A7', 'D4']),
    ('M601', 'pilot.py', "the profile of an installed provider leaves out the pilot's execution-profile assumptions",
     [('"assumptions": sorted(set(assumptions))}', '"assumptions": sorted(set(assumptions))[:1]}')], 'pilot_test', ['F1']),
    ('M602', 'pilot.py', 'an object is opened in a way that waits on a FIFO before its type is checked',
     [('os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd', 'os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd')],
     'pilot_test', ['A9']),
    ('M604', 'pilot.py', 'the bytes read are not admitted again when the file grew after fstat',
     [('                    admit(len(data))\n', '')], 'pilot_test', ['D9']),
    ('M605', 'pilot.py', 'a file grown after fstat is read only to the size fstat gave plus one byte, a prefix',
     [('                    more = f.read(1 << 16)', '                    more = b""')], 'pilot_test', ['D10']),
    ('M606', 'pilot.py', "a JSON kind's tag lets the parser's other ValueErrors escape the resolver",
     [('        except ValueError:\n            return None', '        except C.NotCanonical:\n            return None')],
     'pilot_test', ['A11']),
    ('M607', 'pilot.py', "a receiver's limits that are not a mapping are read as no limits, or fail unhandled",
     [('        if limits is not None and not isinstance(limits, dict):', '        if False:')], 'pilot_test', ['A12']),
    ('M608', 'pilot.py', "a store's layout that is not a string is looked up anyway",
     [('isinstance(s["layout"], str) and s["layout"] in LAYOUTS', 's["layout"] in LAYOUTS')], 'pilot_test', ['A12']),
    ('M594', '../tools/pilot.py', 'a contract row citing a case the test file does not have holds',
     [('out.append(("UNKNOWN_CASE", f"{r[\'id\']} cites {t}, not a case of {TEST}"))', 'pass')], 'pilot_test', ['K2']),
    ('M595', '../tools/pilot.py', "a contract row may cite a mutant that targets none of its cases",
     [('            elif m[4] != TEST or not set(m[5]) & set(r["tests"]):', '            elif False:')], 'pilot_test', ['K2']),
    ('M596', '../tools/pilot.py', 'a contract row may be deferred to a card no filed G9 obligation names',
     [('        if "deferred" in r and r["deferred"] not in cards:', '        if False:')], 'pilot_test', ['K2']),
    ('M597', '../tools/pilot.py', 'a PILOT.md that is not the rendering of the contract source passes',
     [('    if view != render(contract, cards):', '    if False:')], 'pilot_test', ['K2']),
    ('M598', '../tools/pilot.py', "a deferred row is rendered without the duty of the card it is deferred to",
     [('f"deferred to {row[\'deferred\']}, duty `{str(cards.get(row[\'deferred\']))[:12]}`"', 'f"deferred to {row[\'deferred\']}"')],
     'pilot_test', ['K1']),
    # The review waker runs the review replay checker before Codex is woken (waker.py Waker.replay); the
    # checker's observations of any finding are admitted after the reviewed head (eligibility.py).
    ('M609', '../integrations/codex-plugin/waker/waker.py', "a replay may use the network",
     [('"(allow default)", "(deny network*)", ', '"(allow default)", ')], 'review_replay_test', ['W3']),
    ('M610', '../integrations/codex-plugin/waker/waker.py', "a replay may read the checker's seeds",
     [('[self.replayers, *(Path.home() / s for s in SECRETS)]', '[*(Path.home() / s for s in SECRETS)]')],
     'review_replay_test', ['W3']),
    ('M611', '../integrations/codex-plugin/waker/waker.py', "a replay may write anywhere",
     [('"(deny network*)", "(deny file-write*)",', '"(deny network*)",')], 'review_replay_test', ['W3']),
    ('M612', '../integrations/codex-plugin/waker/waker.py', "the waker pushes any record a replay left in the store, printed by the checker or not",
     [('        if xy == "??" and path in want:', '        if xy == "??" and path.startswith(STORE + "records/"):')],
     'review_replay_test', ['W5']),
    ('M613', '../integrations/codex-plugin/waker/waker.py', "the waker pushes an observation signed by any identity",
     [('rec.get("type") == "observation" and rec.get("actor") == actor', 'rec.get("type") == "observation"')],
     'review_replay_test', ['W6']),
    ('M614', '../integrations/codex-plugin/waker/waker.py', "the base's checker replays a pull request that changes the checker",
     [('        if self.blob(base, CHECKER_FILE) != self.blob(head, CHECKER_FILE):', '        if False:')],
     'review_replay_test', ['W9']),
    ('M615', '../integrations/codex-plugin/waker/waker.py', "the observations are pushed wherever the branch now is",
     [('        if tip[:1] != [head]:', '        if False:')], 'review_replay_test', ['W10']),
    ('M616', '../integrations/codex-plugin/waker/waker.py', "Codex is woken in the run that pushed observations, at the head they are not on",
     [('            if not pushed:\n', '            if True:\n')], 'review_replay_test', ['W2']),
    ('M617', '../tools/claimslib/eligibility.py', "the checker's observations of another pull request's finding count as unreviewed",
     [('{o for f in model.findings.values() for o, _ in f.observed.values()}', '{o for f in rv.findings for o, _ in f.observed.values()}')],
     'review_gate_test', ['G34']),
    ('M618', '../tools/claimslib/eligibility.py', "any observation after the reviewed head counts as a replay",
     [('{o for f in model.findings.values() for o, _ in f.observed.values()}', '{o for o, r in model.recs.items() if r["type"] == "observation"}')],
     'review_gate_test', ['G35']),
    ('M619', '../tools/claimslib/review_replay.py', "the checker runs a finding test whose diff reaches outside tests/",
     [('    why = test_problem(test)\n    if why:\n        raise ValueError(why)\n', '    why = test_problem(test)\n')],
     'review_replay_test', ['W8']),
    ('M620', '../tools/claimslib/reviews.py', "a finding filed by hand whose test diff reaches outside tests/ is a finding",
     [('        if doc["test"] is not None:\n            why = RR.test_problem(doc["test"])', '        if False:\n            why = RR.test_problem(doc["test"])')],
     'review_replay_test', ['W7']),
    ('M621', '../integrations/codex-plugin/waker/waker.py', "a seed others may read is used",
     [(' or st.st_mode & 0o077', '')], 'review_replay_test', ['W11']),
    ('M622', '../integrations/codex-plugin/waker/waker.py', "a link to a seed is followed",
     [('            st = path.lstat()', '            st = path.stat()')], 'review_replay_test', ['W11']),
    ('M623', '../tools/claimslib/reviews.py', "`replay --key -` does not read the seed from standard input",
     [('if a.cmd == "replay" and a.key == "-"', 'if False')], 'review_replay_test', ['W1']),
    ('M624', '../tools/claimslib/reviews.py', "a replay observation after the reviewed head is not re-executed against its result",
     [('    if got != result:', '    if False:')], 'review_gate_test', ['G36']),
    # Acceptance due (tools/roadmap.py acceptance_due): the obligation closures the review waker wakes Codex for;
    # a pull request of his verdicts only is merge-eligible (eligibility.py); the waker's acceptance wakes.
    ('M625', 'engine.py', "a closure whose required duty is not DISCHARGED is due for the acceptor's verdict",
     [('    unmet = [c for c in d["requires"] if done.get(c) != "DISCHARGED"]', '    unmet = [c for c in d["requires"] if False]')],
     'roadmap_test', ['P21']),
    ('M626', '../tools/roadmap.py', "a closure the acceptor already accepted is due again (its accept_by is read, not what it awaits)",
     [('or actor not in (c.get("waiting_for") or [])', 'or actor not in m.recs[did]["body"]["accept_by"]')],
     'roadmap_test', ['P22']),
    ('M627', '../tools/roadmap.py', "a closure is due for any actor while it awaits anyone",
     [('or actor not in (c.get("waiting_for") or [])', 'or not c.get("waiting_for")')],
     'roadmap_test', ['P23']),
    ('M628', '../tools/roadmap.py', "a closure the acceptor challenged is due for its verdict",
     [('                or (c["transition"], c["item"]) in challenged:', '                or False:')], 'roadmap_test', ['P24']),
    ('M629', '../tools/roadmap.py', "anyone's challenge hides a closure from the acceptor",
     [('if r["type"] == "challenge" and r["actor"] == actor}', 'if r["type"] == "challenge"}')], 'roadmap_test', ['P24']),
    ('M630', '../tools/roadmap.py', "a closure filed over (done --replaces) is due instead of the one filed in its place",
     [('        c = closures[-1] if closures else None', '        c = closures[0] if closures else None')], 'roadmap_test', ['P25']),
    ('M652', '../tools/roadmap.py', "a filed-over closure is due again once the one filed in its place is admitted (Codex finding aeacfd5c933e)",
     [('if c["act"] in CLOSING]', 'if c["verdict"] == "PENDING"]')], 'roadmap_test', ['P30']),
    ('M653', '../integrations/codex-plugin/waker/waker.py', "two items of one transition share one wake (Codex finding 3acb42fc0511)",
     [('        return f"{record_id(c[\'closure\'])}-{c[\'item\']}"', '        return record_id(c[\'closure\'])')],
     'review_replay_test', ['W15']),
    ('M631', '../tools/claimslib/eligibility.py', "a pull request of an acceptor's records of any type merges as verdicts",
     [(' and model.recs[r]["type"] in ("accept", "challenge")', '')], 'review_gate_test', ['G40']),
    ('M632', '../tools/claimslib/eligibility.py', "an accept by any pinned actor merges as a verdict",
     [('\n                      and model.recs[r]["actor"] in b.cfg["accept_by"])', ')')], 'review_gate_test', ['G39']),
    ('M633', '../tools/claimslib/eligibility.py', "a pull request of verdicts may change more than the store and the views",
     [('    if tail(root, mb, head, added, blobs):\n        return None\n', '    tail(root, mb, head, added, blobs)\n')],
     'review_gate_test', ['G41']),
    ('M634', '../tools/claimslib/eligibility.py', "a pull request of verdicts only is due for review",
     [('    a.verdict = True\n    a.accept = (first["actor"]', '    a.accept = (first["actor"]')], 'review_gate_test', ['G37']),
    ('M635', '../tools/claimslib/gate.py', "the merge commit of a pull request of verdicts names a head closure it does not have",
     [('    if a.facts.get("verdicts"):\n        title', '    if False:\n        title')], 'review_gate_test', ['G42']),
    ('M636', '../integrations/codex-plugin/waker/waker.py', "a wake that exited 0 is woken again in every run",
     [('        if what != "retry":\n            return False, detail\n', '')], 'review_replay_test', ['W12']),
    ('M637', '../integrations/codex-plugin/waker/waker.py', "a closure whose wake is done holds the next one as if it were woken",
     [('            return False, detail\n', '            return True, detail\n')], 'review_replay_test', ['W13']),
    ('M638', '../integrations/codex-plugin/waker/waker.py', "every due closure is woken in one run",
     [('        if woken:\n            why_not = ', '        if False:\n            why_not = ')], 'review_replay_test', ['W13']),
    ('M639', '../integrations/codex-plugin/waker/waker.py', "an acceptance wake starts while Codex's verdict pull request is open",
     [('    if verdicts:\n        return f"held: verdict pull request', '    if False:\n        return f"held: verdict pull request')],
     'review_replay_test', ['W13']),
    ('M640', '../integrations/codex-plugin/waker/waker.py', "an acceptance wake starts when the open pull requests could not be read",
     [('    if found.get("refused"):\n        return "held: the open', '    if False:\n        return "held: the open')],
     'review_replay_test', ['W13']),
    # Gemini's review of #194 head 2, verified by the orchestrating session: the verdict path's admission and the
    # tail's blobs (eligibility.py), the predicate's item and disposition (roadmap.py).
    ('M654', '../tools/claimslib/eligibility.py', "a pull request of verdicts from a fork merges",
     [('    if pr.get("head_repo") != b.cfg["repository"]:', '    if False:')], 'review_gate_test', ['G43']),
    ('M655', '../tools/claimslib/eligibility.py', "a pull request of verdicts from any branch merges",
     [('    if not str(pr.get("branch") or "").startswith(VERDICT_BRANCH):', '    if False:')], 'review_gate_test', ['G44']),
    ('M656', '../tools/claimslib/eligibility.py', "a verdict the base holds already, added again from an earlier commit, counts as new",
     [('    old = [v for v in verdicts if v in held]', '    old = []')], 'review_gate_test', ['G45']),
    ('M646', '../tools/claimslib/eligibility.py', "a verdict on a closure the base's acceptance_due does not name merges",
     [('    late = [v for v in verdicts if _closure_of(model.recs[v]) not in due.get(model.recs[v]["actor"], set())]', '    late = []')],
     'review_gate_test', ['G45', 'G46']),
    ('M647', '../tools/claimslib/eligibility.py', "a pull request of verdicts may add blobs no verdict cites",
     [('        out.append(("TAIL_BLOB_UNCITED"', '        (("TAIL_BLOB_UNCITED"')], 'review_gate_test', ['G47']),
    ('M648', '../tools/claimslib/eligibility.py', "after an accepted head, a blob no record added there cites merges",
     [('        sh.append(("TAIL_BLOB_UNCITED"', '        (("TAIL_BLOB_UNCITED"')], 'review_gate_test', ['G48']),
    ('M649', '../tools/roadmap.py', "a challenge of one item of a transition (or of its results) hides all its closures",
     [('                or (c["transition"], c["item"]) in challenged:', '                or c["transition"] in {x for x, _ in challenged}:')],
     'roadmap_test', ['P28']),
    ('M651', '../integrations/codex-plugin/waker/waker.py', "a fork's pull request named under codex/verdicts/ holds the acceptance wakes",
     [('if x.get("head_repo") == REPO\n', 'if True\n')], 'review_replay_test', ['W16']),
    ('M650', '../tools/roadmap.py', "a closure of a duty already DISCHARGED is due when it is the duty's latest",
     [('        if m.rep["duties"][did]["disposition"] != "OPEN":\n            continue\n', '')], 'roadmap_test', ['P29']),
    # Gemini review of 1a660a6 (engine, pilot): each defect it reported, by the rule it broke.
    ('M641', 'engine.py', "a replacement closure retires the one it supersedes only once its results are accepted",
     [('for old in rep["results"][t]["supersedes"]}', 'for old in rep["results"][t]["supersedes"] if rep["results"][t]["accepted"]}')],
     'contract_test', ['F6']),
    ('M645', 'engine.py', "an admitted delegation retires the pending closure its transition supersedes (Codex 1e7a0108b247)",
     [('if c["verdict"] == "ADMITTED"\n                          and c["act"] in CLOSING_ACTS}', 'if c["verdict"] == "ADMITTED"}')],
     'contract_test', ['F7']),
    # Merge observations filed from Git's history (merged --due) and required at a head (V34-V36).
    ('M657', '../tools/claimslib/reviews.py', "a merge subject naming #10 is read as #1's",
     [('rf"Merge pull request #{rv.pr}(?: |\\Z)"', 'rf"Merge pull request #{rv.pr}"')], 'review_merge_test', ['V35']),
    ('M658', '../tools/claimslib/reviews.py', "a merge that holds none of the pull request's heads is its merge",
     [('_git(root, "log", "--merges", "--ancestry-path", "--format=%H%x00%s", f"{last.commit}..{upto}")',
       '_git(root, "log", "--merges", "--format=%H%x00%s", f"{last.commit}..{upto}")')], 'review_merge_test', ['V35']),
    ('M659', '../tools/claimslib/reviews.py', "a head is filed while a merge in its history is unobserved",
     [('        if missing:\n            raise Refused(f"{commit[:12]}\'s store', '        if False:\n            raise Refused(f"{commit[:12]}\'s store')],
     'review_merge_test', ['V34']),
    ('M660', '../tools/claimslib/reviews.py', "of two merges that both name the pull request, the first is taken",
     [('    if len(found) > 1:\n        raise Refused(f"#{rv.pr} merged at', '    if False:\n        raise Refused(f"#{rv.pr} merged at')],
     'review_merge_test', ['V36']),
    ('M661', '../tools/claimslib/reviews.py', "merged --due observes a pull request observed already",
     [('    return [(n, mc) for n, rv in sorted(model.reviews.items()) if not rv.merges\n',
       '    return [(n, mc) for n, rv in sorted(model.reviews.items())\n')], 'review_merge_test', ['V35']),
    ('M662', '../tools/claimslib/reviews.py', "a head counts merge observations filed after its commit, not in its own store",
     [('unobserved(self.rv.root, Model(store_at(self.rv.root, commit), self.rv.repo.trust(), self.cfg), commit)',
       'unobserved(self.rv.root, self.m, commit)')], 'review_merge_test', ['V35']),
    ('M663', '../tools/claimslib/reviews.py', "a merge observation may name a merge that brought none of the pull request's heads in",
     [("    if not any(_contains(root, h.commit, tip) and not _contains(root, h.commit, base) for h in rv.heads):",
       "    if False:")], 'review_merge_test', ['V37']),
    ('M664', '../tools/claimslib/reviews.py', "a later merge that holds the head through its first parent is the pull request's merge",
     [("_contains(root, h.commit, tip) and not _contains(root, h.commit, base) for h in rv.heads",
       "_contains(root, h.commit, tip) for h in rv.heads")], 'review_merge_test', ['V37']),
    ('M642', '../tools/roadmap.py', "done --replaces names the declined closure only in its residual, not in supersedes",
     [('subject=commit, supersedes=[replaces] if replaces else [])', 'subject=commit)')], 'roadmap_test', ['P26']),
    ('M643', 'pilot.py', "a chain through a shared object is admitted only when its parent is left, after later siblings are read",
     [('                    L.admit(lim, "pilot_depth", len(path) + height[dep])\n', ''),
      ('            height[address] = max((1 + height.get(d, 0) for d in deps), default=0)\n',
       '            height[address] = max((1 + height.get(d, 0) for d in deps), default=0)\n'
       '            L.admit(lim, "pilot_depth", len(path) - 1 + height[address])\n')], 'pilot_test', ['D11']),
    ('M644', 'pilot.py', "a store path with a NUL byte is accepted and raises on the first read",
     [('        if "\\x00" in str(self.root):', '        if False:')], 'pilot_test', ['A13']),
]
# M18 edits store.py instead: authenticity must check the key's actor.
MUTANTS[17] = ("M18", "store.py", "a key bound to another actor authenticates",
               [('    if bound[0] != rec["actor"]:\n', '    if False:\n')], "contract_test", ["N5"])


# A run writes no bytecode into the tree whose identity (source_digest) its matrix names,
# whatever the caller's environment: the test files import tests/world.py and friends from the
# checkout, and a __pycache__ git does not ignore (claims.py's fixture has no .gitignore) would
# change the identity during the run (CI run 39788553711; locally PYTHONDONTWRITEBYTECODE=1 hid it).
NO_BYTECODE = "1"


def run_tests(tmp, tests, timeout=900):
    """{test file: {case: PASS|FAIL}, or None when it produced no results}: each named test
    file run against the packages in `tmp` (WARRANT_IMPL), with results of its own."""
    runs = {}
    for t in tests:
        res = tmp / f"results-{t}.json"
        env = dict(os.environ, WARRANT_IMPL=str(tmp), WARRANT_RESULTS=str(res), PYTHONDONTWRITEBYTECODE=NO_BYTECODE)
        subprocess.run([sys.executable, str(ROOT / "tests" / f"{t}.py")], env=env, capture_output=True,
                       cwd=ROOT / "tests", timeout=timeout, check=False)
        runs[t] = json.loads(res.read_text()) if res.exists() else None
    return runs


def verdict(runs, test, targets):
    """(outcome, detail) from the mutant's own test file: KILLED only when a target fails."""
    if runs.get(test) is None:
        return "CRASH", "no results"
    failed = sorted(k for k, v in runs[test].items() if v == "FAIL")
    if set(failed) & set(targets):
        return "KILLED", ",".join(failed)
    return ("OFF_TARGET", ",".join(failed)) if failed else ("SURVIVED", "")


def run_one(mid, fname, what, edits, test, targets, also=()):
    """(outcome, detail, runs): the mutant applied to a copy of the package, its own test
    file run, then the test files of `also` (for --matrix)."""
    tmp = Path(tempfile.mkdtemp(prefix=f"warrant-{mid}-"))
    try:
        shutil.copytree(PKG, tmp / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
        if fname.startswith("../"):
            # A tool beside the package (../tools/roadmap.py): its directory is copied whole, so
            # the tool's own imports (tools/claims.py) come from the same copy; the test loads it
            # from $WARRANT_IMPL/tools.
            outside = Path(fname[3:]).parts[0]
            shutil.copytree(ROOT / outside, tmp / outside, ignore=shutil.ignore_patterns("__pycache__"))
            p = tmp / fname[3:]
        else:
            p = tmp / "warrant" / fname
        src = p.read_text()
        for old, new in edits:
            if src.count(old) != 1:
                return "BAD_MUTANT", f"{old[:50]!r} found {src.count(old)} times", {}
            src = src.replace(old, new)
        p.write_text(src)
        runs = run_tests(tmp, [test] + [t for t in also if t != test])
        return (*verdict(runs, test, targets), runs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse_args(argv, ids, prog):
    """Options and mutant ids are parsed apart, so a worker count can never become a selector
    (Codex AMEND on 944d085: `--jobs +2` and `--jobs -1` selected nothing and reported 0/0 as
    success). Any bad value exits 2 before a single mutant runs."""
    import argparse
    import os
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2, metavar="N",
                    help="parallel workers, an integer >= 1 (default: the CPU count)")
    ap.add_argument("--matrix", metavar="FILE", help="also write every case's result under every mutant to FILE")
    ap.add_argument("--matrix-tests", default="own", metavar="own|all|T1,T2",
                    help="--matrix: the test files each mutant runs (default: its own only)")
    ap.add_argument("ids", nargs="*", metavar="ID", help="mutant ids to run (default: all of them)")
    ap.add_argument("--shard", metavar="K/N", help="run only part K of N of the mutants (see shards())")
    ns = ap.parse_args(argv)
    if ns.jobs < 1:
        ap.error(f"--jobs must be >= 1, got {ns.jobs}")
    if ns.shard is not None:
        k, _, n = ns.shard.partition("/")
        if not (k.isdigit() and n.isdigit() and 1 <= int(k) <= int(n)) or k != str(int(k)) or n != str(int(n)):
            ap.error(f"--shard must be K/N with 1 <= K <= N, got {ns.shard!r}")
        if ns.ids:
            ap.error("--shard runs a part of all the mutants; it takes no ids")
        ns.shard = (int(k), int(n))
    known = sorted(p.stem for p in (ROOT / "tests").glob("*_test.py"))
    if ns.matrix_tests in ("own", "all"):
        ns.also = [] if ns.matrix_tests == "own" else known
    else:
        ns.also = [t for t in ns.matrix_tests.split(",") if t]
        bad = sorted(set(ns.also) - set(known)) or ([] if ns.also else ["(none)"])
        if bad:
            ap.error(f"--matrix-tests: not a test file of tests/: {', '.join(bad)}")
    if ns.matrix_tests != "own" and not ns.matrix:
        ap.error("--matrix-tests needs --matrix")
    unknown = sorted(set(ns.ids) - set(ids))
    if unknown:
        ap.error(f"unknown mutant id(s): {', '.join(unknown)}")
    return ns


MATRIX = "warrant-mutants/matrix@1"


class SourceUnknown(Exception):
    """The root is not the top level of a git checkout, so its sources have no identity."""


def _git(root, *args):
    out = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args], capture_output=True, check=False)
    if out.returncode != 0:
        raise SourceUnknown(f"git {' '.join(args)} in {root}: {out.stderr.decode(errors='replace').strip()}")
    return out.stdout


def source_digest(root=ROOT):
    """The identity of the sources a matrix answers for: the whole tree the git checkout at
    `root` holds, with no list of folders. Code, tools, tests, records and documents are all
    sources: which folder a byte lives in says nothing about whether a run depended on it
    (AMEND 1 of #172: a change to tools/roadmap.py alone left the old digest of warrant/,
    warrant_agent/ and tests/*.py unchanged, and --merge accepted a stale matrix).

    A clean working tree (no change to a tracked file, no untracked file git does not ignore)
    is named by its git tree id, "tree:<id>". A dirty one is named "worktree:<sha256>" over the
    path, mode and bytes of every tracked and every untracked unignored file as it is on disk
    (a deleted file is absent from it). So any change anywhere, committed or not, gives
    another identity; files git ignores (caches, build output) are not sources. A dirty tree
    is not refused: the local `claims.py audit` loop needs matrices of uncommitted work, and the
    working-tree digest names those bytes as exactly as a tree id names committed ones.
    --merge (SHARD_STALE), every --matrix of both harnesses (run_all checks the identity did
    not change during the run) and tools/claims.py audit (MATRIX_STALE) compare through this
    function only. SourceUnknown when `root` is not the top level of a git checkout."""
    import hashlib
    root = Path(root).resolve()
    top = _git(root, "rev-parse", "--show-toplevel").decode().strip()
    if Path(top).resolve() != root:
        raise SourceUnknown(f"{root} is not the top level of a git checkout (that is {top})")
    if not _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        return "tree:" + _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    tracked = [x for x in _git(root, "ls-files", "-z", "--cached").decode().split("\0") if x]
    untracked = [x for x in _git(root, "ls-files", "-z", "--others", "--exclude-standard").decode().split("\0") if x]
    h = hashlib.sha256()
    for rel in sorted(set(tracked) | set(untracked)):
        f = root / rel
        if f.is_symlink():
            mode, data = b"120000", os.readlink(f).encode()
        elif f.is_file():
            mode, data = (b"100755" if os.access(f, os.X_OK) else b"100644"), f.read_bytes()
        else:
            continue                # deleted: its absence from the digest is the change
        h.update(rel.encode() + b"\0" + mode + b"\0" + hashlib.sha256(data).digest())
    return "worktree:" + h.hexdigest()


def mutant_digest(m):
    """The digest of one matrix row's definition: (id, file, what, edits, test, targets)."""
    import hashlib
    return hashlib.sha256(json.dumps([m[0], m[1], m[2], [list(e) for e in m[3]], m[4], list(m[5])]).encode()).hexdigest()


# Seconds of one run of each test file on the CI runner (ubuntu-latest, 4 vCPU; PR #170, run
# 39769980930), plus about half a second to copy the package. They only balance the shards: a
# wrong or missing number makes one shard slower, it never drops a mutant, since --merge
# recomputes the same partition and refuses any id that is missing or twice.
COST = {"contract_test": 17.9, "compute_test": 3.8, "conditions_test": 0.2, "assessment_test": 0.9,
        "primitives_test": 0.1, "records_test": 0.2, "cli_test": 0.3, "roadmap_test": 3.1, "circle_test": 0.9,
        "agent_handoff_test": 7.0, "agent_write_test": 1.9, "agent_compute_test": 1.9, "agent_mcp_test": 17.0,
        "why_test": 1.3, "store_index_test": 1.3, "shapes_test": 0.1, "replay_test": 4.0, "agent_repo_test": 6.6,
        "reviews_test": 6.7, "review_check_test": 3.9, "review_merge_test": 10.0, "review_replay_test": 25.0,
        "review_integration_test": 9.5, "agent_views_test": 16.0, "review_gate_test": 30.0,
        "pilot_test": 4.0}     # why_test: 0.5 s locally x 2.5 (master c436bd5), until a CI measurement; store_index_test: 0.5 s locally, the same factor; agent_repo_test: 2.6 s locally, the same factor; reviews_test 2.7 s, review_check_test 1.5 s, review_merge_test 2.0 s, review_replay_test 1.0 s, review_integration_test 3.8 s locally, the same factor; agent_views_test: 13.4 s locally, of which 10.5 s sleep past a view's TTL; review_gate_test: 20.4 s locally while review_integration_test took 12.3 s (9.5 s on CI), so about 16 s; review_replay_test 23 s and review_gate_test 34 s locally with the review waker's cases (W1-W11, G34-G36), until a CI measurement; review_merge_test 4.1 s locally with V34-V36, the same factor


def _cost(m):
    return COST.get(m[4], 1.0) + 0.5


def shards(mutants, n, cost=_cost):
    """`mutants` in n parts, a function of the ids, their test files and the cost (COST, or a
    hunt's) only: the costliest first (ties in list order), each to the part with the least cost
    so far (ties to the lowest part). Each part keeps the list order. Every mutant is in exactly
    one part."""
    load, parts = [0.0] * n, [[] for _ in range(n)]
    for i, m in sorted(enumerate(mutants), key=lambda x: (-cost(x[1]), x[0])):
        k = min(range(n), key=lambda j: (load[j], j))
        load[k] += cost(m)
        parts[k].append(i)
    return [[mutants[i] for i in sorted(p)] for p in parts]


def _environment(m):
    """What a mutant's run copies besides the package: the directory of a tool beside it."""
    return Path(m[1][3:]).parts[0] if m[1].startswith("../") else ""


def baseline_red(chosen, runner, jobs):
    """Each test file the chosen mutants target, run once unmutated through the same runner
    (so in the same copied environment, no edits): [(test, environment, failing target cases or
    None when the run gave no results, ids of the mutants that target those cases)]. A red target makes
    every mutant on it read KILLED (primitives#5), so a red one refuses the whole run."""
    import concurrent.futures
    groups = {}
    for m in chosen:
        groups.setdefault((m[4], _environment(m)), []).append(m)
    keys = sorted(groups)

    def base(key):
        ms = groups[key]
        targets = sorted({t for m in ms for t in m[5]})
        got = runner(f"baseline:{key[0]}", ms[0][1], "unmutated", [], key[0], targets)
        runs = got[2] if len(got) > 2 else {}
        return targets, runs.get(key[0])

    red = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for key, (targets, cases) in zip(keys, pool.map(base, keys)):
            failing = None if cases is None else [t for t in targets if cases.get(t) == "FAIL"]
            if failing is None or failing:
                red.append((*key, failing, [m[0] for m in groups[key] if failing is None or set(m[5]) & set(failing)]))
    return red


# How run_all and merge treat mutants that look for blind spots instead of guarding a rule
# (tests/generated_mutants.py): judge(row, m) recomputes a row's outcome from its runs, cost(m)
# balances the shards, baseline(chosen) gives the red files as baseline_red does, from a run made
# before (no runner call). Any outcome is a result: the exit status says the run happened, and
# merge checks each row against judge() instead of requiring KILLED.
Hunt = collections.namedtuple("Hunt", "judge cost baseline")


def run_all(mutants, label, argv, runner, prog="mutants", root=ROOT, hunt=None):
    """Run `mutants` in parallel (--jobs N in argv, default: the CPU count): each one already
    works in its own copy of the package and its own results file, so nothing is shared.
    Output keeps the given order; ids in argv select mutants. The 2026-10-21 CI run with 89
    mutants took 21 of the job's 25 minutes in series. Before any mutant, each targeted test
    file runs once unmutated; a target case that does not pass there refuses the run with
    BASELINE_RED (exit 2). With --matrix the source identity (source_digest) is taken before the
    first run and again before writing: a tree that changed meanwhile, or has no identity, gets
    no matrix (exit 2). Exit 0 only when at least one mutant ran and every one was KILLED;
    a bad option or id exits 2 (SystemExit from argparse). --merge: see merge(). With a `hunt`
    (Hunt) the baseline and the shard costs are the hunt's, --matrix-tests is refused, and the
    exit status is 0 once every chosen mutant has an outcome, whichever it is."""
    import concurrent.futures
    if argv[:1] == ["--merge"]:
        return merge(mutants, label, argv[1:], prog, root=root, hunt=hunt)
    ns = parse_args(argv, [m[0] for m in mutants], prog)
    if hunt and ns.matrix_tests != "own":
        print(f"{label}: --matrix-tests is not an option of a hunt: each mutant runs the test files that execute it")
        return 2
    pick = set(ns.ids)
    chosen = [m for m in mutants if not pick or m[0] in pick]
    if ns.shard:
        chosen = shards(mutants, ns.shard[1], *([hunt.cost] if hunt else []))[ns.shard[0] - 1]
        label = f"{label} shard {ns.shard[0]}/{ns.shard[1]}"
    if not chosen:
        print(f"{label}: no mutants selected; nothing was checked")
        return 2
    before = None
    if ns.matrix:
        try:
            before = source_digest(root)
        except SourceUnknown as e:
            print(f"{label}: SOURCE_UNKNOWN, no matrix can name what it ran: {e}")
            return 2
    red = hunt.baseline(chosen) if hunt else baseline_red(chosen, runner, ns.jobs)
    for test, env, failing, ids in red:
        where = f"{test}" + (f" (with {env}/)" if env else "")
        what = "gave no results" if failing is None else f"fails {','.join(failing)}"
        print(f"BASELINE_RED {where} unmutated {what}; targeted by {' '.join(ids)}")
    if red:
        print(f"{label}: BASELINE_RED, no mutant was run: a target case that fails without a mutant "
              "would read as a kill")
        return 2
    killed, rows, tally = 0, {}, {}
    call = (lambda m: runner(*m, also=ns.also)) if ns.matrix else (lambda m: runner(*m))
    with concurrent.futures.ThreadPoolExecutor(max_workers=ns.jobs) as pool:
        for m, got in zip(chosen, pool.map(call, chosen)):
            outcome, detail = got[0], got[1]
            killed += outcome == "KILLED"
            tally[outcome] = tally.get(outcome, 0) + 1
            print(f"{outcome:<11} {m[0]} {m[1]}: {m[2]}  [{detail}]", flush=True)
            rows[m[0]] = {"definition": mutant_digest(m), "file": m[1], "what": m[2], "test": m[4],
                          "targets": list(m[5]), "outcome": outcome, "runs": got[2] if len(got) > 2 else {}}
            if hunt:
                rows[m[0]]["detail"] = detail
    if hunt:
        print(f"{label}: {len(chosen)} run: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) + f" (jobs={ns.jobs})")
    else:
        print(f"{label}: {killed}/{len(chosen)} killed on target (jobs={ns.jobs})")
    if ns.matrix:
        after = source_digest(root)
        if after != before:
            print(f"{label}: SOURCE_CHANGED, the tree changed during the run ({before} -> {after}); "
                  f"no matrix written to {ns.matrix}")
            return 2
        doc = {"matrix": MATRIX, "harness": prog, "tests": ns.matrix_tests, "source": after,
               "mutants": rows}
        if ns.shard:
            doc["shard"] = list(ns.shard)
        Path(ns.matrix).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        print(f"{label}: matrix of {len(rows)} mutants ({ns.matrix_tests}) written to {ns.matrix}")
    return 0 if hunt or killed == len(chosen) else 1


def check_matrices(docs, mutants, prog, root=ROOT, hunt=None, gate=True, complete=True, prefix="SHARD"):
    """(problems, rows, source): the one validation of matrices that every reader stating what they
    say goes through: --merge here, tests/generated_mutants.py report, tools/claims.py audit (Codex
    AMEND 1 of #178: report trusted the outcomes of a matrix --merge would have refused). `docs` is
    [(name, document)]; `mutants` the list as defined now. Problems, each a (PREFIX_CODE, detail):
    NOT_THIS_HARNESS (not a matrix of `prog`), SOURCE_UNKNOWN / STALE (written over other sources
    than source_digest(root), or a row of a mutant defined otherwise now), SHAPE (documents run with
    different --matrix-tests), DUPLICATE_ID, UNKNOWN_ID, OUTCOME (an outcome the row's own runs do
    not give: hunt.judge, else verdict()), NOT_KILLED (`gate`: every row must be KILLED on target),
    MISSING_ID (`complete`: an id of the list in no document). `rows` holds only the rows with no
    problem of their own; a caller writes or states nothing unless `problems` is empty."""
    def code(c):
        return f"{prefix}_{c}"
    problems = []
    try:
        src = source_digest(root)
    except SourceUnknown as e:
        src = None
        problems.append((code("SOURCE_UNKNOWN"), str(e)))
    by_id = {m[0]: m for m in mutants}
    if len({json.dumps(d.get("tests")) if isinstance(d, dict) else "" for _, d in docs}) > 1:
        problems.append((code("SHAPE"), "the files were run with different --matrix-tests"))
    rows, where = {}, {}
    for f, d in docs:
        if not (isinstance(d, dict) and d.get("matrix") == MATRIX and d.get("harness") == prog
                and isinstance(d.get("mutants"), dict)):
            got = (d.get("matrix"), d.get("harness")) if isinstance(d, dict) else (type(d).__name__, None)
            problems.append((code("NOT_THIS_HARNESS"), f"{f}: {got[0]!r} by {got[1]!r}, not a matrix of {prog}"))
            continue
        if src is not None and d.get("source") != src:
            problems.append((code("STALE"), f"{f}: written over other sources than this checkout's"))
        for mid, row in sorted(d["mutants"].items()):
            if mid in where:
                problems.append((code("DUPLICATE_ID"), f"{mid} in {where[mid]} and {f}"))
                continue
            where[mid] = f
            m = by_id.get(mid)
            if m is None:
                problems.append((code("UNKNOWN_ID"), f"{f}: {mid} is not a mutant of {prog}.py"))
                continue
            if not isinstance(row, dict) or row.get("definition") != mutant_digest(m):
                problems.append((code("STALE"), f"{f}: {mid} is not the current definition"))
                continue
            got = hunt.judge(row, m) if hunt else verdict(row.get("runs") or {}, m[4], m[5])[0]
            if row.get("outcome") != got:
                problems.append((code("OUTCOME"), f"{f}: {mid} is {row.get('outcome')}, its runs give {got}"))
                continue
            if gate and got != "KILLED":
                problems.append((code("NOT_KILLED"), f"{f}: {mid} is {row.get('outcome')}, its runs give {got}"))
                continue
            rows[mid] = row
    missing = [m[0] for m in mutants if m[0] not in where] if complete else []
    if missing:
        problems.append((code("MISSING_ID"), f"{len(missing)} not run: {' '.join(missing)}"))
    return problems, rows, src


def merge(mutants, label, argv, prog, root=ROOT, hunt=None):
    """--merge OUT PART.json ...: the matrices of the parts of one run (--shard K/N --matrix),
    checked against this checkout and joined into one matrix OUT as an unsharded run writes it.
    Refused (exit 1, OUT not written) unless every file is a matrix of this harness over these
    sources with one --matrix-tests, no id is in two files, no id is outside the list, every id of
    the list is in one, every row is the current definition of its mutant, and every outcome is
    KILLED as verdict() recomputes it from the row's own runs. So OUT means: every mutant of the
    list was run once and killed on its target; which part ran it is not part of the claim.
    With a `hunt` the last condition is that every row's outcome is the one hunt.judge recomputes
    from it, whatever it is: OUT means every mutant was run once, and says what each gave."""
    if len(argv) < 2:
        print(f"usage: {prog}.py --merge OUT PART.json [PART.json ...]", file=sys.stderr)
        return 2
    out, files = argv[0], argv[1:]
    problems, docs = [], []
    for f in files:
        try:
            docs.append((f, json.loads(Path(f).read_text())))
        except (OSError, ValueError) as e:
            problems.append(("SHARD_UNREADABLE", f"{f}: {e}"))
    more, rows, src = check_matrices(docs, mutants, prog, root, hunt=hunt, gate=not hunt)
    problems += more
    for code, why in problems:
        print(f"{code:<22} {why}")
    if problems:
        print(f"{label} MERGE: REFUSED ({len(problems)} problems); {out} not written")
        return 1
    doc = {"matrix": MATRIX, "harness": prog, "tests": docs[0][1]["tests"], "source": src, "mutants": rows}
    Path(out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    if hunt:
        print(f"{label} MERGE: {len(rows)}/{len(mutants)} mutants, each run once in one of {len(docs)} files, "
              f"each outcome recomputed from its runs; matrix written to {out}")
        return 0
    print(f"{label} MERGE: {len(rows)}/{len(mutants)} mutants, each run once in one of {len(docs)} files and "
          f"killed on target; matrix written to {out}")
    return 0


def source_checks():
    """The source identity is the whole tree (AMEND 1 of #172), checked on a fixture repository
    made of this checkout's tracked and untracked files, with a genuine KILLED row of M300 (a
    ../tools/roadmap.py mutant) merged over it."""
    import contextlib
    import io
    m300 = next(m for m in MUTANTS if m[0] == "M300")
    got = run_one(*m300)
    work = Path(tempfile.mkdtemp(prefix="mutants-selftest-sources-"))
    git = ["git", "-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "-c", "commit.gpgsign=false"]
    try:
        fix = work / "root"
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                capture_output=True, check=True).stdout.decode().split("\0")
        for rel in sorted({x for x in listed if x}):
            if (ROOT / rel).is_file():
                (fix / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, fix / rel)
        subprocess.run(["git", "init", "-q", str(fix)], check=True)
        subprocess.run([*git, "-C", str(fix), "add", "-A"], check=True)
        subprocess.run([*git, "-C", str(fix), "commit", "-q", "-m", "fixture"], check=True)
        clean = source_digest(fix)
        row = {"definition": mutant_digest(m300), "file": m300[1], "what": m300[2], "test": m300[4],
               "targets": list(m300[5]), "outcome": got[0], "runs": got[2]}

        def part(source):
            f = work / "part.json"
            f.write_text(json.dumps({"matrix": MATRIX, "harness": "mutants", "tests": "own", "source": source,
                                     "mutants": {"M300": row}}))
            return f

        def merged(f):
            out = work / "merged.json"
            out.unlink(missing_ok=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = merge([m300], "SOURCES", [str(out), str(f)], "mutants", root=fix)
            return rc, out.is_file(), "SHARD_STALE" in buf.getvalue()

        def changed(f, rel, edit, keep=False):
            """merge `f` after `edit` (bytes -> bytes, or None: delete) on fix/rel, then undo it."""
            path = fix / rel
            was = path.read_bytes() if path.is_file() else None
            mode = path.stat().st_mode if path.is_file() else None
            new = edit(was)
            if new is None:
                path.unlink()
            elif isinstance(new, int):
                path.chmod(new)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(new)
            try:
                return merged(f)
            finally:
                if was is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(was)
                    path.chmod(mode)
        m300_edit = lambda b: b.replace(m300[3][0][0].encode(), m300[3][0][1].encode())
        add = lambda b: b + b"\n"
        GOOD, STALE = (0, True, False), (1, False, True)
        f = part(clean)
        tree = subprocess.run(["git", "-C", str(fix), "rev-parse", "HEAD^{tree}"], capture_output=True,
                              check=True).stdout.decode().strip()
        checks = [
            ("a genuine run of M300 is KILLED on P9", got[0] == "KILLED"),
            ("a clean tree is named by its git tree id", clean == "tree:" + tree),
            ("--merge of the genuine row over the unchanged tree passes", merged(f) == GOOD),
            ("an uncommitted M300 edit of tools/roadmap.py: SHARD_STALE, nothing written",
             changed(f, "tools/roadmap.py", m300_edit) == STALE),
            ("an uncommitted change of tools/claims.py: SHARD_STALE", changed(f, "tools/claims.py", add) == STALE),
            ("an uncommitted change of .warrant/roles.json: SHARD_STALE", changed(f, ".warrant/roles.json", add) == STALE),
            ("an uncommitted change of README.md: SHARD_STALE", changed(f, "README.md", add) == STALE),
            ("a new untracked file anywhere: SHARD_STALE", changed(f, "examples/new-file.txt", lambda b: b"x") == STALE),
            ("a deleted tracked file: SHARD_STALE", changed(f, "ROADMAP.md", lambda b: None) == STALE),
            ("a file made executable: SHARD_STALE", changed(f, "README.md", lambda b: 0o755) == STALE),
            ("a file git ignores is not a source", changed(f, "tests/__pycache__/x.cpython-311.pyc", lambda b: b"x") == GOOD),
            ("the change undone, the tree merges again", merged(f) == GOOD),
        ]
        (fix / "README.md").write_bytes((fix / "README.md").read_bytes() + b"\n")
        subprocess.run([*git, "-C", str(fix), "commit", "-q", "-am", "readme"], check=True)
        checks.append(("a committed change of README.md (a clean tree, another tree id): SHARD_STALE", merged(f) == STALE))
        subprocess.run(["git", "-C", str(fix), "reset", "-q", "--hard", "HEAD~1"], check=True)
        (fix / "tools" / "roadmap.py").write_bytes(m300_edit((fix / "tools" / "roadmap.py").read_bytes()))
        dirty = source_digest(fix)
        g = part(dirty)
        checks += [
            ("a dirty tree is named by its working-tree digest", dirty.startswith("worktree:") and dirty != clean),
            ("a matrix of a dirty tree merges over the same bytes", merged(g) == GOOD),
            ("... and is SHARD_STALE after one more byte anywhere", changed(g, ".warrant/roles.json", add) == STALE),
            ("... or in README.md", changed(g, "README.md", add) == STALE),
            ("... or after a new untracked file", changed(g, "examples/new-file.txt", lambda b: b"x") == STALE),
            ("... or after a tracked file is deleted", changed(g, "ROADMAP.md", lambda b: None) == STALE),
            ("... or after a file is made executable", changed(g, "README.md", lambda b: 0o755) == STALE),
            ("... but not after a change to a file git ignores", changed(g, "tests/__pycache__/x.cpython-311.pyc", lambda b: b"x") == GOOD),
            ("... and SHARD_STALE once the dirty change is undone", changed(g, "tools/roadmap.py", lambda b: (ROOT / "tools" / "roadmap.py").read_bytes()) == STALE),
        ]
        fake = [("F1", "x.py", "fake", [], "t", ["c"])]

        def write(argv_root, touch=None):
            out = work / "written.json"
            out.unlink(missing_ok=True)

            def runner(*m, also=()):
                if touch and not m[0].startswith("baseline:"):
                    touch()
                return "KILLED", "c", {m[4]: {"c": "FAIL" if not m[0].startswith("baseline:") else "PASS"}}
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    rc = run_all(fake, "SOURCES", ["--jobs", "1", "--matrix", str(out)], runner, root=argv_root)
                except Exception as e:      # a crash is not the refusal this checks
                    rc = f"raised {type(e).__name__}"
            return rc, json.loads(out.read_text())["source"] if out.is_file() else None
        roles = fix / ".warrant" / "roles.json"
        was = roles.read_bytes()
        checks += [
            ("--matrix names the tree it ran over", write(fix) == (0, dirty)),
            ("--matrix writes nothing when the tree changes during the run (SOURCE_CHANGED)",
             write(fix, touch=lambda: roles.write_bytes(was + b"\n")) == (2, None)),
            ("--matrix writes nothing over a root with no identity (SOURCE_UNKNOWN)", write(work) == (2, None)),
        ]
        roles.write_bytes(was)
        subprocess.run(["git", "-C", str(fix), "checkout", "-q", "--", "."], check=True)     # M300's text back
        (fix / ".gitignore").unlink()
        subprocess.run([*git, "-C", str(fix), "commit", "-q", "-am", "no ignore rules"], check=True)
        bare = source_digest(fix)
        mx = work / "real.json"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        env["WARRANT_IMPL"] = ""
        real = subprocess.run([sys.executable, str(fix / "tests" / "mutants.py"), "--jobs", "1", "--matrix", str(mx), "M300"],
                              cwd=fix, env=env, capture_output=True, text=True, timeout=600, check=False)
        checks.append(("a real --matrix run in a tree that ignores nothing, by a caller that writes bytecode, "
                       "leaves the tree as it was and names it",
                       real.returncode == 0 and mx.is_file() and json.loads(mx.read_text())["source"] == bare
                       and source_digest(fix) == bare and bare.startswith("tree:")))
        mx.unlink(missing_ok=True)
        real = subprocess.run([sys.executable, str(fix / "tests" / "agent_mutants.py"), "--jobs", "1", "--matrix", str(mx), "A19"],
                              cwd=fix, env=env, capture_output=True, text=True, timeout=600, check=False)
        checks.append(("... and so does a real --matrix run of tests/agent_mutants.py",
                       real.returncode == 0 and mx.is_file() and json.loads(mx.read_text())["source"] == bare
                       and source_digest(fix) == bare))
        try:
            source_digest(fix / "tools")
            inner = False
        except SourceUnknown:
            inner = True
        checks.append(("a directory inside a checkout has no identity of its own", inner))
        try:
            source_digest(work)
            outside = False
        except SourceUnknown:
            outside = True
        checks.append(("a directory outside any checkout has no identity", outside))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return checks


def selftest():
    """The controller against fixture runners, and both entry points as subprocesses: a worker
    count is never a selector, a bad one is refused before any run, and no selection ever
    succeeds without running something."""
    import contextlib
    import io
    fake = [("F1", "x.py", "fake one", [], "t", ["c"]), ("F2", "x.py", "fake two", [], "t", ["c"])]
    calls = []

    def survived(*m):
        calls.append(m[0])
        return "SURVIVED", ""

    def killed(*m):
        calls.append(m[0])
        return "KILLED", "c"

    based = []

    def green(mid, fname, what, edits, test, targets):
        return "SURVIVED", "", {test: {t: "PASS" for t in targets}}

    printed = []

    def run(argv, runner, mutants=fake, base=green, prog="mutants"):
        """rc and the mutants run, in list order; `base` answers the unmutated runs (ids
        baseline:<test>). The workers call the runners in whatever order the thread pool starts
        them (Python 3.13 on 14 cores: F1 F3 F2 F4 for four), so `calls` is the set of runs put
        in list order, and the order of the verdicts is checked on the output (`printed`)."""
        calls.clear()
        based.clear()
        printed.clear()
        out = io.StringIO()

        def both(*m, **kw):
            if m[0].startswith("baseline:"):
                based.append((m[0], m[1], tuple(m[3])))
                return base(*m)
            return runner(*m, **kw)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = run_all(mutants, "SELFTEST", argv, both, prog=prog)
            except SystemExit as e:
                rc = e.code
        printed.extend(out.getvalue().splitlines())
        order = {m[0]: i for i, m in enumerate(mutants)}
        return rc, sorted(calls, key=lambda c: order.get(c[0] if isinstance(c, tuple) else c, -1))

    checks = [
        ("--jobs 2 runs every mutant and a survivor fails the run", run(["--jobs", "2"], survived) == (1, ["F1", "F2"])),
        ("--jobs 2 with every mutant killed succeeds", run(["--jobs", "2"], killed) == (0, ["F1", "F2"])),
        ("--jobs 1 runs in series with the same verdict", run(["--jobs", "1"], killed) == (0, ["F1", "F2"])),
        ("--jobs +2 is two workers, not a selector", run(["--jobs", "+2"], survived) == (1, ["F1", "F2"])),
        ("--jobs -1 is refused before any mutant runs", run(["--jobs", "-1"], killed) == (2, [])),
        ("--jobs 0 is refused", run(["--jobs", "0"], killed) == (2, [])),
        ("--jobs two is refused", run(["--jobs", "two"], killed) == (2, [])),
        ("--jobs without a value is refused", run(["--jobs"], killed) == (2, [])),
        ("--job is not an abbreviation of --jobs", run(["--job", "2"], killed) == (2, [])),
        ("an unknown id is refused, never an empty success", run(["ZZ"], killed) == (2, [])),
        ("a known and an unknown id together are refused", run(["F1", "ZZ"], killed) == (2, [])),
        ("ids select, and the verdicts print in matrix order",
         run(["F2", "F1"], killed) == (0, ["F1", "F2"]) and [x.split()[1] for x in printed if x.startswith("KILLED")] == ["F1", "F2"]),
        ("an empty matrix is not a success", run([], killed, mutants=[]) == (2, [])),
    ]
    # --matrix: every case's result under every mutant, the verdict still from the own test file
    out = Path(tempfile.mkdtemp(prefix="mutants-selftest-")) / "m.json"

    def with_runs(*m, also=()):
        calls.append((m[0], tuple(also)))
        return "KILLED", "c", {"t": {"c": "FAIL", "d": "PASS"}, **{a: {"x": "PASS"} for a in also}}
    rc_m = run(["--jobs", "2", "--matrix", str(out)], with_runs)
    doc = json.loads(out.read_text()) if out.is_file() else {}
    rows = doc.get("mutants", {})
    rc_all = run(["--matrix", str(out), "--matrix-tests", "contract_test,records_test"], with_runs)
    rows_all = json.loads(out.read_text()).get("mutants", {}) if out.is_file() else {}
    shutil.rmtree(out.parent, ignore_errors=True)
    checks += [
        ("--matrix writes every mutant's runs, case by case", rc_m[0] == 0 and doc.get("matrix") == MATRIX
         and sorted(rows) == ["F1", "F2"] and rows["F1"]["runs"] == {"t": {"c": "FAIL", "d": "PASS"}}
         and rows["F1"]["outcome"] == "KILLED" and rows["F1"]["definition"] == mutant_digest(fake[0])
         and doc.get("source") == source_digest()),
        ("--matrix-tests names the extra test files each mutant runs",
         rc_all[0] == 0 and rows_all.get("F2", {}).get("runs", {}).get("records_test") == {"x": "PASS"}
         and ("F1", ("contract_test", "records_test")) in rc_all[1]),
        ("--matrix-tests without --matrix is refused", run(["--matrix-tests", "all"], with_runs) == (2, [])),
        ("--matrix-tests with an unknown test file is refused",
         run(["--matrix", str(out), "--matrix-tests", "nosuch_test"], with_runs) == (2, [])),
        ("--matrix-tests with no test file is refused", run(["--matrix", str(out), "--matrix-tests", ","], with_runs) == (2, [])),
    ]
    # The red baseline (primitives#5): a target case that fails unmutated refuses the run
    def red(mid, fname, what, edits, test, targets):
        return "KILLED", "c", {test: {"c": "FAIL", "d": "PASS"}}

    def other_red(mid, fname, what, edits, test, targets):
        return "OFF_TARGET", "d", {test: {"c": "PASS", "d": "FAIL"}}

    def no_results(mid, fname, what, edits, test, targets):
        return "CRASH", "no results", {test: None}
    spread = fake + [("F3", "../tools/y.py", "fake three", [], "t", ["c"]), ("F4", "x.py", "fake four", [], "u", ["e"])]
    rc_green = run([], killed, mutants=spread)
    based_green = sorted(based)
    checks += [
        ("a failing target case unmutated is refused BASELINE_RED before any mutant runs",
         run(["--jobs", "2"], killed, base=red) == (2, [])),
        ("a red baseline is refused even when every mutant would read KILLED", run([], killed, base=red)[0] == 2),
        ("a targeted test file that gives no results unmutated is refused", run([], killed, base=no_results) == (2, [])),
        ("a failing case no chosen mutant targets does not refuse", run([], killed, base=other_red) == (0, ["F1", "F2"])),
        ("BASELINE_RED names the failing target cases and only the mutants that target them",
         baseline_red([("F1", "x.py", "", [], "t", ["c"]), ("F2", "x.py", "", [], "t", ["d"])], red, 1)
         == [("t", "", ["c"], ["F1"])]),
        ("a green baseline proceeds to every mutant", rc_green == (0, ["F1", "F2", "F3", "F4"])),
        ("the baseline runs each test file once per copied environment, unmutated",
         based_green == [("baseline:t", "../tools/y.py", ()), ("baseline:t", "x.py", ()), ("baseline:u", "x.py", ())]),
        ("only the test files of the selected mutants get a baseline",
         run(["F4"], killed, mutants=spread) == (0, ["F4"]) and based == [("baseline:u", "x.py", ())]),
    ]
    # --shard K/N: a deterministic partition, each mutant in one part; --merge proves the union
    many = [(f"F{i}", "x.py", f"fake {i}", [], ["t", "u", "contract_test"][i % 3], ["c"]) for i in range(1, 12)]
    parts = shards(many, 3)
    checks += [
        ("shards() puts every mutant in exactly one part",
         sorted(m[0] for p in parts for m in p) == sorted(m[0] for m in many) and all(parts)),
        ("shards() is a function of the list", parts == shards(list(many), 3)),
        ("shards() balances COST: the costly files are spread",
         max(sum(m[4] == "contract_test" for m in p) for p in parts) - min(sum(m[4] == "contract_test" for m in p) for p in parts) <= 1),
        ("shards() places the costliest first: one costly and two cheap in two parts leave the costly one alone",
         [[m[0] for m in q] for q in shards([("F1", "x.py", "", [], "t", ["c"]), ("F2", "x.py", "", [], "t", ["c"]),
                                             ("F3", "x.py", "", [], "contract_test", ["c"])], 2)] == [["F3"], ["F1", "F2"]]),
        ("--shard 0/3 is refused", run(["--shard", "0/3"], killed, mutants=many) == (2, [])),
        ("--shard 4/3 is refused", run(["--shard", "4/3"], killed, mutants=many) == (2, [])),
        ("--shard 1/03 is refused", run(["--shard", "1/03"], killed, mutants=many) == (2, [])),
        ("--shard with ids is refused", run(["--shard", "1/3", "F1"], killed, mutants=many) == (2, [])),
    ]
    sd = Path(tempfile.mkdtemp(prefix="mutants-selftest-shards-"))

    def own_runs(*m, also=()):
        calls.append((m[0], tuple(also)))
        return "KILLED", "c", {m[4]: {"c": "FAIL", "d": "PASS"}}
    for k in (1, 2, 3):
        rc_k = run(["--shard", f"{k}/3", "--matrix", str(sd / f"s{k}.json")], own_runs, mutants=many)
        checks.append((f"--shard {k}/3 runs exactly its part", rc_k == (0, [(m[0], ()) for m in parts[k - 1]])))
    checks.append(("a shard's baseline covers only its own part's test files",
                   sorted({b[0] for b in based}) == sorted({f"baseline:{m[4]}" for m in parts[2]})))

    def merged(names, prog="mutants", tamper=None):
        files = [str(sd / n) for n in names]
        if tamper:
            d = json.loads((sd / names[0]).read_text())
            tamper(d)
            (sd / "x.json").write_text(json.dumps(d))
            files[0] = str(sd / "x.json")
        out = sd / "merged.json"
        out.unlink(missing_ok=True)
        rc = run(["--merge", str(out), *files], killed, mutants=many, prog=prog)[0]
        return rc, json.loads(out.read_text()) if out.is_file() else None

    def flip(d):
        d["mutants"][sorted(d["mutants"])[0]]["outcome"] = "SURVIVED"

    def lie(d):
        mid = sorted(d["mutants"])[0]
        d["mutants"][mid]["runs"] = {"t": {"c": "PASS"}, "u": {"c": "PASS"}, "contract_test": {"c": "PASS"}}

    def drop(d):
        d["mutants"].pop(sorted(d["mutants"])[0])

    def redefine(d):
        d["mutants"][sorted(d["mutants"])[0]]["definition"] = "0" * 64

    def resource(d):
        d["source"] = "0" * 64
    def alien(d):
        d["mutants"]["F99"] = dict(next(iter(d["mutants"].values())))
    rc_ok, doc_ok = merged(["s1.json", "s2.json", "s3.json"])
    if doc_ok:
        (sd / "merged-all.json").write_text(json.dumps(doc_ok))
    checks += [
        ("--merge of all parts writes one matrix of every mutant, without a shard",
         rc_ok == 0 and sorted(doc_ok["mutants"]) == sorted(m[0] for m in many) and "shard" not in doc_ok
         and doc_ok["matrix"] == MATRIX and doc_ok["source"] == source_digest()),
        ("--merge refuses a missing part", merged(["s1.json", "s3.json"]) == (1, None)),
        ("--merge refuses a part given twice", merged(["s1.json", "s2.json", "s3.json", "s2.json"]) == (1, None)),
        ("--merge refuses a part without one of its ids", merged(["s1.json", "s2.json", "s3.json"], tamper=drop) == (1, None)),
        ("--merge refuses an id outside the list", merged(["s1.json", "s2.json", "s3.json"], tamper=alien) == (1, None)),
        ("--merge refuses parts run with different --matrix-tests",
         merged(["s1.json", "s2.json", "s3.json"], tamper=lambda d: d.update(tests="all")) == (1, None)),
        ("--merge of one unsharded matrix of every mutant is the same claim", merged(["merged-all.json"])[0] == 0),
        ("--merge refuses an outcome that is not KILLED", merged(["s1.json", "s2.json", "s3.json"], tamper=flip) == (1, None)),
        ("--merge refuses KILLED that the row's own runs do not give",
         merged(["s1.json", "s2.json", "s3.json"], tamper=lie) == (1, None)),
        ("--merge refuses a row of another definition", merged(["s1.json", "s2.json", "s3.json"], tamper=redefine) == (1, None)),
        ("--merge refuses a part over other sources", merged(["s1.json", "s2.json", "s3.json"], tamper=resource) == (1, None)),
        ("--merge refuses the parts for another harness", merged(["s1.json", "s2.json", "s3.json"], prog="agent_mutants") == (1, None)),
    ]
    # A hunt (tests/generated_mutants.py): any outcome is a result, the baseline and the costs are
    # the hunt's, and merge recomputes each row's outcome from its runs instead of requiring KILLED.
    hunted = []

    def hunt_runner(*m, also=()):
        hunted.append(m[0])
        o = "KILLED" if m[0] in ("F1", "F4") else "SURVIVED"
        return o, "why", {m[4]: {"c": "FAIL" if o == "KILLED" else "PASS"}}

    def hunt_judge(row, m):
        return "KILLED" if any(v == "FAIL" for r in (row.get("runs") or {}).values() for v in (r or {}).values()) \
            else "SURVIVED"
    green_hunt = Hunt(judge=hunt_judge, cost=lambda m: 9.0 if m[4] == "u" else 1.0, baseline=lambda chosen: [])
    red_hunt = green_hunt._replace(baseline=lambda chosen: [("t", "", ["c"], [m[0] for m in chosen])])

    def hrun(argv, hunt=green_hunt):
        hunted.clear()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = run_all(many, "SELFTEST", argv, hunt_runner, hunt=hunt) if argv[:1] != ["--merge"] else \
                    run_all(many, "SELFTEST", argv, None, hunt=hunt)
            except SystemExit as e:
                rc = e.code
        return rc, sorted(hunted)
    hparts = shards(many, 3, green_hunt.cost)
    checks += [
        ("a hunt with survivors exits 0 once every mutant ran", hrun(["--jobs", "2"]) == (0, sorted(m[0] for m in many))),
        ("a hunt's red baseline refuses the run before any mutant", hrun([], hunt=red_hunt) == (2, [])),
        ("a hunt takes no --matrix-tests", hrun(["--matrix", str(sd / "h.json"), "--matrix-tests", "all"]) == (2, [])),
        ("a hunt's shards balance the hunt's cost",
         max(sum(m[4] == "u" for m in p) for p in hparts) - min(sum(m[4] == "u" for m in p) for p in hparts) <= 1
         and hparts != parts),
    ]
    ran = [hrun(["--shard", f"{k}/3", "--matrix", str(sd / f"h{k}.json")])[1] for k in (1, 2, 3)]
    checks.append(("a hunt's --shard K/N runs part K of the hunt's partition",
                   ran == [sorted(m[0] for m in p) for p in hparts]))
    hdoc = json.loads((sd / "h1.json").read_text()) if (sd / "h1.json").is_file() else {}
    hfiles = [str(sd / f"h{k}.json") for k in (1, 2, 3)]

    def hmerged(tamper=None, hunt=green_hunt):
        files = list(hfiles)
        if tamper:
            d = json.loads(Path(files[0]).read_text())
            tamper(d)
            (sd / "hx.json").write_text(json.dumps(d))
            files[0] = str(sd / "hx.json")
        (sd / "hm.json").unlink(missing_ok=True)
        rc = hrun(["--merge", str(sd / "hm.json"), *files], hunt=hunt)[0] if hunt else \
            run(["--merge", str(sd / "hm.json"), *files], killed, mutants=many)[0]
        return rc, json.loads((sd / "hm.json").read_text()) if (sd / "hm.json").is_file() else None

    def promote(d):
        mid = next(i for i, r in sorted(d["mutants"].items()) if r["outcome"] == "SURVIVED")
        d["mutants"][mid]["outcome"] = "KILLED"
    rc_h, doc_h = hmerged()
    checks += [
        ("a hunt's rows keep the runner's detail", all(r.get("detail") == "why" for r in hdoc.get("mutants", {}).values())
         and hdoc.get("shard") == [1, 3]),
        ("a hunt's merge accepts survivors: every mutant ran once, each outcome recomputed",
         rc_h == 0 and sorted(doc_h["mutants"]) == sorted(m[0] for m in many)
         and {r["outcome"] for r in doc_h["mutants"].values()} == {"KILLED", "SURVIVED"}),
        ("a hunt's merge refuses an outcome its runs do not give", hmerged(tamper=promote) == (1, None)),
        ("a hunt's merge refuses a part without one of its ids", hmerged(tamper=drop) == (1, None)),
        ("a hunt's parts are no gate: merged without the hunt they are refused", hmerged(hunt=None) == (1, None)),
    ]
    shutil.rmtree(sd, ignore_errors=True)
    # the real runner: an unmutated copy of a cheap test file reports its cases, all PASS
    mine = [m for m in MUTANTS if m[4] == "records_test"][:2]
    checks.append(("the real baseline runs an unmutated copy and reads it green",
                   baseline_red(mine, run_one, 2) == [] and run_one("baseline:records_test", mine[0][1], "unmutated", [],
                                                                     "records_test", mine[0][5])[2]["records_test"]))
    checks += source_checks()
    for script in ("mutants.py", "agent_mutants.py"):
        for argv in (["--jobs", "-1"], ["--jobs", "+2", "ZZ"], ["--jobs", "0", "M01"]):
            p = subprocess.run([sys.executable, str(ROOT / "tests" / script), *argv], capture_output=True, text=True,
                               cwd=ROOT, timeout=120, check=False)
            ok = p.returncode == 2 and "killed on target" not in p.stdout and ("--jobs" in p.stderr or "unknown mutant" in p.stderr)
            checks.append((f"{script} {' '.join(argv)!r}: exit 2 before any run", ok))
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok ' if ok else 'BAD'} {name}")
    print(f"MUTANTS-SELFTEST: {'ALL PASS' if not bad else f'{len(bad)} FAILURES'} ({len(checks)} checks)")
    return 1 if bad else 0


def main():
    if sys.argv[1:] == ["--selftest"]:
        return selftest()
    ids = [m[0] for m in MUTANTS]
    twice = sorted({i for i in ids if ids.count(i) > 1})
    if twice:
        # An id names one mutant: a claim or a run that cites it must not get two (4ce6f92).
        print(f"BAD_MUTANT ids used twice: {', '.join(twice)}")
        return 1
    return run_all(MUTANTS, "MUTANTS", sys.argv[1:], run_one)


if __name__ == "__main__":
    sys.exit(main())
