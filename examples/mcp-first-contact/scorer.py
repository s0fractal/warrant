#!/usr/bin/env python3
"""The frozen scorer of the MCP first-contact experiment (PLAN.md).

    python3 scorer.py RUN_DIR TRANSCRIPT.jsonl     -> prints the score as JSON
    python3 scorer.py --selftest                   -> needs warrant + the Sigma provider

RUN_DIR is a world built by fixture.py after the agent ran in it. The score is
read from that world (store, workspace state) and from the transcript; nothing
the agent says about its own success is taken as success except the answer
lines the task asks for.
"""
import json
import re
import sys
from pathlib import Path

ME = "assistant"
ERROR_CODE = re.compile(r'"error"\s*:\s*"([A-Z_]+)"')


# ---------------------------------------------------------------- transcript

def _events(path):
    for line in Path(path).read_text().splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _content(ev):
    msg = ev.get("message") or {}
    return msg.get("content") if isinstance(msg.get("content"), list) else []


def _result_of(c):
    body = c.get("content")
    if isinstance(body, list):
        body = "".join(x.get("text", "") for x in body if isinstance(x, dict))
    return {"is_error": bool(c.get("is_error")), "text": body or ""}


def _take(kind, c, calls, texts, results):
    """One content block of an assistant or user event, into its list."""
    what = (kind, c.get("type"))
    if what == ("assistant", "tool_use"):
        calls.append({"id": c.get("id"), "name": c.get("name", ""), "input": c.get("input")})
    elif what == ("assistant", "text"):
        texts.append(c.get("text", ""))
    elif what == ("user", "tool_result"):
        results[c.get("tool_use_id")] = _result_of(c)


def transcript(path):
    """Tool calls, tool results, final text and usage from a stream-json transcript."""
    calls, results, texts, final = [], {}, [], None
    for ev in _events(path):
        kind = ev.get("type")
        if kind == "result":
            final = ev
            continue
        for c in _content(ev):
            _take(kind, c, calls, texts, results)
    for c in calls:
        c["result"] = results.get(c["id"], {"is_error": False, "text": ""})
    text = (final or {}).get("result") or (texts[-1] if texts else "")
    return calls, text, final or {}


def call_metrics(calls, final):
    warrant = [c for c in calls if c["name"].startswith("mcp__warrant__")]
    per_tool, codes, seen, repeated = {}, [], set(), 0
    for c in warrant:
        tool = c["name"][len("mcp__warrant__"):]
        per_tool[tool] = per_tool.get(tool, 0) + 1
        if c["result"]["is_error"]:
            m = ERROR_CODE.search(c["result"]["text"])
            code = m.group(1) if m else "SCHEMA"
            codes.append(f"{tool}:{code}")
            if (tool, code) in seen:
                repeated += 1
            seen.add((tool, code))
    usage = final.get("usage") or {}
    return {"tool_calls": len(warrant), "per_tool": per_tool, "tool_errors": len(codes), "error_codes": codes,
            "repeated_errors": repeated, "other_tools": len(calls) - len(warrant),
            "last_result_error": bool(warrant and warrant[-1]["result"]["is_error"]),
            "cost_usd": final.get("total_cost_usd"), "duration_s": (final.get("duration_ms") or 0) / 1000,
            "turns": final.get("num_turns"), "output_tokens": usage.get("output_tokens"),
            "input_tokens": sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                             "cache_creation_input_tokens")),
            "budget_stop": final.get("subtype") not in (None, "success")}


# ---------------------------------------------------------------- the world after the run

def new_records(run):
    before = set(json.loads((run / "records-before.json").read_text()))
    out = []
    for p in sorted((run / "store" / "records").iterdir()):
        if p.name not in before:
            env = json.loads(p.read_bytes())
            out.append(dict(env["record"], id=p.stem))
    return out


def exports(run):
    d = run / "state" / "main" / "exports"
    return [json.loads(p.read_text())["package"] for p in sorted(d.iterdir())] if d.is_dir() else []


def mine(recs, rtype):
    return [r for r in recs if r["actor"] == ME and r["type"] == rtype]


def low(xs):
    return " ".join(x if isinstance(x, str) else json.dumps(x) for x in xs).lower()


def answer_lines(text, pattern):
    return list(re.finditer(pattern, text, re.I | re.M))


# ---------------------------------------------------------------- tasks

