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
