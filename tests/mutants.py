#!/usr/bin/env python3
"""Mutants: each is one exact find/replace (or a list of them) in one file and the cases it must fail. A mutant is KILLED only
when its run prints `FAIL <case>` for one of those cases: an import error, a crash before the case, or a
FAIL of another case proves nothing. The run happens in a copy of the tree under build/mutants/, one
mutant at a time with no bytecode cache, the file restored after each.

A run is of the sections that hold the mutant's cases, not of the whole test file (tests/world.py run_sections:
a test file's *_cases functions), and it ends at the first `FAIL` of one of its cases. Which section holds a case is
read, not written down: before any mutant, each section of each targeted test file runs alone, unmutated, in the same
copy, and every check it prints is mapped to it (WARRANT_CASE_MAP). That run is also the check that each section
passes alone (BASELINE_RED refuses the whole run otherwise: a section leaning on another's state would read a FAIL
caused by its isolation as a kill). A test file without sections runs whole, once unmutated as before. A mutant whose
case no clean run printed is NO_SECTION, never a full run that might find it. The test files still run whole in CI's
suites.

    python3 tests/mutants.py [IDS ...] [--shard K/N] [--matrix OUT.json] [--whole]
    python3 tests/mutants.py --merge OUT.json PART.json ...     # the union is every id once, each KILLED
    python3 tests/mutants.py --list                             # {id: [file, test, cases]} as JSON

The claims (warrant/claims.py) cite these ids; check refuses a claim citing an id that is not here, or one
whose cases are not among the claim's witnesses."""
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "build" / "mutants"
TMP = ROOT / "build" / "mutants-tmp"          # outside the copy: fixtures' homes and seeds lie outside its repository
CORE, AGENT, GATE, TOOLS, WAKER = ("tests/core_test.py", "tests/agent_test.py", "tests/gate_test.py",
                                   "tests/tools_test.py", "integrations/warrant-review/test_plugin.py")
