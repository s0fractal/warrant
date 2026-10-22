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
     [('        replaced = set(rep["results"].get(c["transition"], {}).get("superseded_by", [])) & closed_by_admitted',
       '        replaced = set(rep["results"].get(c["transition"], {}).get("superseded_by", []))')],
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
     [('        holders.add(eff, m["to"], set())', '        holders.add(eff, m["to"], dl)')], "assessment_test", ["R28"]),
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
     [('    if not all(_hex64(doc[k]) for k in ("input", "environment", "checkpoint", "state", "claimed")):',
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
     [('    if not all(_hex64(doc[k]) for k in ("input", "environment", "witness")):',
       '    if not all(isinstance(doc[k], str) and len(doc[k]) == 64 for k in ("input", "environment", "witness")):')],
     "compute_test", ["C25"]),
    # M170-M174 restore the `$` anchors of AMEND 2 of #164: `$` matches before a final newline
    ("M170", "keys.py", "a hex64 may end in a newline (`$` instead of \\Z; records.HEX64 is this pattern)",
     [('HEX64 = re.compile(r"^[0-9a-f]{64}\\Z")', 'HEX64 = re.compile(r"^[0-9a-f]{64}$")')], "contract_test", ["N7"]),
    ("M171", "keys.py", "a signature may end in a newline",
     [('HEX128 = re.compile(r"^[0-9a-f]{128}\\Z")', 'HEX128 = re.compile(r"^[0-9a-f]{128}$")')], "contract_test", ["N7"]),
    ("M172", "records.py", "a subject may end in a newline",
     [('SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\\Z")', 'SUBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")')],
     "contract_test", ["N7"]),
    ("M173", "records.py", "a question reference may end in a newline",
     [('QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})\\Z")', 'QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})$")')],
     "contract_test", ["N7"]),
    ("M174", "compute.py", "the receipt and cycle hash members use their own `$`-anchored pattern, as at 1d67124",
     [('    return isinstance(v, str) and R.HEX64.match(v) is not None',
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
    ("M185", "keys.py", "a hex64 may be uppercase",
     [('HEX64 = re.compile(r"^[0-9a-f]{64}\\Z")', 'HEX64 = re.compile(r"^[0-9a-fA-F]{64}\\Z")')], "records_test", ["E7"]),
    ("M186", "keys.py", "a hex64 digit is any Unicode digit (`\\d`)",
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
     [('    _fields(record, ("warrant", "type", "actor", "at", "body"), what="record")',
       '    _fields(record, ("warrant", "type", "actor", "at", "body"), ("prior",), what="record")')], "records_test", ["K11"]),
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
    ("M217", "records.py", "a question index may have leading zeros",
     [('QREF = re.compile(r"^[0-9a-f]{64}:(0|[1-9][0-9]{0,3})\\Z")', 'QREF = re.compile(r"^[0-9a-f]{64}:([0-9]{1,4})\\Z")')],
     "records_test", ["D13"]),
    ("M218", "records.py", "a question index digit is any Unicode digit (`\\d`)",
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
     [('(isinstance(b["parent"], str) and HEX64.match(b["parent"]))', '(isinstance(b["parent"], str) and len(b["parent"]) == 64)')],
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
    ("M261", "records.py", "an actor id need not be in NFC",
     [('    _need(unicodedata.is_normalized("NFC", v), f"{what} must be in Unicode NFC")\n', '')], "records_test", ["K12"]),
    ("M262", "records.py", "an actor id may contain a control character",
     [('    _need(not any(unicodedata.category(c) == "Cc" for c in v), f"{what} must not contain a control character")\n', '')],
     "records_test", ["K12"]),
    ("M263", "records.py", "an actor id may begin or end with white space",
     [('    _need(unicodedata.category(v[0]) not in EDGE_SPACE and unicodedata.category(v[-1]) not in EDGE_SPACE,\n'
       '          f"{what} must not begin or end with white space")\n', '')], "records_test", ["K12"]),
    ("M264", "records.py", "only a space separator (Zs) counts as white space at an actor id's ends",
     [('EDGE_SPACE = ("Zs", "Zl", "Zp")', 'EDGE_SPACE = ("Zs",)')], "records_test", ["K12"]),
    ("M265", "records.py", "an actor id may be 201 code points long",
     [('MAX_ACTOR = 200\n', 'MAX_ACTOR = 201\n')], "records_test", ["K12"]),
    ("M266", "records.py", "an actor id's length is counted in UTF-16 code units, not code points",
     [('    _text(v, what, limit=MAX_ACTOR)\n',
       '    _text(v, what, limit=MAX_ACTOR)\n    _need(len(v.encode("utf-16-le")) <= 2 * MAX_ACTOR, f"{what} is too long")\n')],
     "records_test", ["K12"]),
    ("M267", "records.py", "an actor must look like a name (letters, digits, - _ .): what it is gets assessed",
     [('    _text(v, what, limit=MAX_ACTOR)\n',
       '    _text(v, what, limit=MAX_ACTOR)\n    _need(re.fullmatch(r"[A-Za-z0-9_.-]+", v) is not None, f"{what} is not a name")\n')],
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
     [('grant_state(view, g["parent"], view.pos(gid), depth + 1)', 'grant_state(view, g["parent"], (view.pos(gid)[0], END_ID), depth + 1)')],
     "assessment_test", ["R39"]),
    ("M277", "engine.py", "positions are ordered by `at` alone (SPEC-4-7: the id breaks no tie)",
     [('        return (self.recs[rid]["at"], rid)', '        return (self.recs[rid]["at"], "")')], "assessment_test", ["R39"]),
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
     [('    out["children"] = [node(m, c, "requires", seen | {did}) for c in r["requires"]]', '    out["children"] = []')],
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
    # The open circle of witnesses (tools/claims.py, tools/roadmap.py; tests/circle_test.py): A bindings,
    # B acceptance, C lineage and counters from anyone, D the witness ledger.
    ("M319", "../tools/claims.py", "a binding whose proof does not verify is admitted (forged proof)",
     [("    if not K.verify(k[\"public\"], k[\"proof\"], msg):\n", "    if False:\n")], "circle_test", ["B2", "B3", "B8"]),
    ("M320", "../tools/claims.py", "a proof signed by another key is reported as forged (the refusal stays, its code is wrong)",
     [("        if other:\n            return \"BINDING_PROOF_OTHER_KEY\"", "        if False:\n            return \"BINDING_PROOF_OTHER_KEY\"")], "circle_test", ["B3"]),
    ("M321", "../tools/claims.py", "a second key for an actor is admitted (the first binding does not win)",
     [("    if first is not None:\n", "    if False:\n")], "circle_test", ["B4"]),
    ("M322", "../tools/claims.py", "a binding's actor id is not checked against SPEC-3-21",
     [("        R.check_actor(k[\"actor\"])\n    except R.Invalid as e:\n        return \"BINDING_ACTOR_SHAPE\"", "        pass\n    except R.Invalid as e:\n        return \"BINDING_ACTOR_SHAPE\"")], "circle_test", ["B5"]),
    ("M323", "../tools/claims.py", "one key binds two actors",
     [("    if any(p == k[\"public\"] for _, p in admitted):\n", "    if False:\n")], "circle_test", ["B6"]),
    ("M324", "../tools/claims.py", "a binding with no proof is admitted",
     [("    if \"proof\" not in k:\n        return \"BINDING_UNPROVEN\"", "    if \"proof\" not in k:\n        return None, None\n        return \"BINDING_UNPROVEN\"")], "circle_test", ["B7"]),
    ("M325", "../tools/claims.py", "the proof signs {actor, public} without the purpose (no domain separation)",
     [("    return C.canon({\"actor\": actor, \"public\": public, \"purpose\": BINDING})", "    return C.canon({\"actor\": actor, \"public\": public})")], "circle_test", ["B8"]),
    ("M326", "../tools/claims.py", "a trust/2 file without proofs is read as admitted bindings outside a base",
     [("    if legacy and isinstance(doc, dict) and doc.get(\"warrant\") == \"trust/2\":", "    if isinstance(doc, dict) and doc.get(\"warrant\") == \"trust/2\":")], "circle_test", ["B7"]),
    ("M327", "../tools/claims.py", "a binding admitted at the base may be dropped",
     [("            for a, p in was if (a, p) not in have]", "            for a, p in was if False]")], "circle_test", ["B10"]),
    ("M328", "../tools/claims.py", "bind writes a binding check would not admit (another actor's id)",
     [("    if (actor, key.public) not in admitted:\n", "    if False:\n")], "circle_test", ["B9"]),
    ("M329", "../tools/claims.py", "check does not refuse a binding it does not admit",
     [("    out += repo.bindings()[1]\n", "")], "circle_test", ["B11"]),
    ("M330", "../tools/claims.py", "a receiver's own trust file is ignored",
     [("    return [] if not path else [(a, p) for a, p in Trust.load(path).keys.values()]", "    return []")], "circle_test", ["B12"]),
    ("M331", "../tools/claims.py", "anyone may file a claim's acceptance (accept_by not checked)",
     [("        if actor not in accept_by:\n            raise not_acceptor(", "        if False:\n            raise not_acceptor(")], "circle_test", ["K2"]),
    ("M332", "../tools/claims.py", "an acceptor who accepted already files another acceptance",
     [("        if actor in acceptors(model.recs, index, n.tid, 0):\n", "        if False:\n")], "circle_test", ["K7"]),
    ("M333", "../tools/claims.py", "a claim a replaying counter lowers is accepted",
     [("        if low:\n            raise Refused(f\"{cid}: a counter that replays", "        if False:\n            raise Refused(f\"{cid}: a counter that replays")], "circle_test", ["K4"]),
    ("M334", "../tools/claims.py", "accept --all takes a countered claim too (and the batch is refused)",
     [("                        and n.id not in low\n", "")], "circle_test", ["K4"]),
    ("M335", "../tools/claims.py", "an UNBACKED claim's acceptance is filed (it closes nothing)",
     [("        if not n.backed:\n            raise Refused(f\"{cid} is {n.status}", "        if False:\n            raise Refused(f\"{cid} is {n.status}")], "circle_test", ["K2"]),
    ("M336", "../tools/claims.py", "the view does not name who accepted",
     [("    by = f\"accepted by {', '.join(accepted)}\" if accepted else \"\"", "    by = \"\"")], "circle_test", ["K1", "K7"]),
    ("M337", "../tools/claims.py", "an acceptance of another evidence set is shown as the claim's acceptor",
     [("if t == tid and i == item and ev == want for a in actors})", "if t == tid and i == item for a in actors})")], "circle_test", ["K1"]),
    ("M338", "../tools/roadmap.py", "roadmap accept files anyone's acceptance",
     [("        if self.actor not in r[\"accept_by\"] and self.actor not in r[\"owed_to\"]:", "        if False:")], "circle_test", ["K6"]),
    ("M339", "../tools/roadmap.py", "roadmap accept accepts a closure that is no longer pending (already admitted)",
     [("        cands = [c for c in CL.pending_for(self.m.rep, did, self.actor) if transition in (None, c[\"transition\"])]", "        cands = [c for c in self.m.rep[\"duties\"][did][\"candidates\"] if transition in (None, c[\"transition\"])]")], "circle_test", ["K6"]),
    ("M340", "../tools/roadmap.py", "roadmap accept takes a SPEC claim's duty",
     [("        if did not in self.m.obligations:\n", "        if False:\n")], "circle_test", ["K6"]),
    ("M341", "../tools/roadmap.py", "the path does not name who accepted an obligation's closure",
     [("\"accepted_by\": m.accepted_by(did),", "\"accepted_by\": [],")], "circle_test", ["K6"]),
    ("M342", "../tools/claims.py", "another actor than a claim's author may supersede or retire it",
     [("        if n.rec[\"actor\"] != p.rec[\"actor\"]:\n", "        if False:\n")], "circle_test", ["L1", "L2"]),
    ("M343", "../tools/claims.py", "another actor than the document's author files its next version",
     [("            elif p[0][\"actor\"] != r[\"actor\"]:\n", "            elif False:\n")], "circle_test", ["L3"]),
    ("M344", "../tools/claims.py", "the tool files another author's supersession",
     [("        if previous is not None and previous.rec[\"actor\"] != self.actor:\n", "        if False:\n")], "circle_test", ["L3"]),
    ("M345", "../tools/claims.py", "the tool files another author's retirement",
     [("        if cur.rec[\"actor\"] != self.actor:\n            raise Refused(", "        if False:\n            raise Refused(")], "circle_test", ["L3"]),
    ("M346", "../tools/claims.py", "retire stores the counter-evidence before refusing another author",
     [("    if cur.rec[\"actor\"] != a.actor:\n", "    if False:\n")], "circle_test", ["L11"]),
    ("M347", "../tools/claims.py", "the tool files another author's document version",
     [("        if doc.current is not None and doc.nodes[doc.tid][0][\"actor\"] != self.actor:\n", "        if False:\n")], "circle_test", ["L3"]),
    ("M348", "../tools/claims.py", "challenge files a counter that does not replay",
     [("        if why:\n            raise Refused(f\"{a.claim}: the counter does not replay", "        if False:\n            raise Refused(f\"{a.claim}: the counter does not replay")], "circle_test", ["L4"]),
    ("M349", "../tools/claims.py", "a counter that does not replay lowers the backing",
     [("            kind = LOWERS if good else COUNTED", "            kind = LOWERS if counters else COUNTED")], "circle_test", ["L5"]),
    ("M350", "../tools/claims.py", "a counter lowers a claim that has no backing (UNBACKED)",
     [("            whys = {c: replay(c, n) if n.backed else", "            whys = {c: replay(c, n) if True else")], "circle_test", ["L5"]),
    ("M351", "../tools/claims.py", "the author's own challenge does not count",
     [("    if actor == n.rec[\"actor\"]:\n        return True\n", "")], "circle_test", ["L5", "L6"]),
    ("M352", "../tools/claims.py", "the acceptor's (and owed_to's) challenge does not count",
     [("    return d is not None and actor in set(d[\"body\"][\"owed_to\"]) | set(d[\"body\"][\"accept_by\"])", "    return False")], "circle_test", ["L5", "L6"]),
    ("M353", "../tools/claims.py", "anyone's challenge counts (a stranger's thesis blocks check)",
     [("    if actor == n.rec[\"actor\"]:\n        return True\n", "    if True:\n        return True\n")], "circle_test", ["L5", "L6"]),
    ("M354", "../tools/claims.py", "check refuses a thesis as a standing challenge",
     [("if x[\"claim\"] == cid and x[\"kind\"] == COUNTED]", "if x[\"claim\"] == cid and x[\"kind\"] in (COUNTED, THESIS)]")], "circle_test", ["L6"]),
    ("M355", "../tools/claims.py", "check refuses a lowering counter as a standing challenge",
     [("if x[\"claim\"] == cid and x[\"kind\"] == COUNTED]", "if x[\"claim\"] == cid and x[\"kind\"] in (COUNTED, LOWERS)]")], "circle_test", ["L6"]),
    ("M356", "../tools/claims.py", "a challenge's counters are replayed again although it was at the base",
     [("        if r[\"type\"] != \"challenge\" or rid in before:\n", "        if r[\"type\"] != \"challenge\":\n")], "circle_test", ["L7"]),
    ("M357", "../tools/claims.py", "a new challenge's counter that does not replay is admitted",
     [("            if why:\n                out.append((\"COUNTER_NOT_REPLAYED\"", "            if False:\n                out.append((\"COUNTER_NOT_REPLAYED\"")], "circle_test", ["L7"]),
    ("M358", "../tools/claims.py", "a countered claim reads BACKED in the view",
     [("    return \"COUNTERED\" if n.id in low else n.status", "    return n.status")], "circle_test", ["L8"]),
    ("M359", "../tools/claims.py", "a claim's duty terms are not compared with the pins",
     [("    if n.retired or n.kind != \"normative\":\n        return None\n    b = model.recs", "    if True:\n        return None\n    b = model.recs")], "circle_test", ["L9"]),
    ("M360", "../tools/claims.py", "check does not refuse a claim whose duty names another acceptor",
     [("        if terms:\n            out.append((\"CLAIM_DUTY_TERMS\"", "        if False:\n            out.append((\"CLAIM_DUTY_TERMS\"")], "circle_test", ["L9"]),
    ("M361", "../tools/roadmap.py", "an obligation may name its own acceptor",
     [("            if (b[\"owed_to\"], b[\"accept_by\"], b[\"release_by\"]) != (cfg[\"owed_to\"], cfg[\"accept_by\"], []):", "            if False:")], "circle_test", ["L10"]),
    ("M362", "../tools/claims.py", "a supersession counts as an authored claim",
     [("        if n.doc[\"previous\"] is None:\n            rows[n.rec[\"actor\"]][\"authored\"] += 1", "        if True:\n            rows[n.rec[\"actor\"]][\"authored\"] += 1")], "circle_test", ["W1"]),
    ("M363", "../tools/claims.py", "an acceptance is credited to the accepted transition's filer",
     [("            rows[r[\"actor\"]][\"accepts\"].append(rid)", "            rows[recs[b[\"transition\"]][\"actor\"]][\"accepts\"].append(rid)")], "circle_test", ["W2"]),
    ("M364", "../tools/claims.py", "every acceptance of a claim counts as refuted",
     [("            if b[\"transition\"] in refuting and b[\"transition\"] in model.nodes:", "            if b[\"transition\"] in model.nodes:")], "circle_test", ["W3"]),
    ("M365", "../tools/claims.py", "an acceptance whose claim a downgrade's counter refuted is not counted",
     [("    refuting = {against[c] for c in now | set(downs)}", "    refuting = {against[c] for c in now}")], "circle_test", ["W3"]),
    ("M366", "../tools/claims.py", "a challenged closure counts as refuted without a revalidation",
     [("            elif (b[\"transition\"], b[\"item\"]) in challenged and b[\"transition\"] in revalidated:", "            elif (b[\"transition\"], b[\"item\"]) in challenged:")], "circle_test", ["W3"]),
    ("M367", "../tools/claims.py", "a challenge without evidence is not counted",
     [("        if r[\"type\"] == \"challenge\":\n            rows[r[\"actor\"]][\"challenges\"] += 1", "        if r[\"type\"] == \"challenge\" and r[\"body\"][\"evidence\"]:\n            rows[r[\"actor\"]][\"challenges\"] += 1")], "circle_test", ["W4"]),
    ("M368", "../tools/claims.py", "a counter is credited to the last record citing it",
     [("        first = min(rids, key=lambda rid: (recs[rid][\"at\"], rid))", "        first = max(rids, key=lambda rid: (recs[rid][\"at\"], rid))")], "circle_test", ["W5"]),
    ("M369", "../tools/claims.py", "a standing counter that does not replay counts as lowering now",
     [("    now = {c for x in table.values() if x[\"kind\"] == LOWERS for c in x[\"replays\"]}", "    now = {c for x in table.values() for c in x[\"counters\"]}")], "circle_test", ["W6"]),
    ("M370", "../tools/claims.py", "a counter a BACKED re-back cites counts as cited by a downgrade",
     [("        if q.retired or q.kind != \"normative\" or q.backed:\n", "        if q.retired or q.kind != \"normative\":\n")], "circle_test", ["W6"]),
    ("M371", "../tools/claims.py", "any BACKED supersession counts as a re-back",
     [("        if n.backed and prev and prev[\"transition\"] in countered:", "        if n.backed and prev:")], "circle_test", ["W7"]),
    ("M372", "../tools/claims.py", "WITNESSES.md swaps the lowering-now and downgrade columns",
     [("f\"| {len(row['now'])} | {len(row['downgrade'])} | {len(row['rebacks'])} |\")", "f\"| {len(row['downgrade'])} | {len(row['now'])} | {len(row['rebacks'])} |\")")], "circle_test", ["W8"]),
    ("M373", "../tools/claims.py", "WITNESSES.md is compared as text: read_text() turns \\r\\n into \\n",
     [("    elif repo.witnesses.read_bytes() != render_witnesses(repo, model, table).encode():", "    elif repo.witnesses.read_text() != render_witnesses(repo, model, table):")], "circle_test", ["W9"]),
    # AMEND 1 of #170: a name the configuration gives a role is pinned in .warrant/roles.json, not first-come.
    ("M376", "../tools/claims.py", "a role (a pinned key, reserved or collective) admits a binding of another key",
     [("    if role != k[\"public\"]:", "    if False:")], "circle_test", ["R1", "R2b", "R7"]),
    ("M377", "../tools/claims.py", "the repository's bindings are admitted without its roles",
     [("        return admit_bindings(doc, roles=self.roles()[0])", "        return admit_bindings(doc)")], "circle_test", ["R2b"]),
    ("M378", "../tools/claims.py", "bind writes a binding the roles refuse",
     [("    admitted, problems = admit_bindings(doc, roles=repo.roles()[0])", "    admitted, problems = admit_bindings(doc)")], "circle_test", ["R2"]),
    ("M379", "../tools/claims.py", "a role may be pinned to anything",
     [("        if not (v is None or v == COLLECTIVE or (isinstance(v, str) and R.HEX64.match(v))):", "        if False:")], "circle_test", ["R3"]),
    ("M380", "../tools/claims.py", "check does not report a malformed roles file",
     [("    out += why + unpinned(roles, ", "    out += unpinned(roles, ")], "circle_test", ["R3"]),
    ("M381", "../tools/claims.py", "a name the configuration gives a role may be left unpinned (first-come)",
     [("            for a in sorted(set(names) - set(roles))]", "            for a in []]")], "circle_test", ["R4"]),
    ("M382", "../tools/roadmap.py", "roadmap check does not ask for the roadmap's roles to be pinned",
     [("        self.problems += CL.unpinned(", "        _ = CL.unpinned(")], "circle_test", ["R4"]),
    ("M383", "../tools/claims.py", "a pin may take a name from the binding admitted at the base",
     [("            for a, p in was if a in roles and roles[a] != p]", "            for a, p in was if False]")], "circle_test", ["R5"]),
    ("M384", "../tools/claims.py", "pin makes a collective role bindable",
     [("    if roles.get(a.actor) == COLLECTIVE:\n", "    if False:\n")], "circle_test", ["R6"]),
    ("M385", "../tools/claims.py", "pin takes a role from its admitted binding",
     [("    if other:\n        raise Refused(f\"{a.actor} is bound to key", "    if False:\n        raise Refused(f\"{a.actor} is bound to key")], "circle_test", ["R6"]),
]
# M18 edits store.py instead: authenticity must check the key's actor.
MUTANTS[17] = ("M18", "store.py", "a key bound to another actor authenticates",
               [('    if bound[0] != rec["actor"]:\n', '    if False:\n')], "contract_test", ["N5"])


# What a mutant's run takes from this checkout. COPIED: the directories run_one (here and in
# agent_mutants.py) copies, only through copy_source(), so nothing outside them is copied.
# READ_IN_PLACE: what the test files run from the checkout itself, or read there (the selftest
# refuses a test file that names another top-level entry). source_digest() covers both, so a
# matrix's `source` names every byte its runs could have depended on (AMEND 1 of #172: a change
# to tools/roadmap.py alone left the digest unchanged, and --merge accepted a stale matrix).
COPIED = ("warrant", "warrant_agent", "tools")
READ_IN_PLACE = ("tests", "third_party", ".warrant", "trust", "SPEC.md", "SPEC-CLAIMS.md", "WITNESSES.md", "ROADMAP.md")
SOURCES = COPIED + READ_IN_PLACE


def copy_source(tmp, d):
    """Copy directory `d` of this checkout into `tmp`: only a directory of COPIED."""
    if d not in COPIED:
        raise ValueError(f"{d}/ is not in COPIED, so source_digest() would not cover it")
    shutil.copytree(ROOT / d, tmp / d, ignore=shutil.ignore_patterns("__pycache__"))


def run_tests(tmp, tests, timeout=900):
    """{test file: {case: PASS|FAIL}, or None when it produced no results}: each named test
    file run against the packages in `tmp` (WARRANT_IMPL), with results of its own."""
    runs = {}
    for t in tests:
        res = tmp / f"results-{t}.json"
        env = dict(os.environ, WARRANT_IMPL=str(tmp), WARRANT_RESULTS=str(res))
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
        copy_source(tmp, "warrant")
        if fname.startswith("../"):
            # A tool beside the package (../tools/roadmap.py): its directory is copied whole, so
            # the tool's own imports (tools/claims.py) come from the same copy; the test loads it
            # from $WARRANT_IMPL/tools.
            outside = Path(fname[3:]).parts[0]
            if outside not in COPIED:
                return "BAD_MUTANT", f"{fname} is outside COPIED {COPIED}", {}
            copy_source(tmp, outside)
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


def source_digest(root=ROOT):
    """SHA-256 over every file of SOURCES under `root` (all files, not only *.py; no
    __pycache__), by relative path, and the name of each entry of SOURCES that is absent: a
    matrix answers for exactly the code, tools, tests and data its runs used. tools/claims.py
    audit (MATRIX_STALE) and --merge (SHARD_STALE) both compare matrices with this digest."""
    import hashlib
    h = hashlib.sha256()
    for name in sorted(SOURCES):
        top = root / name
        if top.is_file():
            files = [top]
        elif top.is_dir():
            files = sorted((p for p in top.rglob("*") if p.is_file() and "__pycache__" not in p.relative_to(root).parts),
                           key=lambda p: p.relative_to(root).as_posix())
        else:
            h.update(name.encode() + b"\0absent\0")
            continue
        for p in files:
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


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
        "agent_handoff_test": 7.0, "agent_write_test": 1.9, "agent_compute_test": 1.9, "agent_mcp_test": 17.0}


def shards(mutants, n):
    """`mutants` in n parts, a function of the ids, their test files and COST only: the
    costliest first (ties in list order), each to the part with the least cost so far (ties to
    the lowest part). Each part keeps the list order. Every mutant is in exactly one part."""
    load, parts = [0.0] * n, [[] for _ in range(n)]
    for i, m in sorted(enumerate(mutants), key=lambda x: (-(COST.get(x[1][4], 1.0) + 0.5), x[0])):
        k = min(range(n), key=lambda j: (load[j], j))
        load[k] += COST.get(m[4], 1.0) + 0.5
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


def run_all(mutants, label, argv, runner, prog="mutants"):
    """Run `mutants` in parallel (--jobs N in argv, default: the CPU count): each one already
    works in its own copy of the package and its own results file, so nothing is shared.
    Output keeps the given order; ids in argv select mutants. The 2026-10-21 CI run with 89
    mutants took 21 of the job's 25 minutes in series. Before any mutant, each targeted test
    file runs once unmutated; a target case that does not pass there refuses the run with
    BASELINE_RED (exit 2). Exit 0 only when at least one mutant ran and every one was KILLED;
    a bad option or id exits 2 (SystemExit from argparse). --merge: see merge()."""
    import concurrent.futures
    if argv[:1] == ["--merge"]:
        return merge(mutants, label, argv[1:], prog)
    ns = parse_args(argv, [m[0] for m in mutants], prog)
    pick = set(ns.ids)
    chosen = [m for m in mutants if not pick or m[0] in pick]
    if ns.shard:
        chosen = shards(mutants, ns.shard[1])[ns.shard[0] - 1]
        label = f"{label} shard {ns.shard[0]}/{ns.shard[1]}"
    if not chosen:
        print(f"{label}: no mutants selected; nothing was checked")
        return 2
    red = baseline_red(chosen, runner, ns.jobs)
    for test, env, failing, ids in red:
        where = f"{test}" + (f" (with {env}/)" if env else "")
        what = "gave no results" if failing is None else f"fails {','.join(failing)}"
        print(f"BASELINE_RED {where} unmutated {what}; targeted by {' '.join(ids)}")
    if red:
        print(f"{label}: BASELINE_RED, no mutant was run: a target case that fails without a mutant "
              "would read as a kill")
        return 2
    killed, rows = 0, {}
    call = (lambda m: runner(*m, also=ns.also)) if ns.matrix else (lambda m: runner(*m))
    with concurrent.futures.ThreadPoolExecutor(max_workers=ns.jobs) as pool:
        for m, got in zip(chosen, pool.map(call, chosen)):
            outcome, detail = got[0], got[1]
            killed += outcome == "KILLED"
            print(f"{outcome:<11} {m[0]} {m[1]}: {m[2]}  [{detail}]", flush=True)
            rows[m[0]] = {"definition": mutant_digest(m), "file": m[1], "what": m[2], "test": m[4],
                          "targets": list(m[5]), "outcome": outcome, "runs": got[2] if len(got) > 2 else {}}
    print(f"{label}: {killed}/{len(chosen)} killed on target (jobs={ns.jobs})")
    if ns.matrix:
        doc = {"matrix": MATRIX, "harness": prog, "tests": ns.matrix_tests, "source": source_digest(),
               "mutants": rows}
        if ns.shard:
            doc["shard"] = list(ns.shard)
        Path(ns.matrix).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        print(f"{label}: matrix of {len(rows)} mutants ({ns.matrix_tests}) written to {ns.matrix}")
    return 0 if killed == len(chosen) else 1


def merge(mutants, label, argv, prog, root=ROOT):
    """--merge OUT PART.json ...: the matrices of the parts of one run (--shard K/N --matrix),
    checked against this checkout and joined into one matrix OUT as an unsharded run writes it.
    Refused (exit 1, OUT not written) unless every file is a matrix of this harness over these
    sources with one --matrix-tests, no id is in two files, no id is outside the list, every id of
    the list is in one, every row is the current definition of its mutant, and every outcome is
    KILLED as verdict() recomputes it from the row's own runs. So OUT means: every mutant of the
    list was run once and killed on its target; which part ran it is not part of the claim."""
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
    src, by_id = source_digest(root), {m[0]: m for m in mutants}
    if len({json.dumps(d.get("tests")) for _, d in docs}) > 1:
        problems.append(("SHARD_SHAPE", "the files were run with different --matrix-tests"))
    rows, where = {}, {}
    for f, d in docs:
        if d.get("matrix") != MATRIX or d.get("harness") != prog:
            problems.append(("SHARD_NOT_THIS_HARNESS", f"{f}: {d.get('matrix')!r} by {d.get('harness')!r}, not {prog}"))
        if d.get("source") != src:
            problems.append(("SHARD_STALE", f"{f}: written over other sources than this checkout's"))
        for mid, row in sorted((d.get("mutants") or {}).items()):
            if mid in where:
                problems.append(("SHARD_DUPLICATE_ID", f"{mid} in {where[mid]} and {f}"))
                continue
            where[mid] = f
            m = by_id.get(mid)
            if m is None:
                problems.append(("SHARD_UNKNOWN_ID", f"{f}: {mid} is not a mutant of {prog}.py"))
                continue
            if row.get("definition") != mutant_digest(m):
                problems.append(("SHARD_STALE", f"{f}: {mid} is not the current definition"))
            got = verdict(row.get("runs") or {}, m[4], m[5])[0]
            if row.get("outcome") != "KILLED" or got != "KILLED":
                problems.append(("SHARD_NOT_KILLED", f"{f}: {mid} is {row.get('outcome')}, its runs give {got}"))
            rows[mid] = row
    missing = [m[0] for m in mutants if m[0] not in where]
    if missing:
        problems.append(("SHARD_MISSING_ID", f"{len(missing)} not run: {' '.join(missing)}"))
    for code, why in problems:
        print(f"{code:<22} {why}")
    if problems:
        print(f"{label} MERGE: REFUSED ({len(problems)} problems); {out} not written")
        return 1
    doc = {"matrix": MATRIX, "harness": prog, "tests": docs[0][1]["tests"], "source": src, "mutants": rows}
    Path(out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"{label} MERGE: {len(rows)}/{len(mutants)} mutants, each run once in one of {len(docs)} files and "
          f"killed on target; matrix written to {out}")
    return 0


def source_checks():
    """The fingerprint covers what the runs use (AMEND 1 of #172), checked on a copy of the
    sources with a genuine KILLED row of M300 (a ../tools/roadmap.py mutant)."""
    import ast
    import contextlib
    import io
    sys.path.insert(0, str(ROOT / "tests"))
    from agent_mutants import MUTANTS as AGENT
    outside = {Path(m[1][3:]).parts[0] for m in MUTANTS + AGENT if m[1].startswith("../")}
    top = {p.name for p in ROOT.iterdir()}
    named = {}
    for f in sorted((ROOT / "tests").glob("*.py")):
        if f.name not in ("mutants.py", "agent_mutants.py"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in top:
                    named.setdefault(n.value, set()).add(f.name)
    probe = Path(tempfile.mkdtemp(prefix="mutants-selftest-copy-"))
    try:
        copy_source(probe, "examples")
        refused = False
    except ValueError:
        refused = not (probe / "examples").exists()
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    checks = [
        ("every directory a mutant copies is in COPIED", outside <= set(COPIED) and {"warrant", "warrant_agent"} <= set(COPIED)),
        ("copy_source refuses a directory outside COPIED", refused),
        ("every checkout entry a test file names is in SOURCES", set(named) <= set(SOURCES)),
    ]
    m300 = next(m for m in MUTANTS if m[0] == "M300")
    got = run_one(*m300)
    work = Path(tempfile.mkdtemp(prefix="mutants-selftest-sources-"))
    try:
        copy = work / "root"
        for name in SOURCES:
            if (ROOT / name).is_dir():
                shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns("__pycache__"))
            elif (ROOT / name).is_file():
                copy.mkdir(exist_ok=True)
                shutil.copy2(ROOT / name, copy / name)
        row = {"definition": mutant_digest(m300), "file": m300[1], "what": m300[2], "test": m300[4],
               "targets": list(m300[5]), "outcome": got[0], "runs": got[2]}
        part = work / "part.json"
        part.write_text(json.dumps({"matrix": MATRIX, "harness": "mutants", "tests": "own", "source": source_digest(copy),
                                    "mutants": {"M300": row}}))

        def merged():
            out = work / "merged.json"
            out.unlink(missing_ok=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = merge([m300], "SOURCES", [str(out), str(part)], "mutants", root=copy)
            return rc, out.is_file(), "SHARD_STALE" in buf.getvalue()

        def changed(rel, edit):
            f = copy / rel
            if not f.is_file():
                return "absent from the copy", rel
            was = f.read_bytes()
            f.write_bytes(edit(was))
            try:
                return merged()
            finally:
                f.write_bytes(was)
        m300_edit = lambda b: b.replace(m300[3][0][0].encode(), m300[3][0][1].encode())
        checks += [
            ("a genuine run of M300 is KILLED on P9", got[0] == "KILLED"),
            ("a copy of SOURCES has the checkout's digest", source_digest(copy) == source_digest()),
            ("--merge of the genuine row over unchanged sources passes", merged() == (0, True, False)),
            ("--merge refuses it SHARD_STALE once tools/roadmap.py has M300's own edit, and writes nothing",
             changed("tools/roadmap.py", m300_edit) == (1, False, True)),
            ("--merge refuses it SHARD_STALE once tools/claims.py changes", changed("tools/claims.py", lambda b: b + b"\n# x\n") == (1, False, True)),
            ("--merge refuses it SHARD_STALE once a data file the tests read changes (tests/vectors)",
             changed("tests/vectors/ed25519-edge.json", lambda b: b + b"\n") == (1, False, True)),
            ("--merge refuses it SHARD_STALE once the store the tests copy changes (.warrant)",
             changed(".warrant/claims.json", lambda b: b + b"\n") == (1, False, True)),
        ]
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
