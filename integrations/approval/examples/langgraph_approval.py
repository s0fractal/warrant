#!/usr/bin/env python3
"""EXAMPLE (not a supported surface): warrant at a LangGraph interrupt.

This is the whole "LangGraph integration". It is a page of code in the caller's
own approval loop, it imports no LangGraph internals, and it is shipped as an
example precisely so that nobody has to maintain it as a compatibility layer.
`docs/integration-study.md` argues that case; this file is the evidence for it.

WHAT IT SHOWS
-------------
`interrupt()` is the one place in a LangGraph program where execution stops and
waits for a party other than the agent to say yes or no. That is a decision
point the MCP server cannot see, because nothing the agent chooses to call
produces it. Around that pause:

    request  = boundary.record_request(action, requester="agent:...")
    ... the human decides ...
    decision = boundary.record_decision(request, allowed, decider="human:...")
    graph.invoke(Command(resume=...), cfg)

The store then holds the request, the sanction, the rule both cite, and two
signatures from two custodies -- none of which LangGraph itself retains, because
a checkpointer persists *state*, not *decisions*, and the resume value is just a
value in that state.

THE VERSION SURFACE, WHICH IS THE POINT
---------------------------------------
Reading "did the graph pause, and what did it ask?" has changed shape four times:
`Interrupt` was added in 0.2.24, gained `interrupt_id` in 0.4.0, lost `ns` /
`when` / `resumable` / `interrupt_id` in 0.6.0, and as of 1.1 the dict access
`result["__interrupt__"]` is deprecated in favour of a `GraphOutput` container
with `.interrupts`, reachable only by passing `version="v2"` to `invoke`. Both
return shapes are live in 1.2.10 and the kwarg selects between them.

`read_interrupts` below therefore branches on the return type. That branch is
the maintenance surface a framework adapter would own forever, on someone else's
release schedule -- five lines here, and five lines again for every other
framework, which is the M*N cost the study declines to take on.

VERIFIED AGAINST
    langgraph 1.2.10 (PyPI, latest at 2026-07-31), CPython 3.14, in a throwaway
    venv. Run it yourself:  python3 integrations/approval/examples/langgraph_approval.py

LIMITS
------
- The "human" here is a scripted policy function. A real deployment puts a
  person behind it; nothing in the recording changes.
- Both keys live on one host in this demo. The store says so, and so does the
  `sanction_independent` field. Same-host custody is one custody.
- This records the decision. It does not enforce it: the code that resumes the
  graph is the code that must honour the refusal.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "integrations" / "approval"))
from warrant_approval import Boundary                          # noqa: E402

try:
    from typing import Optional
    from typing_extensions import TypedDict
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.constants import START
    from langgraph.graph import StateGraph
    from langgraph.types import Command, interrupt
    from importlib.metadata import version as _pkg_version
except ImportError as e:                                       # pragma: no cover
    sys.exit(f"this example needs langgraph installed: {e}\n"
             "  python3 -m venv v && ./v/bin/pip install langgraph")


def read_interrupts(result):
    """The compatibility branch, isolated so its cost is visible.

    <=1.0 / default today : invoke() returns a dict; interrupts under
                            the "__interrupt__" key (deprecated access on v2).
    >=1.1 with version=v2 : invoke() returns GraphOutput; use .interrupts.
    """
    got = getattr(result, "interrupts", None)
    if got is not None:                      # GraphOutput (1.1+, version="v2")
        return list(got)
    if isinstance(result, dict):             # legacy dict shape
        return list(result.get("__interrupt__") or [])
    return []


class State(TypedDict):
    action: str
    approved: Optional[str]


def build_graph():
    def request_sanction(state: State):
        # The graph asks. It does not decide, and it cannot proceed until
        # somebody outside it answers.
        answer = interrupt({"action": state["action"]})
        return {"approved": answer}

    g = StateGraph(State)
    g.add_node("request_sanction", request_sanction)
    g.add_edge(START, "request_sanction")
    return g.compile(checkpointer=InMemorySaver())


def human_decides(action):
    """Stands in for a person. Returns (allowed, reason)."""
    if "production" in action and "rollback" not in action:
        return False, "denied: production change with no rollback plan"
    return True, "approved: bounded blast radius"


def run(action, boundary, graph, thread_id):
    cfg = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke({"action": action}, cfg)

    pending = read_interrupts(result)
    if not pending:
        return {"action": action, "paused": False}

    asked = pending[0].value                       # what the graph asked
    request = boundary.record_request(
        asked["action"], requester="agent:planner",
        reasons=[f"graph paused at interrupt {pending[0].id[:12]}"])

    allowed, why = human_decides(asked["action"])
    decision = boundary.record_decision(
        request, allowed, decider="human:reviewer", reasons=[why])

    # The refusal must actually stop the work; recording it is not enforcing it.
    resume = "approved" if allowed else "denied"
    final = graph.invoke(Command(resume=resume), cfg)

    return {"action": action, "paused": True, "allowed": allowed,
            "why": why, "request": request, "decision": decision,
            "final_state": getattr(final, "value", final),
            "independent": boundary.sanction_independent}


def main():
    # The package exposes no __version__; the installed distribution is the
    # only honest source, and this example's claims are pinned to it.
    print(f"langgraph {_pkg_version('langgraph')} "
          f"/ python {sys.version.split()[0]}")
    tmpd = Path(tempfile.mkdtemp(prefix="warrant-langgraph-"))
    boundary = Boundary(
        store=tmpd / "store",
        policy_text=("Production changes require a human sanction.\n"
                     "A refusal must name the missing precondition.\n"),
        requester_key=tmpd / "agent.key",
        decider_key=tmpd / "human.key")
    graph = build_graph()

    for i, action in enumerate([
            "deploy build 9f2c to production",
            "deploy build 9f2c to production with rollback to 8e1a"]):
        r = run(action, boundary, graph, f"thread-{i}")
        verdict = "ALLOWED" if r["allowed"] else "REFUSED"
        print(f"\n{verdict}: {action}")
        print(f"  reason    {r['why']}")
        print(f"  request   {r['request'][:16]}...")
        print(f"  decision  {r['decision'][:16]}...")
        print(f"  resumed   {r['final_state']}")

    report = boundary.verify()
    print(f"\nverify: ok={report['ok']} records={report['records']} "
          f"errors={report['errors']} warnings={report['warnings']}")
    print(f"independent sanction (two keys): {boundary.sanction_independent}")
    print(f"store: {tmpd / 'store'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