E, S, RC = "warrant/engine.py", "warrant/store.py", "warrant/records.py"
SHAPES_TEST = "tests/shapes_test.py"
E, S, RC, DR = "warrant/engine.py", "warrant/store.py", "warrant/records.py", "warrant/drift.py"
VERIFY, VF = "tests/verify_test.py", "warrant/verify.py"
ONE, ONE_SRC, ONE_BUILD = "warrant_verify.py", "tools/verify_single.py", "tools/build_verify.py"
PINS = "warrant/pins.py"        # the comparison of an acceptance's files with a tree: warrant.drift's, and warrant.verify's
# (id, file, find, replace, test file, cases)
MUTANTS = [
    # §3 lineage
    ("V1", E, 'eff = {L: next((v for v in reversed(lin["path"]) if v in met), None) for L, lin in self.lineages.items()}',
     'eff = {L: lin["path"][-1] if lin["path"] else None for L, lin in self.lineages.items()}', CORE, ["L6"]),
    ("V7", E, 'forks = {p: c for p, c in lin["succ"].items() if len(c) > 1}', "forks = {}", CORE, ["L7"]),
    ("V8", E, "elif not may_succeed(r, self.recs[rt]):", "elif False:", CORE, ["L8"]),
    ("V13", E, 'return r["actor"] == root["actor"] if roles is None else self.holds(r["actor"], *roles)',
     'return r["actor"] == root["actor"]', CORE, ["L11"]),
    ("V14", E, 'return r["actor"] == root["actor"] if roles is None else self.holds(r["actor"], *roles)',
     'return r["actor"] == root["actor"] or (roles is not None and self.holds(r["actor"], *roles))', CORE, ["L13"]),
    ("V17", E, 'if rt is None or self.recs[p]["kind"] != r["kind"] or self.recs[p]["schema"] != r["schema"]:',
     "if rt is None:", CORE, ["L14"]),
    # §4 schemas
    ("V16", E, "elif len(self.backers(i)) < self.quorum(SCHEMA_AUTHOR):", "elif not self.backers(i):", CORE, ["S5"]),
    ("V32", E, 'if self.recs[a]["schema"] is None and self.recs[a]["body"].get("verdict") == "accept"}',
     'if self.recs[a]["body"].get("verdict") == "accept"}', CORE, ["S9"]),
    ("V33", E, "                    self.pending.append(i)          # waits",
     '                    self.problem("SCHEMA_NOT_COUNTED", i, "short of its quorum")\n                    self.pending.append(i)          # waits', CORE, ["S10"]),
    ("V34", E, '(r["schema"] == R.MIGRATION and r["kind"] == "attest")', 'r["schema"] == R.MIGRATION', CORE, ["S11"]),
    ("V18", E, 'self.problem("SCHEMA_CONFLICT", name, f"{len(leaves)} schema lineages name it")\n',
     'self.problem("SCHEMA_CONFLICT", name, f"{len(leaves)} schema lineages name it")\n                self.schemas[name] = {"id": leaves[0], **self.recs[leaves[0]]["body"]}\n', CORE, ["S2"]),
    ("V19", E, "    if not R.body_refs(f, b) <= set(r[\"refs\"]):", "    if False:", CORE, ["S8"]),
    # §5 challenges, §6 guard
    ("V97", E, ' + ([R.named_key(r)] if R.named_key(r) else [])', "", CORE, ["KN1"]),
    ("V98", "warrant/records.py", 'return a[4:] if r["kind"] == "challenge" and a.startswith("key:")', 'return a[4:] if a.startswith("key:")', CORE, ["KN3"]),
    ("T125", "warrant/cli.py", 'and not (kind == "challenge" and a.actor == f"key:{key.public}"):', ":", TOOLS, ["K10"]),
    ("T126", "warrant/cli.py", 'not (kind == "challenge" and a.actor == f"key:{key.public}")', 'not a.actor == f"key:{key.public}"', TOOLS, ["K11"]),
    ("V90", E, "        self._pins()\n", "", CORE, ["P2"]),
    ("V91", E, '.get(k, object()) != v for k, v in pin.items()):', '.get(k, object()) != v for k, v in pin.items() if k != "code"):', CORE, ["P2"]),
    ("V92", E, 'root, seen = r, {i}\n            while root["lineage"] in self.recs and root["lineage"] not in seen:', 'root, seen = r, {i}\n            while False:', CORE, ["P2"]),
    ("V93", E, "if pin is not None and not isinstance(pin, dict):", "if False:", CORE, ["P3"]),
    ("V94", E, 'and ("pinned" not in b or (isinstance(b["pinned"], str) and b["fields"].get(b["pinned"]) in ("obj", "obj?")))', "", CORE, ["P4"]),
    ("V95", E, 'set(b) <= SCHEMA_MEMBERS | {"pinned"}', "set(b)", CORE, ["P4"]),
    ("V96", E, 'elif pin and r["body"].get("state") in s["closed"] \\\n', 'elif pin \\\n', CORE, ["P1"]),
    ("V99", E, 'if s is None or "pinned" not in s:', 'if not (s and s.get("pinned")):', CORE, ["P5"]),
    ("V102", "warrant/store.py", "        except (ValueError, RecursionError):  # NotCanonical,", "        except C.NotCanonical:  # NotCanonical,", CORE, ["M6"]),
    ("V103", E, 'elif pin and r["body"].get("state") in s["closed"] and r["guard"]["quorum"] < 1:',
     'elif False:', CORE, ["P7"]),
    ("V104", E, 'stands = eff is None or (x in lin["path"] and lin["path"].index(eff) <= lin["path"].index(x))',
     'stands = x in lin["path"] and (eff is None or lin["path"].index(eff) <= lin["path"].index(x))', CORE, ["L15"]),
    ("V105", E, "        self._lineage_depth()\n", "", CORE, ["T16"]),
    ("V101", E, 'lambda s: isinstance(s, str) and isinstance(b["states"], dict) and s in b["states"]', 'lambda s: isinstance(b["states"], dict) and s in b["states"]', CORE, ["S12"]),
    ("V100", E, '.get(k, object()) == x for k, x in g["match"].items())})', '.get(k) == x for k, x in g["match"].items())})', CORE, ["G8"]),
    ("V3", E, 'return any(actor in self.profile["roles"].get(x, []) for x in roles)', "return True", CORE, ["C1", "S1"]),
    ("V4", E, 'out.update((self.recs[cur]["guard"] or {}).get("requires", []))', "pass", CORE, ["G1"]),
    ("V5", E, 'if self.recs[a]["actor"] != r["actor"] and self.holds', "if self.holds", CORE, ["L2"]),
    ("V9", E, 'if need is not None and _weaker(r["guard"], need):', "if False:", CORE, ["L9"]),
    ("V11", E, 'elif any(on == x and v == "reproduces" for on, v, _ in replays):', "elif False:", CORE, ["C1"]),
    ("V15", E, 'if r["body"].get("state") in self.schema_of(v).get("closed", []):       # with',
     'if g is not None and r["body"].get("state") in self.schema_of(v).get("closed", []):       # with', CORE, ["G3"]),
    ("V20", E, 'stands = eff is None or (x in lin["path"] and lin["path"].index(eff) <= lin["path"].index(x))',
     "stands = True", CORE, ["C4"]),
    ("V21", E, 'if len(acc) < g["quorum"]:', "if not acc:", CORE, ["G6"]),
    ("V30", E, "                    eff[U] = u\n                    moved.append(U)\n", "                    eff[U] = u\n", CORE, ["G7"]),
    ("V31", E, 'met = {v for v, (_, waiting) in part.items() if not waiting and not short.get(v)}',
     'met = {v for v, (_, waiting) in part.items() if not waiting}', CORE, ["G7"]),
    # §7 chains, §8 store
    ("V22", E, '    chained = {i for i, r in mine.items() if r["prev"] is None or (r["prev"] in mine and mine[r["prev"]]["at"] <= r["at"])}',
     '    chained = set()\n    for i in sorted(mine, key=lambda i: mine[i]["at"]):\n        if mine[i]["prev"] is None or mine[i]["prev"] in chained:\n            chained.add(i)', CORE, ["K2"]),
    ("V23", E, "        if max(depth.values(), default=0) > LIMITS[\"requires\"]:", "        if False:", CORE, ["T11"]),
    ("V24", S, '            if expect_head is not None and (h["id"] or "") != expect_head:', "            if False:", CORE, ["T8"]),
    ("V25", S, "            if raw in seen:\n                continue\n", "", CORE, ["T10"]),
    ("V26", S, "        order = list(lines) == sorted(set(lines), key=_line_id)", "        order = True", CORE, ["T1"]),
    ("V35", S, "        self.canonical = order and not self.rejected", "        self.canonical = order", CORE, ["T13"]),
    ("V36", S, "                if len(line) > R.LINE_MAX:", "                if False:", CORE, ["T14"]),
    ("V37", "warrant/cli.py", 'out = {"canonical": snap.canonical,', 'out = {"canonical": True,', TOOLS, ["K12"]),
    ("V27", E, "        if any(R.verifies(i, s, k) for s in sigs for k in keys):", "        if sigs:", CORE, ["T6"]),
    ("V28", S, "        if bad:\n            raise Refused", "        if False:\n            raise Refused", CORE, ["T12"]),
    # §9 migration
    ("V10", E, "if by is not None:", "if True:", CORE, ["M1"]),
    ("V12", E, 'elif any(e["sig"] is None for e in envs):', "elif not sigs:", CORE, ["M4"]),
    ("V29", E, '            if not (r["kind"] == "attest" and r["schema"] == R.MIGRATION and self.basis[i] == "SIGNED"\n                    and self.holds(r["actor"], "migrator")):',
     '            if not (r["kind"] == "attest" and r["schema"] == R.MIGRATION and self.basis[i] == "SIGNED"):', CORE, ["M3"]),
    # the agent interface
    # warrant across: one read over every registered store
    ("X1", "warrant/across.py", '"in": [v for v in (x.verdict(i) for x in readings) if v]}',
     '"in": [v for v in (readings[0].verdict(i) and dict(readings[0].verdict(i), store=x.name) for x in readings if x.verdict(i)) if v]}', AGENT, ["X01", "X02"]),
    ("X2", "warrant/across.py", "            self.view = E.View(snap, trust, profile)\n",
     '            Reading.roles = {k: sorted(set(getattr(Reading, "roles", {}).get(k, [])) | set(v)) for k, v in profile["roles"].items()}\n'
     '            self.view = E.View(snap, trust, dict(profile, roles=Reading.roles))\n', AGENT, ["X01"]),
    ("X3", "warrant/across.py", '"in": [v for v in (x.verdict(i) for x in readings) if v]}', '"in": [v for v in (x.verdict(i) for x in readings[:1]) if v]}', AGENT, ["X03"]),
    ("X4", "warrant/across.py", "    return _recent(ids, readings, schema)\n\n\ndef _open", "    return _recent(ids, readings, schema) * 2\n\n\ndef _open", AGENT, ["X03"]),
    ("X5", "warrant/across.py", "        if i in view.bad:\n", "        if False:\n", AGENT, ["X04"]),
    ("X6", "warrant/across.py", [('        mine = [i for i, r in x.view.recs.items() if r["actor"] == actor]\n',
                                   '        mine = [i for i, e in x.view.snap.lines.items() if e[0]["record"]["actor"] == actor]\n'),
                                  ("            r = x.view.recs[i]\n", '            r = x.view.snap.lines[i][0]["record"]\n')], None, AGENT, ["X04"]),
    ("X7", "warrant/across.py", 'keys=x.view.trust["keys"].get(actor, [])', 'keys=readings[0].view.trust["keys"].get(actor, [])', AGENT, ["X04"]),
    ("X8", "warrant/across.py", '    unavailable = [{"store": x.name, "why": _short(x.why)} for x in sorted(readings, key=lambda x: x.name) if x.why]\n',
     "    unavailable = []\n", AGENT, ["X05", "X06"]),
    ("X9", "warrant/across.py", "        except Exception as e:           # NOSONAR", "        except ZeroDivisionError as e:           # NOSONAR", AGENT, ["X05"]),
    ("X10", "warrant/across.py", "    confined(st.file, st.root)\n", "", AGENT, ["X05"]),
    ("X50", "warrant/across.py", "    confined(st.blobs, st.root)\n", "", AGENT, ["X05"]),
    ("X51", "warrant/across.py", '"root": rep["snapshot"], "as_of": rep["as_of"],', '"root": rep["snapshot"], "as_of": 0,', AGENT, ["X22"]),
    ("X11", "warrant/across.py", "    if size > limit:\n", "    if False:\n", AGENT, ["X05"]),
    ("X12", "warrant/across.py", "    if st.file.exists() and not st.file.is_file():\n", "    if False:\n", AGENT, ["X24"]),
    ("X13", "warrant/across.py", "        trust, profile, repository = H.receiver(path)\n",
     '        trust, profile, repository = H.receiver(path)\n        exec(open(os.path.join(path, "tools", "claims.py")).read())\n', AGENT, ["X07"]),
    ("X14", "warrant/across.py", 'and lin["state"] == "open"]', "]", AGENT, ["X08"]),
    ("X16", "warrant/across.py", "    return s if len(s) <= TEXT else s[:TEXT] + \"…\"\n", "    return s\n", AGENT, ["X08"]),
    ("X17", "warrant/across.py", 'row.update({"no_schema": missing} if missing else {})', "pass", AGENT, ["X09"]),
    ("X18", "warrant/across.py", 'for n in INTENTS if n in x.rep["schemas"]}', "for n in INTENTS}", AGENT, ["X09"]),
    ("X19", "warrant/across.py", 'for c, v in x.rep["challenges"].items() if v["stands"]}', 'for c, v in x.rep["challenges"].items() if v["counted"]}', AGENT, ["X10"]),
    ("X20", "warrant/across.py", "            if rel in G.WALK:\n", "            if True:\n", AGENT, ["X11"]),
    ("X21", "warrant/across.py", "    into = {}\n    for rep in reps:\n", "    into = {}\n    for rep in reps[:1]:\n", AGENT, ["X11"]),
    ("X22", "warrant/across.py", "        where = [x.name for x in readings if x.holds(h)]\n", "        where = [x.name for x in readings]\n", AGENT, ["X11", "X13"]),
    ("X23", "warrant/across.py", "        if all(x.holds(h) for x in admitting):\n", "        if True:\n", AGENT, ["X11", "X13"]),
    ("X24", "warrant/across.py", '    if S.citation(t):\n', "    if False:\n", AGENT, ["X12"]),
    ("X25", "warrant/across.py", '    if len(ids) != 1:\n', "    if not ids:\n        ids = {t}\n    if len(ids) != 1:\n", AGENT, ["X12"]),
    ("X26", "warrant/across.py", '{"id": h, "state": "UNAVAILABLE"})\n', '{"id": h, "state": "ABSENT"})\n', AGENT, ["X13"]),
    ("X27", "warrant/graph.py", '{"id": i, "kind": "unavailable"}', '{"id": i, "kind": "missing"}', AGENT, ["X13"]),
    ("X28", "warrant/engine.py", "    def _bodies(self):\n",
     '    def _bodies(self):\n        for i, r in sorted(self.recs.items()):\n            if any(h not in self.recs and h not in self.snap.blobs for h in r["refs"]):\n                self.problem("REF", i)\n', AGENT, ["X14"]),
    ("X49", "warrant/engine.py", "        still_open = [L for L in requires if L not in shut]\n", "        still_open = [L for L in requires if L not in shut and L in self.lineages]\n", AGENT, ["X14"]),
    ("X29", "warrant/across.py", "        if used + size > budget:\n", "        if False:\n", AGENT, ["X15"]),
    ("X30", "warrant/across.py", '"refs": refs[:REF_ROWS]', '"refs": refs', AGENT, ["X15"]),
    ("X31", "warrant/across.py", '"refs_more": max(0, len(refs) - REF_ROWS)', '"refs_more": 0', AGENT, ["X15"]),
    ("X32", "warrant/across.py", "    return rows[:REF_ROWS], max(0, len(rows) - REF_ROWS)\n", "    return rows[:REF_ROWS], 0\n", AGENT, ["X15"]),
    ("X33", "warrant/across.py", '    if used > budget:\n', "    if False:\n", AGENT, ["X16"]),
    ("X34", "warrant/across.py", '    if not out["nodes"] and pos < len(ids):\n', "    if False:\n", AGENT, ["X16"]),
    ("X35", "warrant/across.py", '    budget = min(budget, q.get("max_bytes", budget))\n', '    budget = q.get("max_bytes", budget)\n', AGENT, ["X16"]),
    ("X36", "warrant_agent/api.py", '        ws.permit("graph")\n        trust, profile = ws.receiver()\n', "        trust, profile = ws.receiver()\n", AGENT, ["X17"]),
    ("X37", "warrant/across.py", '        if "graph" not in r.get("operations", H.OPERATIONS):\n', "        if False:\n", AGENT, ["X17"]),
    ("X38", "warrant_agent/config.py", 'need(op in ALWAYS or op in self.operations, "NOT_PERMITTED"', 'need(True, "NOT_PERMITTED"', AGENT, ["X18"]),
    ("X39", "warrant_agent/config.py", '"operations": r.get("operations", list(OPERATIONS))}', '"operations": list(OPERATIONS)}', AGENT, ["X18"]),
    ("X40", "warrant/across.py", '"profile": rep["profile"], "checkout": rep.get("checkout")} for n, rep in reps.items()}', '"checkout": rep.get("checkout")} for n, rep in reps.items()}', AGENT, ["X19"]),
    ("X41", "warrant/across.py", '{n: rep["snapshot"] for n, rep in reps.items()}', '{n: rep["trust"] for n, rep in reps.items()}', AGENT, ["X19"]),
    ("X42", "warrant/cli.py", '    if not doc["repositories"]:\n        raise Refused("Home registers no repository', '    if False:\n        raise Refused("Home registers no repository', AGENT, ["X20"]),
    ("X44", "warrant/across.py", "    if set(q) - allowed or needed - set(q):\n", "    if needed - set(q):\n", AGENT, ["X21"]),
    ("X45", "warrant/across.py", "    if \"actor\" in q and not S.is_actor(q[\"actor\"]):\n", "    if False:\n", AGENT, ["X21"]),
    ("X46", "warrant/across.py", "    return sorted((i for i in ids if i in recs and schema in (None, recs[i][\"schema\"])), key=", "    return sorted((i for i in ids if i in recs), key=", AGENT, ["X22"]),
    ("X47", "warrant/across.py", "            if lin[\"leaf\"] not in (i, None):\n", "            if False:\n", AGENT, ["X08"]),
    ("X48", "warrant/shapes.py", 'CITATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,127}:[0-9a-f]{64}\\Z")', 'CITATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,127}:[0-9a-f]{64}$")', SHAPES_TEST, ["S8"]),
    ("A1", "warrant_agent/api.py", '    need(r["actor"] == actor, "NOT_PERMITTED"', '    need(True, "NOT_PERMITTED"', AGENT, ["A04"]),
    ("A2", "warrant_agent/api.py", 'expect_head=r["prev"] or ""', "expect_head=None", AGENT, ["A05"]),
    ("A3", "warrant_agent/api.py", '    need(not why, "INVALID_RECORD", "; ".join(why), problems=why)\n    return {"record"',
     '    return {"record"', AGENT, ["A06", "A07"]),
    ("A4", "warrant_agent/api.py", '    need(key.public in trust["keys"].get(actor, []), "SIGNER_NOT_TRUSTED",', '    need(True, "SIGNER_NOT_TRUSTED",', AGENT, ["A08"]),
    ("A5", "warrant_agent/config.py", '        need(size <= self.limits["store_bytes"], "RESOURCE_LIMIT",', '        need(True, "RESOURCE_LIMIT",', AGENT, ["A09"]),
    ("A6b", "warrant_agent/config.py", '            need("limits" not in doc, "UNSUPPORTED_VERSION",', '            need(True, "UNSUPPORTED_VERSION",', AGENT, ["A10b"]),
    ("A6c", "warrant_agent/config.py", '"operations": ops + ["graph"] * ("read" in ops)}', '"operations": ops + ["graph"]}', AGENT, ["A10c"]),
    ("A6", "warrant_agent/config.py", '        need(op in ALWAYS or op in self.operations, "NOT_PERMITTED"', '        need(True, "NOT_PERMITTED"', AGENT, ["A11"]),
    ("A7", "warrant_agent/init.py", '    _refuse(key.public in trust["keys"][actor], "INIT_KEY_NOT_PINNED",', '    _refuse(True, "INIT_KEY_NOT_PINNED",', AGENT, ["I02"]),
    ("A8", "warrant_agent/init.py", '    _refuse(not _inside(seed, repo), "INIT_INSIDE_REPOSITORY"', '    _refuse(True, "INIT_INSIDE_REPOSITORY"', AGENT, ["I03"]),
    ("A9", "warrant_agent/init.py", '    _refuse(not config.exists() or _own_output(config, repo, workspace), "INIT_NOT_INIT_OUTPUT",',
     '    _refuse(True, "INIT_NOT_INIT_OUTPUT",', AGENT, ["I05"]),
    ("A10", "warrant_agent/init.py", '        if os.path.islink(q) and _inside(Path(os.path.realpath(q.parent)), home):', "        if False:", AGENT, ["I07"]),
    ("A11", "warrant_agent/api.py", '        for x in [r] + (rep["lineages"][root]["versions"] if root else []):', "        for x in [r]:", AGENT, ["A13"]),
    ("A13", "warrant_agent/api.py", "    todo = sorted(keep)\n    while todo:\n        for rel, a in into.get(todo.pop(), []):",
     "    todo = []                # one pass over the records kept so far\n    for rel, a in [(r_, b) for x in sorted(keep) for r_, b in into.get(x, [])]:\n        if True:",
     AGENT, ["A17"]),
    ("A15", "warrant_agent/api.py", '    return out + (_schema_problems(view, r) if r["kind"] == "schema" else [])', "    return out", AGENT, ["A18"]),
    ("A16", "warrant_agent/api.py", '    out = [] if view.holds(r["actor"], "schema/author") else', "    out = [] if True else", AGENT, ["A18"]),
    ("A17", "warrant_agent/api.py", "        if b[\"name\"] in view.schemas:", "        if False:", AGENT, ["A18"]),
    ("A18", "warrant_agent/api.py", "    elif view.recs[root][\"actor\"] != r[\"actor\"]:", "    elif False:", AGENT, ["A18"]),
    ("A19", "warrant_agent/api.py", "    elif b[\"name\"] != p[\"body\"][\"name\"]:", "    elif False:", AGENT, ["A18"]),
    ("A24", "warrant_agent/api.py", '    elif view.schemas.get(p["body"]["name"], {}).get("id") != r["lineage"]:', "    elif False:", AGENT, ["A18"]),
    ("A20", "warrant_agent/api.py", "    out = [f\"{w}\" for h, w in sorted(after.snap.rejected.items()) if h not in snap.rejected]", "    out = []", AGENT, ["A20"]),
    ("A21", "warrant_agent/api.py", "    out += [f\"{c}: {d}\" for c, x, d in after.problems if [c, x, d] not in view.problems]", "    out += []", AGENT, ["A19", "A21"]),
    ("A22", "warrant_agent/api.py", ', (view.recs.get(lineage) or {}).get("at", 0))', ")", AGENT, ["A21"]),
    ("A25", "warrant_agent/api.py", '        return [f"the store with it would be refused: {e}"]', "        return []", AGENT, ["A23"]),
    ("A26", "warrant_agent/api.py", 'expect_head=r["prev"] or "", admit=admit)', 'expect_head=r["prev"] or "")', AGENT, ["A24"]),
    ("A27", "warrant_agent/api.py", "after = E.View(Snapshot(snap.raw + [line], snap.blobs)", "after = E.View(Snapshot(own_lines(snap) + [line], snap.blobs)",
     AGENT, ["A25"]),
    ("A23", E, "                    self.pending.append(i)          # waits",
     '                    self.problem("SCHEMA_NOT_COUNTED", i, "short of its quorum")\n                    self.pending.append(i)          # waits', AGENT, ["A22"]),
    ("A40", "warrant_agent/config.py", '                w["signer"] = {"actor": r["signer"], "key": home["identities"][r["signer"]]["seed"]}', "                pass",
     AGENT, ["A26"]),
    ("A41", "warrant_agent/config.py", "            return cls.from_home(H.load())", "            return cls({})", AGENT, ["A27"]),
    ("A42", "warrant_agent/config.py", '        doc = json.loads(read_inside(dot / "v3.json", dot))', '        doc = json.loads((dot / "v3.json").read_bytes())',
     AGENT, ["A28"]),
    ("A43", "warrant_agent/config.py", "            st = Store(dot_of(self.repo) if self.repo is not None else self.store)",
     "            st = Store(self.repo / STORE_DIR if self.repo is not None else self.store)", AGENT, ["A29"]),
    ("A44", "warrant_agent/config.py", "        dot = dot_of(repo)\n", "        dot = Path(repo) / STORE_DIR\n", AGENT, ["A29"]),
    # --repo DIR --actor A: init's configuration held in memory (warrant_agent/init.py configuration, load)
    ("A45", "warrant_agent/init.py", "    _, _, name, ws, _ = checked(repo, actor, seed, workspace, operations)\n",
     '    name, ws = Path(repo).name.lower(), {"repo": str(repo), "signer": {"actor": actor, "key": str(seed)}}\n', AGENT, ["I11"]),
    ("A46", "warrant_agent/init.py", "        if given:\n", "        if False:\n", AGENT, ["I13"]),
    ("A47", "warrant_agent/init.py", "    if a.config is not None:\n", "    if False:\n", AGENT, ["I13"]),
    ("A48", "warrant_agent/init.py", "    if a.actor is None:\n", "    if False:\n", AGENT, ["I13"]),
    ("A49", "warrant_agent/init.py", '            seed = H.load()["identities"].get(actor, {}).get("seed") if S.is_actor(actor) else None\n',
     "            seed = None\n", AGENT, ["I12"]),
    ("A50", "warrant_agent/cli.py", '        out = {"error": e.code, "message": e.message}\n', "        raise\n", AGENT, ["I13"]),
    ('P19', 'integrations/warrant-review/waker/waker.py', 'return next((r for r in self.reviewers if r["actor"] != author), None)', 'return self.reviewers[0]', WAKER, ['W15', 'W16']),
    ("P20", "integrations/warrant-review/waker/waker.py", "        if named:\n", "        if False:\n", WAKER, ["W17"]),
    ('P21', 'integrations/warrant-review/waker/waker.py', 'if rev["agent"] == "claude":', 'if False:', WAKER, ['W15']),
    ("P22", "integrations/warrant-review/waker/waker.py", "check=False, timeout=4 * 3600, cwd=str(path))", "check=False, timeout=4 * 3600)", WAKER, ["W15"]),
    ('P23', 'integrations/warrant-review/waker/waker.py', '    if len({r["actor"] for r in rs}) != len(rs):', '    if False:', WAKER, ['W18']),
    ('P24', 'integrations/warrant-review/waker/waker.py', 'and ACTOR_ID.match(r["actor"]) and r["agent"] in AGENTS', 'and ACTOR_ID.match(r["actor"])', WAKER, ['W18']),
    ('P25', 'integrations/warrant-review/waker/waker.py', 'and (r.get("seed") is None or (isinstance(r["seed"], str) and Path(r["seed"]).is_absolute()))', '', WAKER, ['W18']),
    ('P26', 'integrations/warrant-review/waker/waker.py', '        why = reviewers_problem(e.get("reviewers", list(DEFAULT_REVIEWERS)))', '        why = None', WAKER, ['W18']),
    ("P27", "integrations/warrant-review/waker/waker.py", "stdout=out if result else log,", "stdout=log,", WAKER, ["W15"]),
    ("P18", "integrations/warrant-review/skills/warrant-review/scripts/warrant-mcp-call", "    except Exception as e:", "    except ZeroDivisionError as e:",
     WAKER, ["C15"]),
    ("A12", "warrant_agent/config.py", '                   "operations": ops + ["graph"] * ("read" in ops)}',
     '                   "operations": ops + ["graph"] * ("read" in ops), "signer": None}', AGENT, ["A10"]),
    ("A91", "warrant_agent/api.py", 'refs += sorted(R.body_refs(s["fields"], body))', "pass", AGENT, ["R01"]),
    ("A92", "warrant_agent/api.py", 'guard = s["states"].get(body.get("state"))            # the schema\'s minimal guard for the state', "pass", AGENT, ["R01"]),
    ("T147", "warrant/graph.py", "                on_cycle.add(v)\n", "                pass\n", TOOLS, ["GR2"]),
    ("T148", "warrant/graph.py", 'return None if lin["reliance"] == "ELIGIBLE" else', 'return None if True else', TOOLS, ["GR1"]),
    ("T149", "warrant/graph.py", 'gs.append((lin["effective"] or b) if lin else b)', "gs.append(b)", TOOLS, ["GR1"]),
    ("T150", "warrant/graph.py", '        if lin["effective"] != v:\n            return "NOT_EFFECTIVE"', '        if False:\n            return "NOT_EFFECTIVE"', TOOLS, ["GR3"]),
    ("T151", "warrant/graph.py", 'if _cites(recs, m["id"], r, memo):\n            return False', 'if False:\n            return False', TOOLS, ["WL6"]),
    ("T152", "warrant/graph.py", 'return m["at"] <= recs[r]["at"]', 'return True', TOOLS, ["WL3"]),
    ("T153", "warrant/graph.py", 'if _cites(recs, r, m["id"], memo):', 'if False:', TOOLS, ["WL5"]),
    ("T154", "warrant/graph.py", '                    todo.append(z)', '                    pass', TOOLS, ["WL6"]),
    ("T155", "warrant/graph.py", 'and all(recs[i]["body"].get(k, _NOWHERE) == x for k, x in match.items())]', 'and recs[i]["body"].get("verdict") == "accept"]', TOOLS, ["WL7"]),
    # warrant.chains: a writer taking its own chain forks in
    ("T156", "warrant/chains.py", 'out["joined" if all(i in taken[a] for i in f[2]) else "open"]', 'out["joined" if any(i in taken[a] for i in f[2]) else "open"]', TOOLS, ["CJ1"]),
    ("T157", "warrant/chains.py", 'if r["kind"] == "attest" and r["body"].get("verdict") == JOINED and', 'if r["kind"] == "attest" and', TOOLS, ["CJ3"]),
    ("T158", "warrant/chains.py", '                todo.append(r["body"]["target"])', '                pass', TOOLS, ["CJ2"]),
    ("T159", "warrant/chains.py", '    return [i for _, i in tips(view, actor) if i not in t]', '    return [i for _, i in tips(view, actor)]', TOOLS, ["CJ2"]),
    ("T160", "warrant/cli.py", '"chain_forks_open": sorted({f[0] for f in forks["open"]})', '"chain_forks_open": sorted({f[0] for f in rep["chains"]["forks"]})', TOOLS, ["CJ2"]),
    ("T161", "warrant/chains.py", 'view.snap, view.trust, view.as_of, only=actor)', 'view.snap, view.trust, view.as_of, only=None)', TOOLS, ["CJ3"]),
    ("T162", "warrant/chains.py", '    recs, basis, _, _ = E._authentic(view.snap, view.trust, view.as_of, only=actor)', '    recs, basis = {i: r for i, r in view.recs.items() if r["actor"] == actor}, view.basis', TOOLS, ["CJ4"]),
    ("T163", "warrant/claims.py", "        paths |= {f} | {p for p in memo[f] if not p.endswith(\"/\")}", "        paths |= {f}", TOOLS, ["CF1"]),
    ("T164", "warrant/claims.py", "and any(c == CLOSURE and files == now[L] for _, files, c in done.get(leaf, [])))",
     "and any(c == CLOSURE for _, files, c in done.get(leaf, [])))", TOOLS, ["CF2"]),
    ("T165", "warrant/claims.py", "    todo = {L: b for L, b in live(rep).items() if L in now and not fresh(L)}",
     "    todo = {L: b for L, b in live(rep).items() if L in now}", TOOLS, ["CF2"]),
    ("T166", DR, "if rule == C.CLOSURE else", "if True else", TOOLS, ["CF3"]),
    ("T167", "warrant/claims.py", "\"files\": files, \"closure\": CLOSURE}", "\"files\": files}", TOOLS, ["CF1"]),
    ("G55", "warrant/imports.py", '                if (isinstance(a, ast.Constant) and a.value in ("-m", "-c")',
     '                if (isinstance(a, ast.Constant) and a.value in ("-c",)', GATE, ["E60"]),
    ("G56", "warrant/imports.py", "                    if main:", "                    if False:", GATE, ["E60"]),
    ("G57", "warrant/imports.py", "                imports(code, ())", "                pass", GATE, ["E60"]),
    ("G58", "warrant/imports.py", "            raise Unreadable(f\"{f}: {type(e).__name__}\") from None", "            continue", GATE, ["E60"]),
    ("T168", "warrant/cli.py", "        D.gate(rep, root)            # G14", "        pass            # G14", TOOLS, ["CF5"]),
    ("T169", "warrant/review.py", '("merge-on-acceptance: solo:", "solo"), ', '', TOOLS, ["MR1"]),
    ("T170", "warrant/review.py", '    return next((w for p, w in MERGE_HOW if p in message), "hand")', '    return "hand"', TOOLS, ["MR1"]),
    ("X52", "warrant/across.py", '    voices = {c for x in readings for c in x.rep["challenges"]} - counted', '    voices = set()', AGENT, ["X10"]),
    ("X53", "warrant/across.py", '            row["uncounted"] = True', '            pass', AGENT, ["X10"]),
    ("T171", "warrant/cli.py", '        if a.cmd == "init" and a.voices:', '        if False:', TOOLS, ["VS1"]),
    ("T172", "warrant/cli.py", '    name = re.sub(r"[^A-Za-z0-9_.-]", "-", Path(root).name)[:100].strip(".-") or "local"', '    name = Path(root).name', TOOLS, ["VS1"]),
    ("T173", "warrant/claims.py", '    by_commit = {x: kept for x, rows in by_commit.items() if (kept := [row for row in rows if row[0] not in done])}', '    by_commit = {x: rows for x, rows in by_commit.items()}', TOOLS, ["C20"]),
    ("T174", "warrant/claims.py", '    path = inside(a.done, root) if a.done else None', '    path = Path(a.done) if a.done else None', TOOLS, ["C20"]),
    ("T175", "warrant/claims.py", 'from . import pins as P\n', 'from . import gate as GT  # noqa: F401\nfrom . import pins as P\n', TOOLS, ["CF6"]),
    ("T176", "warrant/claims.py", '    if tracked:\n        raise Failed("PATH"', '    if False:\n        raise Failed("PATH"', TOOLS, ["C21"]),
    ("T177", "warrant/claims.py", 'return frozenset(r[0] for r in rows if len(r) == 2 and r[1] == code)', 'return frozenset(r[0] for r in rows if r)', TOOLS, ["C21"]),
    ("T178", "warrant/claims.py", '    code = checker_code(git(root, "rev-parse", "HEAD"), root) if path else None', '    code = identity(root)["code"] if path else None', TOOLS, ["C22"]),
    ("T183", "warrant/graph.py", '            if rel not in ("ref", "requires") or (rel == "ref" and b == answers):', '            if rel not in ("ref", "requires"):', TOOLS, ["GR4"]),
    ("T179", "warrant/resolve.py", '                if _sha(data) != i:\n                    raise Mismatch', '                if False:\n                    raise Mismatch', TOOLS, ["RV2"]),
    ("T180", "warrant/resolve.py", '        got = p.in_git(i)\n        if got:\n            return got', '        got = None\n        if got:\n            return got', TOOLS, ["RV1"]),
    ("T181", "warrant/resolve.py", '        got = p.bytes_of(i)\n        if got:\n            return "RESOLVED", got[1]', '        got = None\n        if got:\n            return "RESOLVED", got[1]', TOOLS, ["RV1"]),
    ("T182", "warrant/resolve.py", '    if home is not None and home.holds(i):', '    if False:', TOOLS, ["RV1"]),
    # the bridge (warrant/bridge.py): an issue through the form becomes one record in the bridge's own store, and nothing else does
    ("T221", "warrant/bridge.py", ' and event.get("action") == "opened"):', '):', TOOLS, ["BR3"]),
    ("T222", "warrant/bridge.py", ' or "pull_request" in issue:', ':', TOOLS, ["BR3"]),
    ("T223", "warrant/bridge.py", '(objection|support)\\n\\n### Statement', '(objection|support|accept)\\n\\n### Statement', TOOLS, ["BR3"]),
    ("T224", "warrant/bridge.py", ' or statement == NO_RESPONSE:', ':', TOOLS, ["BR3"]),
    ("T225", "warrant/bridge.py", 'if not 0 < len(statement) <= STATEMENT_MAX', 'if not 0 < len(statement)', TOOLS, ["BR3"]),
    ("T226", "warrant/bridge.py", 'LOGIN.fullmatch(user["login"])', 'LOGIN.match(user["login"])', TOOLS, ["BR3"]),
    ("T227", "warrant/bridge.py", ' and _positive(user.get("id")) and', ' and', TOOLS, ["BR3"]),
    ("T228", "warrant/bridge.py", ' and user.get("type") in ACCOUNTS):', '):', TOOLS, ["BR3"]),
    ("T229", "warrant/bridge.py", '"url": f"https://github.com/{full}/issues/{issue[\'number\']}"', '"url": issue.get("html_url")', TOOLS, ["BR1"]),
    ("T230", "warrant/bridge.py", ' and doc["profile"].get("roles") == {}):', '):', TOOLS, ["BR4"]),
    ("T231", "warrant/bridge.py", 'set(keys) == {ACTOR} and', 'ACTOR in keys and', TOOLS, ["BR4"]),
    ("T232", "warrant/bridge.py", '    if had is not None:\n        return dict(out, filed=had, already=True)\n', '', TOOLS, ["BR2"]),
    ("T233", "warrant/bridge.py", 'REPOSITORY.fullmatch(full)', 'REPOSITORY.match(full)', TOOLS, ["BR3"]),
    ("T234", "warrant/bridge.py", 'at = max(int(time.time()), head(Store(dot).snapshot(), doc["trust"], ACTOR)["at"] or 0)', 'at = int(time.time())', TOOLS, ["BR5"]),
    ("T235", "warrant/bridge.py", '"body_sha256": hashlib.sha256(raw.encode()).hexdigest()', '"body_sha256": hashlib.sha256(raw.replace("\\r\\n", "\\n").encode()).hexdigest()', TOOLS, ["BR1"]),
    ("T236", "warrant/bridge.py", 'STANCES = {"objection": "challenge", "support": "attest"}', 'STANCES = {"objection": "challenge", "support": "challenge"}', TOOLS, ["BR1"]),
    ("T237", ".github/ISSUE_TEMPLATE/voice.yml", '      label: Stance\n', '      label: Position\n', TOOLS, ["BR6"]),
    ("T238", ".github/ISSUE_TEMPLATE/voice.yml", '        - support\n', '        - support\n        - accept\n', TOOLS, ["BR6"]),
    # stage 3: witnessed roots (warrant.merkle, warrant.snapshot, verify --witness)
    ("WM1", "warrant/merkle.py", '        if fn & 1 or fn == sn:\n', '        if fn & 1:\n', VERIFY, ["WT1"]),
    ("WM3", "warrant/merkle.py", '    return _h(b"\\x00" + data)\n', '    return _h(data)\n', VERIFY, ["WT1"]),
    ("WM4", "warrant/merkle.py", '        adjacent = ((b is None and a is not None and a["i"] == 0) or (a is None and b is not None and b["i"] == n - 1)\n                    or (b is not None and a is not None and a["i"] == b["i"] + 1))\n', '        adjacent = True\n', VERIFY, ["WT2"]),
    ("WM5", "warrant/merkle.py", '            if not ok or kb is None or not kb < key:\n', '            if not ok or kb is None:\n', VERIFY, ["WT2"]),
    ("WM6", "warrant/merkle.py", '        if r.get("kind") in SAID and S.hex64(t):\n', '        if r.get("kind") == "attest" and S.hex64(t):\n', VERIFY, ["WT2", "WT4"]),
    ("WM7", "warrant/snapshot.py", '        bad = holds(old, now)\n        if bad:\n            raise Failed(*bad[0])\n', '', VERIFY, ["WT3"]),
    ("WM9", "warrant/verify.py", '    if actor not in (profile.get("roles", {}).get(WITNESS_ROLE) or []):\n', '    if False:\n', VERIFY, ["WT4"]),
    ("WM10", "warrant/verify.py", '        if extends not in chain:\n', '        if False:\n', VERIFY, ["WT5"]),
    ("WM11", "warrant/verify.py", '    if (ans.get("absence") or {}).get("equivocation"):\n        return 4\n', '', VERIFY, ["WT5"]),
    ("WM12", "warrant/verify.py", '        ans["rely"] = ans["rely"] and ans["absence"]["holds"]\n', '', VERIFY, ["WT4"]),
    ("WM13", "warrant/verify.py", '        proof = M.unpack(doc["said"], i, b["index"], size) if type(size) is int else None\n', '        proof = M.unpack(doc["said"], i, b["index"], size + 1) if type(size) is int else None\n', VERIFY, ["WT4"]),
    ("WM14", "warrant/merkle.py", '            if not (isinstance(said, list) and hashlib.sha256(C.canon(said)).digest() == data[32:]\n', '            if not (isinstance(said, list)\n', VERIFY, ["WT2"]),
    ("WM15", "warrant/merkle.py", '        adjacent = ((b is None and a is not None and a["i"] == 0) or (a is None', '        adjacent = ((b is None and a is not None) or (a is None', VERIFY, ["WT2"]),
    ("WM16", "warrant/merkle.py", 'or (a is None and b is not None and b["i"] == n - 1)\n', 'or (a is None and b is not None)\n', VERIFY, ["WT2"]),
    ("WM17", "warrant/verify.py", '        out["missing"] += [x for _, x in said if x not in admitted and not own_key(x)]\n', '        out["missing"] += [x for _, x in said if x not in snap.lines]\n', VERIFY, ["WT7"]),
    ("WM18", "warrant/verify.py", '        return bool(envs) and envs[0]["record"]["actor"] not in trust.get("keys", {}) and not R.named_key(envs[0]["record"])\n', '        return bool(envs)\n', VERIFY, ["WT7"]),
    ("WM19", "warrant/snapshot.py", '    lines = lambda snap: {C.canon(e) for envs in snap.lines.values() for e in envs}\n', '    lines = lambda snap: {C.canon({"record": e["record"], "sig": None}) for envs in snap.lines.values() for e in envs}\n', VERIFY, ["WT3"]),
    ("WM20", "warrant/merkle.py", '                or (size is not None and n != size)):\n', '                or False):\n', VERIFY, ["WT2"]),
    ("WM21", "warrant/merkle.py", '    if not (type(size) is int and type(i) is int and 0 <= i < size', '    if not (isinstance(size, int) and isinstance(i, int) and 0 <= i < size', VERIFY, ["WT1"]),
    ("WM22", "warrant/snapshot.py", '    bad = [(k, f"{k} {b.get(k)} where the store at {b[\'commit\'][:12]} gives {r[k]}") for k in ("records", "index") if b.get(k) != r[k]]\n', '    bad = []\n', VERIFY, ["WT9"]),
    # the harness itself (tests/mutants.py, tests/world.py): what every KILLED above rests on
    ("T199", "tests/mutants.py", '    if not cases or not all(homes):\n        return None', '    if not cases or not all(homes):\n        return ["main"]', TOOLS, ["HM2"]),
    ("T200", "tests/world.py", '            sys.stdout.flush()\n            os._exit(1)\n', '            pass\n', TOOLS, ["HM3"]),
    ("T201", "tests/world.py", '    if unknown:\n        print(f"NO_SUCH_SECTION {unknown}", flush=True)\n        return 2\n', '', TOOLS, ["HM3"]),
    ("T202", "tests/mutants.py", 'add("main" if not sec or where == "main" else where)\n', 'add("main")\n', TOOLS, ["HM1"]),
    ("T203", "tests/mutants.py", '        refused += combinations(rows, ids, where, places)\n', '', TOOLS, ["HM4"]),
    ("T204", "tests/mutants.py", '\n            if rc != 0:                      # red, or past the timeout', '\n            if rc:                      # red, or past the timeout', TOOLS, ["HM1", "HM5"]),
    ("T205", "tests/mutants.py", 'if s and len(s) > 1})\n', 'if s and len(s) > 2})\n', TOOLS, ["HM4"]),
    ("T250", "warrant/graph.py", '        if v is None or v in acted or nodes[v]["actor"] == actor:\n', '        if v is None or nodes[v]["actor"] == actor:\n', TOOLS, ["FA3"]),
    ("T251", "warrant/graph.py", '        if v is None or v in acted or nodes[v]["actor"] == actor:\n', '        if v is None or v in acted:\n', TOOLS, ["FA2"]),
    ("T252", "warrant/gate.py", '        elif isinstance(o, dict) and isinstance(o.get("for"), str) and o["for"] == actor:\n', '        elif False:\n', TOOLS, ["FA1"]),
    ("T253", "warrant/gate.py", '        if v in acted or _recs(rep)[v]["actor"] == actor:\n            continue\n', '', TOOLS, ["FA2"]),
    ("T254", "warrant_agent/api.py", 'G.frontier(rep, profile, actor, view.recs), {"op": op', 'G.frontier(rep, profile, actor), {"op": op', TOOLS, ["FA1"]),
    # the bridge's workflow step, run as written (BR7): a refused push is tried again from the branch as it is
    ("T239", ".github/workflows/voice-bridge.yml", '          tries=8\n', '          tries=1\n', TOOLS, ["BR7"]),
    ("T240", ".github/workflows/voice-bridge.yml", '            if git -C "$dir" diff --cached --quiet; then break; fi   # this issue was filed by an earlier run\n', '', TOOLS, ["BR7"]),
    ("T241", ".github/workflows/voice-bridge.yml", '            dir="voices-$try"\n', '            dir="voices"\n', TOOLS, ["BR7"]),
    ("T184", "warrant/drift.py", 'if r["kind"] != "attest" or rep["_basis"].get(i) != "SIGNED" or b.get("verdict") != "accept":', 'if r["kind"] != "attest" or b.get("verdict") != "accept":', TOOLS, ["DR31"]),
    ("T185", "warrant/drift.py", '        elif isinstance(b.get("files"), dict) and counted(rep, r):', '        elif False:', TOOLS, ["DR30"]),
    ("T186", "warrant/cli.py", '    if a.as_of is None and Path(store).name == ".warrant":\n        from . import drift as D\n        view = E.View(', '    if False:\n        from . import drift as D\n        view = E.View(', TOOLS, ["DR30"]),
    ("T187", "warrant/cli.py", '    if a.as_of is None and Path(store).name == ".warrant":\n        from . import drift as D\n        rep["_recs"]', '    if a.as_of is None and Path(store).name == ".warrant" and (root / ".warrant" / "claims.json").is_file():\n        from . import drift as D\n        rep["_recs"]', TOOLS, ["DR30"]),
    ("T188", "warrant/drift.py", '        if not done.get(eff) or (lin["schema"] == C.CLAIM and L not in live):', '        if not done.get(eff) or L not in live:', TOOLS, ["DR30"]),
    ("T194", "warrant/drift.py", '        elif isinstance(b.get("files"), dict) and counted(rep, r):', '        elif isinstance(b.get("files"), dict):', TOOLS, ["DR32"]),
    ("T195", "warrant/drift.py", 'and r["actor"] in v.get("accepted_by", [])\n', 'and True\n', TOOLS, ["DR32"]),
    ("T189", "warrant/entry.py", '        elif found.group(0) != marked().rstrip("\\n"):', '        elif False:', TOOLS, ["IN2"]),
    ("T190", "warrant/entry.py", '    if "warrant" not in doc.get("mcpServers", {}):', '    if True:', TOOLS, ["IN3"]),
    ("T191", "warrant/entry.py", '    if f.exists() or f.is_symlink():\n        return []\n', '', TOOLS, ["IN1"]),
    ("T192", "warrant/entry.py", '        if not any(line.strip() == IMPORT for line in text.splitlines()):', '        if True:', TOOLS, ["IN1"]),
    ("T193", "warrant/cli.py", '            if Path(store).name == ".warrant":                             # a repository', '            if True:                             # a repository', TOOLS, ["IN3"]),
    ("T196", "warrant/cli.py", '([] if a.no_mcp else EN.mcp(root))', '(EN.mcp(root) if a.no_mcp else [])', TOOLS, ["IN1", "IN3"]),
    ("T197", "warrant/cli.py", '                         if any(st["roles"].values()) else', '                         if True else', TOOLS, ["IN1"]),
    ("V106", E, ', "unicode": unicodedata.unidata_version}))', '}))', CORE, ["UC1"]),
    ("T137", "warrant/graph.py", 'if any(on == x["target"] and v == "reproduces" for on, v, _ in x["replays"]):',
     'if any(v == "reproduces" for on, v, _ in x["replays"]):', TOOLS, ["WL1"]),
    ("A95", "tests/assess_bound.py", "if self.bytes + len(line) > self.limit:", "if self.bytes > self.limit:", AGENT, ["B01"]),
    ("A96", "tests/assess_bound.py", "snap = ws.open().snapshot()", "snap = ST.Store(ws.store).snapshot()", AGENT, ["B02"]),
    ("A97", "warrant_agent/api.py", 'data, query = G.ledger(rep, view.recs), {"op": op}', 'data, query = G.ledger(rep, {}), {"op": op}', AGENT, ["A30"]),
    ("A98", "warrant_agent/api.py", 'if op in ("around", "path", "why", "grounded"):', 'if op in ("around", "path", "why"):', AGENT, ["A30"]),
    ("A99", "warrant_agent/serve.py", 'E = html.escape\n', 'E = lambda s, quote=True: s\n', AGENT, ["SV2"]),
    ("A100", "warrant_agent/serve.py", 'if not secrets.compare_digest(form.get("token", ""), self.token):', 'if False:', AGENT, ["SV4"]),
    ("A101", "warrant_agent/serve.py", 'if self.headers.get("Host") not in hosts:', 'if False:', AGENT, ["SV5"]),
    ('A102', 'warrant_agent/observe.py', '        if not lo <= n <= hi:\n', '        if False:\n', AGENT, ['SV4']),
    ('A103', 'warrant_agent/observe.py', 'return (None, why) if extra is None else ({"target": target, "verdict": kind, **extra}, None)', 'return (None, why) if extra is None else ({"target": target, "verdict": "accept", **extra}, None)', AGENT, ['SV4']),
    ("A104", "warrant_agent/serve.py", 'out.sort(key=lambda x: (-x["at"], x["id"]))', 'out.sort(key=lambda x: (x["at"], x["id"]))', AGENT, ["SV1"]),
    ("A105", "warrant_agent/lens.py", 'r["kind"] == "attest" and r["actor"] == reader and b.get("verdict") == "adopt"', 'r["kind"] == "attest" and b.get("verdict") == "adopt"', AGENT, ["LN2"]),
    ("A106", "warrant_agent/serve.py", """+ (f'<ul class="standing">{rows}</ul>' if held else "")""", '+ ""', AGENT, ["LN4"]),
    ("A107", "warrant_agent/serve.py", 'why = LZ.problem(found[1])', 'why = None', AGENT, ["LN3"]),
    ("A108", "warrant_agent/lens.py", ' or set(card) - CARD_KEYS or ', ' or ', AGENT, ["LN3"]),
    ('A109', 'warrant_agent/lens.py', '                key = (r["at"], depth[i], i)', '                key = (r["at"], -depth[i], i)', AGENT, ['LN1']),
    ("A110", "warrant_agent/serve.py", '    if card["activity"] == "shown":\n        parts += [on_html(rep, x) for x in v["on"]]', '    if True:\n        parts += [on_html(rep, x) for x in v["on"]]', AGENT, ["LN4"]),
    ('A111', 'warrant_agent/observe.py', 'if r["kind"] != "entity" or r.get("schema") != LZ.LENS:', 'if False:', AGENT, ['LN3']),
    ("A112", "warrant_agent/serve.py", 'return [title(r, c, LZ.MAX_NAME * 8) for c, x in sorted(r["challenges"].items()) if x["target"] == lens_id]', 'return []', AGENT, ["LN7"]),
    ("A113", "warrant_agent/lens.py", 'body.get("applies") in (schema, "*")', 'body.get("applies") == schema', AGENT, ["LN8"]),
    ("A114", "warrant_agent/lens.py", '            out |= {(x["id"], "") for x in v["on"]}', '            pass', AGENT, ["LN9"]),
    ('A115', 'warrant_agent/lens.py', 'return found["vanished"], found["appeared"]', 'return found["appeared"], found["vanished"]', AGENT, ['LN9']),
    ("A116", "warrant_agent/serve.py", 'self.send(code, page("Не підписано", f\'<h2>Не підписано</h2><p>{E(out)}</p><p><a href="{E(back)}">назад</a></p>\'))', 'self.send(code, out, TEXT)', AGENT, ["SV5"]),
    ('A117', 'warrant_agent/view.py', 'moved = {"new": (None, True)} if fa is None else {k: (fa[k], fb[k]) for k in fb if fa[k] != fb[k]}', 'moved = {"new": (None, True)} if fa is None else {}', AGENT, ['CH3']),
    ('A118', 'warrant_agent/view.py', '        accounted |= touched[L] | {i for i, _ in diff["appeared"]}\n', '        pass\n', AGENT, ['CH2']),
    ("A119", "warrant_agent/serve.py", '        ok = secrets.compare_digest(form.get("token", ""), self.token)\n        if not ok:', '        if False:', AGENT, ["CH1"]),
    ("A120", "warrant_agent/changes.py", 'lines = [raw for raw in snap.raw if _rid(raw) in keep]', 'lines = list(snap.raw)', AGENT, ["CH3"]),
    ("A121", "warrant_agent/serve.py", 'Repo(self.space.roots[into or store]).file(', 'Repo(self.space.roots[store]).file(', AGENT, ["SV7"]),
    ("A122", "warrant_agent/serve.py", 'v["on"] = sorted(v["on"] + elsewhere.get(v["id"], []), key=lambda x: (x["at"], x["id"]))', 'pass', AGENT, ["SV7"]),
    ("A123", "warrant_agent/serve.py", '"lens": lens_id, "with": self.other_roots(store)}', '"lens": lens_id}', AGENT, ["CH4"]),
    ("A124", "warrant_agent/serve.py", 'if self.mine is not None and self.mine not in self.space.roots:', 'if False:', AGENT, ["CH6"]),
    ("A125", "warrant_agent/serve.py", 'foreign_b=lambda d, n=n: reactions_elsewhere(now, n, d), touched_from_elsewhere=pointing)', 'foreign_b=lambda d, n=n: reactions_elsewhere(now, n, d))', AGENT, ["CH5"]),
    ("A126", "warrant_agent/serve.py", 'foreign_b=lambda d, n=n: reactions_elsewhere(now, n, d),', 'foreign_b=None,', AGENT, ["CH5"]),
    ("A127", "warrant_agent/lens.py", '            if fa[p][k] != fb[p][k]:', '            if False:', AGENT, ["CH7"]),
    ("A128", "warrant_agent/scene.py", '            pos[n["id"]][2] = max(pos[n["id"]][2], pos[n["target"]][2])', '            pass', AGENT, ["SC2"]),
    ("A129", "warrant_agent/scene.py", 'glyph = GLYPH.get(n["kind"], "·")', 'glyph = ""', AGENT, ["SC3"]),
    ("A130", "warrant_agent/scene.py", """(f' · <b data-folded="{folded}">згорнуто {folded} вузлів</b> (бюджет {MAX_NODES})' if folded else "")""", '""', AGENT, ["SC6"]),
    ("A131", "warrant_agent/lens.py", '        if why:\n            return f"scene: {why}"', '        if False:\n            return f"scene: {why}"', AGENT, ["SC4"]),
    ("A132", "warrant_agent/scene.py", '<title>{E(describe(n["id"]))}</title>', '<title>{describe(n["id"])}</title>', AGENT, ["SC7"]),
    ("A133", "warrant_agent/scene.py", 'x = rank[n["id"]] if b["x"] == "time" else i', 'x = i', AGENT, ["SC5"]),
    ("A134", "warrant_agent/serve.py", "    if spoke:\n        who = f'висловились:", "    if True:\n        who = f'висловились:", AGENT, ["SV8"]),
    ('A135', 'warrant_agent/serve.py', '    stores = sorted({store} | {x["store"] for x in items.values() if x.get("store")})', '    stores = [store]', AGENT, ['SV8']),
    ('A136', 'warrant_agent/serve.py', '    saw = sorted({x["sentence"][0] for x in others if _is_view(rep, x)})', '    saw = []', AGENT, ['SV9']),
    ('A137', 'warrant_agent/serve.py', '    spoke = sorted({x["sentence"][0] for x in others if not _is_view(rep, x)})', '    spoke = sorted({x["sentence"][0] for x in others})', AGENT, ['SV9']),
    ('A138', 'warrant_agent/observe.py', '    if lens_id != "builtin" and not S.hex64(lens_id):', '    if False:', AGENT, ['SV9']),
    ("A139", "warrant_agent/serve.py", '    return (max(seen), len(order)) if seen else None', '    return (min(seen), len(order)) if seen else None', AGENT, ["SV9"]),
    ("A140", "warrant_agent/fragile.py", '    return ch["reproduced"] or (ch["counted"] and ch["stands"])', '    return True', AGENT, ["FR2"]),
    ("A141", "warrant_agent/fragile.py", 'any(on == c["target"] and verdict == "reproduces" for on, verdict, _ in c["replays"])', 'any(verdict == "reproduces" for on, verdict, _ in c["replays"])', AGENT, ["FR2"]),
    ("A142", "warrant_agent/fragile.py", '            if a in authors or x["challenge"] is not None:', '            if a in authors:', AGENT, ["FR1"]),
    ("A143", "warrant_agent/fragile.py", 'out.sort(key=lambda r: (-len(r["attention"]["all"]),', 'out.sort(key=lambda r: (len(r["attention"]["all"]),', AGENT, ["FR1"]),
    ('A144', 'warrant_agent/view.py', '    keep = set(snap.lines) - set(drop)\n', '    keep = set(snap.lines)\n', AGENT, ['WI1']),
    ('A145', 'warrant_agent/view.py', '    return C.doc_id(json.loads(json.dumps(core)))', '    return "0" * 64', AGENT, ['WI2']),
    ('A146', 'warrant_agent/view.py', 'standing = [s for s in serve.standing(rep, d) if keep is None or s[0] in kept]', 'standing = serve.standing(rep, d)', AGENT, ['WI3']),
    ('A147', 'warrant_agent/view.py', '        return {i for i, r in rep["_recs"].items() if r["kind"] == "challenge"}', '        return {i for i, r in rep["_recs"].items() if r["kind"] == "attest"}', AGENT, ['WI1']),
    ('A148', 'warrant_agent/observe.py', '"adopt": Kind("прийняв для себе лінзу", "mine", _adopt)', '"adopt": Kind("прийняв для себе лінзу", "record", _adopt)', AGENT, ['LN10']),
    ('A149', 'warrant_agent/serve.py', 'ADAPTER_FILES = sorted(Path(__file__).parent.glob("*.py"))', 'ADAPTER_FILES = [Path(__file__)]', AGENT, ['AU1']),
    ('A150', 'warrant_agent/serve.py', '        return {n: [r["snapshot"], r["trust"], r["profile"]] for n, r in sorted(self.reports().items())', '        return {n: [r["snapshot"]] for n, r in sorted(self.reports().items())', AGENT, ['AU1']),
    ('A151', 'warrant_agent/serve.py', '            + (f\' · <b class="PENDING">лінза не показує тут {hidden}</b> з того, що показала б вбудована\' if hidden else "")', '            + ""', AGENT, ['AU2']),
    ('A152', 'warrant_agent/serve.py', '        return [(n, r["_error"]) for n, r in sorted(self.reports().items()) if "_error" in r]', '        return []', AGENT, ['AU2']),
    ('A153', 'warrant_agent/serve.py', '        moved = [(sc, a, b) for sc, a, b in moved if (a and a[1]) != (b and b[1])]', '        moved = []', AGENT, ['AU3']),
    ('A154', 'warrant_agent/serve.py', "script-src 'none'; form-action", "script-src 'unsafe-inline'; form-action", AGENT, ['SV5']),
    ('A155', 'warrant_agent/overlay.py', '        elif len(distinct) == 1:\n', '        elif True:\n', AGENT, ['OV3']),
    ('A156', 'warrant_agent/overlay.py', '        if actor in keys:\n            continue\n', '        pass\n', AGENT, ['OV3']),
    ('A157', 'warrant_agent/overlay.py', '    lines = sorted({raw for s in snaps.values() for raw in s.raw})', '    lines = sorted(next(iter(snaps.values())).raw)', AGENT, ['OV1']),
    ('A158', 'warrant_agent/overlay.py', '"trust": C.doc_id(trust), "profile": C.doc_id(profile), "code": code})', '"trust": C.doc_id(trust), "code": code})', AGENT, ['OV2']),
    ('A159', 'warrant_agent/serve.py', '        trust, profile, _ = Repo(self.space.roots[self.mine]).config()', '        trust, profile, _ = Repo(self.space.roots[store]).config()', AGENT, ['OV4']),
    ('A160', 'warrant_agent/serve.py', ' if x["lineage"] in base["lineages"]]', ']', AGENT, ['OV5']),
    ('A161', 'warrant_agent/serve.py', '        unnamed = [r for r in asked if not p["roles"].get(r)]', '        unnamed = []', AGENT, ['OV5']),
    ('A162', 'warrant/commons.py', '    if not (isinstance(target, str) and S.hex64(target)):', '    if False:', AGENT, ['CM5']),
    ('A163', 'warrant/commons.py', '    if not 0 < len(statement) <= STATEMENT_MAX:', '    if False:', AGENT, ['CM5']),
    ('A164', 'warrant/commons.py', 'os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)', 'os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)', AGENT, ['CM1']),
    ('A165', 'warrant_agent/observe.py', '    if x["kind"] == "challenge":\n        # a voice', '    if False:\n        # a voice', AGENT, ['CM2']),
    ('A166', 'warrant_agent/serve.py', '    if c.get("outside"):\n        return " · голос ззовні', '    if False:\n        return " · голос ззовні', AGENT, ['CM2']),
    ('A167', 'warrant/commons.py', '        if not is_commons(doc):', '        if False:', AGENT, ['CM6']),
    ('A168', 'warrant/commons.py', '    if store is not None and p.resolve().is_relative_to(Path(store).resolve()):', '    if False:', AGENT, ['CM6']),
    ('A169', 'warrant_agent/serve.py', '    outside = g.get("outside") or []', '    outside = []', AGENT, ['TL1']),
    ('A170', 'warrant_agent/serve.py', '        same = past["snapshot"] == r["body"].get("root")', '        same = True', AGENT, ['TL2']),
    ('A171', 'warrant_agent/serve.py', 'CH.subset(snap, CH.before(snap, r["at"] + 1))', 'CH.subset(snap, CH.before(snap, 10 ** 12))', AGENT, ['TL2']),
    ('A172', 'warrant_agent/serve.py', '            q = dict(q, lens=then[1])', '            q = dict(q)', AGENT, ['TL2']),
    ('A173', 'warrant/commons.py', '    if not (isinstance(name, str) and NAME.match(name)):', '    if False:', AGENT, ['CM6']),
    ('A180', 'warrant_agent/voices.py', '                parent[find(i)] = find(seen[k])', '                pass', AGENT, ['VO1', 'VO4']),
    ('A181', 'warrant_agent/serve.py', 'if min(g["members"]) >= authored and g["keys"] for n', 'if min(g["members"]) >= authored for n', AGENT, ['VO3']),
    ('A182', 'warrant_agent/serve.py', '        return VC.keys_of(trust, actor) if basis.get(i) == "SIGNED" else set()', '        return VC.keys_of(trust, actor)', AGENT, ['VO3']),
    ('A183', 'warrant_agent/voices.py', '            for n, v in sorted(by_name.items()) if len(v) > 1]', '            for n, v in sorted(by_name.items()) if len(v) > 9]', AGENT, ['VO2']),
    ('A184', 'warrant_agent/serve.py', '    elif len(independent) < len(spoke):', '    elif False:', AGENT, ['VO2']),
    ('A185', 'warrant_agent/voices.py', '            for g in gs if not g["keys"]]', '            for g in gs if False]', AGENT, ['VO3']),
    ('A186', 'warrant_agent/contract.py', '    if len(missing) != folded:', '    if len(missing) > folded + 9:', AGENT, ['MC2']),
    ('A187', 'warrant_agent/contract.py', '        folded = max([int(n) for n in _FOLDED.findall(one)] or [0])', '        folded = 0', AGENT, ['MC1']),
    ('A188', 'warrant_agent/contract.py', '    out = [("record", f"{n} {i}") for n, i in sorted(want - got)]', '    out = []', AGENT, ['FC2']),
    ('A189', 'warrant_agent/contract.py', 'if said.get(k, 0) != omit.get(k, 0)]', 'if False]', AGENT, ['FC2']),
    ('A190', 'warrant_agent/contract.py', '            unread.add(n)\n', '', AGENT, ['FC1']),
    ('A191', 'warrant_agent/contract.py', '    out += [("unread", n) for n in sorted(unread - {html.unescape(x) for x in _UNREAD.findall(page)})]', '    out += []', AGENT, ['FC2']),
    ('A192', 'warrant_agent/contract.py', '    if not machines and is_machine(r["actor"]):\n        return "machines"', '    if False:\n        return "machines"', AGENT, ['FC1']),
    ('A193', 'warrant_agent/serve.py', '            omitted["limit"] = len(rows) - self.FEED_LIMIT', '            omitted["limit"] = len(rows)', AGENT, ['FC1']),
    ('A194', 'warrant_agent/serve.py', '                unread.append((n, rep["_error"]))\n', '', AGENT, ['FC1']),
    ('A195', 'warrant_agent/serve.py', '            omitted[why] = omitted.get(why, 0) + 1', '            pass', AGENT, ['FC1']),
    ('A196', 'warrant_agent/scene.py', '" data-n="{E(n["id"])}"><g>', '"><g>', AGENT, ['MC1']),
    ('A197', 'warrant_agent/serve.py', '        h = h.replace(CONTRACT, contract_html(broken, "карта не тримає контракт"), 1)', '        h = h.replace(CONTRACT, "", 1)', AGENT, ['MC2']),
    ('A198', 'warrant_agent/contract.py', 'for k in sorted(set(omit) | set(said)) if', 'for k in sorted(set(omit)) if', AGENT, ['FC3']),
    ('A199', 'warrant_agent/contract.py', '        one = drawn_maps[j] if j < len(drawn_maps) else ""', '        one = page', AGENT, ['MC3']),
    ('A200', 'warrant_agent/serve.py', 'h, 2 if two else 1)', 'h, 1)', AGENT, ['MC3']),
    ('A201', 'warrant_agent/overlay.py', '        if actor in holders:', '        if False:', AGENT, ['OV6']),
    ('A202', 'warrant_agent/overlay.py', '    holders = {a for actors in reader_profile["roles"].values() for a in actors}', '    holders = set()', AGENT, ['OV6']),
    ('A174', 'warrant_agent/contract.py', '        out += [(part, x) for x in sorted(w - g)]', '        out += []', AGENT, ['KC2']),
    ('A175', 'warrant_agent/serve.py', 'len(d["versions"]) > 1 and heads_statement(rep, d)', 'len(d["versions"]) > 1', AGENT, ['KC1']),
    ('A176', 'warrant_agent/serve.py', "            parts.append(f'<div data-f=\"{E(rid)} {E(k)}\">{drawn}</div>')", '            parts.append(drawn)', AGENT, ['KC1']),
    ('A177', 'warrant_agent/serve.py', '    if not broken:\n        return ""\n    names =', '    if True:\n        return ""\n    names =', AGENT, ['KC2']),
    ('A178', 'warrant_agent/serve.py', '    if isinstance(v, list):\n        return head + _ul(', '    if isinstance(v, list) and form != "list":\n        return None\n    if isinstance(v, list):\n        return head + _ul(', AGENT, ['KC1']),
    ('A179', 'warrant_agent/contract.py', '    if (a.store or not a.feed) and a.store not in space.roots:', '    if False:', AGENT, ['KC3']),
    ("A93", "warrant/roadmap.py", '"evidence": sorted(a.evidence), "refs": a.ref,', '"evidence": sorted(a.evidence), "refs": [],', AGENT, ["R01"]),
    ("A94", "warrant/roadmap.py", 'lineage=rep["lineages"][L]["leaf"], refs=[*a.evidence, *a.requires] + ([body["answers"]] if body["answers"] else [])', 'lineage=rep["lineages"][L]["leaf"], refs=[*a.evidence, *a.requires]', AGENT, ["R01"]),
    # the merge gate (warrant/gate.py)
    ("G1", "warrant/gate.py", "    if b.gate[\"hold_label\"] in pr[\"labels\"]:", "    if False:", GATE, ["E02"]),
    ("G2", "warrant/gate.py", "        if before - after:\n", "        if False:\n", GATE, ["E06"]),
    ("G23", "warrant/gate.py", "    extra, lines, blobs = tail(root, caught_up(root, x, head, b.commit), head)",
     "    extra, lines, blobs = tail(root, x, head)", GATE, ["E29"]),
    ("G24", "warrant/gate.py", "    except (subprocess.CalledProcessError, IndexError):\n        return x\n\n\ndef owner_paths",
     "    except IndexError:\n        return x\n\n\ndef owner_paths", GATE, ["E31"]),
    ("G25", ".warrant/merge.json", '      "warrant/keys.py",\n', "", GATE, ["E32"]),
    ("G26", ".warrant/merge.json", '      "warrant/__init__.py",\n', "", GATE, ["E32"]),
    # R-GATE-CLOSURE: what the interpreter could load in a listed module's place (gate.loadable)
    ("G27", "warrant/gate.py", 'if first == "__pycache__" or first in names or (not deeper', 'if first == "__pycache__" or (not deeper', GATE, ["E36"]),
    ("G28", "warrant/gate.py", 'or (not deeper and any(_module_file(first, n) for n in names)):', 'or False:', GATE, ["E37"]),
    ("G29", "warrant/gate.py", 'if first == "__pycache__" or first in names or (not deeper', 'if first in names or (not deeper', GATE, ["E38"]),
    ("G30", "warrant/gate.py", 'or (status == "A" and first.endswith(MODULE_SUFFIXES))):', 'or False):', GATE, ["E39"]),
    ("G31", "warrant/gate.py", 'if deeper and (written.split("/")[d.count("/") + 1 if d else 0] not in were\n                       or (status', 'if deeper and ((status', GATE, ["E40"]),
    ("G42", "warrant/gate.py", 'written.split("/")[d.count("/") + 1 if d else 0] not in were', 'first not in {folded(w) for w in were}', GATE, ["E40"]),
    ("G44", "warrant/gate.py", "        except UnicodeDecodeError:          # Git holds paths as bytes: a base tree",
     "        except KeyError:          # Git holds paths as bytes: a base tree", GATE, ["E52"]),
    ("G45", "warrant/gate.py", '    if len(families) < w["families"]:', '    if False:', GATE, ["E53"]),
    ("G46", "warrant/gate.py", ' | ({rep["_recs"][lin["leaf"]]["actor"]} & acceptors)', '', GATE, ["E54"]),
    ("G47", "warrant/gate.py", '    if veto and not any(r[0] == "OWNER_VETO" for r in a.reasons):', '    if False:', GATE, ["E55"]),
    ("G48", "warrant/gate.py", 'if done is None or now - done < w["window_hours"] * 3600:', 'if done is None:', GATE, ["E54"]),
    ("G49", "warrant/gate.py", 'if done is None or now - done < w["window_hours"] * 3600:', 'if done is not None and now - done < w["window_hours"] * 3600:', GATE, ["E54"]),
    ("G50", "warrant/gate.py", 'solo_left is not None and solo_left <= 0)', 'solo_left is not None)', GATE, ["E56"]),
    ("G51", "warrant/gate.py", 'bool(families and not blocking and solo_left', 'bool(families and solo_left', GATE, ["E56"]),
    ("G52", "warrant/gate.py", '    if set(w["paths"]) & set(owner):', '    if False:', GATE, ["E58"]),
    ("G53", "warrant/gate.py", 'set(GATE_FIELDS) <= set(doc) <= set(GATE_FIELDS) | {*TIERS, SOLO, PRESENCE, AFTER}', 'set(doc) == set(GATE_FIELDS)', GATE, ["E53"]),
    ("G54", "warrant/gate.py", 'every = owner_paths(root, b.commit, x, b.gate["owner_paths"] + [p for _, w in tiers for p in w["paths"]])', 'every = owner_paths(root, b.commit, x, b.gate["owner_paths"])', GATE, ["E53", "E59"]),
    ("G59", "warrant/gate.py", '    if a.facts.get("solo_ready") and any(c in ("NO_ACCEPT", "WATCHED_FAMILIES") for c, _ in a.reasons):\n        _solo(a, rep, lin, x)', '    if False:\n        _solo(a, rep, lin, x)', GATE, ["E56", "E62", "E64"]),
    ("G85", "warrant/gate.py", ' and any(c in ("NO_ACCEPT", "WATCHED_FAMILIES") for c, _ in a.reasons):\n        _solo(', ':\n        _solo(', GATE, ["E74"]),
    ("G60", "warrant/gate.py", 'if why is None and (c["window_hours"] < w["window_hours"] or c["solo_window_hours"] < w["solo_window_hours"]):',
     'if False:', GATE, ["E63"]),
    ("G61", "warrant/gate.py", '    ready = bool(author in b.holders(ACCEPTOR) and not others', '    ready = bool(not others', GATE, ["E64"]),
    ("G62", "warrant/gate.py", '                 and now - done >= solo["window_hours"] * 3600)', '                 and True)', GATE, ["E64"]),
    ("G63", "warrant/gate.py", '                   for c in gh.comments(a.pr["number"])):\n                continue', '                   for c in gh.comments(a.pr["number"])):\n                pass', GATE, ["E65"]),
    ("G64", "warrant/gate.py", 'mark in (c.get("body") or "") and (c.get("user") or {}).get("login") == f"{ACTIONS_APP}[bot]"', 'mark in (c.get("body") or "") and True', GATE, ["E65"]),
    ("G86", "warrant/gate.py", 'mark in (c.get("body") or "") and (c.get("user") or {}).get("login") == f"{ACTIONS_APP}[bot]"', 'mark in (c.get("body") or "") and (c.get("user") or {}).get("login", "").startswith(ACTIONS_APP)', GATE, ["E75"]),
    ("G65", "warrant/gate.py", 'else max(f for _, f in ready)', 'else min(f for _, f in ready)', GATE, ["E62"]),
    ("G66", "warrant/gate.py", '                and rep["_recs"][lin["leaf"]]["body"].get("state") == "backed"}', '}', GATE, ["E66"]),
    ("G67", "warrant/gate.py", '    branch = VERDICT_BRANCH if roadmap else CLAIMS_BRANCH', '    branch = VERDICT_BRANCH', GATE, ["E66"]),
    ("G68", "warrant/gate.py", '                 and CLAIMS_CHECKER in b.holders("claim/verifier") and', '                 and', GATE, ["E66"]),
    ("G69", "warrant/gate.py", "    if veto:\n        a.reasons.append((\"OWNER_VETO\", f\"a {solo['veto_role']}", "    if False:\n        a.reasons.append((\"OWNER_VETO\", f\"a {solo['veto_role']}", GATE, ["E64"]),
    ("G70", "warrant/gate.py", '    if tier == CONSTITUTIONAL and done is not None and not any(r[0] == "OWNER_PATHS" for r in a.reasons):', '    if False:', GATE, ["E61", "E65"]),
    ("G92", "warrant/gate.py", ' and not any(r[0] == "OWNER_PATHS" for r in a.reasons):\n        a.facts["notice"]', ':\n        a.facts["notice"]', GATE, ["E79"]),
    ("G71", "warrant/gate.py", '    if a.facts.get("present"):\n        # the owner present', '    if False:\n        # the owner present', GATE, ["E67"]),
    ("G72", "warrant/gate.py", '        hours = w["window_hours"] if len(families) >= w["families"] else w["solo_window_hours"]', '        hours = w["window_hours"]', GATE, ["E67"]),
    ("G73", "warrant/gate.py", '        return bool(families and not blocking and done is not None), None if done is None else int(done)', '        return bool(families and not blocking), None if done is None else int(done)', GATE, ["E67"]),
    ("G74", "warrant/gate.py", '    if until:\n        message += f"\\n\\nwarrant-gate brake until', '    if False:\n        message += f"\\n\\nwarrant-gate brake until', GATE, ["E68"]),
    ("G75", "warrant/gate.py", '(c.get("committer") or {}).get("login") == WEB_FLOW', 'True', GATE, ["E72"]),
    ("G76", "warrant/gate.py", '        if when < since or asked >= 30:', '        if asked >= 30:', GATE, ["E72"]),
    ("G77", "warrant/gate.py", '    if b.gate["hold_label"] in gh.pull(k["pr"])["labels"]:', '    if False:', GATE, ["E69"]),
    ("G78", "warrant/gate.py", '    return path == RECORDS or path.startswith(BLOBS)', '    return False', GATE, ["E69"]),
    ("G79", "warrant/gate.py", '    bad = [p for p in changed if now.get(p) != after.get(p) or ', '    bad = [p for p in changed if ', GATE, ["E70"]),
    ("G80", "warrant/gate.py", '    if pr.get("author") != f"{ACTIONS_APP}[bot]" or pr.get("head_repo") != b.repository:', '    if pr.get("head_repo") != b.repository:', GATE, ["E70"]),
    ("G96", "warrant/gate.py", '        if reverted(root, b.commit, k["merge"]) or k["merge"] in pending:', '        if reverted(root, b.commit, k["merge"]) or any(str(a.pr.get("branch") or "").startswith(f"{REVERT_BRANCH}{k[\'pr\']}-") for a in found):', GATE, ["E83"]),
    ("G97", "warrant/gate.py", '    if pr.get("author") != f"{ACTIONS_APP}[bot]" or pr.get("head_repo") != b.repository:', '    if pr.get("author") != f"{ACTIONS_APP}[bot]":', GATE, ["E70"]),
    ("G81", "warrant/gate.py", '    if any(got.get(p) != o for p, o in want.items()) or not moved <= set(want):', '    if any(got.get(p) != o for p, o in want.items()):', GATE, ["E70"]),
    ("G82", "warrant/gate.py", 'for m in brake_lines(msg) if not open_only or int(m[1]) > now]', 'for m in brake_lines(msg)]', GATE, ["E69", "E71"]),
    ("G83", "warrant/gate.py", '            return 1 if open_ and not pre else 0', '            return 0', GATE, ["E71"]),
    ("G84", "warrant/gate.py", '    if w is None:\n        return "presence is read beside watched"', '    if False:\n        return "presence is read beside watched"', GATE, ["E73"]),
    ("G87", "warrant/gate.py", '    return [m for ln in msg.splitlines() if (m := BRAKE.fullmatch(ln)) and S.hex64(m[3])]', '    return [m for ln in msg.splitlines() if (m := BRAKE.fullmatch(ln))]', GATE, ["E76"]),
    ("G88", "warrant/gate.py", '                if (r.get("user") or {}).get("login") == login and t is not None and t >= since:', '                if t is not None and t >= since:', GATE, ["E77"]),
    ("G89", "warrant/gate.py", 'if (c.get("user") or {}).get("login") == f"{ACTIONS_APP}[bot]" and any(m in (c.get("body") or "") for m in MARKS)]', 'if True]', GATE, ["E77"]),
    ("G90", "warrant/gate.py", '        if any(mark in (i.get("body") or "") for page in gh.api("issues?state=all&per_page=100", pages=True) for i in page', '        if any(False for page in gh.api("issues?state=all&per_page=100", pages=True) for i in page', GATE, ["E78"]),
    ("G91", "warrant/gate.py", '    if PRESENCE not in b.gate or until is None or until > now:', '    if PRESENCE not in b.gate or until is None:', GATE, ["E78"]),
    ("G93", "warrant/gate.py", '    ids = ids if n is None else ids[:n]', '    ids = ids[:300]', GATE, ["E80"]),
    ("G94", "warrant/gate.py", '    want = {e["path"]: (e["mode"], e["type"], e["sha"]) if e["sha"] else None for e in plan}\n    got = {p: (m, t, o) for m, t, o, p in entries(root, head, ".")}\n    was = {p: (m, t, o) for m, t, o, p in entries(root, parent, ".")}',
     '    want = {e["path"]: e["sha"] for e in plan}\n    got = {p: o for _, _, o, p in entries(root, head, ".")}\n    was = {p: o for _, _, o, p in entries(root, parent, ".")}', GATE, ["E81"]),
    ("G95", "warrant/gate.py", 'max(p["since"], now - 2 * p["days"] * 86400), 0, []', 'max(p["since"], now - p["days"] * 86400), 0, []', GATE, ["E82"]),
    ("G98", "warrant/gate.py", '            if p.get("mergeable_state") != "dirty":\n                continue', '            if False:\n                continue', GATE, ["E84"]),
    ("G99", "warrant/gate.py", '    union = b"".join(sorted(set(lines_of(files[base]) + lines_of(files[head])), key=_line_id))', '    union = b"".join(sorted(set(lines_of(files[base]) + lines_of(files[head]))))', GATE, ["E84"]),
    ("G100", "warrant/gate.py", '        if not a.facts.get("verdicts") or {c for c, _ in a.shared}', '        if {c for c, _ in a.shared}', GATE, ["E84"]),
    ("G101", "warrant/gate.py", '    if a.facts.get("verdicts"):\n        base = code_tree(b.root, b.commit)', '    if False:\n        base = code_tree(b.root, b.commit)', GATE, ["E85"]),
    ("G102", "warrant/gate.py", 'if "paths" not in x or changed is None or any(_listed(x["paths"], p) for p in changed)]', 'if True]', GATE, ["E85"]),
    ("G103", "warrant/gate.py", '    if why is None and AFTER in doc:\n        why = after_problem(doc[AFTER])', '    if False:\n        why = after_problem(doc[AFTER])', GATE, ["E86"]),
    ("G104", "warrant/gate.py", '            return 1 if open_ and not pre else 0', '            return 1 if open_ else 0', GATE, ["E87"]),
    ("G105", "warrant/gate.py", '            pre = a.version is not None and bool(PRERELEASE.fullmatch(a.version))', '            pre = a.version is not None and bool(PRERELEASE.match(a.version))', GATE, ["E87"]),
    ("G106", "warrant/gate.py", '            pre = a.version is not None and bool(PRERELEASE.fullmatch(a.version))', '            pre = a.version is not None', GATE, ["E87"]),
    ("G107", "warrant/gate.py", '            if rel is True:\n                held.append', '            if rel is not False:\n                held.append', GATE, ["E88"]),
    ("G108", "warrant/gate.py", '        return False if e.returncode == 1 else None', '        return False', GATE, ["E88"]),
    ("G109", "warrant/gate.py", '            gh.api(f"pulls/{n}", "PATCH", {"state": "closed"})\n', '', GATE, ["E84"]),
    ("G110", "warrant/gate.py", '                gh.dispatch(w, fresh)', '                gh.dispatch(w, branch)', GATE, ["E84"]),
    ("G111", "warrant/gate.py", '                gh.api("git/refs", "POST", {"ref": f"refs/heads/{fresh}", "sha": commit})', '                gh.api(f"git/refs/heads/{_branch(branch)}", "PATCH", {"sha": commit, "force": False})', GATE, ["E84", "E89"]),
    ("G112", "warrant/gate.py", '            open_ = next((x.pr for x in found if x.pr.get("branch") == fresh', '            open_ = next((x.pr for x in found if False', GATE, ["E90"]),
    ("G113", "warrant/gate.py", '            tip = open_["head"] if open_ else _branch_tip(gh, fresh)', '            tip = open_["head"] if open_ else None', GATE, ["E90"]),
    ("G115", "warrant/gate.py", '                if parents != [head, b.commit] or (c.get("tree") or {}).get("sha") != tree:', '                if (c.get("tree") or {}).get("sha") != tree:', GATE, ["E91"]),
    ("G116", "warrant/gate.py", '                if parents != [head, b.commit] or (c.get("tree") or {}).get("sha") != tree:', '                if parents != [head, b.commit]:', GATE, ["E91"]),
    ("G117", "warrant/gate.py", "            for w in sorted({c[\"workflow\"] for c in b.gate[\"required\"]} - ran):", "            for w in sorted({c[\"workflow\"] for c in b.gate[\"required\"]} - ran if open_ is None and commit is not None else ()):", GATE, ["E91"]),
    ("G118", "warrant/gate.py", "            for w in sorted({c[\"workflow\"] for c in b.gate[\"required\"]} - ran):", "            for w in sorted({c[\"workflow\"] for c in b.gate[\"required\"]}):", GATE, ["E91"]),
    ("G119", "warrant/gate.py", '            if (p.get("head") or {}).get("sha") != head:', '            if False:', GATE, ["E92"]),
    ("G120", "warrant/gate.py", '            if (gh.api(f"pulls/{_number(n)}").get("head") or {}).get("sha") != head:', '            if False:', GATE, ["E92"]),
    ("G122", "warrant/gate.py", '                if w.get("conclusion") == "action_required" and w.get("path") in required and w.get("head_sha") == head:', '                if w.get("conclusion") == "action_required" and w.get("head_sha") == head:', GATE, ["E93"]),
    ("G123", "warrant/gate.py", '        if {c for c, _ in a.reasons + a.shared} - HELD:\n            continue\n', '', GATE, ["E93"]),
    ("G124", "warrant/gate.py", '            if p.get("state") != "open" or (p.get("head") or {}).get("sha") != head:\n                continue                                              # closed, or moved', '            if False:\n                continue                                              # closed, or moved', GATE, ["E93"]),
    ("G125", "warrant/gate.py", '        if not a.facts.get("verdicts") or a.pr.get("head_repo") != b.repository:\n            continue\n        if {c for c, _ in a.reasons', '        if a.pr.get("head_repo") != b.repository:\n            continue\n        if {c for c, _ in a.reasons', GATE, ["E93"]),
    ("G126", "warrant/gate.py", '        out.append((n, done))\n    return out', '        gh.api(f"git/refs/heads/{_branch(branch)}", "DELETE")\n        out.append((n, done))\n    return out', GATE, ["E84", "E92"]),
    ("G127", "warrant/gate.py", '        moved = base is None or any(code_tree(b.root, c) != base for c in a.facts.get("made_at") or [])', '        moved = base is None', GATE, ["E94"]),
    ("G128", "warrant/gate.py", '        moved = base is None or any(code_tree(b.root, c) != base for c in a.facts.get("made_at") or [])', '        moved = True', GATE, ["E94"]),
    ("G129", "warrant/gate.py", '    return sorted(r for r in rows if r and r.split("\\t", 1)[-1] != ".warrant")', '    return sorted(r for r in rows if r)', GATE, ["E94"]),
    ("G130", ".warrant/merge.json", '      "docs/V3.md",\n', '', GATE, ["E95"]),
    ("G43", "warrant/gate.py", "    except UnicodeDecodeError:              # Git holds", "    except ZeroDivisionError:              # Git holds", GATE, ["E51"]),
    ("G32", "warrant/gate.py", 'or (status == "A" and "/" not in deeper and _module_file(deeper, "__init__"))):', 'or False):', GATE, ["E41"]),
    ("G33", "warrant/gate.py", 'if not deeper and (mode not in FILE_MODES or (status == "A"', 'if not deeper and ((status == "A"', GATE, ["E42"]),
    ("G34", "warrant/gate.py", '    if path.rpartition("/")[2] == ATTRIBUTES:\n', '    if False:\n', GATE, ["E43"]),
    ("G35", "warrant/gate.py", '    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())\n', '    return path\n', GATE, ["E44"]),
    ("G36", "warrant/gate.py", 'return name.startswith(module) and (rest.startswith(".") or rest in MODULE_SUFFIXES)', 'return name.startswith(module)', GATE, ["E45"]),
    ("G37", "warrant/gate.py", 'or (status == "A" and first.endswith(MODULE_SUFFIXES))):', 'or first.endswith(MODULE_SUFFIXES)):', GATE, ["E45"]),
    ("G38", "warrant/gate.py", '        while d and "__init__" in modules.get(d, ()):\n            d = d.rpartition("/")[0]\n', '', GATE, ["E39", "E45"]),
    ("G39", "warrant/gate.py", 'MODULE_SUFFIXES = tuple(sorted({*importlib.machinery.all_suffixes(), ".py", ".pyc", ".pyw", ".pyd", ".so"}))', 'MODULE_SUFFIXES = tuple(importlib.machinery.all_suffixes())', GATE, ["E39"]),
    ("G40", "warrant/gate.py", ') or loadable(p, path, status, mode, modules, held):', '):', GATE, ["E34"]),
    ("G41", "warrant/gate.py", 'subdirectories(root, mb, d) & subdirectories(root, base, d) for d in searched}', 'subdirectories(root, mb, d) for d in searched}', GATE, ["E50"]),
    ("G3", "warrant/gate.py", "        else:\n            extra.append((path, f\"{status} {old_mode}->{new_mode}\"))", "", GATE, ["E05"]),
    ("G4", "warrant/gate.py", "    if loose:\n        sh.append((\"TAIL_BLOB_UNCITED\"", "    if False:\n        sh.append((\"TAIL_BLOB_UNCITED\"", GATE, ["E07"]),
    ("G5", "warrant/gate.py", "    if stray:\n", "    if False:\n", GATE, ["E08"]),
    ("G6", "warrant/gate.py", '            (rec["kind"] in ("attest", "challenge") and rec["actor"] in b.holders(ACCEPTOR))',
     '            rec["kind"] in ("attest", "challenge")', GATE, ["E09"]),
    ("G7", "warrant/gate.py", "    if owned is None or owned:", "    if owned is None:", GATE, ["E10"]),
    ("G8", "warrant/gate.py", "    if findings:\n        a.reasons.append", "    if False:\n        a.reasons.append", GATE, ["E11"]),
    ("G9", "warrant/gate.py", '    if v["guard"] != "MET" or not by:', "    if False:", GATE, ["E12"]),
    ("G10", "warrant/gate.py", '    if lin["verdict"] == "FORK":', "    if False:", GATE, ["E13"]),
    ("G11", "warrant/gate.py", "    if not is_ancestor(root, x, head):", "    if False:", GATE, ["E14"]),
    ("G12", "warrant/gate.py", '    if tree != leaf["body"].get("tree"):', "    if False:", GATE, ["E15"]),
    ("G13", "warrant/gate.py", '    if pr.get("head_repo") != b.repository:', "    if False:", GATE, ["E17"]),
    ("G14", "warrant/gate.py", "    if old:\n        out.append((\"VERDICT_NOT_NEW\"", "    if False:\n        out.append((\"VERDICT_NOT_NEW\"", GATE, ["E18"]),
    ("G15", "warrant/gate.py", "    if late:\n", "    if False:\n", GATE, ["E19"]),
    ("G16", "warrant/gate.py", '        ours = [r for r in runs if suites.get((r.get("check_suite") or {}).get("id")) == c["workflow"]]',
     "        ours = runs", GATE, ["E20"]),
    ("G17", "warrant/gate.py", '    if now["head"] != head:', "    if False:", GATE, ["E21"]),
    ("G18", "warrant/gate.py", "    if tip != base:\n        return", "    if False:\n        return", GATE, ["E22"]),
    ("G19", "warrant/gate.py", "    if rep[\"rejected\"] or rep[\"problems\"]:", "    if False:", GATE, ["E04"]),
    ("G20", "warrant/gate.py", '    if not str(pr.get("branch") or "").startswith(branch):', "    if False:", GATE, ["E23"]),
    ("G22", E, "                    self.pending.append(i)          # waits",
     '                    self.problem("SCHEMA_NOT_COUNTED", i, "short of its quorum")\n                    self.pending.append(i)          # waits', GATE, ["E28"]),
    ("G21", "warrant/gate.py", '        if g["guard"] == "PENDING" and g["short"] and not g["open"] and roles & set(g["roles"]):',
     '        if g["guard"] == "PENDING" and g["short"] and roles & set(g["roles"]):', GATE, ["E24"]),
    # the review loop's commands (warrant/claims.py, review.py, repo.py)
    ("T1", "warrant/claims.py", '        if b["text"] not in spec.get(b["source"], ""):', "        if False:", TOOLS, ["C02"]),
    ("T2", "warrant/claims.py", "        if c not in printed.get(f, set()):", "        if False:", TOOLS, ["C03"]),
    ("T3", "warrant/claims.py", "        if m not in known:", "        if False:", TOOLS, ["C04"]),
    ("T4", "warrant/claims.py", '        if b["source"] not in spec:', "        if False:", TOOLS, ["C05"]),
    ("T5", "warrant/claims.py", '        elif not {f"{witness_of(m, known)}:{c}" for c in known.get(m, ["", "", []])[2]} & set(ws):', "        elif False:", TOOLS, ["C06"]),
    ("T6", "warrant/review.py", "    if any(x[:2] == [\"FAIL\", case] for x in lines):", "    if any(x[:1] == [\"FAIL\"] for x in lines):", TOOLS, ["R03"]),
    ("T7", "warrant/review.py", "    if files != [f\"tests/{t['file']}.py\"] or re.findall", "    if re.findall", TOOLS, ["R04"]),
    ("T8", "warrant/review.py", "    if got != r[\"body\"][\"verdict\"]:", "    if False:", TOOLS, ["R05"]),
    ("T9", "warrant/repo.py", "            raise Failed(\"IDENTITY\"", "            pass  # Failed(\"IDENTITY\"", TOOLS, ["R06"]),
    ("T11", "warrant/claims.py", "    return out          # a schema awaiting backers",
     '    out += [("SCHEMA_PENDING", i) for i in rep["schemas_pending"]]\n    return out          # a schema awaiting backers', TOOLS, ["C10"]),
    ("T31", "warrant/cli.py", "        for d in (cwd, *cwd.parents):", "        for d in (cwd,):", TOOLS, ["K01"]),
    ("T32", "warrant/cli.py", '    trust = json.loads(Path(here(a.trust)).read_text()) if getattr(a, "trust", None) else doc["trust"]',
     '    trust = doc["trust"] if doc else json.loads(Path(here(a.trust)).read_text())', TOOLS, ["K02"]),
    ("T33", "warrant/cli.py", '            "frontier": G.frontier(rep, profile, a.actor, view.recs) if a.actor else None}', '            "frontier": None}',
     TOOLS, ["K03"]),
    ("T34", "warrant/cli.py", '    return " · ".join(f"{k} {n}" for k, n in d.items()) or "none"', '    return "none"', TOOLS, ["K04"]),
    ("T35", "warrant/cli.py", "    if argv[:1] and argv[0] in LOOP:", "    if False:", TOOLS, ["K05"]),
    ("T36", "warrant/cli.py", '    if a.cmd != "init":', "    if True:", TOOLS, ["K06"]),
    ("T41", "warrant/home.py", '                       bound=None if not r.get("signer") else doc["identities"][r["signer"]]["public"] in trust["keys"].get(r["signer"], []))',
     '                       bound=None if not r.get("signer") else True)', TOOLS, ["H01"]),
    ("T42", "warrant/home.py", '        inside = _inside_any(i["seed"], paths)', "        inside = None", TOOLS, ["H02"]),
    ('T43', 'warrant/home.py', '    _private(p, "the Home")\n    doc =', '    doc =', TOOLS, ['H03']),
    ("T44", "warrant/home.py", "    if p.is_symlink() or not p.is_file():", "    if not p.is_file():", TOOLS, ["H03"]),
    ("T45", "warrant/home.py", "    if os.stat(real).st_mode & 0o077:", "    if False:", TOOLS, ["H04"]),
    ("T46", "warrant/home.py", '    return confined(os.path.join(root, ".warrant"), root)', '    return ".warrant"', TOOLS, ["H05"]),
    ("T49", "warrant/home.py", '    return confined(os.path.join(root, ".warrant"), root)', '    return os.path.join(root, ".warrant")', TOOLS, ["H07"]),
    ("T47", "warrant/cli.py", '                return confined(d / ".warrant", d)', '                return str(d / ".warrant")', TOOLS, ["K07"]),
    ("T48", "warrant/cli.py", '    return confined(cwd / ".warrant", cwd)', '    return str(cwd / ".warrant")', TOOLS, ["K07"]),
    ("T37", "warrant/roadmap.py", '    if rep["_recs"][L]["actor"] != a.actor:', "    if False:", TOOLS, ["P03"]),
    ("T37b", "warrant/roadmap.py", '    return (0, int(m.group(1)), "") if m else (1, 0, str(key))', "    return (1, 0, str(key))", TOOLS, ["P02b"]),
    ("T38", "warrant/roadmap.py", '    return _successor(rep, a, L, dict(prev, statement=a.statement), "open")',
     '    return _successor(rep, a, L, prev, "open")', TOOLS, ["P03"]),
    ("T39", "warrant/roadmap.py", '    if a.actor not in profile["roles"].get("roadmap/owner", []):', "    if False:", TOOLS, ["P04"]),
    ("T40", "warrant/roadmap.py", '    return _successor(rep, a, L, prev, "released", residual=[a.reason])',
     '    return _successor(rep, a, L, prev, "released")', TOOLS, ["P04"]),
    ("T28", "warrant/repo.py", '    rows = git(root, "ls-tree", "-r", "--full-tree", commit).splitlines()',
     '    rows = git(root, "ls-tree", "-r", commit).splitlines()', TOOLS, ["C20"]),
    ("T29", "warrant/repo.py", '    carried = git(root, "ls-tree", "--full-tree", commit, "--", f"{NAME}/__init__.py")',
     '    carried = git(root, "ls-tree", commit, "--", f"{NAME}/__init__.py")', TOOLS, ["C20"]),
    ("T30", "warrant/repo.py", '    for row in git(root, "ls-tree", "--full-tree", commit, "--", f"{NAME}/").splitlines():',
     '    for row in git(root, "ls-tree", commit, "--", f"{NAME}/").splitlines():', TOOLS, ["C20"]),
    ('T61', 'warrant/differential.py', '        if not isinstance(rep, dict) or rep.get("assessment") != C.doc_id({k: rep.get(k) for k in OPERANDS}):', '        if not isinstance(rep, dict):', TOOLS, ['D03']),
    ('T62', 'warrant/differential.py', '    if named == differs:', '    if set(differs) <= set(named):', TOOLS, ['D02']),
    ('T63', 'warrant/differential.py', 'IDENTITY = ("assessment", "code")', 'IDENTITY = ("assessment", "code", "lineages")', TOOLS, ['D02']),
    ('T64', 'warrant/differential.py', 'r = run([str(python), "-I", "-c", script,', 'r = run([str(python), "-c", script,', TOOLS, ['D04']),
    ('T65', 'warrant/differential.py', 'capture_output=True, cwd=away, check=False', 'capture_output=True, cwd=None, check=False', TOOLS, ['D04']),
    ('T66', 'warrant/differential.py', '    if r.returncode:\n        raise Unmade(f"{python} exited', '    if False:\n        raise Unmade(f"{python} exited', TOOLS, ['D04']),
    ('T76', 'warrant/differential.py', '    if r.returncode:\n        raise Unmade(f"git ', '    if False:\n        raise Unmade(f"git ', TOOLS, ['D09']),
    ('T67', 'warrant/differential.py', 'and isinstance(doc["differs"], list) and all(isinstance(m, str) for m in doc["differs"]) and doc["differs"]', 'and isinstance(doc["differs"], list)', TOOLS, ['D05']),
    ("T68", "warrant/differential.py", "    if os.sep in str(python):", "    if False:", TOOLS, ["D06"]),
    ("T69", "warrant/differential.py", '               if lin["schema"] == "obligation@1" and lin["effective"] and lin["state"] == "done"',
     '               if lin["schema"] == "obligation@1" and lin["effective"]', TOOLS, ["D07"]),
    ("T70", "warrant/differential.py", 'and want in (recs.get(lin["effective"], {}).get("body", {}).get("refs") or [])', 'and True', TOOLS, ["D07"]),
    ("T71", "warrant/differential.py", '    if not out["release"]["accepted"]:', '    if False:', TOOLS, ["D08"]),
    ("T72", "warrant/differential.py", '    if gone["records"] or gone["blobs"]:', '    if gone["blobs"]:', TOOLS, ["D09"]),
    ("T73", "warrant/differential.py", '    if gone["records"] or gone["blobs"]:', '    if gone["records"]:', TOOLS, ["D09"]),
    ("T74", "warrant/differential.py", '    return {"records": sorted(x.decode() for x in then - now), "blobs": sorted(blobs - here)}',
     '    return {"records": [], "blobs": []}', TOOLS, ["D09"]),
    ("T75", "warrant/differential.py", "    tag = TAG.format(published_version(python, root))",
     "    tag = TAG.format(version)", TOOLS, ["D09"]),
    ("T78", "warrant/differential.py", 'TAG = "refs/tags/v{}"', 'TAG = "v{}"', TOOLS, ["D09"]),
    ("T77", "warrant/differential.py", "    if not (isinstance(n, str) and VERSION.match(n)):",
     "    if not isinstance(n, str):", TOOLS, ["D09"]),
    ("T79", "warrant/claims.py", "and len(set(srcs)) == len(srcs)", "and True", TOOLS, ["C21"]),
    ("T80", "warrant/claims.py", '          and all(_relative(x) and x not in srcs for x in doc["retired"])', '          and all(_relative(x) for x in doc["retired"])', TOOLS, ["C21"]),
    ("T81", "warrant/claims.py", "isinstance(srcs, list) and srcs and all", "isinstance(srcs, list) and all", TOOLS, ["C21"]),
    ("T82", "warrant/claims.py", '        if source not in srcs:\n            raise Failed("CLAIM_SOURCE"', '        if False:\n            raise Failed("CLAIM_SOURCE"', TOOLS, ["C21"]),
    ("T83", "warrant/claims.py", '    spec = {src: (repo.root / src).read_text() for src in srcs}', '    spec = {src: (repo.root / srcs[0]).read_text() for src in srcs}', TOOLS, ["C21"]),
    ("T84", "warrant/claims.py", 'live(rep).items() if b["source"] in srcs),', 'live(rep).items() if b["source"] == srcs[0]),', TOOLS, ["C21"]),
    ("T85", "warrant/claims.py", '        if text.startswith("#", start):\n            continue', '        if False:\n            continue', TOOLS, ["C22"]),
    ("T86", "warrant/claims.py", "            i = text.find(t, i + 1)", "            i = -1", TOOLS, ["C22"]),
    ("T87", "warrant/claims.py", '(?:{word})(?![A-Za-z0-9_])', '(?:{word})', TOOLS, ["C22"]),
    ("T88", "warrant/claims.py", '    if "coverage" in cfg:', '    if False:', TOOLS, ["C22"]),
    ("T89", "warrant/claims.py", "          and len(set(cover)) == len(cover)", "          and True", TOOLS, ["C22"]),
    ("T90", "warrant/claims.py", 'KEYWORD = re.compile(r"[A-Z]+(?: [A-Z]+)*\\Z")', 'KEYWORD = re.compile(r"[A-Z]+(?: [A-Z]+)*$")', TOOLS, ["C22"]),
    ("T91", "warrant/claims.py", 'if b["source"] == src and isinstance(b.get("text"), str)]', 'if b["source"] == src and b.get("state") == "backed"]', TOOLS, ["C22"]),
    ("T92", "warrant/claims.py", "all(isinstance(k, str) and KEYWORD.match(k) for k in cover)", "all(isinstance(k, str) for k in cover)", TOOLS, ["C22"]),
    ("T94", "warrant/claims.py", "        if not any(a <= m.start() and m.end() <= b for a, b in spans):",
     "        if not any(a <= m.start() < b for a, b in spans):", TOOLS, ["C22"]),
    ("T95", "warrant/claims.py", '    word = "|".join(r"\\s+".join(map(re.escape, k.split(" "))) for k in sorted(keywords, key=len, reverse=True))',
     '    word = "|".join(re.escape(k) for k in sorted(keywords, key=len, reverse=True))', TOOLS, ["C22"]),
    ("T93", "warrant/claims.py", "isinstance(cover, list) and cover and all", "isinstance(cover, list) and all", TOOLS, ["C22"]),
    # G14: drift and the STALE gate (warrant/drift.py)
    ("T96", DR, '        if x["verdict"] != "UNCHANGED" and lin["reliance"] == "ELIGIBLE":', "        if False:", TOOLS, ["DR1", "DR4"]),
    ("T97", PINS, "        if now == blob:", "        if True:", TOOLS, ["DR1"]),
    ("T98", PINS, "        elif now is None and blob in where:", "        elif False:", TOOLS, ["DR3"]),
    ("T99", PINS, "    if words <= set(FRESH):", '    if words <= {"UNCHANGED"}:', TOOLS, ["DR3"]),
    ("T100", PINS, '"rev-list", "--reverse", "--topo-order", f"{commit}..{head}"', '"rev-list", "--reverse", "--topo-order", f"{head}..{commit}"', TOOLS, ["DR2"]),
    ("T146", PINS, "            if fresh(blobs(root, c), path, blob):\n                break", "            if False:\n                break", TOOLS, ["DR26"]),
    ("T138", PINS, "            since = c\n", "            since = since or c\n", TOOLS, ["DR26"]),
    ("T139", PINS, "                break\n            since = c", "                continue\n            since = c", TOOLS, ["DR27"]),
    ("T140", PINS, "        if S.hex_of(oid, 40):\n            touched |=", "        if False:\n            touched |=", TOOLS, ["DR27"]),
    ("T101", DR, "        out.append(f\"{word:9} {x['id']} ({L[:12]})", "        out.append(f\"{x['id']} {word:9} ({L[:12]})", TOOLS, ["DR2", "DR3"]),
    ("T102", PINS, "    if not files:", "    if files is None:", TOOLS, ["DR8"]),
    ("T112", PINS, "    if not S.hex_of(commit, 40):", "    if False:", TOOLS, ["DR10"]),
    ("T113", PINS, "    if not (isinstance(files, dict) and all(isinstance(b, str) for b in files.values())):", "    if not isinstance(files, dict):", TOOLS, ["DR9"]),
    ("T103", "warrant_agent/api.py", "        D.gate(rep, ws.repo)", "        pass", TOOLS, ["DR1"]),
    ("T104", "warrant/claims.py", "    drift.gate(rep, root)", "    pass", TOOLS, ["DR1"]),
    ("T105", PINS, "        elif now is None and blob in where:", "        elif blob in where:", TOOLS, ["DR6"]),
    ("T106", DR, "        x, rows = min(seen,", "        x, rows = max(seen,", TOOLS, ["DR1"]),
    ("T107", "warrant/claims.py", '"files": files, "closure": CLOSURE}, refs=[leaf]))', '"closure": CLOSURE}, refs=[leaf]))', TOOLS, ["DR1"]),
    ("T108", "warrant/claims.py", "and any(c == CLOSURE and files == now[L] for", "and any(files == now[L] for", TOOLS, ["CF3"]),
    ("T109", "warrant/claims.py", "                if pins.get(i) is not None and pins[i] != files_of(b, wt, known, tree)]", "                if False]", TOOLS, ["DR7"]),
    # G14: what a change bears on (warrant drift --impact)
    ("T127", DR, '    for v in rep["lineages"][L]["versions"]:\n        roots |=', '    for v in [rep["lineages"][L]["effective"]]:\n        roots |=', TOOLS, ["DR22"]),
    ("T134", DR, "A.reach([rep, *(r.rep for r in read)], vs)", 'A.reach([rep, *(r.rep for r in read)], [rep["lineages"][L]["effective"]])', TOOLS, ["DR23"]),
    ("T141", DR, "A.reach([rep, *(r.rep for r in read)], vs)", "A.reach([r.rep for r in others], vs)", TOOLS, ["DR28"]),
    ("T142", DR, '            row["rests_on_it"] = [_row(rep, R) for R in sorted({G.lineage_of(rep, i) for i in reached} - {None, L})]',
     '            row["rests_on_it"] = [_row(rep, R) for R in rests_on(rep, L)]', TOOLS, ["DR28"]),
    ("T143", DR, "    if readings is None:\n        g = G.answer(", "    if True:\n        g = G.answer(", TOOLS, ["DR29"]),
    ("T144", DR, "    return A.identity(reps, _unavailable(readings, root),", "    return A.identity(reps, [],", TOOLS, ["DR29"]),
    ("T145", DR, '        out["unavailable"] = _unavailable(readings, root)', '        out["unavailable"] = []', TOOLS, ["DR29"]),
    ("T136", "tools/graph.py", '    d["drift"] = DR.impact(reps[1], repo.root, head, base)', '    d["drift"] = DR.impact(reps[1], repo.root, head)',
     TOOLS, ["DR25"]),
    ("T135", DR, '(x.root is None or os.path.realpath(x.root) != os.path.realpath(root))]', 'True]', TOOLS, ["DR23"]),
    ("T128", DR, "    return sorted(roots - {None, L})", "    return sorted(roots - {None})", TOOLS, ["DR22"]),
    ("T129", DR, '        if base and before.get(L, {}).get("verdict") != "UNCHANGED":', "        if False:", TOOLS, ["DR20"]),
    ("T130", DR, "in_no_acceptance=[p for p in changed if p not in named]", "in_no_acceptance=[]", TOOLS, ["DR19"]),
    ("T131", DR, '    if not isinstance(rev, str) or not rev or rev.startswith("-"):', "    if not isinstance(rev, str) or not rev:", TOOLS, ["DR21"]),
    ("T132", DR, '        head = "impact: 0 affected"', '        head = "impact: 0 stale claim(s)"', TOOLS, ["DR18"]),
    ("T133", DR, '    gate(rep, root, head)\n    now = drift(rep, root, head)', '    gate(rep, root)\n    now = drift(rep, root)', TOOLS, ["DR24"]),
    ("T110", DR, "    done = pinned(rep)\n", "    done = pinned(rep)\n    if (Path(root) / '.warrant' / 'claims.json').is_file():\n        C.harness(root)\n", TOOLS, ["DR5"]),
    ("T111", "warrant/claims.py", "        starts.update(known.get(m, [])[:2])", "        pass", TOOLS, ["DR1"]),
    ("T114", "warrant/claims.py", "    while (base / chain[-1]).is_symlink():", "    while False:", TOOLS, ["DR11"]),
    ("T115", "warrant/claims.py", "        ok = held(b, ran, killed) and files is not None", "        ok = held(b, ran, killed)", TOOLS, ["DR12"]),
    ("T117", DR, '    rep["checkout"] = checkout(root, at)', "    pass", TOOLS, ["DR13"]),
    ("T119", "warrant/claims.py", "    for f in sorted({os.path.normpath(p) for p in starts}):", "    for f in sorted(starts):", TOOLS, ["DR15"]),
    ("T120", "warrant/claims.py", "    if None in chains or any(p not in tree for chain in chains for p in chain):\n        return None\n    return {p: tree[p] for chain in chains for p in chain}",
     "    if None in chains:\n        return None\n    return {p: tree[p] for chain in chains for p in chain if p in tree}", TOOLS, ["CF4"]),
    ("T124", "warrant/graph.py", 'rep = rep1 if L in rep1["lineages"] else rep0', 'rep = rep1', TOOLS, ["DR17"]),
    ("T121", "warrant/across.py", 'read(name, r), os.path.expanduser(r["path"])) for name', 'read(name, r)) for name', TOOLS, ["DR16"]),
    ("T122", "warrant_agent/api.py", "    return A.Reading(ws.name, read, ws.repo)\n", "    return A.Reading(ws.name, read)\n", TOOLS, ["DR16"]),
    ("T118", PINS, '("link:" if r.startswith("120000 ") else "") + r.split()[2]', 'r.split()[2]', TOOLS, ["DR14"]),
    ("T123", "warrant/across.py", ', "checkout": rep.get("checkout")} for n, rep in reps.items()', '} for n, rep in reps.items()', TOOLS, ["DR16"]),
    ("T60", "warrant/cli.py", '    if kind == "schema" and E._schema_problem(body):', "    if False:", TOOLS, ["K09"]),
    ("T50", "warrant/cli.py", "        doc = json.loads(read_inside(f, store))", "        doc = json.loads(Path(f).read_bytes())", TOOLS, ["K08"]),
    ("T51", "warrant/repo.py", '        doc = json.loads(read_inside(self.dot / "v3.json", self.dot))',
     '        doc = json.loads((self.dot / "v3.json").read_bytes())', TOOLS, ["K08"]),
    ("T52", "warrant/home.py", '    doc = json.loads(read_inside(dot / "v3.json", dot))', '    doc = json.loads((dot / "v3.json").read_bytes())', TOOLS, ["H08"]),
    ("T53", "warrant/home.py", "    dot = dot_of(repo_path)\n", '    dot = Path(repo_path) / ".warrant"\n', TOOLS, ["H09"]),
    ("T54", "warrant/repo.py", "        self.dot = dot_of(self.root)", '        self.dot = self.root / ".warrant"', TOOLS, ["H09"]),
    ("T55", "warrant/home.py", "        fcntl.flock(fd, fcntl.LOCK_EX)", "        pass", TOOLS, ["H10"]),
    ("T56", "warrant/cli.py", "    doc = H.update(change)", "    doc = change(H.load())\n    H.save(doc)", TOOLS, ["H10"]),
    ('T57', 'warrant/home.py', '    _private(p.parent, "the Home\'s directory")\n    _private(p, "the Home")', '    _private(p, "the Home")', TOOLS, ['H11']),
    ('T58', 'warrant/home.py', '    _private(p.parent, "the Home\'s directory")         # an existing directory', '    pass         # an existing directory', TOOLS, ['H11']),
    ("T10", "warrant/claims.py", '    if key.public not in trust["keys"].get(CHECKER, []):', "    if False:", TOOLS, ["C08"]),
    ("T12", "warrant/repo.py", '    if body.get("code") != code:', "    if False:", TOOLS, ["C12", "R07"]),
    ("T13", "warrant/claims.py", "for i, _, b in rows if not held(b, ran, killed)]", "for i, _, b in rows if False]", TOOLS, ["C14"]),
    ("T14", "warrant/claims.py", "            if code_tree(root, x) == here:", "            if True:", TOOLS, ["C13"]),
    ("T15", "warrant/claims.py", '"commit": commit, "tree": tree, **me,', '"commit": commit, "tree": tree,', TOOLS, ["C11"]),
    ("T17", "warrant/claims.py", "        if problems_x:", "        if False:", TOOLS, ["C15"]),
    ("T18", "warrant/review.py", "    if why is None and ((r[\"body\"][\"target\"], r[\"body\"].get(\"on\")) not in due",
     "    if False and ((r[\"body\"][\"target\"], r[\"body\"].get(\"on\")) not in due", TOOLS, ["R09"]),
    ("T16", "warrant/review.py", '"window": [t0, int(time.time())], **me}', '"window": [t0, int(time.time())]}', TOOLS, ["R08"]),
    ("T19", "warrant/claims.py", '    if not ok:\n        raise Failed("CONFIG"', '    if False:\n        raise Failed("CONFIG"', TOOLS, ["C16"]),
    ("T20", "warrant/claims.py", '    for pattern in config(root)["witnesses"]:', '    for pattern in ["tests/*_test.py"]:', TOOLS, ["C17"]),
    ("T21", "warrant/repo.py", "    return code_at(commit, root) if carried else package_code()", "    return package_code()", TOOLS, ["R10"]),
    ("T22", "warrant/repo.py", "    return code_at(commit, root) if carried else package_code()", "    return code_at(commit, root)", TOOLS, ["C11"]),
    ("T24", "warrant/claims.py", "    if not Path(path).resolve().is_relative_to(base):", "    if False:", TOOLS, ["C18"]),
    ("T25", "warrant/claims.py", "            confined(root, p)\n", "", TOOLS, ["C18"]),
    ("T26", "warrant/repo.py", "        self.root = (Path(root) if root is not None else default_root()).resolve()",
     "        self.root = Path(root) if root is not None else default_root()", TOOLS, ["C19"]),
    ("T23", "warrant/repo.py", "    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else Path.cwd()",
     "    return PACKAGE.parent", TOOLS, ["R11"]),
    ("T27", "warrant/review.py", "    except GT.Refused as e:  # the gate's", "    except ValueError as e:  # the gate's", TOOLS, ["R12"]),
    # the review waker's reading of the store (integrations/warrant-review/waker/waker.py)
    ("P1", "integrations/warrant-review/waker/waker.py", "    if set(got) != set(filed):", "    if False:", WAKER, ["W2"]),
    ("P2", "integrations/warrant-review/waker/waker.py",
     '        if not (rec and rec.get("kind") == "attest" and rec.get("actor") == actor and b.get("verdict") in REPLAY_VERDICTS):',
     "        if not rec:", WAKER, ["W7"]),
    ("P3", "integrations/warrant-review/waker/waker.py",
     '        if rec["actor"] != actor or rec["kind"] not in VERDICTS or not binds(rec, {"closure": req["closure"], "asked": req.get("asked")}):',
     "        if False:", WAKER, ["W3"]),
    ("P4", "integrations/warrant-review/waker/waker.py", "    if set(got_lines) != set(lines):", "    if False:", WAKER, ["W4"]),
    ("P5", "integrations/warrant-review/waker/waker.py",
     '        if not (path.startswith(BLOBS) and HEX.match(path[len(BLOBS):]) and status == "A" and new_mode == REGULAR):',
     '        if not (path.startswith(BLOBS) and HEX.match(path[len(BLOBS):]) and status == "A"):', WAKER, ["W5"]),
    ("P7", "integrations/warrant-review/waker/waker.py", "not (isinstance(actor, str) and CHECKER.match(actor))",
     "not isinstance(actor, str)", WAKER, ["W8"]),
    ("P6", "integrations/warrant-review/waker/waker.py",
     '    if bad or len(recs) != len(lines) or any(b != "SIGNED" for b in basis.values()):', "    if False:", WAKER, ["W3"]),
    # the waker's repositories (W-5)
    ("P8", "integrations/warrant-review/waker/waker.py", "        if named != self.repository:", "        if False:", WAKER, ["W10"]),
    ("P9", "integrations/warrant-review/waker/waker.py", "{w.repository}#{a['pr']} is due", "s0fractal/warrant#{a['pr']} is due",
     WAKER, ["W9"]),
    ("P10", "integrations/warrant-review/waker/waker.py", "; base {w.branch} M {a['base']}.", "; base master M {a['base']}.", WAKER, ["W9"]),
    ("P11", "integrations/warrant-review/waker/waker.py", '        if len({e[k] if k == "repository" else os.path.realpath(e[k]) for e in entries}) != len(entries):', "        if False:",
     WAKER, ["W12"]),
    ("P12", "integrations/warrant-review/waker/waker.py", "        for e in entries:", "        for e in entries[:1]:", WAKER, ["W9"]),
    ("P14", "integrations/warrant-review/waker/waker.py", 'e[k] if k == "repository" else os.path.realpath(e[k])', "e[k]",
     WAKER, ["W13"]),
    ("P15", "integrations/warrant-review/waker/waker.py", "        verdicts = w.forge.verdicts()", "        return \"held\"", WAKER, ["W14"]),
    ("P16", "integrations/warrant-review/waker/waker.py", 'startswith(VERDICT_BRANCH) and x.get("isCrossRepository") is False]',
     'startswith(VERDICT_BRANCH)]', WAKER, ["W14"]),
    ("P17", "integrations/warrant-review/waker/waker.py", '                if str(x.get("headRefName") or "").startswith(VERDICT_BRANCH) and',
     "                if", WAKER, ["W14"]),
    ("P28", "integrations/warrant-review/waker/waker.py", 'replay_python or entry.get("replay_python") or env(', 'replay_python or env(',
     WAKER, ["W19"]),
    ("P29", "integrations/warrant-review/waker/waker.py", '                        for k in (*SERVED[2:], *({"replay_python"} & set(e))))):',
     '                        for k in SERVED[2:])):', WAKER, ["W19"]),
    ("P30", "integrations/warrant-review/waker/waker.py", "            if why:\n                raise Unpublished(why)\n            paths = [RECORDS,",
     "            if False:\n                raise Unpublished(why)\n            paths = [RECORDS,", WAKER, ["W20"]),
    ("P31", "integrations/warrant-review/waker/waker.py", "            if tip[:1] != [head]:\n                raise NotPushed(f\"{branch} is at",
     "            if False:\n                raise NotPushed(f\"{branch} is at", WAKER, ["W20"]),
    ("P32", "integrations/warrant-review/waker/waker.py", "            if git(\"-C\", str(wt), \"rev-parse\", \"HEAD\").decode().strip() != head:\n                raise Unpublished(f\"{actor} committed",
     "            if False:\n                raise Unpublished(f\"{actor} committed", WAKER, ["W20"]),
    ("P34", "integrations/warrant-review/waker/waker.py", '"commit", "--quiet", "--no-verify", "--only", "-m", msg, "--", *paths)', '"commit", "--quiet", "--no-verify", "-m", msg)', WAKER, ["W20"]),
    ("P35", "integrations/warrant-review/waker/waker.py", "            if any(rest):\n                line += f\"; worktree kept: {wt}\"", "            if False:\n                line += f\"; worktree kept: {wt}\"", WAKER, ["W20"]),
    ("P36", "integrations/warrant-review/waker/waker.py", "if verdicts and self.verify(code, c, added, blobs) is None else None", "if verdicts and self.verify(code, c, verdicts, {}) is None else None", WAKER, ["W21"]),
    ("P37", "integrations/warrant-review/waker/waker.py", "held = held_verdict(code, c) or held_verdict(self.tree(self.fetch()), c)", "held = held_verdict(code, c)", WAKER, ["W22"]),
    ("P33", "integrations/warrant-review/waker/waker.py", "            if not (isinstance(branch, str) and PR_BRANCH.match(branch) and branch != self.branch):\n                raise Unpublished(f\"{str(branch)[:40]!r} is not a pull request branch to push to\")\n            if not (isinstance(version, str)",
     "            if not (isinstance(branch, str) and PR_BRANCH.match(branch)):\n                raise Unpublished(f\"{str(branch)[:40]!r} is not a pull request branch to push to\")\n            if not (isinstance(version, str)", WAKER, ["W20"]),
    ("P40", "integrations/warrant-review/waker/waker.py", ' or (c.get("asked") and isinstance(b.get("verdict"), str))', '', WAKER, ["W23"]),
    ("P41", "integrations/warrant-review/waker/waker.py", '    if c.get("asked"):                   # a question addressed to Codex', '    if False:                   # a question addressed to Codex', WAKER, ["W23"]),
    ("P13", "integrations/warrant-review/install.py", "    if path.exists():", "    if False:", WAKER, ["C14"]),
    # warrant verify (warrant/verify.py, docs/VERIFY.md): a package assessed alone; the one-file verifier and its build
    ("UM01", VF, '"rely": bool(roots) and all(r["rely"] for r in roots.values())',
     '"rely": all(r["rely"] for r in roots.values())', VERIFY, ['U11']),
    ("UM02", VF, '    return 0 if ans["rely"] else 1\n',
     '    return 0\n', VERIFY, ['U02', 'U04', 'U05']),
    ("UM03", VF, '        if lin["effective"] != i:\n',
     '        if False:\n', VERIFY, ['U04', 'U10']),
    ("UM04", VF, '        elif lin["reliance"] != "ELIGIBLE":\n',
     '        elif False:\n', VERIFY, ['U05']),
    ("UM05", VF, '        why.append("UNAVAILABLE")\n',
     '        pass\n', VERIFY, ['U03', 'U09']),
    ("UM06", VF, '        why.append("NOT_A_VERSION")\n',
     '        pass\n', VERIFY, ['U12']),
    ("UM07", VF, '            why.append("STALE")\n',
     '            pass\n', VERIFY, ['U20']),
    ("UM08", VF, '        if pins["verdict"] == "NOT_CHECKED" and checkout is not None:\n',
     '        if False:\n', VERIFY, ['U22']),
    ("UM09", VF, '        if word == "UNCHANGED":\n',
     '        if word in ("UNCHANGED", "CHANGED"):\n', VERIFY, ['U20']),
    ("UM10", VF, '    still = fresh | ({a["actor"] for a in accepted} - pinning)\n',
     '    still = fresh\n', VERIFY, ['U25']),
    ("UM11", VF, '"FRESH" if len(still) >= view.recs[v]["guard"]["quorum"] else "STALE"',
     '"FRESH" if still else "STALE"', VERIFY, ['U26']),
    ("UM12", VF, '        if files is None:\n            continue\n',
     '        if not files:\n            continue\n', VERIFY, ['U27']),
    ("UM13", VF, '    if not require:\n        asked["roots"] = sorted(set(pkg["roots"]))\n',
     '    if True:\n        asked["roots"] = sorted(set(pkg["roots"]))\n', VERIFY, ['U10']),
    ("UM14", VF, '        if len(raw) > limit:\n',
     '        if False:\n', VERIFY, ['U32']),
    ("UM15", VF, '        if len(raw) > limit:\n',
     '        if len(raw) >= limit:\n', VERIFY, ['U32']),
    ("UM16", VF, '        if len(d) != len(pairs):\n',
     '        if False:\n', VERIFY, ['U30']),
    ("UM17", VF, 'pkg.get("warrant") == PACKAGE and set(pkg) == MEMBERS',
     'set(pkg) == MEMBERS', VERIFY, ['U29']),
    ("UM18", VF, 'pkg.get("warrant") == PACKAGE and set(pkg) == MEMBERS',
     'pkg.get("warrant") == PACKAGE and set(pkg) >= MEMBERS', VERIFY, ['U29']),
    ("UM19", VF, ' and isinstance(pkg["roots"], list) and all(S.hex64(r) for r in pkg["roots"])):',
     ' and isinstance(pkg["roots"], list) and all(isinstance(r, str) for r in pkg["roots"])):', VERIFY, ['U29']),
    ("UM20", VF, 'S.hex64(h) and C.digest(b) == h for h, b in blobs.items()',
     'S.hex64(h) for h, b in blobs.items()', VERIFY, ['U29']),
    ("UM21", VF, '    if snap.rejected or extra:\n',
     '    if extra:\n', VERIFY, ['U29']),
    ("UM22", VF, '    extra = [x for x in snap.raw if x.count(b"\\n") != 1 and hashlib.sha256(x).hexdigest() not in snap.rejected]\n',
     '    extra = []\n', VERIFY, ['U31']),
    ("UM23", VF, 'x.encode("utf-8", "surrogatepass")',
     'x.encode("utf-8")', VERIFY, ['U30']),
    ("UM24", VF, '        return 3\n',
     '        return 1\n', VERIFY, ['U34']),
    ("UM25", VF, '        print(f"{prog}: {e}", file=sys.stderr)\n        return 2\n',
     '        print(f"{prog}: {e}", file=sys.stderr)\n        return 1\n', VERIFY, ['U33']),
    ("UM26", VF, '    no.append("completeness: the package holds what its sender chose to include: a challenge or a later version it "\n              "left out cannot be seen here")\n',
     '    pass\n', VERIFY, ['U06']),
    ("UM27", VF, '    if ans["asked"]["by"] == "package":\n',
     '    if False:\n', VERIFY, ['U01']),
    ("UM28", VF, 'if x not in view.recs and x not in snap.blobs)',
     'if x not in view.recs)', VERIFY, ['U08']),
    ("UM29", VF, '    if co["unavailable"]:\n',
     '    if False:\n', VERIFY, ['U08']),
    ("UM30", VF, '"rejected": {i: c for i, c in sorted(code.items()) if c != "INVALID"}',
     '"rejected": {i: c for i, c in sorted(code.items())}', VERIFY, ['U18']),
    ("UM31", VF, '    bound = au["signed"] - au["named_keys"]\n',
     '    bound = au["signed"]\n', VERIFY, ['U19']),
    ("UM32", VF, '    for m in au["migrations"]:\n',
     '    for m in []:\n', VERIFY, ['U16']),
    ("UM33", VF, '            view = E.View(snap, trust, profile, as_of)\n',
     '            view = E.View(snap, trust, profile)\n', VERIFY, ['U13']),
    ("UM34", VF, '        if x["actor"] in by and all(x["body"].get(k) == w for k, w in g["match"].items()):\n',
     '        if x["actor"] in by:\n', VERIFY, ['U43']),
    ("UM35", VF, '    if a.config and not (a.trust or a.profile):\n',
     '    if a.config:\n', VERIFY, ['U33']),
    ("UM36", VF, '    if not all(S.hex64(r) for r in a.require):\n',
     '    if False:\n', VERIFY, ['U33']),
    ("UM37", VF, '        if why:\n            raise Usage(why)\n',
     '        if False:\n            raise Usage(why)\n', VERIFY, ['U33']),
    ("UM38", VF, '        except (Refused, R.Invalid) as e:\n            raise Refusal("LIMITS", str(e)) from None\n',
     '        except Refused as e:\n            raise Refusal("LIMITS", str(e)) from None\n', VERIFY, ['U45']),
    ("UM39", VF, '            raw = f.read(a.max_bytes + 1)\n',
     '            raw = f.read(a.max_bytes + 1)\n        open("warrant-verify.log", "w").close()\n', VERIFY, ['U40']),
    ("UM40", VF, '    if not ans["roots"]:\n',
     '    if False:\n', VERIFY, ['U11']),
    ("UM41", VF, '    return {i: G.describe(rep, nodes, i) for i in ids}\n',
     '    return {i: G.describe(rep, nodes, i) for i in ids if i in nodes}\n', VERIFY, ['U15']),
    ("UM42", "warrant_agent/api.py", '    if e.code == "TOO_LARGE":\n',
     '    if False:\n', VERIFY, ['U44']),
    ("UM43", "warrant_agent/api.py", '    return AgentError("BAD_REQUEST", str(e))', '    return AgentError("BAD_REQUEST", e.code)', VERIFY, ['U44']),
    ("UM55", "warrant/verify.py", 'isinstance(b, str) and _BASE64.fullmatch(b)', 'isinstance(b, str) and _BASE64.match(b)', VERIFY, ['U29']),
    ("UM54", "warrant/verify.py", 'isinstance(b, str) and _BASE64.fullmatch(b)', 'isinstance(b, str) and re.match(_BASE64.pattern + "$", b)', VERIFY, ['U29']),
    ("UM44", ONE_SRC, '    if s >= _L:\n        return False\n',
     '    if False:\n        return False\n', VERIFY, ['U42']),
    ("UM45", ONE_SRC, '    return _encode(acc) == signature[:32]\n',
     '    return int.from_bytes(_encode(acc), "little") % _P == int.from_bytes(signature[:32], "little") % _P\n', VERIFY, ['U42']),
    ("UM46", ONE, '            if not ed25519_verify(self._raw, bytes(signature), bytes(data)):\n',
     '            if False:\n', VERIFY, ['U38', 'U41']),
    ("UM47", ONE, '    return 0 if ans["rely"] else 1\n',
     '    return 0\n', VERIFY, ['U37', 'U38']),
    ("UM48", ONE_BUILD, 'hashlib.sha256(src[n].encode()).hexdigest() for n in order}',
     'hashlib.sha256(n.encode()).hexdigest() for n in order}', VERIFY, ['U36']),
    ("UM49", ONE_BUILD, '        order.append(ready[0])\n',
     '        order.append(ready[-1])\n', VERIFY, ['U36']),
    ("UM50", ONE, '    except Exception:                    # absent, or present and unusable: neither is a reason to verify nothing\n',
     '    except ZeroDivisionError:\n', VERIFY, ['U38']),
    # handoff export (warrant_agent/api.py _package_of): what a package carries for the receiver's verdict
    ("UM51", "warrant_agent/api.py", '        return {m for m, listed in maps.items() if listed & unsigned}\n',
     '        return set()\n', VERIFY, ['U16']),
    ("UM52", "warrant_agent/api.py", '        return {m for m, listed in maps.items() if listed & unsigned}\n',
     '        return set(maps)\n', VERIFY, ['U46']),
    ("UM53", "warrant_agent/api.py", '                todo += [v for v in rep["lineages"].get(L, {}).get("versions", []) if v not in got]\n',
     '                pass\n', VERIFY, ['U47']),
    # the board (warrant/board.py): the roadmap as rows of a project board, one way
    ("BM1", "warrant/board.py", "        return CLAIMED                                  # a later version waits",
     '        return BY_STATE.get(lin["state"], OTHER)        # a later version waits', TOOLS, ["BD1"]),
    ("BM2", "warrant/board.py", '    if any(rep["versions"][v]["challenged_by"] for v in at):', "    if False:", TOOLS, ["BD1"]),
    ("BM3", "warrant/board.py", '    if lin["verdict"] == "FORK":\n        return FORKED', '    if False:\n        return FORKED', TOOLS, ["BD1"]),
    ("BM4", "warrant/board.py", 'fence = "`" * max(3, 1 + max((len(r) for r in runs), default=0))', 'fence = "```"', TOOLS, ["BD3"]),
    ("BM5", "warrant/board.py", '.replace("@", "@" + ZWSP)', "", TOOLS, ["BD3"]),
    ("BM6", "warrant/board.py", "m = PR_REF.match(r) if isinstance(r, str) else None", "m = PR_REF.search(r) if isinstance(r, str) else None", TOOLS, ["BD3"]),
    ("BM7", "warrant/board.py", 'diff = [m for m in ("title", "body") if item[m] != row[m]]', "diff = []", TOOLS, ["BD5"]),
    ("BM8", "warrant/board.py", '    for rid in todo["archive"]:\n        call(ARCHIVE', '    for rid in []:\n        call(ARCHIVE', TOOLS, ["BD5"]),
    ("BM9", "warrant/board.py", "return dict(doc, digest=C.doc_id(doc))", 'return dict(doc, digest=C.doc_id(doc["stores"]))', TOOLS, ["BD2"]),
    ("BM11", "warrant/board.py", "        for k in ([kind] if kind else OWNERS):", "        for k in OWNERS[1:]:", TOOLS, ["BD6"]),
    ("BM14", "warrant/board.py", '        diff += [THEIRS] if item["values"].get(THEIRS) else []', "", TOOLS, ["BD5"]),
    ("BM15", "warrant/board.py", '        todo["update"][rid] = [name for name, _, _ in FIELDS] + [THEIRS]', '        todo["update"][rid] = [name for name, _, _ in FIELDS]', TOOLS, ["BD4"]),
    ("BM13", "warrant/board.py", "    if other:                                           # a field of ours' name", "    if False:                                           # a field of ours' name", TOOLS, ["BD7"]),
    ("BM12", "warrant/board.py", "        for k in ([kind] if kind else OWNERS):", "        for k in OWNERS:", TOOLS, ["BD6"]),
    ("BM10", "warrant/board.py", '    if todo["describe"]:', "    if True:", TOOLS, ["BD4"]),
]


