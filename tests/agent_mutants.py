#!/usr/bin/env python3
"""Each mutant removes one guard of warrant_agent and must make ITS case fail.

    python3 tests/agent_mutants.py [--jobs N] [ID ...]
    python3 tests/agent_mutants.py --shard K/N --matrix FILE | --merge OUT FILE ...

The controller is tests/mutants.py's run_all: the same red-baseline guard, shards and merge.

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
     [("    need(S.hex64(draft_id), \"BAD_REQUEST\", \"draft_id is a hex64 address\")\n", "")],
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
    ("A31", "../warrant/shapes.py", "a view token may end in a newline (shapes.HEX32, the one definition)",
     [('HEX32 = re.compile(r"^[0-9a-f]{32}\\Z")', 'HEX32 = re.compile(r"^[0-9a-f]{32}$")')], "agent_handoff_test", ["V12"]),
    ("A32", "_assess_worker.py", "the worker's view token is its own `$`-anchored pattern, not shapes.HEX32",
     [('TOKEN = S.HEX32', 'TOKEN = __import__("re").compile(r"^[0-9a-f]{32}$")')], "agent_handoff_test", ["V12"]),
    ("A33", "config.py", "a workspace or expectation handle may end in a newline",
     [('HANDLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}\\Z")', 'HANDLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")')],
     "agent_handoff_test", ["H15"]),
    ("A34", "../warrant/shapes.py", "the hex64 predicate payload and manifest ids use is `$`-anchored, as handoff's own copy was at 1d67124",
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
     [('request_id = "auto:" + C.doc_id(given)', 'request_id = "auto:" + C.doc_id(dict(given, t=time.time_ns()))')],
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
     [('    need(S.is_actor(actor), "BAD_REQUEST", "actor: not an actor id (SPEC §3)")',
       '    need(isinstance(actor, str) and actor, "BAD_REQUEST", "actor")')], "agent_write_test", ["W10"]),
    # F43: prepare extends the signer's chain; commit is a compare-and-swap on its head (SPEC §3)
    ("A57", "drafts.py", "prepare files a genesis whatever the signer's head is",
     [('full, prev=head[0] if head else None)', 'full, prev=None)')], "agent_write_test", ["W11"]),
    ("A58", "drafts.py", "prepare dates the record now even when the signer's head is dated later",
     [('max(int(time.time()), head[1] if head else 0)', 'int(time.time())')], "agent_write_test", ["W11"]),
    ("A59", "drafts.py", "commit files the draft with no check of the signer's head",
     [('            store.extend(d["record"], key, ws.trust())\n', '            store.put_record(d["record"], key)\n')],
     "agent_write_test", ["W11"]),
    ("A60", "drafts.py", "a moved head is refused untyped",
     [('                                         "prepare it again", reason="CHAIN_MOVED") from None',
       '                                         "prepare it again") from None')], "agent_write_test", ["W11"]),
    # Agent interface under the spec (SPEC §10): one guard per sentence a case witnesses
    ("A61", "api.py", "a request's unknown members are accepted (a request member could choose the signer)",
     [('    need(not extra, "BAD_REQUEST", f"unknown members {sorted(extra)}")\n', "")], "agent_write_test", ["W06"]),
    ("A62", "api.py", "the interface version a request names is not checked",
     [('    if isinstance(req, dict) and "agent_api" in req and req["agent_api"] != AGENT_API:\n', "    if False:\n")],
     "agent_mcp_test", ["M02"]),
    ("A63", "api.py", "bytes read from a view are not marked as untrusted data",
     [('            "untrusted_data": True}\n', '            "untrusted_data": False}\n')], "agent_handoff_test", ["V07"]),
    ("A64", "views.py", "a view whose assessment failed is kept",
     [("    except AgentError:\n        shutil.rmtree(vdir, ignore_errors=True)\n        raise\n",
       "    except AgentError:\n        raise\n")], "agent_handoff_test", ["V08"]),
    ("A66", "views.py", "a view never expires",
     [('    if meta["expires"] is None or time.time() >= meta["expires"]:\n', '    if meta["expires"] is None:\n')],
     "agent_handoff_test", ["V03"]),
    ("A67", "api.py", "a cursor of another view, kind or target is accepted",
     [('    if len(parts) != 4 or parts[:3] != [token, kind, target or ""] or not parts[3].isdigit():\n',
       "    if len(parts) != 4 or not parts[3].isdigit():\n")], "agent_mcp_test", ["M05"]),
    ("A68", "handoff.py", "another manifest from the expected source matches the expectation",
     [('    elif expect["manifest"] != mhash:\n', "    elif False:\n")], "agent_handoff_test", ["H05"]),
    ("A69", "handoff.py", "import promotes a delivery whatever its relation",
     [("    if rel not in allowed:\n", "    if False:\n")], "agent_handoff_test", ["H06"]),
    ("A70", "handoff.py", "an inspected transfer is not bounded by transfer_bytes",
     [("            if total > limit:\n", "            if False:\n")], "agent_handoff_test", ["H12"]),
    ("A71", "drafts.py", "a transition prepared without closes is refused instead of closing nothing",
     [('    if rtype == "transition" and "closes" not in body:\n', "    if False:\n")], "agent_mcp_test", ["M13"]),
    ("A72", "drafts.py", "a retried commit signs and files the draft again instead of returning the filed record",
     [("    if dst.is_file():\n        why, rec", "    if False:\n        why, rec")], "agent_write_test", ["W04"]),
    ("A73", "drafts.py", "a committed draft's status is not written down (a new request reads PREPARED)",
     [('        d["status"] = "COMMITTED"\n        views.write_json(path, d)\n', '        d["status"] = "COMMITTED"\n')],
     "agent_write_test", ["W05"]),
    ("A74", "glossary.py", "explain has no entry for a refusal code (NO_ASSESSMENT)",
     [('    "NO_ASSESSMENT": (', '    "NO_ASSESSMENT_": (')], "agent_mcp_test", ["M16"]),
    ("A75", "config.py", "every operation is permitted, whatever the operator listed",
     [('        need(op in self.operations, "NOT_PERMITTED",', '        need(True, "NOT_PERMITTED",')],
     "agent_write_test", ["W09"]),
    ("A76", "computeops.py", "compute reports any provider as accepted by the profile",
     [('    accepted = provider.id in ws.profile().get("providers", [])\n', "    accepted = True\n")],
     "agent_compute_test", ["S08"]),
    ("A77", "computeops.py", "the provider runs without the workspace's provider_seconds deadline",
     [('        out = provider.call(op, args, blobs, timeout=ws.limits["provider_seconds"])\n',
       "        out = provider.call(op, args, blobs)\n")], "agent_compute_test", ["S07"]),
    ("A78", "drafts.py", "a challenge of a closure the use already holds (CHALLENGED) is refused: a use gate on recording",
     [("    full = _accept_body(vdir, body) if rtype == \"accept\" else fill(rtype, body)\n",
       "    full = _accept_body(vdir, body) if rtype == \"accept\" else fill(rtype, body)\n"
       "    from warrant import engine as _E\n"
       "    if rtype == \"challenge\" and any(_E.reliance(report, did, next(iter(ws.uses)))[\"state\"] == \"CHALLENGED\"\n"
       "                                     for did, d in report[\"duties\"].items() for c in d[\"candidates\"]\n"
       "                                     if c[\"transition\"] == body.get(\"target\")):\n"
       "        raise AgentError(\"NOT_PERMITTED\", \"the use holds this closure already\")\n")],
     "agent_write_test", ["W07"]),
    ("A79", "handoff.py", "a MATCH is reported as attesting the source complete",
     [('"source_completeness": "UNATTESTED", "reasons": reasons}',
       '"source_completeness": "COMPLETE" if relation == "MATCH_EXPECTED_SET" else "UNATTESTED", "reasons": reasons}')],
     "agent_handoff_test", ["H01"]),
    ("A80", "cli.py", "the command line rewrites a request before the backend sees it",
     [("        out = api.call(cfg, a.operation, req)\n",
       '        out = api.call(cfg, a.operation, dict(req, request_id="cli") if a.operation == "prepare" else req)\n')],
     "agent_mcp_test", ["M01"]),
    ("A81", "mcp_server.py", "an MCP `targets` left out is sent as null instead of being left out of the request",
     [("    return {k: v for k, v in kw.items() if v is not None}\n",
       "    return {k: v for k, v in kw.items() if v is not None or k == \"targets\"}\n")],
     "agent_mcp_test", ["M09"]),
    ("A82", "api.py", "a target's reliance does not hold the use, whatever the policy accepts",
     [('        if st["state"] not in policy.get("reliance", ["ELIGIBLE"]):\n', "        if False:\n")],
     "agent_handoff_test", ["H01"]),
    ("A83", "api.py", "a delivery relation the use's policy does not accept does not hold the use",
     [('    if delivery["relation"] not in allowed:\n', "    if False:\n")], "agent_handoff_test", ["H02"]),
    ("A84", "drafts.py", "an accept without evidence takes the transition's whole evidence, not its item's",
     [('    ev = evidence if item is None else closes[item].get("evidence") if isinstance(closes[item], dict) else None\n',
       "    ev = evidence\n")], "agent_write_test", ["W13"]),
    ("A85", "handoff.py", "an expectation's source is not checked",
     [('    elif expect.get("source") not in (None, manifest["source"]):\n', "    elif False:\n")],
     "agent_handoff_test", ["H17"]),
    ("A86", "handoff.py", "an expectation's exporter is not checked at inspection",
     [('    elif expect.get("exporter") and exporter != expect["exporter"]:\n', "    elif False:\n")],
     "agent_handoff_test", ["H17"]),
    # A repository checkout (tests/agent_repo_test.py): init, the repository's trust, prepare's blobs.
    ("A87", "init.py", "init accepts a seed whose key is not the one roles.json pins for the actor",
     [('    _refuse(key.public == pin, "INIT_KEY_NOT_PINNED",', '    _refuse(True, "INIT_KEY_NOT_PINNED",')], "agent_repo_test", ["I02"]),
    ("A88", "init.py", "init takes a reserved, collective or unpinned actor as a signer",
     [('    _refuse(S.hex64(pin), "INIT_ACTOR_NOT_PINNED",', '    _refuse(True, "INIT_ACTOR_NOT_PINNED",')], "agent_repo_test", ["I03"]),
    ("A89", "init.py", "init takes a pinned key whose binding trust.json does not admit",
     [('    _refuse((actor, key.public) in admitted, "INIT_NOT_ADMITTED",', '    _refuse(True, "INIT_NOT_ADMITTED",')],
     "agent_repo_test", ["I04"]),
    ("A90", "init.py", "init writes the configuration or the state, or reads the seed, inside the repository",
     [('        _refuse(not _inside(p, repo), "INIT_INSIDE_REPOSITORY",', '        _refuse(True, "INIT_INSIDE_REPOSITORY",')],
     "agent_repo_test", ["I06"]),
    ("A91", "init.py", "init replaces an existing configuration without --force",
     [('    _refuse(force or not config.exists(), "INIT_CONFIG_EXISTS",', '    _refuse(True, "INIT_CONFIG_EXISTS",')],
     "agent_repo_test", ["I08"]),
    ("A92", "init.py", "the profile does not count the roadmap's results acceptors",
     [('results_by=rm["results_accept_by"])', 'results_by=[])')], "agent_repo_test", ["I01"]),
    ("A93", "init.py", "a missing seed is not refused as such (it is read anyway)",
     [('    _refuse(seed.is_file(), "INIT_NO_SEED",', '    _refuse(True, "INIT_NO_SEED",')], "agent_repo_test", ["I05"]),
    ("A104", "init.py", "init writes or reads outside the operator's directory",
     [('    if os.path.commonpath([real, base]) == base:\n        return Path(real)', '    if True:\n        return Path(real)')],
     "agent_repo_test", ["I11"]),
    ("A94", "config.py", "a repository's bindings are admitted without its roles",
     [("    admitted, refused = B.admit_bindings(doc, roles=roles)", "    admitted, refused = B.admit_bindings(doc)")],
     "agent_repo_test", ["T02"]),
    ("A95", "config.py", "a roles file with a problem is read as fewer pins",
     [('    need(not problems, "BAD_REQUEST", "repository trust: "', '    need(True, "BAD_REQUEST", "repository trust: "')],
     "agent_repo_test", ["T03"]),
    ("A96", "config.py", "a repository's trust is read once, when the configuration loads",
     [('            self.trust_path, self.roles_path = Path(trust["bindings"]), Path(trust["roles"])\n',
       '            self.trust_path, self.roles_path = Path(trust["bindings"]), Path(trust["roles"])\n'
       '            self._frozen = C.canon(repository_trust(self.trust_path, self.roles_path))\n'),
      ("        return C.canon(repository_trust(self.trust_path, self.roles_path))", "        return self._frozen")],
     "agent_repo_test", ["T01"]),
    ("A97", "drafts.py", "a draft's blobs are not stored at commit",
     [('    for doc, h in zip(d.get("blobs", []), d["preview"].get("blobs", [])):', '    for doc, h in []:')],
     "agent_repo_test", ["B01"]),
    ("A98", "drafts.py", "a blob the body does not cite is accepted",
     [('    need(len(cited) == len(ids), "BAD_REQUEST",', '    need(True, "BAD_REQUEST",')], "agent_repo_test", ["B02"]),
    ("A99", "drafts.py", "a draft's blobs are not part of its inputs",
     [('    given = {"type": rtype, "body": body, **({"blobs": blobs} if blobs is not None else {})}',
       '    given = {"type": rtype, "body": body}')], "agent_repo_test", ["B03"]),
    ("A100", "drafts.py", "a commit under another signer stores the draft's blobs before it is refused",
     [('        if (actor, key.id) != (d["actor"], d["key"]):\n            raise AgentError("SIGNER_CHANGED"',
       '        _put_blobs(store, d)\n        if (actor, key.id) != (d["actor"], d["key"]):\n            raise AgentError("SIGNER_CHANGED"')],
     "agent_repo_test", ["B04"]),
    ("A101", "api.py", "a scoped context lists only the unowned questions of its scope",
     [("E.questions(report, scope=scope, owned=True)", "E.questions(report, scope=scope)")], "agent_repo_test", ["Q03"]),
    ("A102", "api.py", "a scope's questions come after the frontier",
     [('    if scope is not None:\n        items += [{"section": "question", "item": q} for q in E.questions(report, scope=scope, owned=True)]\n'
       '    items += [{"section": "frontier", "item": f} for f in E.frontier(report, actor)]\n',
       '    items += [{"section": "frontier", "item": f} for f in E.frontier(report, actor)]\n'
       '    if scope is not None:\n        items += [{"section": "question", "item": q} for q in E.questions(report, scope=scope, owned=True)]\n')],
     "agent_repo_test", ["Q03"]),
    ("A103", "api.py", "a context page read later forgets the context's scope",
     [('req.get("cursor"), max_bytes, ctx.get("scope"))', 'req.get("cursor"), max_bytes, None)')], "agent_repo_test", ["Q03"]),
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
        from mutants import NO_BYTECODE
        env = dict(os.environ, WARRANT_IMPL=str(tmp), WARRANT_RESULTS=str(res), PYTHONDONTWRITEBYTECODE=NO_BYTECODE)
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
    sys.dont_write_bytecode = True      # importing tests/mutants.py must not write tests/__pycache__ (NO_BYTECODE)
    from mutants import run_all
    return run_all(MUTANTS, "AGENT MUTANTS", sys.argv[1:], run_one, prog="agent_mutants")


if __name__ == "__main__":
    sys.exit(main())
