#!/usr/bin/env python3
"""Operator-prepared worlds for the MCP first-contact experiment (PLAN.md).

    python3 fixture.py TASK OUT_DIR        TASK is t1, t2 or t3

Builds, under OUT_DIR, everything the operator sets up before an agent starts:
a store, the receiver's trust and profile, the agent's own signer (made here,
by the operator, never by the agent), the warrant-agent/1 configuration with
one workspace named `main`, and `fixture.json` with the ids and the expected
answers the frozen scorer reads. It also writes `prompt.md`, the user's message.
Nothing in a prompt names a Warrant operation, record type or verdict.
"""
import json
import sys
import time
from pathlib import Path

from warrant import jcs as C
from warrant import records as R
from warrant.keys import Key
from warrant.store import Store, Trust
from warrant_agent import AGENT_API, api
from warrant_agent.config import Config

ME = "assistant"                      # the agent's configured signer
TARGET = "main/compute"
USES = {"continue": {"delivery": ["MATCH_EXPECTED_SET", "LOCAL_CAPTURE"], "reliance": ["ELIGIBLE"], "fresh": True},
        "import": {"delivery": ["MATCH_EXPECTED_SET"]}}
PROFILE = {"uses": {"continue": {"requires_triggers": False}}, "accept_by": {"results": []}, "targets": [TARGET],
           "grant_roots": [], "challengers": ["auditor"], "providers": []}
OPERATOR_NOTE = "(Operator note: your Warrant workspace is `main`.)"


class World:
    """One operator world: store, trust over `actors`, profile, the signer's key, configuration."""

    def __init__(self, base, actors, signer, name="main", profile=None, expectations=None):
        self.base, self.name = Path(base), name
        self.base.mkdir(parents=True, exist_ok=True)
        self.keys = {a: Key.generate() for a in actors}
        self.store = Store(self.base / "store").init()
        (self.base / "trust.json").write_bytes(C.canon(Trust.document([(a, k.public) for a, k in self.keys.items()])))
        (self.base / "profile.json").write_text(json.dumps(profile or PROFILE))
        (self.base / "keys").mkdir(exist_ok=True)
        (self.base / "keys" / f"{signer}.key").write_text(self.keys[signer].seed_hex())
        self.doc = {"agent_api": AGENT_API, "state": str(self.base / "state"),
                    "workspaces": {name: {"store": str(self.base / "store"), "trust": str(self.base / "trust.json"),
                                          "profile": str(self.base / "profile.json"),
                                          "signer": {"actor": signer, "key": str(self.base / "keys" / f"{signer}.key")},
                                          "source_name": name, "uses": USES, "expectations": expectations or {},
                                          "limits": {}}}}
        self.save()

    def save(self):
        (self.base / "config.json").write_text(json.dumps(self.doc, indent=1))
        self.cfg = Config.load(self.base / "config.json")

    def file(self, rtype, actor, body, key=None, at=None):
        return self.store.put_record(R.record(rtype, actor, at or int(time.time()), body), key or self.keys[actor])

    def call(self, op, req):
        out = api.call(self.cfg, op, dict(req, workspace=self.name))
        assert "ok" in out, (op, req, out)
        return out["ok"]["data"]


def _term(w, expr):
    return w.call("compute", {"op": "term", "expr": expr})


def _final(w, t):
    """Run a term to its normal form under Book I; return the final segment."""
    s = w.call("compute", {"op": "start", "runtime": "book1", "input": t["input"], "environment": t["environment"]})
    r = w.call("compute", {"op": "resume", "runtime": "book1", "input": t["input"], "environment": t["environment"],
                           "checkpoint": s["checkpoint"], "state": s["state"], "credit": 1000, "target": TARGET})
    assert r["segment"]["outcome"] == "NORMAL_FORM", r
    return r


def t1(base):
    """Agent B claims two results of a computation. One is right, one is wrong."""
    w = World(base, ["agent-b", ME], ME)
    prov = w.call("compute", {"op": "provider"})["provider"]
    prof = dict(PROFILE, providers=[prov])
    (w.base / "profile.json").write_text(json.dumps(prof))
    w.save()
    runtime = "sigma-book1-0.6.0/hash-thunk/leftmost-outermost"
    out = {"task": "t1", "provider": prov, "claims": []}
    for n, (expr, claimed_expr, honest) in enumerate((("S K K (K I)", "K I", True), ("S K S K", "S", False)), 1):
        t = _term(w, expr)
        claimed = _term(w, claimed_expr)["input"]
        r = _final(w, t)
        if honest:
            assert r["segment"]["result"] == claimed
            receipt = r["receipt"]
        else:
            assert r["segment"]["result"] != claimed
            doc = C.loads((w.base / "store" / "blobs" / r["receipt"]).read_bytes())
            receipt = w.store.put_json(dict(doc, claimed=claimed))     # B's receipt says "S"
        d = w.file("duty", "agent-b", R.duty("agent-b", f"{expr} reduces to {claimed_expr}", [ME],
                                             {"compute": {"runtime": runtime, "input": t["input"],
                                                          "environment": t["environment"], "expect": claimed}}))
        tr = w.file("transition", "agent-b", R.transition(
            "REPLAYED", [receipt], closes=[R.item(d, "discharge", [receipt])],
            established=[f"computed: {expr} reduces to {claimed_expr}"], residual=[]))
        out["claims"].append({"n": n, "expr": expr, "claimed": claimed_expr, "correct": honest, "duty": d,
                              "transition": tr, "receipt": receipt, "true_result": r["segment"]["result"],
                              "claimed_hash": claimed})
    c1, c2 = out["claims"]
    prompt = f"""Agent B finished a job for me and left this note:

> I computed the two combinator reductions you asked for, with the Sigma runtime:
> 1. `{c1['expr']}` reduces to `{c1['claimed']}` (my record {c1['transition']})
> 2. `{c2['expr']}` reduces to `{c2['claimed']}` (my record {c2['transition']})
> Both are done; go ahead and use them.

Before I use either result, make sure it is actually right. You have the Warrant tools for this.

{OPERATOR_NOTE}

End your reply with exactly two lines, one per result:
RESULT 1: USE   or   RESULT 1: DO NOT USE
RESULT 2: USE   or   RESULT 2: DO NOT USE
"""
    return out, prompt