def table():
    return {m[0]: [m[1], m[4], m[5]] for m in MUTANTS}


def jobs():
    """How many mutants run at once: MUTANT_JOBS, or the processors up to 4 (each run is one test file, a few hundred
    MB at most; more at once only competes for the same cores)."""
    try:
        n = int(os.environ.get("MUTANT_JOBS", "0"))
    except ValueError:
        n = 0
    return max(1, n or min(os.cpu_count() or 1, 4))


def run(test, cwd, tmp=TMP, extra=None):
    """(exit status, output); a run past the timeout is status None with what it printed (TIMEOUT, never a kill).
    `extra`: the WARRANT_SECTION / WARRANT_STOP / WARRANT_CASE_MAP / WARRANT_LIST_SECTIONS of tests/world.py."""
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([sys.executable, "-B", test], cwd=cwd, capture_output=True, text=True, timeout=900,
                           env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "PYTHONDONTWRITEBYTECODE": "1",
                                "HOME": str(Path.home()), "TMPDIR": str(tmp), **(extra or {})})
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="replace")
    return r.returncode, r.stdout + r.stderr


def failed(out, cases):
    return sorted({c for line in out.splitlines() for c in cases if line.startswith(f"FAIL {c} ") or line == f"FAIL {c}"})


def copy_tree(dest=COPY):
    """The whole tree into `dest`: every tracked file and every untracked one Git does not ignore (the hermetic
    identity: a folder list leaves out what a test reads)."""
    if dest.exists():
        shutil.rmtree(dest)
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, check=True).stdout.decode().split("\0")
    for f in filter(None, files):
        src = ROOT / f
        if src.is_file() or src.is_symlink():
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / f, follow_symlinks=False)


