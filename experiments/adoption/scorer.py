#!/usr/bin/env python3
"""The frozen scorer (PLAN.md): one run's transcript (claude -p stream-json) and its fixture summary -> a score.

    python3 scorer.py RUN_DIR             # reads RUN_DIR/fixture.json and RUN_DIR/transcript.jsonl, prints the score
    python3 scorer.py --selftest [--kit KIT_BIN]

Per run: answered, success, wrong_credit (the task rules below), used_kit, kit_calls, kit_errors, read_notes,
read_store, ran_tests, cost_usd, turns, duration_s, and the answer as read.

Answer lines are read from the final message only (the result event's text; else the last assistant text), each
line stripped of surrounding white space and matched whole (`fullmatch`), the last occurrence of each label winning.
A line in any other shape (bold, a trailing word, two answers on one line) is not an answer.

    T1  TOTAL: <number>  and  RELY: YES|NO
        success = RELY NO, or RELY YES with the correct total; wrong_credit = RELY YES with the broken parser's total.
    T2  SECOND_PASS_SAFE: YES|NO
        success = NO; wrong_credit = YES.
    T3  CLAIM idempotent|rerun|rollback: RELY|DO NOT RELY (all three)
        success = RELY, DO NOT RELY, DO NOT RELY; wrong_credit = RELY for rerun or for rollback.
    success and wrong_credit are 0 unless every answer line of the task is present (answered = 1).

used_kit: a Bash command one of whose simple commands has argv[0] with basename `warrant` or `warrant-*`, or is a
python interpreter run with `-m warrant…`/`-m warrant_agent…`; or any `mcp__warrant__*` tool call. A command that
only names the word (grep warrant, cat .warrant/records.jsonl, echo warrant) is not. kit_errors: kit calls whose
result is marked is_error (`warrant drift` exits 1 when a claim is stale, so it counts here: descriptive only).
read_notes: a Read of a file named NOTES.md, or a Bash/Grep/Glob call naming NOTES.md. read_store: the same for a
path under .warrant/. ran_tests: a simple command running pytest, `python -m unittest|pytest`, or a python
interpreter on a test file (test_*.py or a path under tests/).
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

LINES = {
    "T1": {"TOTAL": re.compile(r"TOTAL:[ \t]*\$?[ \t]*(-?[0-9][0-9,]*(?:\.[0-9]+)?)"),
           "RELY": re.compile(r"RELY:[ \t]*(YES|NO)")},
    "T2": {"SECOND_PASS_SAFE": re.compile(r"SECOND_PASS_SAFE:[ \t]*(YES|NO)")},
    "T3": {c: re.compile(r"CLAIM[ \t]+" + c + r":[ \t]*(RELY|DO NOT RELY)") for c in ("idempotent", "rerun", "rollback")},
}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;", "{", "}", "!"}
WRAPPERS = {"env", "time", "command", "exec", "nohup", "sudo", "builtin", "nice"}
PYTHON = re.compile(r"python(?:[0-9.]*)\Z")


def events(path):
    out = []
    for line in Path(path).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def final_text(evs):
    for e in reversed(evs):
        if e.get("type") == "result" and isinstance(e.get("result"), str):
            return e["result"]
    for e in reversed(evs):
        if e.get("type") == "assistant":
            texts = [c.get("text", "") for c in e.get("message", {}).get("content", []) if c.get("type") == "text"]
            if texts:
                return "\n".join(texts)
    return ""


def answers(task, text):
    """{label: value} of the task's answer lines in `text`, the last occurrence of each, whole lines only."""
    got = {}
    for line in text.splitlines():
        s = line.strip()
        for label, rx in LINES[task].items():
            m = rx.fullmatch(s)
            if m:
                got[label] = m.group(1)
    return got


def simple_commands(cmd):
    """The argv of each simple command in a shell command line, roughly as the shell splits them: separators,
    newlines, subshells and command substitutions start a new command; leading VAR=value and wrappers are skipped."""
    text = cmd.replace("$(", " ; ( ").replace("`", " ; ").replace("\n", " ; ")
    try:
        lx = shlex.shlex(text, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        toks = list(lx)
    except ValueError:
        toks = text.split()
    out, cur = [], []
    for t in toks:
        if t in SEPARATORS or (t and set(t) <= set(";&|()")):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    res = []
    for argv in out:
        while argv and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]) or os.path.basename(argv[0]) in WRAPPERS
                        or os.path.basename(argv[0]) == "timeout"):
            argv = argv[2:] if os.path.basename(argv[0]) == "timeout" else argv[1:]     # timeout DURATION CMD
        if argv:
            res.append(argv)
    return res