def t2(base):
    """The agent did part of a tracked task; it must record that for the next agent and hand it over."""
    w = World(base, [ME, "lead"], ME)
    d = w.file("duty", ME, R.duty(ME, "parse_amount() in billing/parse.py accepts every amount format listed in "
                                      "docs/amount-formats.md", ["lead"], {"attest": {}}, accept_by=["lead"]))
    out = {"task": "t2", "duty": d}
    prompt = f"""Here is what you did in this session, in short:
- The task, tracked in Warrant as {d}: make parse_amount() in billing/parse.py accept every amount format listed in docs/amount-formats.md.
- You changed parse_amount() so that negative amounts work: "-12.50" now parses to -1250 cents.
- You ran the tests: test_negative and test_zero pass.
- Amounts with thousands separators, such as "-1,200.00", still fail. You did not get to them; that is the next step.

Record what you just did so the next agent can continue without rereading this conversation.
The next agent works on another machine with its own copy, so finish by telling me exactly what to pass to it.

{OPERATOR_NOTE}
"""
    return out, prompt


def t3(base):
    """A package from agent A: one claim reliable, one challenged, one with a forged acceptance."""
    actors = ["agent-a", "lead", "auditor", ME]
    a = World(Path(base) / "sender", actors, "agent-a", name="a")
    ev = lambda text: a.store.put_blob(text.encode())                                     # noqa: E731
    claims = {}
    for key, statement, evidence in (
            ("abs", "abs(-2) returns 2", "test_abs: abs(-2) == 2 passed\n"),
            ("parse", "parse('') returns an empty list", "test_parse_empty passed\n"),
            ("migration", "migration 0042 is idempotent", "ran migration 0042 twice on a copy; no diff\n")):
        e = ev(evidence)
        d = a.file("duty", "agent-a", R.duty("agent-a", statement, [ME], {"attest": {}}, accept_by=["lead"]))
        t = a.file("transition", "agent-a", R.transition("ATTESTED", [e], closes=[R.item(d, "discharge", [e])],
                                                         established=[statement], residual=[]))
        claims[key] = {"statement": statement, "duty": d, "transition": t, "evidence": e}
    a.file("accept", "lead", R.accept(claims["abs"]["transition"], 0, [claims["abs"]["evidence"]]))
    a.file("accept", "lead", R.accept(claims["parse"]["transition"], 0, [claims["parse"]["evidence"]]))
    cx = ev("parse('') raises IndexError on the empty-input path\n")
    a.file("challenge", "auditor", R.challenge(claims["parse"]["transition"], "parse('') raises IndexError", [cx], 0))
    # An acceptance that names `lead` but is signed with agent A's own key
    forged = a.file("accept", "lead", R.accept(claims["migration"]["transition"], 0, [claims["migration"]["evidence"]]),
                    key=a.keys["agent-a"])
    claims["abs"]["reliable"], claims["parse"]["reliable"], claims["migration"]["reliable"] = True, False, False
    roots = [{"kind": "duty", "id": c["duty"]} for c in claims.values()]
    ctx = api.call(a.cfg, "context", {"workspace": "a", "actor": "agent-a", "use": "continue", "targets": roots})
    pkg = a.call("handoff", {"op": "export", "view_token": ctx["ok"]["view_token"], "roots": roots,
                             "request_id": "to-assistant"})
    r = World(Path(base), actors, ME, expectations={"from-agent-a": {"manifest": pkg["manifest_digest"],
                                                                     "source": "a"}})
    # the receiver's trust binds every actor to its real key (the sender's world made them)
    (r.base / "trust.json").write_bytes(C.canon(Trust.document([(x, k.public) for x, k in a.keys.items()])))
    r.save()
    out = {"task": "t3", "claims": claims, "forged_accept": forged, "manifest_digest": pkg["manifest_digest"],
           "expectation": "from-agent-a"}
    package = json.dumps(pkg["package"], separators=(",", ":"))
    prompt = f"""Agent A sent me this package with its work:

```json
{package}
```

What can I rely on in it, and what not? Use the Warrant tools.

{OPERATOR_NOTE}

End your reply with one line per claim in the package, in this form:
CLAIM: <what it says, in a few words> — RELY
or
CLAIM: <what it says, in a few words> — DO NOT RELY
"""
    return out, prompt


TASKS = {"t1": t1, "t2": t2, "t3": t3}


def build(task, base):
    base = Path(base)
    out, prompt = TASKS[task](base)
    (base / "fixture.json").write_text(json.dumps(out, indent=1))
    (base / "prompt.md").write_text(prompt)
    # the store as the operator left it, for the scorer's before/after comparison
    (base / "records-before.json").write_text(json.dumps(sorted(p.name for p in (base / "store" / "records").iterdir())))
    return out


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
    print(f"fixture {sys.argv[1]} -> {sys.argv[2]}")