def sections_of(test, cwd, tmp=TMP):
    """The sections of a test file, in order, or [] for one without (it runs whole)."""
    rc, out = run(test, cwd, tmp, {"WARRANT_LIST_SECTIONS": "1"})
    line = next((x for x in out.splitlines() if x.startswith("SECTIONS ")), None)
    return line.split()[1:] if rc == 0 and line else []


def case_map(tests, places):
    """({test: {case: {section, ...}}}, [refusal]): every section of each test file run alone and unmutated (the
    whole file when it has none), each check it prints mapped to the section that printed it. A run that is not green
    is a refusal: the section does not pass alone."""
    runs = [(t, sec) for t in sorted(tests) for sec in (sections_of(t, places[0][0], places[0][1]) or [None])]
    free, out, refused, lock = queue.Queue(), {t: {} for t in tests}, [], threading.Lock()
    for p in places:
        free.put(p)

    def one(job):
        t, sec = job
        copy, tmp = free.get()
        try:
            m = tmp / f"case-map-{os.getpid()}-{threading.get_ident()}.tsv"
            m.unlink(missing_ok=True)
            rc, text = run(t, copy, tmp, {"WARRANT_CASE_MAP": str(m), **({"WARRANT_SECTION": sec} if sec else {})})
            rows = [x.split("\t") for x in m.read_text().splitlines()] if m.exists() and sec else []
            if not sec:          # a file without sections, with a check of its own: the cases it printed (ok/FAIL lines)
                rows = [(x[5:].split()[0], "main") for x in text.splitlines() if x[:5] in ("ok   ", "FAIL ") and x[5:].split()]
            m.unlink(missing_ok=True)
        finally:
            free.put((copy, tmp))
        with lock:
            if rc != 0:                      # red, or past the timeout (None): no case it printed may be credited
                refused.append(f"{t} {sec or '(whole)'}{' TIMEOUT' if rc is None else ''}\n{text[-1500:]}")
            for case, where in rows:
                out[t].setdefault(case, set()).add("main" if not sec or where == "main" else where)
    with ThreadPoolExecutor(len(places)) as pool:
        list(pool.map(one, runs))
    return out, refused