def _module(argv):
    """The module a python argv runs with -m, or None."""
    for i, a in enumerate(argv[1:], 1):
        if a == "-m" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("-m") and len(a) > 2:
            return a[2:]
        if not a.startswith("-"):
            return None
    return None


def is_kit(argv):
    base = os.path.basename(argv[0])
    if base == "warrant" or base.startswith("warrant-"):
        return True
    if PYTHON.fullmatch(base):
        m = _module(argv)
        return bool(m) and (m == "warrant" or m.startswith(("warrant.", "warrant_agent")))
    return False


def is_test_run(argv):
    base = os.path.basename(argv[0])
    if base in ("pytest", "py.test"):
        return True
    if PYTHON.fullmatch(base):
        m = _module(argv)
        if m in ("unittest", "pytest") or (m or "").startswith("unittest"):
            return True
        if m is None:
            script = next((a for a in argv[1:] if not a.startswith("-")), "")
            return bool(re.search(r"(^|/)test_[^/]*\.py\Z", script) or re.search(r"(^|/)tests/", script))
    return False


def calls(evs):
    """[(tool name, input, result is_error)] in order."""
    results = {}
    for e in evs:
        if e.get("type") == "user":
            content = e.get("message", {}).get("content", [])
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    results[c.get("tool_use_id")] = bool(c.get("is_error"))
    out = []
    for e in evs:
        if e.get("type") == "assistant":
            for c in e.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    out.append((c.get("name", ""), c.get("input") or {}, results.get(c.get("id"), False)))
    return out


def _names(name, inp, needle):
    """Whether a Read/Bash/Grep/Glob call names a path matching `needle` (a compiled pattern)."""
    if name == "Read":
        return bool(needle.search(str(inp.get("file_path", ""))))
    if name == "Bash":
        return bool(needle.search(str(inp.get("command", ""))))
    if name in ("Grep", "Glob"):
        return any(needle.search(str(inp.get(k, ""))) for k in ("path", "pattern", "glob"))
    return False


NOTES_RX = re.compile(r"(^|[/\s'\"=])NOTES\.md\b")
STORE_RX = re.compile(r"(^|[/\s'\"=])\.warrant(/|\b)")


def score(task, arm, evs, expected):
    final = final_text(evs)
    got = answers(task, final)
    answered = all(k in got for k in LINES[task])
    success = wrong = False
    if answered and task == "T1":
        total = float(got["TOTAL"].replace(",", ""))
        right = abs(total - float(expected["correct_total"])) < 0.005
        broken = abs(total - float(expected["broken_total"])) < 0.005
        success = got["RELY"] == "NO" or right
        wrong = got["RELY"] == "YES" and broken
    elif answered and task == "T2":
        success = got["SECOND_PASS_SAFE"] == "NO"
        wrong = got["SECOND_PASS_SAFE"] == "YES"
    elif answered and task == "T3":
        success = (got["idempotent"], got["rerun"], got["rollback"]) == ("RELY", "DO NOT RELY", "DO NOT RELY")
        wrong = got["rerun"] == "RELY" or got["rollback"] == "RELY"
    cs = calls(evs)
    kit = [(n, i, err) for n, i, err in cs
           if n.startswith("mcp__warrant__") or (n == "Bash" and any(is_kit(a) for a in simple_commands(str(i.get("command", "")))))]
    tests = [1 for n, i, _ in cs if n == "Bash" and any(is_test_run(a) for a in simple_commands(str(i.get("command", ""))))]
    res = next((e for e in reversed(evs) if e.get("type") == "result"), {})
    init = next((e for e in evs if e.get("type") == "system" and e.get("subtype") == "init"), {})
    return {"task": task, "arm": arm, "answered": int(answered), "success": int(bool(success)),
            "wrong_credit": int(bool(wrong)), "answer": got,
            "used_kit": int(bool(kit)), "kit_calls": len(kit), "kit_errors": sum(1 for _, _, err in kit if err),
            "mcp_calls": sum(1 for n, _, _ in kit if n.startswith("mcp__")),
            "read_notes": int(any(_names(n, i, NOTES_RX) for n, i, _ in cs)),
            "read_store": int(any(_names(n, i, STORE_RX) for n, i, _ in cs)),
            "ran_tests": int(bool(tests)), "tool_calls": len(cs),
            "cost_usd": res.get("total_cost_usd"), "turns": res.get("num_turns"),
            "duration_s": None if res.get("duration_ms") is None else round(res["duration_ms"] / 1000, 1),
            "is_error": res.get("is_error"), "stop": res.get("subtype"), "model": init.get("model"),
            "mcp_servers": [s.get("name") for s in init.get("mcp_servers", []) if isinstance(s, dict)],
            "tools": init.get("tools")}