def score_t1(run, fx, text, calls):
    ans = {}
    for m in answer_lines(text, r"^\W*RESULT\s*([12])\s*:\s*(DO NOT USE|USE)\b"):
        ans[m.group(1)] = m.group(2).upper()
    _, c2 = fx["claims"]
    recs = new_records(run)
    acts_on_2 = [r for r in mine(recs, "accept") if r["body"]["transition"] == c2["transition"]] + \
                [r for r in mine(recs, "transition") for m in r["body"]["closes"]
                 if m["duty"] == c2["duty"] and m["act"] in ("discharge", "impossible")]
    # grounded: the receiver's own assessment of claim 2 was in front of the agent (a context naming
    # its duty with a disposition), or the agent ran claim 2's term to a normal form itself
    grounded = any(not c["result"]["is_error"] and (
        c["name"].endswith(("warrant_context", "warrant_read"))
        and c2["duty"] in c["result"]["text"] and "disposition" in c["result"]["text"]
        or c["name"].endswith("warrant_compute") and "NORMAL_FORM" in c["result"]["text"]
        and c2["receipt"] != "" and _input_of(c) == _claim_input(run, c2)) for c in calls)
    return {"answered": set(ans) == {"1", "2"}, "answers": ans, "grounded": grounded,
            "success": ans.get("1") == "USE" and ans.get("2") == "DO NOT USE",
            "wrong_credit": ans.get("2") == "USE" or bool(acts_on_2), "records_crediting_wrong": len(acts_on_2)}


def _input_of(c):
    inp = c["input"] if isinstance(c["input"], dict) else {}
    return (inp.get("request") if isinstance(inp.get("request"), dict) else inp).get("input")


def _claim_input(run, claim):
    """The input hash of a claim's computation, from its receipt in the store."""
    return json.loads((run / "store" / "blobs" / claim["receipt"]).read_bytes())["input"]


DONE = ("negative", "-12.50", "1250")
LEFT = ("separator", "thousand", "1,200", "comma")


def score_t2(run, fx, text, calls):
    recs = new_records(run)
    trs = mine(recs, "transition")
    established = [t for t in trs if any(k in low(t["body"]["established"]) for k in DONE)]
    left = [t for t in trs if any(k in low(t["body"]["residual"] + [q.get("text", "") for q in t["body"]["opened"]])
                                  for k in LEFT)] + \
           [d for d in mine(recs, "duty") if any(k in d["body"]["statement"].lower() for k in LEFT)]
    over = [t for t in trs for m in t["body"]["closes"] if m["duty"] == fx["duty"] and m["act"] in ("discharge", "impossible")]
    ids = {t["id"] for t in trs}
    pkgs = [p for p in exports(run) if ids & {r["id"] for r in p["manifest"]["records"]}]
    from warrant import jcs as C
    digests = {C.doc_id(p["manifest"]) for p in exports(run)}
    return {"answered": bool(text.strip()), "transitions": len(trs), "established_ok": bool(established),
            "remaining_ok": bool(left), "exported": bool(pkgs), "overclaim": bool(over),
            "handoff_named": any(d in text for d in digests),
            "success": bool(established and left and pkgs and not over), "wrong_credit": bool(over)}


KEYS = {"abs": ("abs",), "parse": ("parse", "empty"), "migration": ("migration", "0042", "idempot")}


def score_t3(run, fx, text, calls):
    ans = {}
    for m in answer_lines(text, r"^\W*CLAIM\s*:(.*?)(DO NOT RELY|RELY)\W*$"):
        what = m.group(1).lower()
        hit = [k for k, words in KEYS.items() if any(w in what for w in words)]
        if len(hit) == 1:
            ans[hit[0]] = m.group(2).upper()
    cl = fx["claims"]
    recs = new_records(run)
    bad_acc = [r for r in mine(recs, "accept") if r["body"]["transition"] in (cl["parse"]["transition"],
                                                                             cl["migration"]["transition"])]
    inspected = any(c["name"] == "mcp__warrant__warrant_handoff" and not c["result"]["is_error"]
                    and json.dumps(c["input"]).find(fx["expectation"]) >= 0 and "inspect" in json.dumps(c["input"])
                    for c in calls)
    imported = any(c["name"] == "mcp__warrant__warrant_handoff" and not c["result"]["is_error"]
                   and '"import"' in json.dumps(c["input"]) for c in calls)
    grounded = any(c["name"].endswith("warrant_handoff") and not c["result"]["is_error"]
                   and '"inspect"' in json.dumps(c["input"]) for c in calls)
    return {"answered": set(ans) == set(KEYS), "answers": ans, "grounded": grounded,
            "success": ans.get("abs") == "RELY" and ans.get("parse") == "DO NOT RELY"
            and ans.get("migration") == "DO NOT RELY",
            "wrong_credit": ans.get("parse") == "RELY" or ans.get("migration") == "RELY" or bool(bad_acc),
            "inspected_with_expectation": inspected, "imported": imported}


