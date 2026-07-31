# The approval boundary — record who asked, who sanctioned, and under which rule

The MCP server ([`../mcp-server/`](../mcp-server/)) lets an agent file its own
decisions. That channel has one structural blind spot: **the agent chooses what
to record.** Everything it produces is self-report.

This records the other side — the moment an action is sanctioned or refused by
someone who is not the agent. A human answering an approval prompt, a harness
allowing or blocking a tool call, a policy engine returning allow/deny. Two
things are true there and nowhere else: a party with different custody says yes
or no, and it says so against a stated rule.

```
record_request(action, requester)   ->  a propose, signed by whoever asked
record_decision(prior, allowed, decider) -> an accept/reject, signed by whoever sanctioned
```

Both cite a policy blob pinning the rules in force. The store then holds the
request, the sanction, the rule, and two signatures — none of which the
surrounding framework retains, because a checkpointer persists *state*, not
decisions.

Standard library only. Talks to warrant through the CLI as a subprocess, never
by importing internals, so `impl/` stays a dependency of nothing.

## Use it

```python
from warrant_approval import Boundary

b = Boundary(store=".warrants", policy_text="Production changes need a human.",
             requester_key="keys/agent.key", decider_key="keys/human.key")

req = b.record_request("deploy build 9f2c to production", requester="agent:planner")
dec = b.record_decision(req, allowed=False, decider="human:sre",
                        reasons=["denied: no rollback plan"])
```

Pass `check=<compiled ski@v1 blob hash>, runtime="ski@v1", verdict="pass"` to
give the decision a reason a stranger can **re-execute offline** instead of a
sentence they have to trust. That is the difference between demonstrating
plumbing and demonstrating the claim; compile one with
`impl/ski_policy.compile_check` (see [`../../docs/authoring-checks.md`](../../docs/authoring-checks.md)).

## Custody, honestly

`sanction_independent` is on every record and is computed from the **actual
keys**, never from the actor strings — naming an actor `human` costs nothing and
proves nothing. If the requester and decider share a key they are one custody
wearing two names, and the field says `False`. `warrant verify` says the same
thing from the other side: `binding unverified (no keyring): key X claims actor Y`.

Same-host custody is one custody. This code reports that; it cannot fix it.

## It records, it does not enforce

Filing `allowed=True` after denying the action stores a signed lie. A warrant
proves the record is intact and signed by the key's holder — never that the
prose is true in the world. The code that resumes the work is the code that must
honour the refusal.

## Bindings are examples, not supported surfaces

[`examples/`](examples/) holds two, deliberately kept small:

- **`pretooluse_hook.py`** — a Claude Code `PreToolUse` hook. The contract is
  JSON on stdin and stdout, so it needs no import and **is exercised by
  `tools/check.py`** on any clean checkout.
- **`langgraph_approval.py`** — a LangGraph `interrupt()` loop. Verified against
  langgraph 1.2.10. **Not** covered by `tools/check.py`: gating a check on an
  optional package would make every clean run report UNRUN, and an unrun check
  is not a passed one.

Why examples rather than packages — and why there will not be a CrewAI one —
is argued in [`../../docs/integration-study.md`](../../docs/integration-study.md).
Short version: the boundary is maintained here, the bindings are a page of code
in the caller's own loop, and a maintained adapter per framework is an M×N
obligation this project cannot staff.

## Tests

```bash
python3 integrations/approval/warrant_approval.py selftest
python3 integrations/approval/examples/test_pretooluse_hook.py
```

Both are wired into `python3 tools/check.py`. Each carries a negative control —
a tampered byte must flip the store to `ok:false` — because a test that only
ever sees the verifier say yes never asks whether it can say no.