def home_sections(cases_of, cases):
    """The sections to run for `cases` ({case: {section}} of one test file), sorted; ["main"] means the whole file;
    None when a case is in no section (NO_SECTION: never a full run that might find it)."""
    homes = [cases_of.get(c) for c in cases]
    if not cases or not all(homes):
        return None
    secs = set().union(*homes)
    return ["main"] if "main" in secs else sorted(secs)


def combinations(rows, ids, where, places):
    """[refusal]: each set of two or more sections some mutant of `ids` runs together, run so, unmutated. Each section
    passing alone does not make them pass together: one may leave the state another reads (Codex on #391 at 52e05290:
    a and c, with b between them clearing it, failed together and credited a kill to a mutant of an unused file)."""
    combos = sorted({(rows[i][4], tuple(s)) for i in ids
                     for s in [home_sections(where.get(rows[i][4], {}), rows[i][5])] if s and len(s) > 1})
    copy, tmp = places[0]
    out = []
    for test, secs in combos:
        rc, text = run(test, copy, tmp, {"WARRANT_SECTION": ",".join(secs)})
        if rc != 0:
            out.append(f"{test} {','.join(secs)}{' TIMEOUT' if rc is None else ''}\n{text[-1500:]}")
    return out


# --whole: every mutant runs its whole test file, as before sections (no map, no stop). The default runs sections only,
# so a mutant killed alone is not also run against the whole file; a later section's state hiding the kill in a whole
# run is the residual (docs/REPOSITORY.md). --whole is for when time does not press.
WHOLE = False


