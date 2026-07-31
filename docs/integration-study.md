# Where the warrant stack should integrate next

**Status: a study with a working prototype. Nothing here is adopted.** No
independent gate ran. Every version number below was checked by executing
something on 2026-07-31; the command is named beside the claim, so a reader who
distrusts the conclusion can re-derive the input.

## The question, and the trap

An MCP server already exists (`integrations/mcp-server/`). It is the
protocol-shaped channel: one integration, every MCP client. The open question is
whether to add framework-level bridges, and to which.

The trap is that framework adapters are M×N. Ten half-maintained integrations
with no users is a known way to kill a small project, and this one has a bus
factor of one. So the default answer is **no adapters**, and a candidate has to
earn its place by reaching a decision point the protocol otherwise cannot see.

That gives a test with three parts, applied identically to all three candidates:

1. **Is there a decision point?** Not activity, not a state change — a moment
   where something is sanctioned or refused.
2. **Is the sanctioner independent of the agent?** A record of a choice the agent
   made and chose to report is self-report. Warrant's entire pitch against trace
   logs is that a log takes the agent's own JSON as fact; an integration that
   re-imports that assumption distributes a *weaker* claim under this project's
   name, which is worse than no integration.
3. **What does the contract cost to maintain?** A wire format is cheap and dated;
   a Python API is a standing obligation on somebody else's release schedule.

A fourth question turned out to matter as much as the first three, and it is
worth stating separately because it is easy to fake:

4. **Does the recorded reason re-execute, or is it prose?** An integration that
   files a warrant whose reason is a sentence demonstrates *plumbing*. One whose
   reason a stranger recomputes offline demonstrates the actual claim. Both look
   identical in a demo. Only the second is the product.

---

## Candidate 1 — LangGraph `interrupt()`

**Verified against `langgraph` 1.2.10** (latest on PyPI at 2026-07-31), CPython
3.14.6, in a throwaway venv. Version history read from
`https://pypi.org/pypi/langgraph/json`; API surface read out of the installed
package with `inspect.getsource`, not from documentation or memory.

### The hypothesis was right about the decision point

The brief's hypothesis — that the natural integration is not another
checkpointer but the human-in-the-loop interrupt — holds, and for a sharper
reason than "it is where the graph pauses". A checkpointer persists *state*. The
resume value is just a value inside that state, indistinguishable afterwards
from anything else the graph computed. Nothing in LangGraph retains **that a
different party sanctioned it, or under which rule**. That is precisely the gap
a warrant fills, and it is a decision point MCP cannot see: nothing the agent
elects to call produces it.

Confirmed by running: a node calling `interrupt({...})` halts; `invoke` returns
the pending interrupt; `Command(resume=...)` continues. The bridge sits entirely
in the caller's own loop and touches **no internals** — two public surfaces, one
to read the pause and one to answer it.

### But the read-path is being migrated right now

The object a bridge must read has changed shape four times. Three of these are
quoted from the `Interrupt` docstring **in the installed package**, which is the
strongest available evidence because it is the maintainers' own record:

| Version | Change to the interrupt read-path |
|---|---|
| 0.2.24 | `Interrupt` introduced |
| 0.4.0 | `interrupt_id` introduced as a property |
| 0.6.0 | `ns`, `when`, `resumable`, `interrupt_id` **removed** |
| 1.0 | `interrupt_id` deprecated in favour of `id` (`LangGraphDeprecatedSinceV10`) |
| 1.1 | `result["__interrupt__"]` **deprecated** in favour of a `GraphOutput` container with `.interrupts` (`LangGraphDeprecatedSinceV11`) |

The 1.1 change is the one that matters, and it is not historical — it is live.
In 1.2.10 **both return shapes exist simultaneously**, selected by a kwarg:

- `graph.invoke(state, cfg)` returns a plain `dict`; interrupts under
  `"__interrupt__"`.
- `graph.invoke(state, cfg, version="v2")` returns `GraphOutput`; interrupts
  under `.interrupts`, and dict-style access to it warns
  `LangGraphDeprecatedSinceV11`.

