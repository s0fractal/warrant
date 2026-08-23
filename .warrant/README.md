# The gate this repository runs on its own changes

One command, one artifact:

```sh
python3 tools/gate.py --base origin/master --head HEAD
```

It measures the change, pins those measurements into [`gate.wpl`](gate.wpl),
compiles the rule to a `ski@v1` term, and writes `gate-report.md` answering six
questions: what changed, who proposed it, which policy was in force, what was
checked, which reason you can re-run, and **what exactly would flip the verdict**.

The last one is why this exists. A gate that says "rejected" is a wall. A gate
that says `lines_added: 510 → down to 300 flips it` is a review.

## Where the rule comes from, and why it matters

In CI the gate runs from the **base** revision and reads its rule with
`--policy-from <base sha>`; the proposed change is diffed and never executed.

It took two rounds to get there, and both are worth knowing. The first version
ran the gate from the pull request's own checkout, so a change could rewrite
`gate.wpl` into a tautology and award itself an `ACCEPT`. Reading the rule from
the base fixed that — and the hole moved up a level: on `pull_request`, GitHub
takes the **workflow** from the change, so it could rewrite `agent-gate.yml`,
restore a head checkout and fabricate a comment. The defendant had stopped
editing the judge and was still editing the courtroom.

The trigger is therefore `pull_request_target`, which runs the workflow and
checks out the code from the base branch. That trigger is safe under exactly one
condition, which this workflow keeps: **the head is never executed.** It is
fetched as a git object — by `refs/pull/<n>/head`, because a fork's commit exists
under no other name here — then diffed and read for commit trailers, and nothing
else.

Both attacks are reproduced in `tests/gate_isolation.py`, which fails if either
ever stops being defeated, and which reads the workflow YAML too: a guarantee in
Python is worth nothing if the workflow stops obeying it.

The job that can comment on a pull request downloads an artifact and posts it. It
does not check out the repository, so write capability and repository code never
share a runner.

## What it is not

It does not judge whether a change is correct, safe or wanted, and it is not a
substitute for a reviewer. It says that a stated rule was applied to measured
facts, that the rule's bytes are pinned by hash, and that anybody can re-execute
the reason and get the same verdict — including someone who does not trust the
machine that produced it.

## Editing the rule

`gate.wpl` is the rule. Facts written as `{{name}}` are substituted from the
measurement; everything else is literal. WPL will refuse a policy that declares a
fact it never uses — an unused fact looks like it constrains the decision and
does not — and it has no arithmetic on purpose, so every operand is a literal or
a pinned fact and the verifier re-executes each step rather than trusting a
number the compiler worked out.
