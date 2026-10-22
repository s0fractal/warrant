#!/usr/bin/env python3
"""Each mutant removes one guard of warrant_agent and must make ITS case fail.

    python3 tests/agent_mutants.py [--jobs N] [ID ...]

KILLED only when the named case fails; OFF_TARGET, SURVIVED, CRASH and
BAD_MUTANT are not kills."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MUTANTS = [
    ("A01", "handoff.py", "the package's own manifest digest becomes the expectation",
     [("    expect = ws.expectation(expectation)\n",
       "    expect = ws.expectation(expectation) or {\"manifest\": C.doc_id(manifest), \"handle\": \"package\"}\n")],
     "agent_handoff_test", ["H04"]),
    ("A02", "handoff.py", "the manifest's envelope digests are not checked",
     [("        elif rid in declared and C.digest(data) != declared[rid]:\n", "        elif False:\n")],
     "agent_handoff_test", ["H07"]),
    ("A03", "handoff.py", "missing declared bytes do not change the relation",
     [("    elif missing:\n        relation = \"MISSING_DECLARED_BYTES\"\n", "")], "agent_handoff_test", ["H02"]),
    ("A04", "views.py", "the view assesses a default profile, not the receiver's",
     [("    trust_bytes, profile = ws.trust_bytes(), ws.profile()   # each read once",
       "    trust_bytes, profile = ws.trust_bytes(), dict(ws.profile(), challengers=[\"auditor\"])")],
     "agent_handoff_test", ["V05"]),
    ("A05", "api.py", "a read of a view re-assesses the live store",
     [("    meta, report, vdir = views.load(ws, req[\"view_token\"])\n",
       "    meta, report, vdir = views.load(ws, req[\"view_token\"])\n"
       "    meta, report, _ = views.load(ws, views.capture(ws)[\"token\"])\n")],
     "agent_handoff_test", ["V01"]),
    ("A06", "api.py", "truncation is not marked",
     [("\"truncated\": nxt is not None,", "\"truncated\": False,")], "agent_handoff_test", ["V04"]),
    ("A07", "views.py", "an incomplete import does not hold use",
     [("        if doc.get(\"status\") != \"COMPLETE\" and not _landed(ws, doc):\n            out.append(p.stem)\n", "")],
     "agent_handoff_test", ["H11"]),
    ("A08", "api.py", "the decision id ignores what is observed now",
     [("\"as_of\": meta[\"as_of\"], \"observed\": observed,", "\"as_of\": meta[\"as_of\"],")],
     "agent_handoff_test", ["V01"]),
    ("A09", "drafts.py", "a repeated prepare files a new draft",
     [("        need(d[\"inputs\"] == inputs, \"CONFLICT\", \"request_id was prepared with other inputs\")\n        return d\n",
       "        need(d[\"inputs\"] == inputs, \"CONFLICT\", \"request_id was prepared with other inputs\")\n        path.unlink()\n")],
     "agent_write_test", ["W02"]),
    ("A10", "drafts.py", "another body under the same request id is accepted",
     [("        need(d[\"inputs\"] == inputs, \"CONFLICT\", \"request_id was prepared with other inputs\")\n", "")],
     "agent_write_test", ["W03"]),
    ("A11", "drafts.py", "a draft is signed by whoever is configured now",
     [("        if (actor, key.id) != (d[\"actor\"], d[\"key\"]):\n", "        if False:\n")],
     "agent_write_test", ["W08"]),
    ("A12", "handoff.py", "records that do not authenticate are promoted",
     [("    if invalid:\n        raise AgentError(\"IMPORT_BLOCKED\"", "    if False:\n        raise AgentError(\"IMPORT_BLOCKED\"")],
     "agent_handoff_test", ["H09"]),
    ("A13", "computeops.py", "compute reads the store again for each byte",
     [("            ck, st = _bytes(snap, req[\"checkpoint\"], \"checkpoint\"), _bytes(snap, req[\"state\"], \"state\")\n",
       "            ck, st = _bytes(snap, req[\"checkpoint\"], \"checkpoint\"), _bytes(snap, req[\"state\"], \"state\")\n"
       "            _real = provider.call\n"
       "            def _late(op_, args_, blobs_, timeout=None, _r=_real):\n"
       "                args_[\"state\"] = base64.b64encode((ws.store / \"blobs\" / req[\"state\"]).read_bytes()).decode()\n"
       "                return _r(op_, args_, blobs_, timeout=timeout)\n"
       "            provider.call = _late\n")],
     "agent_compute_test", ["S10"]),
    ("A16", "views.py", "a view writes any name it is handed",
     [("    need(pattern.match(name) is not None, \"BAD_REQUEST\", \"not a content address\")\n", "")],
     "agent_handoff_test", ["H08"]),
    ("A17", "api.py", "a changed receiver expectation does not hold current use",
     [("    if exp is not None and exp[\"state\"] != \"CURRENT\":\n", "    if False:\n")], "agent_handoff_test", ["H13"]),
    ("A18", "handoff.py", "import trusts the relation computed at inspection",
     [("    if delivery[\"expectation\"] is not None and \\\n", "    if False and \\\n")], "agent_handoff_test", ["H13"]),
    ("A19", "drafts.py", "a draft id is any string",
     [("    need(_hex64(draft_id), \"BAD_REQUEST\", \"draft_id is a hex64 address\")\n", "")],
     "agent_write_test", ["W09"]),
    ("A20", "drafts.py", "a draft file is read whatever workspace it names",
     [("d.get(\"workspace\") == ws.name and d.get(\"draft_id\") == draft_id", "d.get(\"draft_id\") == draft_id")],
     "agent_write_test", ["W09"]),
    ("A21", "drafts.py", "a draft file is read whatever id it names",
     [("d.get(\"workspace\") == ws.name and d.get(\"draft_id\") == draft_id", "d.get(\"workspace\") == ws.name")],
     "agent_write_test", ["W09"]),
    ("A22", "handoff.py", "import does not re-check the exporter under the current trust",
     [("    if want and _declaration_actor(", "    if False and _declaration_actor(")], "agent_handoff_test", ["H14"]),
    ("A23", "api.py", "a changed receiver trust does not hold a fresh use",
     [("    if not observed[\"trust_current\"] and (policy.get(\"fresh\", True) or delivery.get(\"exporter\")):\n",
       "    if False:\n")],
     "agent_handoff_test", ["H14"]),
    ("A24", "views.py", "an unfinished import holds the workspace even after its bytes all landed",
     [("    return True\n\n\ndef incomplete_imports", "    return False\n\n\ndef incomplete_imports")],
     "agent_handoff_test", ["H14"]),
    ("A26", "api.py", "an exporter-based delivery holds on a trust change only for fresh uses",
     [("(policy.get(\"fresh\", True) or delivery.get(\"exporter\"))", "policy.get(\"fresh\", True)")],
     "agent_handoff_test", ["H14"]),
    ("A27", "views.py", "an unfinished import counts as landed from whatever is left in staging",
     [("    manifest = read_json(spath)[\"manifest\"]\n", "    manifest = {\"records\": [], \"blobs\": []}\n")],
     "agent_handoff_test", ["H14"]),
    ("A25", "config.py", "only the manifest digest identifies an expectation",
     [("        return None if e is None else C.digest(json.dumps(e, sort_keys=True, separators=(\",\", \":\")).encode())",
       "        return None if e is None else e[\"manifest\"]")], "agent_handoff_test", ["H14"]),
    ("A28", "views.py", "an admission limit in the worker becomes NO_ASSESSMENT, not RESOURCE_LIMIT",
     [("    if (vdir / \"refusal.json\").is_file():\n", "    if False:\n")], "agent_handoff_test", ["V09"]),
    ("A29", "config.py", "a malformed engine limit in the configuration is accepted",
     [("            L.resolve(self.assessment_limits())\n", "            pass\n")], "agent_handoff_test", ["V10"]),
    ("A30", "_assess_worker.py", "the worker reads whatever directory it is given",
     [("    if not (p.is_absolute() and TOKEN.match(p.name)", "    if False and (p.is_absolute() and TOKEN.match(p.name)")],
     "agent_handoff_test", ["V11"]),
    ("A14", "mcp_server.py", "a refusal is returned as an ordinary result",
     [("        raise ToolError(json.dumps(out, sort_keys=True))\n", "        return out\n")], "agent_mcp_test", ["M02"]),
    ("A15", "mcp_server.py", "the server writes a banner to stdout",
     [("    server.run(\"stdio\")\n", "    print(\"warrant-agent-mcp ready\", flush=True)\n    server.run(\"stdio\")\n")],
     "agent_mcp_test", ["M03"]),
    # A31-A35 restore the `$` anchors of AMEND 2 of #164 (`$` matches before a final newline)
    ("A31", "views.py", "a view token may end in a newline",
     [('TOKEN = re.compile(r"^[0-9a-f]{32}\\Z")', 'TOKEN = re.compile(r"^[0-9a-f]{32}$")')], "agent_handoff_test", ["V12"]),
    ("A32", "_assess_worker.py", "the worker accepts a view directory whose name ends in a newline",
     [('TOKEN = re.compile(r"^[0-9a-f]{32}\\Z")', 'TOKEN = re.compile(r"^[0-9a-f]{32}$")')], "agent_handoff_test", ["V12"]),
    ("A33", "config.py", "a workspace or expectation handle may end in a newline",
     [('HANDLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}\\Z")', 'HANDLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")')],
     "agent_handoff_test", ["H15"]),
    ("A34", "handoff.py", "a payload or manifest id uses its own `$`-anchored hex64, as at 1d67124",
     [("    return isinstance(v, str) and HEX64.match(v) is not None",
       "    return isinstance(v, str) and __import__(\"re\").match(r\"^[0-9a-f]{64}$\", v) is not None")], "agent_handoff_test", ["H15"]),
    ("A35", "views.py", "a view file name uses its own `$`-anchored address, as at 1d67124",
     [('    need(pattern.match(name) is not None, "BAD_REQUEST", "not a content address")',
       '    need(re.match(pattern.pattern.replace("\\\\Z", "$"), name) is not None, "BAD_REQUEST", "not a content address")')],
     "agent_handoff_test", ["H15"]),
    # A41-A53: the first-contact interface (examples/mcp-first-contact); each removes one property, not a wording
    ("A41", "api.py", "the overview shows the signer's key file",
     [('"signer": ws.signer[0] if ws.signer else None,', '"signer": [ws.signer[0], str(ws.signer[1])] if ws.signer else None,')],
     "agent_mcp_test", ["M06"]),
    ("A42", "api.py", "an id that is no duty of the view is taken for a transition",
     [("    if tid in report[\"results\"]:\n        return \"transition\"\n", "    return \"transition\"\n")],
     "agent_mcp_test", ["M07"]),
    ("A43", "api.py", "a duty capsule lists only admitted closures",
     [('for c in report["duties"][tid]["candidates"]]', 'for c in report["duties"][tid]["candidates"] if c["verdict"] == "ADMITTED"]')],
     "agent_mcp_test", ["M08"]),
    ("A44", "api.py", "a transition capsule drops why its items were not admitted",
     [('if k in c and k != "transition"}', 'if k in c and k not in ("transition", "why")}')],
     "agent_compute_test", ["S11"]),
    ("A45", "api.py", "the default use is a fixed name, not the operator's first configured use",
     [("        return next(iter(ws.uses))\n", "        return \"continue\"\n")], "agent_mcp_test", ["M09"]),
    ("A46", "handoff.py", "export checks its manifest with an assert again (an untyped crash, gone under -O)",
     [('    need(manifest_problem(manifest) is None, "BAD_REQUEST", f"export: {manifest_problem(manifest)}")\n',
       "    assert manifest_problem(manifest) is None\n")], "agent_mcp_test", ["M10"]),
    ("A47", "api.py", "an inspection without targets shows no capsules instead of the package's roots",
     [('        shapes = [(r["kind"], r["id"]) for r in req["manifest"]["roots"]]\n', "        shapes = []\n")],
     "agent_mcp_test", ["M11"]),
    ("A48", "api.py", "the boundary counts invalid records but does not name them",
     [('[_invalid(ws, meta, i, w) for i, w in sorted(report["invalid_records"].items())][:20]', "[]")],
     "agent_mcp_test", ["M11"]),
    ("A49", "api.py", "a package in one piece drops its declaration",
     [('payload=pkg["payload"], **({"declaration": pkg["declaration"]} if "declaration" in pkg else {}))',
       'payload=pkg["payload"])')], "agent_mcp_test", ["M11"]),
    ("A50", "api.py", "a context page is read without the view that made it",
     [('        need(kind != "context", "BAD_REQUEST", "a context page needs the view_token of warrant_context")\n', "")],
     "agent_mcp_test", ["M12"]),
    ("A51", "drafts.py", "a draft without a request id gets a fresh name each time",
     [('request_id = "auto:" + C.doc_id({"type": rtype, "body": body})',
       'request_id = "auto:" + C.doc_id({"type": rtype, "body": body, "t": time.time_ns()})')],
     "agent_mcp_test", ["M13"]),
    ("A52", "drafts.py", "an invalid body is refused without its type's template",
     [('raise AgentError("BAD_REQUEST", f"invalid {rtype}: {e}", template=TEMPLATES[rtype]) from None',
       'raise AgentError("BAD_REQUEST", f"invalid {rtype}: {e}") from None')], "agent_mcp_test", ["M13"]),
    ("A53", "computeops.py", "evaluate calls any result the expected one",
     [('same_normal_form=seg.get("outcome") == "NORMAL_FORM" and seg.get("result") == e["input"])',
       'same_normal_form=seg.get("outcome") == "NORMAL_FORM")')], "agent_compute_test", ["S12"]),
    # A54-A56 restore the unguarded reads of stored record bytes of 7a56a56 (Codex P2 on PR #167)
    ("A54", "api.py", "an invalid record's bytes are read as a record (as at 7a56a56)",
     [('        rec = _record_shape((ws.state / "views" / meta["token"] / "records" / f"{rid}.json").read_bytes())\n',
       '        rec = C.loads((ws.state / "views" / meta["token"] / "records" / f"{rid}.json").read_bytes())["record"]\n'
       '        rec.get("type")\n')],
     "agent_mcp_test", ["M15"]),
    ("A55", "api.py", "the workspace index reads every stored record, authentic or not (as at 7a56a56)",
     [("    for rid, rec in good.items():\n",
       "    for rid, rec in ((i, C.loads(d)[\"record\"]) for i, d in snap.records.items() if d[:1] == b\"{\"):\n"
       "        rec.get(\"type\")\n")],
     "agent_mcp_test", ["M15"]),
    ("A56", "api.py", "a target's record type is read from bytes that are not a record",
     [('    rtype = rec["type"] if rec else "unreadable"\n',
       '    rtype = C.loads(p.read_bytes())["record"].get("type", "unreadable")\n')],
     "agent_mcp_test", ["M15"]),
    # W5: the actor id of SPEC §3 in the agent's configuration and requests
    ("A36", "config.py", "the configured signer need not be an actor id",
     [('                R.check_actor(signer["actor"], "signer actor")       # SPEC §3: the one shape of an actor id\n',
       '                pass\n')], "agent_write_test", ["W10"]),
    ("A37", "api.py", "a context request's actor is any non-empty string, as at 849cbfa",
     [('    need(_is_actor(actor), "BAD_REQUEST", "actor: not an actor id (SPEC §3)")',
       '    need(isinstance(actor, str) and actor, "BAD_REQUEST", "actor")')], "agent_write_test", ["W10"]),
]


def run_one(mid, fname, what, edits, test, targets, also=()):
    """(outcome, detail, runs), as tests/mutants.py's run_one; `also`: more test files (--matrix)."""
    from mutants import verdict
    tmp = Path(tempfile.mkdtemp(prefix=f"warrant-agent-{mid}-"))
    try:
        shutil.copytree(ROOT / "warrant", tmp / "warrant", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "warrant_agent", tmp / "warrant_agent", ignore=shutil.ignore_patterns("__pycache__"))
        p = tmp / "warrant_agent" / fname
        src = p.read_text()
        for old, new in edits:
            if src.count(old) != 1:
                return "BAD_MUTANT", f"{old[:50]!r} found {src.count(old)} times", {}
            src = src.replace(old, new)
        p.write_text(src)
        res = tmp / "results.json"
        env = dict(os.environ, WARRANT_IMPL=str(tmp), WARRANT_RESULTS=str(res))
        run = subprocess.run([sys.executable, str(ROOT / "tests" / f"{test}.py")], env=env, capture_output=True,
                             text=True, cwd=ROOT / "tests", timeout=1800, check=False)
        if not res.exists():
            return "CRASH", "no results: " + " | ".join(run.stderr.strip().splitlines()[-3:]), {test: None}
        from mutants import run_tests
        runs = {test: json.loads(res.read_text()), **run_tests(tmp, [t for t in also if t != test], timeout=1800)}
        return (*verdict(runs, test, targets), runs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    from mutants import run_all
    return run_all(MUTANTS, "AGENT MUTANTS", sys.argv[1:], run_one, prog="agent_mutants")


if __name__ == "__main__":
    sys.exit(main())