Both were executed; both behaviours are as described. So an adapter written
today must branch on the return type, and that branch is a permanent tax on
someone else's release cadence. The prototype isolates it in one function
(`read_interrupts`) specifically so its cost is visible rather than smeared
through the code.

**Honest correction to a tempting conclusion:** "the API moves too fast for a
thin adapter" is *not* supportable as a blanket claim. The churn 0.2 → 0.6 was
pre-1.0, and 1.0 shipped 2025-10-17 — the project has been post-1.0 for nine
months. The accurate statement is narrower and still decisive: the specific
surface a bridge reads is mid-migration *within* the stable major, and there is
no deprecation removal date published for the old shape.

### Reach and cost

- **Reaches:** LangGraph users who use `interrupt()`. Real, but one framework.
- **Contract:** a Python API. Two public names, but a Python API.
- **Breaks when:** the dict return shape is finally removed, or `Interrupt`
  loses another field as it did in 0.6.0.
- **Testable on a clean checkout:** **no.** This is the disqualifying practical
  fact. `tools/check.py` exits 2 on any UNRUN check by design ("an unrun check is
  not a passed one"). A check gated on `langgraph` being installed makes every
  clean run non-green; a check *not* gated makes the suite depend on a
  third-party package. Neither is acceptable, so a maintained LangGraph adapter
  would ship with its central claim permanently unexercised by the project's own
  gate.

---

## Candidate 2 — OpenTelemetry GenAI semantic conventions

**Verified against `opentelemetry-sdk` 1.44.0 and
`opentelemetry-semantic-conventions` 0.65b0** (installed 2026-07-31), plus the
`open-telemetry/semantic-conventions-genai` repository at `main`, fetched and
searched locally. Repository metadata from the GitHub API.

This is the incumbent — the thing the stack defines itself against. The
attraction is real: a bridge that emits a warrant alongside a span reaches
wherever telemetry already flows, asking nobody to change frameworks. It fails
the test on four independent grounds, any one of which would be sufficient.

### 1. There is no decision point to attach to

The GenAI conventions model **activity**: inference, embeddings, retrieval,
memory, tool execution. Searched the whole repository tree for `approval`,
`human_in_the_loop`, `sanction`, `authoriz`, `consent`. The only hit in any
model or documentation file is inside a demo script, where it is an argument to
a third-party framework's decorator (`@tool(approval_mode="never_require")`) —
an artefact of the framework being illustrated, not a convention. The nearest
thing is `gen_ai.evaluation.*` (score, label, explanation), which is *scoring*,
not *sanctioning*: it says how good an output was, never that anyone with
standing permitted it.

So there is nothing to bridge *to*. A warrant attached to a GenAI span would be
attached to a record of work performed, not of permission granted.

### 2. The attachment mechanism does not exist either

The obvious clean extension point is a `SpanProcessor` — a documented plugin
interface. It does not do the job, for a structural reason verified by running:

```
on_start  → receives a writable `_Span`   (outcome not yet known)
on_end    → receives a `ReadableSpan`     (outcome known, object immutable)
```

Attempting `span.set_attribute(...)` in `on_end` raises
`AttributeError: 'ReadableSpan' object has no attribute 'set_attribute'`.

A processor can therefore sign a finished span and write a warrant out-of-band,
but it **cannot put the warrant id back onto the span**. Correlation is one-way:
holding the warrant you can find the trace, holding the trace you cannot find
the warrant. For an audit trail that is the wrong direction — the auditor
arrives with the trace.

### 3. The namespace is mid-migration between repositories

Every one of the **60** `gen_ai.*` constants in the shipped
`opentelemetry-semantic-conventions` 0.65b0 is marked `Deprecated`. Not some —
all 60, counted programmatically. The deprecation text reads:

> Deprecated: Moved to the [OpenTelemetry GenAI semantic conventions repository](https://github.com/open-telemetry/semantic-conventions-genai).

That repository was **created 2026-05-05** — under three months old — has **zero
releases**, was last pushed the day before this study, and still carries a `TODO`
placeholder where its schema URL belongs. In its model tree, **177 of 177**
stability declarations read `stability: development`, OpenTelemetry's lowest
tier, and `docs/gen-ai/gen-ai-spans.md` states verbatim `**Status**:
[Development][DocumentStatus]`.

Churn is not hypothetical here: `gen_ai.system` was renamed to
`gen_ai.provider.name`, and the shipped package retains the old constant solely
to carry its own deprecation notice.

### 4. The deepest objection: it would sign the agent's self-report

Even granting the first three, the span is emitted **by the agent's own process,
with the agent's own credentials**. A warrant produced there is signed by the
key that process holds. It would prove the telemetry was not altered in transit
— worth something — while proving nothing about whether any independent party
agreed to anything.

That is the trace-log assumption with a signature stapled to it. Shipping it
under warrant's name would make the project's sharpest claim ("do not trust the
log, re-execute the reason") into marketing, because the thing being signed is
still the log. Reach is not free when what travels is a weaker claim.

**Verdict: declined.** Not "later" — the first two objections are structural, and
the fourth would remain true even if OTel added an approval convention tomorrow,
unless the signer's custody were separated from the agent's.

---

## Candidate 3 — the approval boundary itself

The third candidate is not another framework. It is the observation that
candidates 1 and 3 are the *same shape*, and that the shape — not either
binding — is the thing worth building.

Wherever an agent action is sanctioned by an independent party, the same four
facts exist: **what was asked, who asked, who decided, and under which rule.**
LangGraph's `interrupt()` is one instance. A harness tool-permission hook is
another. A policy engine returning allow/deny is a third. They differ only in
how those four facts are delivered.

So: build the boundary framework-free, and let bindings be examples.

The second binding is what proves this is not a rationalisation. Claude Code's
`PreToolUse` hook (documented at `https://code.claude.com/docs/en/hooks`,
checked 2026-07-31) is a **subprocess contract** — one JSON object in on stdin,
one out on stdout:

```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "..."}}
```

`permissionDecision` is one of `allow | deny | ask | defer`. Against the test:

1. **Decision point:** yes — explicitly a permission decision, with a reason
   field the contract already reserves.
2. **Independent sanctioner:** yes, and more strongly than LangGraph. The
   harness decides; the agent does not choose to file the record and **cannot
   suppress it**. This is the property the MCP server can never have, since
   there the agent elects to call `warrant_file_decision`.
3. **Contract cost:** a wire format. No import, no dependency, no version
   pinning — and, decisively, **testable on a clean checkout**, because a JSON
   contract can be exercised exactly as the harness exercises it.

That asymmetry against LangGraph is the whole argument, and it is now executable:
the hook binding is wired into `tools/check.py` and runs everywhere; the
LangGraph binding is not, and cannot honestly be.

---

## Ranking

| | Candidate | Decision point | Sanctioner independent | Maintenance surface | Reaches | Verdict |
|---|---|---|---|---|---|---|
| **1** | **The approval boundary (framework-free)** | yes, by construction | yes | none — stdlib only, owned here | anywhere with an approval step | **build this** |
| **2** | Harness permission hook (`PreToolUse`) | explicit allow/deny/ask | yes — agent cannot suppress | a JSON wire format | Claude Code users | ship as an example, tested |
| **3** | LangGraph `interrupt()` | yes, real | yes — a human | a Python API, mid-migration | LangGraph users | ship as an example, **untested by the gate**, say so |
| **4** | OpenTelemetry GenAI semconv | **none exists** | **no** — agent signs itself | a namespace changing repositories | everyone with telemetry | **declined** |

**Recommendation: build the boundary; adopt no framework adapter.**

The maintainer's hypothesis about LangGraph was right about *where* the decision
is and wrong about what to build there. The interrupt is genuinely the right
point. But the bridge to it is a page of code in the caller's own loop, and a
page of code is a documented recipe, not a package. Shipping it as a maintained
adapter would buy a little convenience and take on the M×N obligation
permanently — the next request is CrewAI, then AutoGen, then LlamaIndex, and the
answer to each has to be "no" for a reason that does not sound arbitrary. The
reason is: **we maintain the boundary, not the bindings.**

---

## What was built

`integrations/approval/` — around 300 lines, standard library only.

- `warrant_approval.py` — the boundary. `record_request` (who asked),
  `record_decision` (who sanctioned), `record_approval` (both, linked).
  Talks to warrant through the **CLI as a subprocess**, never by importing
  internals — the same choice `integrations/mcp-server/server.py` makes, and the
  reason `impl/` remains a dependency of nothing.
- `examples/langgraph_approval.py` — the LangGraph binding. Executed.
- `examples/pretooluse_hook.py` + `test_pretooluse_hook.py` — the hook binding.
  Executed, and wired into `tools/check.py`.

### The constraint, honoured

`impl/` imports nothing new. The dependency arrow points **into** the core and
never out of it: the boundary imports nothing from a framework, and the
framework-specific files live under `examples/` where they are optional by
construction. A candidate that required the core to import a framework would be
disqualified by construction; none of the three did, but only because the
boundary was designed to keep it that way.

### Custody is a first-class output, not a footnote

The value of this boundary is that the decider is independent. If the requester
and the decider sign with the same key they are **one custody wearing two
names**, and every claim of independent sanction collapses. So
`sanction_independent` is computed from the actual keys — never from the actor
strings, which cost nothing to write — and returned on every record. The
selftest asserts both directions: two keys report `True`, one key reused reports
`False`. `warrant verify` says the same thing from the other side, emitting
`binding unverified (no keyring): key <k> claims actor <a>`.

In both example bindings the two keys sit on one host, and the store says so.
Same-host custody is one custody; separating it is a deployment decision this
code can report on but cannot make.

### The reason re-executes — in one path, and only one

Per question 4 above, this is stated precisely rather than flatteringly:

- The **boundary selftest** files an approval whose reason is a compiled
  `ski@v1` term (`staging_only ∧ ¬customer_data`). The CLI re-executes it at
  filing time and **refuses to file at all** if the verdict does not reproduce,
  so the passing test is itself evidence of re-execution. An uncompiled `ski@v1`
  check is rejected rather than silently stored as text no verifier can run.
- The **two example bindings file prose reasons.** They demonstrate plumbing.
  A real deployment would compile its approval rule into a `ski@v1` check and
  pass the blob hash — the boundary already accepts one — at which point the
  refusal becomes re-executable by a stranger. The examples do not do this
  because inventing a plausible production policy would be the more dishonest
  choice: it would look like the stronger claim while resting on a rule nobody
  agreed to.

`warrant verify` marks the prose case `UNVERIFIABLE: reject with prose-only
reasons`, and the selftest asserts that it does. The distinction is visible in
the store rather than only in this document.

---

## Actual output

Framework-free selftest, wired into `tools/check.py`, no third-party package:

```
$ python3 integrations/approval/warrant_approval.py selftest
  ok    two keys are two custodies
  ok    refusal filed with distinct ids
  ok    refusal reports independent sanction
  ok    approval with a ski@v1 check files (verdict reproduced at filing)
  ok    the filed reason is a ski@v1 check, not prose
  ok    uncompiled ski@v1 check refused
  ok    decision links its request as prior
  ok    decision is a reject
  ok    both records cite the same policy
  ok    store verifies ok
  ok    records counted
  ok    prose-only reject is flagged UNVERIFIABLE
  ok    tamper actually changed a byte
  ok    one flipped byte makes the store fail
  ok    failure is reported as an error, not a warning
  ok    restoring the byte restores the verdict
  ok    same key is reported as ONE custody
  ok    empty action refused
  ok    non-hex prior refused
  ok    key inside the store refused

approval boundary selftest: ALL PASS
```

Hook binding, exercised as a real subprocess over the documented wire format:

```
$ python3 integrations/approval/examples/test_pretooluse_hook.py
  ok    hook exits 0 (it advises; it never crashes the agent)
  ok    echoes hookEventName as the contract requires
  ok    destructive command -> deny
  ok    refusal names the rule that matched
  ok    refusal carries the warrant id it filed
  ok    one request + one sanction filed (got 2)
  ok    filed as propose + reject (got ['propose', 'reject'])
  ok    the refusal links the request it answers
  ok    the decider is the harness, not the agent (got harness:pretooluse)
  ok    store verifies ok: 0 errors
  ok    one tampered byte flips the store to ok:false
  ok    benign command -> defer
  ok    a deferral files no record (2 -> 2)
  ok    non-shell tool -> defer (this rule set has no opinion)
  ok    unparseable input -> defer, exit 0
  ok    unusable store still denies (the RULE stands without the recorder)
  ok    and it does not claim a warrant it failed to file

pretooluse hook: ALL PASS
```

LangGraph binding, against a real installation in a throwaway venv:

```
$ ./venv/bin/python integrations/approval/examples/langgraph_approval.py
langgraph 1.2.10 / python 3.14.6

REFUSED: deploy build 9f2c to production
  reason    denied: production change with no rollback plan
  request   a243b9e4d2ffffb7...
  decision  c37e20640be400ff...
  resumed   {'action': 'deploy build 9f2c to production', 'approved': 'denied'}

ALLOWED: deploy build 9f2c to production with rollback to 8e1a
  reason    approved: bounded blast radius
  request   beb6f969e3e352d7...
  decision  265ded7e64804321...
  resumed   {'action': '...with rollback to 8e1a', 'approved': 'approved'}

verify: ok=True records=4 errors=0 warnings=5
independent sanction (two keys): True
```

The five warnings are `binding unverified (no keyring)` — the store correctly
declining to confirm that either key belongs to the actor it names. Without a
keyring that is the honest report, and it is left visible rather than suppressed.

Without LangGraph installed the example exits with a message naming the missing
package. Both paths were run.

---

## Limits, stated

- **It records; it does not enforce.** Calling `record_decision(allowed=True)`
  after denying the action stores a signed lie. Warrant proves integrity and
  custody, never that the prose is true in the world. In the hook binding the
  harness enforces and the recorder is best-effort: a filing failure **defers**
  rather than denying, because an audit trail that becomes an outage gets
  uninstalled. The test pins that behaviour, including that a failed filing does
  not claim a warrant id it never obtained.
- **Two keys on one host are still one custody.** Reported, not solved.
- **The example rule sets are toys.** Four regexes in the hook, one string match
  in the LangGraph example. They exist to make the boundary observable.
- **The LangGraph binding is not covered by `tools/check.py`** and will break
  silently when the dict return shape is removed. This is a deliberate,
  named gap, not an oversight — see the disqualifying fact under Candidate 1.
- **No independent gate ran.** Green suites are necessary and not sufficient;
  in this repository every real defect has been found with the suites green.
  Two assertions in these very tests were wrong when first written and passed
  vacuously — `prior` is a list, not a string, and `actor` is an object, not a
  string — which is the argument for the negative controls, not against them.

---

## The maintenance cost being recommended

**Take on:** `integrations/approval/warrant_approval.py` and the hook binding.
Standard library, no third-party contract, two checks in `tools/check.py` that
run on any clean checkout. This is close to the cheapest thing that could
demonstrate the claim, and its cost does not scale with the number of agent
frameworks in the world — which is the entire point.

**Do not take on:** a maintained adapter for any framework. The LangGraph file
is an example and should be labelled one forever. When someone asks for CrewAI,
the answer is the recipe, not a package.

**If the maintainer's time halved, drop the LangGraph example first.** It is the
only artefact here with an external version dependency, the only one the gate
cannot exercise, and the only one that will rot without anyone noticing. Its
argumentative work is already done and preserved in this document: it
demonstrated that the interrupt is a real decision point *and* that binding to
it costs a page of code — which is exactly why the recommendation is to keep the
boundary and not the binding. Deleting the file loses nothing but a
demonstration; keeping it while unable to run it would be the kind of claim this
repository exists to avoid.