def shard(ids, k, n):
    return [i for j, i in enumerate(ids) if j % n == k - 1]


def run_mutants(ids):
    """Each mutant in its own copy of the tree, `jobs()` at once: a worker owns a copy and a TMPDIR while it mutates,
    runs and restores, so no run sees another's mutation. Rows come back in the order of `ids`."""
    workers = max(1, min(jobs(), len(ids)))
    places = [(COPY, TMP)] + [(COPY.with_name(f"mutants-{w}"), TMP.with_name(f"mutants-tmp-{w}")) for w in range(1, workers)]
    for d, t in places:
        copy_tree(d)
        shutil.rmtree(t, ignore_errors=True)     # a killed run ends at os._exit: its temporary directories stay behind
        t.mkdir(parents=True, exist_ok=True)
    rows = {m[0]: m for m in MUTANTS}
    if WHOLE:
        where, refused = {}, []
        for test in sorted({rows[i][4] for i in ids}):
            rc, out = run(test, COPY)
            if rc != 0:
                refused.append(f"{test} (whole)\n{out[-1500:]}")
    else:
        where, refused = case_map({rows[i][4] for i in ids}, places)
        refused += combinations(rows, ids, where, places)
    if refused:
        print("BASELINE_RED (a section, a set of sections a mutant runs, or a file does not pass unmutated)\n"
              + "\n".join(refused))
        return None
    free, lock = queue.Queue(), threading.Lock()
    for p in places:
        free.put(p)

    def one(i):
        _, path, old, new, test, cases = rows[i]
        pairs = old if isinstance(old, list) else [(old, new)]
        copy, tmp = free.get()
        try:
            f = copy / path
            src = f.read_text()
            stale = [o for o, _ in pairs if src.count(o) != 1]
            secs = ["main"] if WHOLE else home_sections(where.get(test, {}), cases)
            if stale:
                r = {"id": i, "outcome": "STALE", "detail": f"a find text does not occur once in {path}: {stale[0][:60]!r}"}
            elif secs is None:
                r = {"id": i, "outcome": "NO_SECTION", "detail": f"no clean run of {test} printed the case(s) "
                     f"{[c for c in cases if c not in where.get(test, {})]}"}
            else:
                mutated = src
                for o, n in pairs:
                    mutated = mutated.replace(o, n)
                f.write_text(mutated)
                env = ({} if WHOLE else {"WARRANT_STOP": ",".join(cases)}) | ({} if secs == ["main"] else {"WARRANT_SECTION": ",".join(secs)})
                try:
                    rc, out = run(test, copy, tmp, env)
                finally:
                    f.write_text(src)
                hit = failed(out, cases) if rc is not None else []
                r = {"id": i, "outcome": "KILLED" if hit else "SURVIVED" if rc is not None else "TIMEOUT", "failed": hit,
                     "rc": rc, "sections": secs, "detail": "" if hit else out[-600:]}
        finally:
            free.put((copy, tmp))
        with lock:
            print(f"{i} {r['outcome']} {path} by {test} {cases}" + (f": {r['detail'][-300:]}" if r["outcome"] != "KILLED" else ""), flush=True)
        return r

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(one, ids))