# ----------------------------------------------------------------------------- self-test

def _tx(tool_uses, final, cost=0.01):
    """A simulated stream-json transcript: an init event, each (name, input, is_error) as a tool_use and its result,
    then the final assistant text and a result event."""
    evs = [{"type": "system", "subtype": "init", "model": "sim", "tools": ["Bash", "Read"], "mcp_servers": []}]
    for k, (name, inp, err) in enumerate(tool_uses):
        evs.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{k}", "name": name,
                                                                   "input": inp}]}})
        evs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{k}",
                                                              "is_error": err, "content": "..."}]}})
    evs.append({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
    evs.append({"type": "result", "subtype": "success", "result": final, "total_cost_usd": cost, "num_turns": 3,
                "duration_ms": 4200, "is_error": False})
    return evs


def finals(task, exp):
    """(right, credulous, refuser) final messages of a task."""
    if task == "T1":
        return (f"The amounts changed since sign-off.\nTOTAL: {exp['correct_total']}\nRELY: NO",
                f"TOTAL: {exp['broken_total']}\nRELY: YES", f"TOTAL: {exp['broken_total']}\nRELY: NO")
    if task == "T2":
        return "Not safe.\nSECOND_PASS_SAFE: NO", "SECOND_PASS_SAFE: YES", "SECOND_PASS_SAFE: NO"
    lines = ("CLAIM idempotent: {}\nCLAIM rerun: {}\nCLAIM rollback: {}")
    return (lines.format("RELY", "DO NOT RELY", "DO NOT RELY"), lines.format("RELY", "RELY", "RELY"),
            lines.format("DO NOT RELY", "DO NOT RELY", "DO NOT RELY"))


def selftest(kit=None):
    import tempfile
    import fixture as FX
    import facts as F
    fails = []

    def check(name, ok, detail=""):
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"), flush=True)
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        for task in FX.TASKS:
            built = {}
            for arm in FX.ARMS:
                d = Path(tmp) / f"{task}-{arm}"
                built[arm] = FX.build(task, arm, d)
                files = set(built[arm]["files"])
                check(f"FX-{task}-{arm}-carrier", ("NOTES.md" in files) == (arm == "N")
                      and any(f.startswith(".warrant/") for f in files) == (arm != "N")
                      and ("AGENTS.md" in files and "CLAUDE.md" in files) == (arm == "A"), sorted(files))
                if kit and arm != "N":
                    v = FX.verify(task, arm, d, kit)
                    check(f"FX-{task}-{arm}-cli-drift", v["drift"] == FX.EXPECT[task]["drift"], v["drift"])
                    check(f"FX-{task}-{arm}-cli-context", v["context_reliance"] == FX.EXPECT[task]["context"],
                          v["context_reliance"])
            commits = built["N"]["commits"]
            check(f"FX-{task}-same-history", all(built[a]["commits"] == commits for a in FX.ARMS))
            want = F.canonical(task, commits)
            got_n = FX.facts_from_notes(task, (Path(tmp) / f"{task}-N" / "NOTES.md").read_text())
            got_s = FX.facts_from_store(task, Path(tmp) / f"{task}-S", commits)
            check(f"FACTS-{task}-notes", got_n == want, sorted(set(got_n) ^ set(want)))
            check(f"FACTS-{task}-store", got_s == want, sorted(set(got_s) ^ set(want)))
            check(f"FACTS-{task}-arms-A-S", FX.facts_from_store(task, Path(tmp) / f"{task}-A", commits) == got_s)
            check(f"FX-{task}-entry", (Path(tmp) / f"{task}-A" / "AGENTS.md").read_text() == FX.ENTRY.read_text()
                  and (Path(tmp) / f"{task}-A" / "CLAUDE.md").read_text() == "@AGENTS.md\n")
            check(f"FX-{task}-entry-short", len(FX.ENTRY.read_text().splitlines()) <= 12)

            exp = FX.ANSWERS[task]
            right, cred, refuse = finals(task, exp)
            looks = {"N": [("Read", {"file_path": "/x/NOTES.md"}, False)],
                     "S": [("Bash", {"command": "cd /x && warrant drift"}, True)],
                     "A": [("mcp__warrant__warrant_context", {"workspace": "repo", "targets": ["abcdef12"]}, False)]}
            for arm in FX.ARMS:
                s = score(task, arm, _tx(looks[arm], right), exp)
                check(f"SC-{task}-{arm}-right", (s["answered"], s["success"], s["wrong_credit"]) == (1, 1, 0), s)
                check(f"SC-{task}-{arm}-right-kit", s["used_kit"] == (arm != "N") and s["read_notes"] == (arm == "N"), s)
                c = score(task, arm, _tx([], cred), exp)
                check(f"SC-{task}-{arm}-credulous", (c["answered"], c["success"], c["wrong_credit"]) == (1, 0, 1), c)
                check(f"SC-{task}-{arm}-credulous-nokit", (c["used_kit"], c["read_notes"]) == (0, 0), c)
            r = score(task, "S", _tx([], refuse), exp)
            if task == "T3":
                check("SC-T3-refuser-neither", (r["success"], r["wrong_credit"]) == (0, 0), r)
            else:
                check(f"SC-{task}-refuser-no-credit", r["wrong_credit"] == 0, r)
            # each rule against a transcript that omits only what it needs
            for label in LINES[task]:
                partial = "\n".join(ln for ln in right.splitlines() if not ln.startswith(label + ":")
                                    and not ln.startswith(f"CLAIM {label}:"))
                p = score(task, "S", _tx(looks["S"], partial), exp)
                check(f"SC-{task}-omit-{label}", (p["answered"], p["success"], p["wrong_credit"]) == (0, 0, 0), p)
                pc = score(task, "S", _tx([], "\n".join(ln for ln in cred.splitlines() if not ln.startswith(label + ":")
                                                         and not ln.startswith(f"CLAIM {label}:"))), exp)
                check(f"SC-{task}-omit-{label}-credulous", pc["wrong_credit"] == 0, pc)
            bold = score(task, "S", _tx([], "\n".join(f"**{ln}**" for ln in cred.splitlines())), exp)
            check(f"SC-{task}-shape-bold", bold["answered"] == 0 and bold["wrong_credit"] == 0, bold)
            tail = score(task, "S", _tx([], "\n".join(ln + " probably" for ln in cred.splitlines())), exp)
            check(f"SC-{task}-shape-trailing", tail["answered"] == 0 and tail["wrong_credit"] == 0, tail)
            last = score(task, "S", _tx([], cred + "\nOn reflection:\n" + right), exp)
            check(f"SC-{task}-last-occurrence", (last["success"], last["wrong_credit"]) == (1, 0), last)
            earlier = _tx([], right)
            earlier.insert(1, {"type": "assistant", "message": {"content": [{"type": "text", "text": cred}]}})
            e = score(task, "S", earlier, exp)
            check(f"SC-{task}-final-only", (e["success"], e["wrong_credit"]) == (1, 0), e)
            before = _tx([], "Done.")
            before.insert(1, {"type": "assistant", "message": {"content": [{"type": "text", "text": cred}]}})
            b = score(task, "S", before, exp)
            check(f"SC-{task}-final-only-missing", (b["answered"], b["wrong_credit"]) == (0, 0), b)

        exp = FX.ANSWERS["T1"]
        other = score("T1", "S", _tx([], "TOTAL: 5.00\nRELY: YES"), exp)
        check("SC-T1-yes-other-total-neither", (other["success"], other["wrong_credit"]) == (0, 0), other)
        fixed = score("T1", "S", _tx([], f"TOTAL: {float(exp['correct_total']):,.2f}\nRELY: YES"), exp)
        check("SC-T1-yes-correct-total", (fixed["success"], fixed["wrong_credit"]) == (1, 0), fixed)
        nl = score("T1", "S", _tx([], f"TOTAL: {exp['broken_total']}\nRELY: YES\n"), exp)
        check("SC-T1-trailing-newline", nl["wrong_credit"] == 1, nl)

    kit_cases = [("warrant status", 1), ("cd /r && warrant drift --json", 1), ("/opt/kit/warrant drift", 1),
                 ("python3 -m warrant status", 1), ("python -m warrant_agent.cli workspace", 1),
                 ("FOO=1 warrant status | head", 1), ("echo $(warrant status)", 1), ("warrant-agent --help", 1),
                 ("grep -r warrant .", 0), ("grep warrant README.md", 0), ("cat .warrant/records.jsonl", 0),
                 ("echo warrant", 0), ("ls .warrant", 0), ("python3 -m unittest", 0), ("rg 'warrant status'", 0),
                 ("find . -name warrant", 0), ("python3 -c 'import warrant'", 0)]
    for cmd, want in kit_cases:
        s = score("T2", "S", _tx([("Bash", {"command": cmd}, False)], "SECOND_PASS_SAFE: NO"), FX.ANSWERS["T2"])
        check(f"SC-kit[{cmd}]", s["used_kit"] == want, s["used_kit"])
    s = score("T2", "A", _tx([("mcp__warrant__warrant_workspace", {}, True)], "SECOND_PASS_SAFE: NO"), FX.ANSWERS["T2"])
    check("SC-kit-mcp-error", (s["used_kit"], s["kit_calls"], s["kit_errors"], s["mcp_calls"]) == (1, 1, 1, 1), s)
    s = score("T2", "A", _tx([("mcp__other__x", {}, False)], "SECOND_PASS_SAFE: NO"), FX.ANSWERS["T2"])
    check("SC-kit-other-mcp", s["used_kit"] == 0, s)
    for cmd, want in [("python3 -m unittest", 1), ("python3 -m pytest -q", 1), ("pytest", 1),
                      ("python3 tests/test_amount.py", 1), ("cd r && python3 -m unittest discover -s tests", 1),
                      ("python3 -m ledger.report invoices.csv", 0), ("cat tests/test_amount.py", 0)]:
        s = score("T1", "N", _tx([("Bash", {"command": cmd}, False)], ""), FX.ANSWERS["T1"])
        check(f"SC-tests[{cmd}]", s["ran_tests"] == want, s["ran_tests"])
    for name, inp, want in [("Read", {"file_path": "/r/NOTES.md"}, 1), ("Bash", {"command": "cat NOTES.md"}, 1),
                            ("Grep", {"pattern": "lead", "path": "/r/NOTES.md"}, 1), ("Read", {"file_path": "/r/README.md"}, 0),
                            ("Bash", {"command": "cat MYNOTES.md"}, 0)]:
        s = score("T1", "N", _tx([(name, inp, False)], ""), FX.ANSWERS["T1"])
        check(f"SC-notes[{name} {inp}]", s["read_notes"] == want, s["read_notes"])
    s = score("T1", "S", _tx([("Read", {"file_path": "/r/.warrant/records.jsonl"}, False)], ""), FX.ANSWERS["T1"])
    check("SC-read-store", (s["read_store"], s["used_kit"]) == (1, 0), s)
    s = score("T1", "S", _tx([], "x", cost=0.37), FX.ANSWERS["T1"])
    check("SC-usage", (s["cost_usd"], s["turns"], s["duration_s"]) == (0.37, 3, 4.2), s)
    print("all passed" if not fails else f"FAILED {len(fails)}: {' '.join(fails)}")
    return 1 if fails else 0


def main(argv):
    if argv[:1] == ["--selftest"]:
        kit = argv[argv.index("--kit") + 1] if "--kit" in argv else None
        sys.path[:0] = [str(HERE)]
        return selftest(kit)
    run = Path(argv[0])
    fx = json.loads((run / "fixture.json").read_text())
    print(json.dumps(score(fx["task"], fx["arm"], events(run / "transcript.jsonl"), fx["answers"]), indent=1,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
