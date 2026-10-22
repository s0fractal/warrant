#!/usr/bin/env python3
"""Each mutant undoes one critical rule of the package and must make ITS case fail.

    python3 tests/mutants.py [--jobs N] [ID ...]
    python3 tests/mutants.py --selftest     # the runner itself against fixture runners

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
     [('if c["target"] in closures and (c["actor"] in counts or c.get("counter_observation")))',
       'if c["target"] in closures)')], "conditions_test", ["K2"]),
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
    ("M56", "engine.py", "an evidence-weighted challenge still needs a listed challenger",
     [('if c["target"] in closures and (c["actor"] in counts or c.get("counter_observation")))',
       'if c["target"] in closures and c["actor"] in counts)')], "conditions_test", ["K4"]),
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
     [('    if m["to"] not in got:\n        missing.append(f"{m[\'to\']} (incoming)")\n    else:\n        pos = max(pos, got[m["to"]])',
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
     [('    if rec["at"] > at:\n        return "NOT_YET", "granted after this position"\n', '')], "assessment_test", ["R14"]),
    ("M91", "engine.py", "a grant never expires",
     [('    if g["expires"] is not None and at >= g["expires"]:\n        return "EXPIRED", f"expired at {g[\'expires\']}"\n', '')],
     "assessment_test", ["R15"]),
    ("M92", "engine.py", "a parent grant is judged at the act's position, not at its child's",
     [('    pst, why = grant_state(view, g["parent"], rec["at"], depth + 1)', '    pst, why = grant_state(view, g["parent"], at, depth + 1)')],
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
     [('    if t["actor"] in set(d["owed_to"]) | set(d["release_by"]):', '    if t["actor"] in set(d["owed_to"]):')],
     "assessment_test", ["R26"]),
    ("M117", "engine.py", "any actor's acceptance stands for the duty's accept_by",
     [('    missing = sorted(set(d["accept_by"]) - got)', '    missing = [] if got else sorted(d["accept_by"])')],
     "contract_test", ["A2"]),
    ("M118", "engine.py", "a filer's challenged record elsewhere weighs on its other closures",
     [('    yield _challenged(rep, _counting_challenges(rep, set(r["current_closures"]), r))\n',
       '    yield _challenged(rep, _counting_challenges(rep, set(r["current_closures"]), r))\n'
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
    ("M133", "compute.py", "a receipt's hashes are not checked",
     [('    if not all(isinstance(doc[k], str) and len(doc[k]) == 64 for k in ("input", "environment", "checkpoint", "state", "claimed")):\n        return "receipt hashes"\n', '')],
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
     [('    if r["code"] != "NORMAL_FORM":\n', '    if False:\n')], "compute_test", ["C4"]),
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
    ap.add_argument("ids", nargs="*", metavar="ID", help="mutant ids to run (default: all of them)")
    ns = ap.parse_args(argv)
    if ns.jobs < 1:
        ap.error(f"--jobs must be >= 1, got {ns.jobs}")
    unknown = sorted(set(ns.ids) - set(ids))
    if unknown:
        ap.error(f"unknown mutant id(s): {', '.join(unknown)}")
    return ns


def run_all(mutants, label, argv, runner, prog="mutants"):
    """Run `mutants` in parallel (--jobs N in argv, default: the CPU count): each one already
    works in its own copy of the package and its own results file, so nothing is shared.
    Output keeps the given order; ids in argv select mutants. The 2026-10-21 CI run with 89
    mutants took 21 of the job's 25 minutes in series. Exit 0 only when at least one mutant
    ran and every one was KILLED; a bad option or id exits 2 (SystemExit from argparse)."""
    import concurrent.futures
    ns = parse_args(argv, [m[0] for m in mutants], prog)
    pick = set(ns.ids)
    chosen = [m for m in mutants if not pick or m[0] in pick]
    if not chosen:
        print(f"{label}: no mutants selected; nothing was checked")
        return 2
    killed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=ns.jobs) as pool:
        for m, (outcome, detail) in zip(chosen, pool.map(lambda m: runner(*m), chosen)):
            killed += outcome == "KILLED"
            print(f"{outcome:<11} {m[0]} {m[1]}: {m[2]}  [{detail}]", flush=True)
    print(f"{label}: {killed}/{len(chosen)} killed on target (jobs={ns.jobs})")
    return 0 if killed == len(chosen) else 1


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

    def run(argv, runner, mutants=fake):
        calls.clear()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = run_all(mutants, "SELFTEST", argv, runner)
            except SystemExit as e:
                rc = e.code
        return rc, list(calls)

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
        ("ids select, in matrix order", run(["F2", "F1"], killed) == (0, ["F1", "F2"])),
        ("an empty matrix is not a success", run([], killed, mutants=[]) == (2, [])),
    ]
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