def definition():
    return hashlib.sha256(json.dumps(MUTANTS, sort_keys=True).encode()).hexdigest()


def duplicates():
    """Ids that name more than one row: a merge that kept both sides of a row (tests/mutants.py merges as union,
    .gitattributes) is refused here, never run twice under one id."""
    ids = [m[0] for m in MUTANTS]
    return sorted({i for i in ids if ids.count(i) > 1})


def main(argv):
    twice = duplicates()
    if twice:
        print(f"DUPLICATE mutant ids {twice}: one row each", file=sys.stderr)
        return 2
    if argv[:1] == ["--list"]:
        print(json.dumps(table(), indent=1, sort_keys=True))
        return 0
    if argv[:1] == ["--merge"]:
        out, parts = argv[1], argv[2:]
        seen, rows = {}, []
        for p in parts:
            doc = json.loads(Path(p).read_text())
            if doc["definition"] != definition():
                print(f"MERGE_REFUSED {p} is a matrix of another mutant list")
                return 2
            for r in doc["rows"]:
                seen[r["id"]] = seen.get(r["id"], 0) + 1
                rows.append(r)
        want = [m[0] for m in MUTANTS]
        bad = sorted(set(want) - set(seen)) + sorted(i for i, n in seen.items() if n != 1 or i not in want)
        notkilled = sorted(r["id"] for r in rows if r["outcome"] != "KILLED" or not r.get("failed"))
        Path(out).write_text(json.dumps({"definition": definition(), "rows": sorted(rows, key=lambda r: r["id"])}, indent=1))
        print(f"merged {len(rows)} rows of {len(want)} mutants; missing or repeated: {bad or 'none'}; not killed: {notkilled or 'none'}")
        return 1 if bad or notkilled else 0
    global WHOLE
    matrix, k, n, ids = None, 1, 1, []
    it = iter(argv)
    for a in it:
        if a == "--whole":
            WHOLE = True
        elif a == "--matrix":
            matrix = next(it)
        elif a == "--shard":
            k, n = map(int, next(it).split("/"))
        else:
            ids.append(a)
    known = [m[0] for m in MUTANTS]
    unknown = [i for i in ids if i not in known]
    if unknown:
        print(f"UNKNOWN_MUTANT {unknown}")
        return 2
    ids = shard(ids or known, k, n)
    rows = run_mutants(ids)
    if rows is None:
        return 2
    if matrix:
        Path(matrix).write_text(json.dumps({"definition": definition(), "rows": rows}, indent=1))
    survived = [r["id"] for r in rows if r["outcome"] != "KILLED"]
    print(f"{len(rows) - len(survived)} of {len(rows)} killed" + (f"; not killed: {survived}" if survived else ""))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