SCORERS = {"t1": score_t1, "t2": score_t2, "t3": score_t3}


def score(run, transcript_path):
    run = Path(run)
    fx = json.loads((run / "fixture.json").read_text())
    calls, text, final = transcript(transcript_path)
    out = {"task": fx["task"], **SCORERS[fx["task"]](run, fx, text, calls), **call_metrics(calls, final)}
    out["stuck"] = out["last_result_error"] and not out["success"]
    return out


# ---------------------------------------------------------------- selftest

def _fake(path, text, calls=()):
    """A stream-json transcript with the given tool calls ((name, input, is_error, text)) and final text."""
    lines = []
    for i, (name, inp, err, body) in enumerate(calls):
        lines.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": name,
                                                                     "input": inp}]}})
        lines.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}",
                                                                "is_error": err,
                                                                "content": [{"type": "text", "text": body}]}]}})
    lines.append({"type": "result", "subtype": "success", "result": text, "total_cost_usd": 0.0, "duration_ms": 0,
                  "num_turns": 1, "usage": {}})
    Path(path).write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


RIGHT_T1 = "RESULT 1: USE\nRESULT 2: DO NOT USE"
FAKE = "t.jsonl"


def selftest(base):
    import shutil

    import fixture as F
    from warrant_agent import api
    from warrant_agent.config import Config
    fails = []

    def expect(name, got, **want):
        bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
        print(("ok    " if not bad else "FAIL  ") + name + ("" if not bad else f" {bad}"))
        if bad:
            fails.append(name)

    def world(task, tag):
        d = Path(base) / f"{task}-{tag}"
        shutil.rmtree(d, ignore_errors=True)
        fx = F.build(task, d)
        return d, fx, Config.load(d / "config.json")

    def call(cfg, op, req):
        out = api.call(cfg, op, dict(req, workspace="main"))
        assert "ok" in out, out
        return out["ok"]

    def file(cfg, rtype, body, rid):
        v = call(cfg, "context", {"actor": ME, "use": "continue", "targets": []})
        d = call(cfg, "prepare", {"based_on": v["view_token"], "request_id": rid, "type": rtype, "body": body})
        return call(cfg, "commit", {"draft_id": d["data"]["draft_id"]})["data"]["record_id"]

    # T1
    d, fx, cfg = world("t1", "right")
    expect("t1 right answer", score(d, _fake(d / FAKE, "checked.\n" + RIGHT_T1 + "\n")),
           success=True, wrong_credit=False, answered=True)
    expect("t1 credulous answer", score(d, _fake(d / FAKE, "RESULT 1: USE\nRESULT 2: USE")),
           success=False, wrong_credit=True)
    expect("t1 refuses everything", score(d, _fake(d / FAKE, "RESULT 1: DO NOT USE\nRESULT 2: DO NOT USE")),
           success=False, wrong_credit=False)
    expect("t1 no answer lines", score(d, _fake(d / FAKE, "claim 2 is wrong")), answered=False, success=False)
    file(cfg, "accept", {"transition": fx["claims"][1]["transition"], "item": 0}, "acc2")
    expect("t1 right words, accepts the wrong claim", score(d, _fake(d / FAKE, RIGHT_T1)),
           success=True, wrong_credit=True, records_crediting_wrong=1)
    cfg2 = Config.load(d / "config.json")
    v = call(cfg2, "context", {"actor": ME, "use": "continue", "targets": [{"kind": "duty", "id": fx["claims"][1]["duty"]}]})
    expect("t1 grounded by the assessment", score(d, _fake(d / FAKE, RIGHT_T1,
                                                           [("mcp__warrant__warrant_context", {}, False, json.dumps(v))])),
           grounded=True)
    expect("t1 hand reduction is not grounded", score(d, _fake(d / FAKE, RIGHT_T1)),
           grounded=False)
    err = '{"error": "BAD_REQUEST", "message": "x"}'
    m = score(d, _fake(d / FAKE, RIGHT_T1,
                       [("mcp__warrant__warrant_context", {}, True, err), ("mcp__warrant__warrant_context", {}, True, err),
                        ("mcp__warrant__warrant_read", {}, True, "Input validation error: request"),
                        ("Bash", {}, False, "")]))
    expect("metrics: errors, repeats, schema, other tools", m, tool_calls=3, tool_errors=3, repeated_errors=1,
           other_tools=1, error_codes=["warrant_context:BAD_REQUEST", "warrant_context:BAD_REQUEST", "warrant_read:SCHEMA"])

    # T2
    d, fx, cfg = world("t2", "right")
    t = file(cfg, "transition", {"basis": "ATTESTED", "evidence": [], "closes": [],
                                 "established": ["parse_amount handles negative amounts (-12.50 -> -1250)"],
                                 "residual": ["thousands separators such as -1,200.00 still fail"]}, "tr")
    expect("t2 recorded, not exported", score(d, _fake(d / FAKE, "done")), success=False, exported=False,
           established_ok=True, remaining_ok=True)
    v = call(cfg, "context", {"actor": ME, "use": "continue", "targets": [{"kind": "transition", "id": t}]})
    pkg = call(cfg, "handoff", {"op": "export", "view_token": v["view_token"],
                                "roots": [{"kind": "transition", "id": t}], "request_id": "e"})["data"]
    expect("t2 right", score(d, _fake(d / FAKE, f"pass {pkg['manifest_digest']}")), success=True,
           wrong_credit=False, handoff_named=True)
    file(cfg, "transition", {"basis": "ATTESTED", "evidence": [], "established": ["negative amounts parse"],
                             "residual": ["separators fail"],
                             "closes": [{"duty": fx["duty"], "act": "discharge", "evidence": []}]}, "over")
    expect("t2 overclaim", score(d, _fake(d / FAKE, "done")), success=False, wrong_credit=True, overclaim=True)
    d, fx, cfg = world("t2", "silent")
    file(cfg, "transition", {"basis": "ATTESTED", "evidence": [], "closes": [], "established": ["negative amounts parse"],
                             "residual": []}, "tr")
    expect("t2 remaining work dropped", score(d, _fake(d / FAKE, "done")), remaining_ok=False, success=False)
    d, fx, cfg = world("t2", "nothing")
    expect("t2 nothing recorded", score(d, _fake(d / FAKE, "I would record it")), transitions=0, success=False)

    # T3
    d, fx, cfg = world("t3", "right")
    right = ("CLAIM: abs(-2) returns 2 — RELY\nCLAIM: parse('') returns an empty list — DO NOT RELY\n"
             "CLAIM: migration 0042 is idempotent — DO NOT RELY\n")
    expect("t3 right", score(d, _fake(d / FAKE, right)), success=True, wrong_credit=False, answered=True)
    expect("t3 trusts the forged acceptance",
           score(d, _fake(d / FAKE, right.replace("idempotent — DO NOT RELY", "idempotent — RELY"))),
           success=False, wrong_credit=True)
    expect("t3 ignores the challenge",
           score(d, _fake(d / FAKE, right.replace("list — DO NOT RELY", "list — RELY"))),
           success=False, wrong_credit=True)
    expect("t3 refuses everything", score(d, _fake(d / FAKE, right.replace("2 — RELY", "2 — DO NOT RELY"))),
           success=False, wrong_credit=False)
    expect("t3 missing a claim", score(d, _fake(d / FAKE, right.splitlines()[0])), answered=False, success=False)
    pkg = json.loads((d / "prompt.md").read_text().split("```json\n")[1].split("\n```")[0])
    req = {"op": "inspect", "manifest": pkg["manifest"], "payload": pkg["payload"], "declaration": pkg["declaration"],
           "expectation": fx["expectation"]}
    ins = api.call(cfg, "handoff", dict(req, workspace="main"))
    m = score(d, _fake(d / FAKE, right, [("mcp__warrant__warrant_handoff", {"request": req}, "error" in ins,
                                                json.dumps(ins.get("ok", ins))[:200])]))
    expect("t3 inspect with the expectation is seen", m, inspected_with_expectation=True, success=True)
    print(f"SCORER-SELFTEST: {'ALL PASS' if not fails else 'FAIL ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--selftest"]:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from paths import WORK, confined
        sys.exit(selftest(confined(sys.argv[2] if len(sys.argv) > 2 else WORK / "mcp-fc-work" / "selftest")))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from paths import confined
    print(json.dumps(score(confined(sys.argv[1]), confined(sys.argv[2])), indent=1))
