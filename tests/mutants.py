#!/usr/bin/env python3
"""Mutants: each is one exact find/replace (or a list of them) in one file and the cases it must fail. A mutant is KILLED only
when its run prints `FAIL <case>` for one of those cases: an import error, a crash before the case, or a
FAIL of another case proves nothing. The run happens in a copy of the tree under build/mutants/, one
mutant at a time with no bytecode cache, the file restored after each. Before any mutant, each targeted
test file runs once unmutated in the same copy and must pass (BASELINE_RED refuses the whole run).

    python3 tests/mutants.py [IDS ...] [--shard K/N] [--matrix OUT.json]
    python3 tests/mutants.py --merge OUT.json PART.json ...     # the union is every id once, each KILLED
    python3 tests/mutants.py --list                             # {id: [file, test, cases]} as JSON

The claims (warrant/claims.py) cite these ids; check refuses a claim citing an id that is not here, or one
whose cases are not among the claim's witnesses."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "build" / "mutants"
TMP = ROOT / "build" / "mutants-tmp"          # outside the copy: fixtures' homes and seeds lie outside its repository
CORE, AGENT, GATE, TOOLS, PILOT, WAKER = ("tests/core_test.py", "tests/agent_test.py", "tests/gate_test.py",
                                          "tests/tools_test.py", "tests/pilot_test.py", "integrations/codex-plugin/test_plugin.py")
E, S, RC = "warrant/engine.py", "warrant/store.py", "warrant/records.py"
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
    ("V3", E, 'return any(actor in self.profile["roles"].get(x, []) for x in roles)', "return True", CORE, ["C1", "S1"]),
    ("V4", E, 'out.update((self.recs[cur]["guard"] or {}).get("requires", []))', "pass", CORE, ["G1"]),
    ("V5", E, 'if self.recs[a]["actor"] != r["actor"] and self.holds', "if self.holds", CORE, ["L2"]),
    ("V9", E, 'if need is not None and _weaker(r["guard"], need):', "if False:", CORE, ["L9"]),
    ("V11", E, 'elif any(on == x and v == "reproduces" for on, v, _ in replays):', "elif False:", CORE, ["C1"]),
    ("V15", E, 'if r["body"].get("state") in self.schema_of(v).get("closed", []):       # with',
     'if g is not None and r["body"].get("state") in self.schema_of(v).get("closed", []):       # with', CORE, ["G3"]),
    ("V20", E, 'stands = x in lin["path"] and (eff is None or lin["path"].index(eff) <= lin["path"].index(x))',
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
    ("V37", "warrant/cli.py", 'out = {"canonical": snap.canonical,', 'out = {"canonical": True,', CORE, ["T15"]),
    ("V27", E, "        if any(R.verifies(i, s, k) for s in sigs for k in keys):", "        if sigs:", CORE, ["T6"]),
    ("V28", S, "        if bad:\n            raise Refused", "        if False:\n            raise Refused", CORE, ["T12"]),
    # §9 migration
    ("V10", E, "if by is not None:", "if True:", CORE, ["M1"]),
    ("V12", E, 'elif any(e["sig"] is None for e in envs):', "elif not sigs:", CORE, ["M4"]),
    ("V29", E, '            if not (r["kind"] == "attest" and r["schema"] == R.MIGRATION and self.basis[i] == "SIGNED"\n                    and self.holds(r["actor"], "migrator")):',
     '            if not (r["kind"] == "attest" and r["schema"] == R.MIGRATION and self.basis[i] == "SIGNED"):', CORE, ["M3"]),
    # the agent interface
    ("A1", "warrant_agent/api.py", '    need(r["actor"] == actor, "NOT_PERMITTED"', '    need(True, "NOT_PERMITTED"', AGENT, ["A04"]),
    ("A2", "warrant_agent/api.py", 'expect_head=r["prev"] or ""', "expect_head=None", AGENT, ["A05"]),
    ("A3", "warrant_agent/api.py", '    need(not why, "INVALID_RECORD", "; ".join(why), problems=why)\n    return {"record"',
     '    return {"record"', AGENT, ["A06", "A07"]),
    ("A4", "warrant_agent/api.py", '    need(key.public in trust["keys"].get(actor, []), "SIGNER_NOT_TRUSTED",', '    need(True, "SIGNER_NOT_TRUSTED",', AGENT, ["A08"]),
    ("A5", "warrant_agent/config.py", '        need(size <= self.limits["store_bytes"], "RESOURCE_LIMIT",', '        need(True, "RESOURCE_LIMIT",', AGENT, ["A09"]),
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
    ('P19', 'integrations/codex-plugin/waker/waker.py', 'return next((r for r in self.reviewers if r["actor"] != author), None)', 'return self.reviewers[0]', WAKER, ['W15', 'W16']),
    ("P20", "integrations/codex-plugin/waker/waker.py", "        if named:\n", "        if False:\n", WAKER, ["W17"]),
    ('P21', 'integrations/codex-plugin/waker/waker.py', 'if rev["agent"] == "claude":', 'if False:', WAKER, ['W15']),
    ("P22", "integrations/codex-plugin/waker/waker.py", "check=False, timeout=4 * 3600, cwd=str(path))", "check=False, timeout=4 * 3600)", WAKER, ["W15"]),
    ('P23', 'integrations/codex-plugin/waker/waker.py', '    if len({r["actor"] for r in rs}) != len(rs):', '    if False:', WAKER, ['W18']),
    ('P24', 'integrations/codex-plugin/waker/waker.py', 'and ACTOR_ID.match(r["actor"]) and r["agent"] in AGENTS', 'and ACTOR_ID.match(r["actor"])', WAKER, ['W18']),
    ('P25', 'integrations/codex-plugin/waker/waker.py', 'and (r.get("seed") is None or (isinstance(r["seed"], str) and Path(r["seed"]).is_absolute()))', '', WAKER, ['W18']),
    ('P26', 'integrations/codex-plugin/waker/waker.py', '        why = reviewers_problem(e.get("reviewers", list(DEFAULT_REVIEWERS)))', '        why = None', WAKER, ['W18']),
    ("P27", "integrations/codex-plugin/waker/waker.py", "stdout=out if result else log,", "stdout=log,", WAKER, ["W15"]),
    ("P18", "integrations/codex-plugin/skills/warrant-review/scripts/warrant-mcp-call", "    except Exception as e:", "    except ZeroDivisionError as e:",
     WAKER, ["C15"]),
    ("A12", "warrant_agent/config.py", '                   "operations": [o for o in doc.get("operations", OPERATIONS) if o in OPERATIONS] + ["graph"]}',
     '                   "operations": [o for o in doc.get("operations", OPERATIONS) if o in OPERATIONS] + ["graph"], "signer": None}', AGENT, ["A10"]),
    # the merge gate (warrant/gate.py)
    ("G1", "warrant/gate.py", "    if b.gate[\"hold_label\"] in pr[\"labels\"]:", "    if False:", GATE, ["E02"]),
    ("G2", "warrant/gate.py", "        if before - after:\n", "        if False:\n", GATE, ["E06"]),
    ("G23", "warrant/gate.py", "    extra, lines, blobs = tail(root, caught_up(root, x, head, b.commit), head)",
     "    extra, lines, blobs = tail(root, x, head)", GATE, ["E29"]),
    ("G24", "warrant/gate.py", "    except (subprocess.CalledProcessError, IndexError):\n        return x\n\n\ndef owner_paths",
     "    except IndexError:\n        return x\n\n\ndef owner_paths", GATE, ["E31"]),
    ("G3", "warrant/gate.py", "        else:\n            extra.append((path, f\"{status} {old_mode}->{new_mode}\"))", "", GATE, ["E05"]),
    ("G4", "warrant/gate.py", "    if loose:\n        sh.append((\"TAIL_BLOB_UNCITED\"", "    if False:\n        sh.append((\"TAIL_BLOB_UNCITED\"", GATE, ["E07"]),
    ("G5", "warrant/gate.py", "    if stray:\n", "    if False:\n", GATE, ["E08"]),
    ("G6", "warrant/gate.py", '            (rec["kind"] in ("attest", "challenge") and rec["actor"] in b.holders("pr/acceptor"))',
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
    ("G20", "warrant/gate.py", '    if not str(pr.get("branch") or "").startswith(VERDICT_BRANCH):', "    if False:", GATE, ["E23"]),
    ("G22", E, "                    self.pending.append(i)          # waits",
     '                    self.problem("SCHEMA_NOT_COUNTED", i, "short of its quorum")\n                    self.pending.append(i)          # waits', GATE, ["E28"]),
    ("G21", "warrant/gate.py", '        if g["guard"] == "PENDING" and g["short"] and not g["open"] and roles & set(g["roles"]) \\',
     '        if g["guard"] == "PENDING" and g["short"] and roles & set(g["roles"]) \\', GATE, ["E24"]),
    # the review loop's commands (warrant/claims.py, review.py, repo.py)
    ("T1", "warrant/claims.py", "        if b[\"text\"] not in spec:", "        if False:", TOOLS, ["C02"]),
    ("T2", "warrant/claims.py", "        if c not in printed.get(f, set()):", "        if False:", TOOLS, ["C03"]),
    ("T3", "warrant/claims.py", "        if m not in known:", "        if False:", TOOLS, ["C04"]),
    ("T4", "warrant/claims.py", '        if b["source"] != source:', "        if False:", TOOLS, ["C05"]),
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
    ("T33", "warrant/cli.py", '            "frontier": G.frontier(rep, profile, a.actor) if a.actor else None}', '            "frontier": None}',
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
    # the review waker's reading of the store (integrations/codex-plugin/waker/waker.py)
    ("P1", "integrations/codex-plugin/waker/waker.py", "    if set(got) != set(filed):", "    if False:", WAKER, ["W2"]),
    ("P2", "integrations/codex-plugin/waker/waker.py",
     '        if not (rec and rec.get("kind") == "attest" and rec.get("actor") == actor and b.get("verdict") in REPLAY_VERDICTS):',
     "        if not rec:", WAKER, ["W7"]),
    ("P3", "integrations/codex-plugin/waker/waker.py",
     '        if rec["actor"] != actor or rec["kind"] not in VERDICTS or not binds(rec, {"closure": req["closure"]}):',
     "        if False:", WAKER, ["W3"]),
    ("P4", "integrations/codex-plugin/waker/waker.py", "    if set(got_lines) != set(lines):", "    if False:", WAKER, ["W4"]),
    ("P5", "integrations/codex-plugin/waker/waker.py",
     '        if not (path.startswith(BLOBS) and HEX.match(path[len(BLOBS):]) and status == "A" and new_mode == REGULAR):',
     '        if not (path.startswith(BLOBS) and HEX.match(path[len(BLOBS):]) and status == "A"):', WAKER, ["W5"]),
    ("P7", "integrations/codex-plugin/waker/waker.py", "not (isinstance(actor, str) and CHECKER.match(actor))",
     "not isinstance(actor, str)", WAKER, ["W8"]),
    ("P6", "integrations/codex-plugin/waker/waker.py",
     '    if bad or len(recs) != len(lines) or any(b != "SIGNED" for b in basis.values()):', "    if False:", WAKER, ["W3"]),
    # the waker's repositories (W-5)
    ("P8", "integrations/codex-plugin/waker/waker.py", "        if named != self.repository:", "        if False:", WAKER, ["W10"]),
    ("P9", "integrations/codex-plugin/waker/waker.py", "{w.repository}#{a['pr']} is due", "s0fractal/warrant#{a['pr']} is due",
     WAKER, ["W9"]),
    ("P10", "integrations/codex-plugin/waker/waker.py", "; base {w.branch} M {a['base']}.", "; base master M {a['base']}.", WAKER, ["W9"]),
    ("P11", "integrations/codex-plugin/waker/waker.py", '        if len({e[k] if k == "repository" else os.path.realpath(e[k]) for e in entries}) != len(entries):', "        if False:",
     WAKER, ["W12"]),
    ("P12", "integrations/codex-plugin/waker/waker.py", "        for e in entries:", "        for e in entries[:1]:", WAKER, ["W9"]),
    ("P14", "integrations/codex-plugin/waker/waker.py", 'e[k] if k == "repository" else os.path.realpath(e[k])', "e[k]",
     WAKER, ["W13"]),
    ("P15", "integrations/codex-plugin/waker/waker.py", "        verdicts = w.forge.verdicts()", "        return \"held\"", WAKER, ["W14"]),
    ("P16", "integrations/codex-plugin/waker/waker.py", 'startswith(VERDICT_BRANCH) and x.get("isCrossRepository") is False]',
     'startswith(VERDICT_BRANCH)]', WAKER, ["W14"]),
    ("P17", "integrations/codex-plugin/waker/waker.py", '                if str(x.get("headRefName") or "").startswith(VERDICT_BRANCH) and',
     "                if", WAKER, ["W14"]),
    ("P13", "integrations/codex-plugin/install.py", "    if path.exists():", "    if False:", WAKER, ["C14"]),
]

# The G9 pilot (warrant_pilot/pilot.py, tools/pilot.py): Warrant 2's ids and replacements, kept so that the pilot
# contract (tools/pilot-contract.json, docs/PILOT.md) cites the same mutants.
PILOT_MUTANTS = [
    ('M568', 'warrant_pilot/pilot.py', '            if C.digest(data) != h:\n', '            if False:\n', PILOT, ['A2']),
    ('M569', 'warrant_pilot/pilot.py', '                raise _Stop("DIGEST_MISMATCH", address,', '                continue\n                raise _Stop("DIGEST_MISMATCH", address,', PILOT, ['A2']),
    ('M570', 'warrant_pilot/pilot.py', '        if value is None:\n            raise _Stop("KIND_MISMATCH"', '        if False:\n            raise _Stop("KIND_MISMATCH"', PILOT, ['A3', 'A5']),
    ('M571', 'warrant_pilot/pilot.py', '    if not (sep and S.hex64(h)):', '    if not (sep and len(h) == 64):', PILOT, ['A4', 'D4']),
    ('M572', 'warrant_pilot/pilot.py', 'os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent', 'os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent', PILOT, ['A6', 'A10']),
    ('M573', 'warrant_pilot/pilot.py', '        self.kinds = {k: KINDS[k] for k in names}', '        self.kinds = dict(KINDS)', PILOT, ['A7']),
    ('M574', 'warrant_pilot/pilot.py', '        return verify(res) if res["result"] == RESOLVED else res', '        return verify(res)', PILOT, ['D3']),
    ('M575', 'warrant_pilot/pilot.py', '                if dep in on_path:\n', '                if False:\n', PILOT, ['D5']),
    ('M576', 'warrant_pilot/pilot.py', '                if dep in objects:\n', '                if dep in objects:\n                    used["edges"] -= 1\n', PILOT, ['D6']),
    ('M577', 'warrant_pilot/pilot.py', '                    L.admit(lim, "pilot_depth", len(path) + height[dep])\n', '', PILOT, ['D7', 'D11']),
    ('M578', 'warrant_pilot/pilot.py', '            admit(st.st_size)\n', '', PILOT, ['D9']),
    ('M579', 'warrant_pilot/pilot.py', '        L.admit(lim, "pilot_objects", len(objects) + 1)\n', '', PILOT, ['D6']),
    ('M580', 'warrant_pilot/pilot.py', ',\n            f"sigma-checkpoint:{doc[\'checkpoint\']}", f"sigma-state:{doc[\'state\']}"]', ']', PILOT, ['D1', 'D2']),
    ('M581', 'warrant_pilot/pilot.py', '    why = P.receipt_problem(doc)\n    if why:\n        raise ValueError(why)\n', '', PILOT, ['D8', 'D3']),
    ('M582', 'warrant_pilot/pilot.py', '    if set(doc) != {"schema", "requires"}:', '    if False:', PILOT, ['A8']),
    ('M583', 'warrant_pilot/pilot.py', '"MISSING": INCONCLUSIVE', '"MISSING": REFUSED', PILOT, ['D2', 'A5', 'A6']),
    ('M584', 'warrant_pilot/pilot.py', '    if v["provider"] != P.identity_of_files(mods):', '    if False:', PILOT, ['F3']),
    ('M585', 'warrant_pilot/pilot.py', 'set(doc) == PROFILE_FIELDS and', 'PROFILE_FIELDS <= set(doc) and', PILOT, ['F3']),
    ('M586', 'warrant_pilot/pilot.py', 'all(S.hex64(x) for x in mods.values())', 'all(isinstance(x, str) for x in mods.values())', PILOT, ['F3']),
    ('M587', 'warrant_pilot/pilot.py', '\n            and v == sorted(set(v)))', ')', PILOT, ['F3']),
    ('M588', 'warrant_pilot/pilot.py', '    return C.doc_id(doc)\n', '    return C.doc_id({k: v for k, v in doc.items() if k != "axioms"})\n', PILOT, ['F1', 'F2']),
    ('M589', 'warrant_pilot/pilot.py', 'set(v) == VERIFIER_FIELDS', 'VERIFIER_FIELDS <= set(v)', PILOT, ['F3']),
    ('M591', 'warrant_pilot/pilot.py', '        return (name[:2], name[2:])', '        return (name[:2], name)', PILOT, ['A1']),
    ('M592', 'warrant_pilot/pilot.py', '                if dep in objects:\n', '                if False:\n', PILOT, ['D1']),
    ('M593', 'warrant_pilot/pilot.py', '            doc = C.loads(data)', '            doc = C.loads(C.canon(C.json.loads(data)))', PILOT, ['F4', 'A3']),
    ('M600', 'warrant_pilot/pilot.py', '"UNKNOWN_KIND": INCONCLUSIVE', '"UNKNOWN_KIND": REFUSED', PILOT, ['A7', 'D4']),
    ('M601', 'warrant_pilot/pilot.py', '"assumptions": sorted(set(assumptions))}', '"assumptions": sorted(set(assumptions))[:1]}', PILOT, ['F1']),
    ('M602', 'warrant_pilot/pilot.py', 'os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd', 'os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd', PILOT, ['A9']),
    ('M604', 'warrant_pilot/pilot.py', '                    admit(len(data))\n', '', PILOT, ['D9']),
    ('M605', 'warrant_pilot/pilot.py', '                    more = f.read(1 << 16)', '                    more = b""', PILOT, ['D10']),
    ('M606', 'warrant_pilot/pilot.py', '        except ValueError:\n            return None', '        except C.NotCanonical:\n            return None', PILOT, ['A11']),
    ('M607', 'warrant_pilot/pilot.py', '        if limits is not None and not isinstance(limits, dict):', '        if False:', PILOT, ['A12']),
    ('M608', 'warrant_pilot/pilot.py', 'isinstance(s["layout"], str) and s["layout"] in LAYOUTS', 's["layout"] in LAYOUTS', PILOT, ['A12']),
    ('M594', 'tools/pilot.py', 'out.append(("UNKNOWN_CASE", f"{r[\'id\']} cites {t}, not a case of {TEST}"))', 'pass', PILOT, ['K2']),
    ('M595', 'tools/pilot.py', '        elif m[4] != TEST or not set(m[5]) & set(r["tests"]):', '        elif False:', PILOT, ['K2']),
    ('M596', 'tools/pilot.py', '    if "deferred" in r and r["deferred"] not in cards:', '    if False:', PILOT, ['K2']),
    ('M597', 'tools/pilot.py', '    if view != render(contract, cards):', '    if False:', PILOT, ['K2']),
    ('M598', 'tools/pilot.py', 'f"deferred to {row[\'deferred\']}, duty `{str(cards.get(row[\'deferred\']))[:12]}`"', 'f"deferred to {row[\'deferred\']}"', PILOT, ['K1']),
    ('M643', 'warrant_pilot/pilot.py', [('                    L.admit(lim, "pilot_depth", len(path) + height[dep])\n', ''), ('            height[address] = max((1 + height.get(d, 0) for d in deps), default=0)\n', '            height[address] = max((1 + height.get(d, 0) for d in deps), default=0)\n            L.admit(lim, "pilot_depth", len(path) - 1 + height[address])\n')], None, PILOT, ['D11']),
    ('M644', 'warrant_pilot/pilot.py', '        if "\\x00" in str(self.root):', '        if False:', PILOT, ['A13']),
]
MUTANTS += PILOT_MUTANTS


def table():
    return {m[0]: [m[1], m[4], m[5]] for m in MUTANTS}


def run(test, cwd):
    """(exit status, output); a run past the timeout is status None with what it printed (TIMEOUT, never a kill)."""
    try:
        r = subprocess.run([sys.executable, "-B", test], cwd=cwd, capture_output=True, text=True, timeout=900,
                           env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "PYTHONDONTWRITEBYTECODE": "1",
                                "HOME": str(Path.home()), "TMPDIR": str(TMP)})
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="replace")
    return r.returncode, r.stdout + r.stderr


def failed(out, cases):
    return sorted({c for line in out.splitlines() for c in cases if line.startswith(f"FAIL {c} ") or line == f"FAIL {c}"})


def copy_tree():
    """The whole tree into COPY: every tracked file and every untracked one Git does not ignore (the hermetic
    identity: a folder list leaves out what a test reads)."""
    if COPY.exists():
        shutil.rmtree(COPY)
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, check=True).stdout.decode().split("\0")
    for f in filter(None, files):
        src = ROOT / f
        if src.is_file() or src.is_symlink():
            (COPY / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, COPY / f, follow_symlinks=False)


def shard(ids, k, n):
    return [i for j, i in enumerate(ids) if j % n == k - 1]


def run_mutants(ids):
    copy_tree()
    TMP.mkdir(parents=True, exist_ok=True)
    rows = {m[0]: m for m in MUTANTS}
    for test in sorted({rows[i][4] for i in ids}):
        rc, out = run(test, COPY)
        if rc:
            print(f"BASELINE_RED {test}\n{out[-2000:]}")
            return None
    out_rows = []
    for i in ids:
        _, path, old, new, test, cases = rows[i]
        pairs = old if isinstance(old, list) else [(old, new)]
        f = COPY / path
        src = f.read_text()
        stale = [o for o, _ in pairs if src.count(o) != 1]
        if stale:
            out_rows.append({"id": i, "outcome": "STALE", "detail": f"a find text does not occur once in {path}: {stale[0][:60]!r}"})
        else:
            mutated = src
            for o, n in pairs:
                mutated = mutated.replace(o, n)
            f.write_text(mutated)
            try:
                rc, out = run(test, COPY)
            finally:
                f.write_text(src)
            hit = failed(out, cases) if rc is not None else []
            out_rows.append({"id": i, "outcome": "KILLED" if hit else "SURVIVED" if rc is not None else "TIMEOUT", "failed": hit, "rc": rc,
                             "detail": "" if hit else out[-600:]})
        r = out_rows[-1]
        print(f"{i} {r['outcome']} {path} by {test} {cases}" + (f": {r['detail'][-300:]}" if r["outcome"] != "KILLED" else ""), flush=True)
    return out_rows


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
    matrix, k, n, ids = None, 1, 1, []
    it = iter(argv)
    for a in it:
        if a == "--matrix":
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
