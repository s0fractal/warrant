# Warrant in 15 minutes

Warrant 2 records work as signed records in a store. One pure function,
`assess`, reads one view of that store (its bytes, the reader's own trust file
and profile, a time) and answers what may be relied on now, and what is still
owed and by whom. This page walks one example with the `warrant` command: a
duty, the transition that closes it, the acceptance it needs, a challenge, and
the verdict changing. The contract behind each step is [SPEC.md](SPEC.md).

The page is executable. CI runs every command block below, in order, in a fresh
directory, under `bash -eu -o pipefail` (`tests/quickstart_test.py`), and
compares what each block prints with the output shown after it, byte for byte.
One substitution is made first: the value of `assessment_id` reads `…` here. It
names the exact view, which includes the identity of the installed engine's
code and of the optional compute provider, so it differs between installs.

Install it with `pip install --pre warrant-graph` (Python 3.10 or later; the
only dependency is `cryptography`). Without the optional compute provider,
reading commands print a one-line warning on standard error; nothing on this
page computes.

## The six records

| Record | Says |
| --- | --- |
| `duty` | a condition someone owes someone: attest, observe, or compute; optionally scheduled |
| `transition` | work done: basis, evidence, established, residual, opened questions, exact closures |
| `accept` | acceptance of one exact closure item (or of a transition's results) |
| `observation` | what an observer saw, when, with which probe |
| `grant` | permission to release named duties, attenuable |
| `challenge` | a counterexample against a closure or a result |

This page files a duty, a transition, an acceptance and a challenge. An
observation closes a duty whose condition is `observe` (`examples/2-service.sh`);
a grant lets someone release a duty they are not owed.

## 1. A store, two signers, one trust file

```sh setup
warrant init --store store
printf '%064x\n' 1 > claude.key
printf '%064x\n' 2 > codex.key
warrant trust --trust trust.json --actor claude --key claude.key
warrant trust --trust trust.json --actor codex --key codex.key
```

```output
{
  "store": "store"
}
{
  "actor": "claude",
  "public": "4cb5abf6ad79fbf5abbccafcc269d85cd2651ed4b885b5869f241aedf0a5ba29",
  "trust": "trust.json"
}
{
  "actor": "codex",
  "public": "7422b9887598068e32c4448a949adb290d0f4e35b9e01b0ee5f1a1e600fe2674",
  "trust": "trust.json"
}
```

A key file holds an Ed25519 seed in hex. These two are fixed so that every id
on this page is exact; make a real one with `warrant key --out FILE`, which
writes a random seed with mode 0600 and never overwrites a file. The trust file
belongs to the reader: it binds actor names to public keys. A key authenticates
a record; it does not authorize anything.

## 2. A duty

`claude` takes on a condition that `codex` is owed and must accept:

```sh duty
D=$(warrant file --id --store store --key claude.key --actor claude --at 1000 --type duty - <<EOF
{"statement": "parse() rejects empty input",
 "holder": "claude", "owed_to": ["codex"], "accept_by": ["codex"],
 "condition": {"attest": {}}}
EOF
)
echo "$D"
```

```output
4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff
```

`--id` prints only the new record's id, and `--at` sets the record's time (the
default is now). A duty or transition body may omit its structural members;
`warrant file` fills them with empty values (`[]`, `null`; a transition's
`evidence` becomes exactly what its items cite), so the short body files the
same record as the full one. The meaning is never filled: a missing
`statement`, `holder`, `owed_to`, `accept_by`, `condition`, `basis`,
`established`, `residual` or `closes` is refused.

Every reading command assesses one view: `--store`, the reader's `--trust`, a
time `--as-of` (default: now) and a `--profile` (default: one use, `act`). This
page reads at time 2000:

```sh open
view() { warrant "$1" --store store --trust trust.json --as-of 2000 "${@:2}"; }
view reliance "$D"
view frontier claude
```

```output
{
  "assessment_id": "…",
  "causes": [
    "disposition OPEN"
  ],
  "state": "NOT_CLOSED",
  "target": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
  "use": "act"
}
{
  "actor": "claude",
  "assessment_id": "…",
  "frontier": [
    {
      "duty": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
      "need": "close",
      "statement": "parse() rejects empty input"
    }
  ]
}
```

## 3. A transition that closes it

`claude` records the work: on what basis, what it established, what it leaves
unestablished (the residual), a question it opens, and the exact item it
closes.

```sh close
T=$(warrant file --id --store store --key claude.key --actor claude --at 1100 --type transition - <<EOF
{"basis": "ATTESTED",
 "established": ["parse('') raises ValueError"],
 "residual": ["non-ASCII input was not examined"],
 "opened": [{"text": "should whitespace-only input be rejected too?", "scope": null}],
 "closes": [{"duty": "$D", "act": "discharge", "evidence": []}]}
EOF
)
view reliance "$D"
view frontier codex
```

```output
{
  "assessment_id": "…",
  "causes": [
    "disposition OPEN"
  ],
  "state": "NOT_CLOSED",
  "target": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
  "use": "act"
}
{
  "actor": "codex",
  "assessment_id": "…",
  "frontier": [
    {
      "awaiting": [
        [
          "codex"
        ]
      ],
      "duty": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
      "item": 0,
      "last_acceptance": true,
      "need": "accept",
      "transition": "c470cd197169fbca7e6eb81bfc103ce50e1d61f1e921694a3681729f8206fa64",
      "waiting_for": [
        "codex"
      ]
    }
  ]
}
```

Filing the closure does not close the duty: the duty names `codex` in
`accept_by`, so it waits for that acceptance, and `codex`'s frontier says so.

## 4. The acceptance

`codex` accepts exactly item 0 of that transition:

```sh accept
warrant accept --store store --key codex.key --actor codex --at 1200 "$T" --item 0
view reliance "$D"
view capsule "$D"
view questions
```

```output
{
  "record": "0b7e15f11e3b3e893d8bc71ab3fa2578367edce9c03a0a87c578a72c49534927",
  "type": "accept"
}
{
  "assessment_id": "…",
  "causes": [],
  "state": "ELIGIBLE",
  "target": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
  "use": "act"
}
{
  "accept_by": [
    "codex"
  ],
  "assessment_id": "…",
  "basis": [
    "ATTESTED:claude"
  ],
  "capsule": "warrant/2",
  "challenges": [],
  "closed_by": [
    "c470cd197169fbca7e6eb81bfc103ce50e1d61f1e921694a3681729f8206fa64"
  ],
  "completeness": "UNATTESTED",
  "disposition": "DISCHARGED",
  "evidence": [],
  "holder": "claude",
  "kind": "duty",
  "limits": [
    "non-ASCII input was not examined"
  ],
  "owed_to": [
    "codex"
  ],
  "periods": null,
  "reliance": "ELIGIBLE",
  "revalidate_when": [],
  "revisit_because": [],
  "statement": "parse() rejects empty input",
  "target": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
  "use": "act",
  "waiting_for": []
}
{
  "assessment_id": "…",
  "questions": [
    {
      "opened_by": "claude",
      "owned": false,
      "question": "c470cd197169fbca7e6eb81bfc103ce50e1d61f1e921694a3681729f8206fa64:0",
      "scope": null,
      "taken_by": [],
      "text": "should whitespace-only input be rejected too?"
    }
  ]
}
```

The capsule is what the next agent reads instead of a transcript: the result,
its basis, its limits (the residual travels with it), the evidence by id, and
what the view cannot establish (`completeness` is always `UNATTESTED`: a view
cannot prove that nothing is missing from it). The opened question belongs to
nobody until a duty answers it.

## 5. A challenge

`codex` files a counterexample against the accepted closure:

```sh challenge
warrant file --store store --key codex.key --actor codex --at 1300 --type challenge - <<EOF
{"target": "$T", "item": 0, "statement": "parse(' ') is accepted", "evidence": []}
EOF
view reliance "$D"
view frontier claude
```

```output
{
  "record": "f1ec32f54e57f03f7f16e59831e3343f9aefcab3a680f75bcdd495163c3acd63",
  "type": "challenge"
}
{
  "assessment_id": "…",
  "causes": [
    "challenge f1ec32f54e57: parse(' ') is accepted"
  ],
  "state": "CHALLENGED",
  "target": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
  "use": "act"
}
{
  "actor": "claude",
  "assessment_id": "…",
  "frontier": [
    {
      "causes": [
        "challenge f1ec32f54e57: parse(' ') is accepted"
      ],
      "duty": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
      "need": "revalidate (CHALLENGED for act)"
    }
  ]
}
```

History is not rewritten: the duty stays DISCHARGED (the next step prints its
disposition). What changes is whether a present action may rely on it: it is
CHALLENGED, and `claude`'s frontier now asks for a revalidation. A revalidating transition, accepted again, restores
it (`examples/5-changed-grounds.sh`).

## 6. The same verdict from Python

The command line is a thin layer over the package. `assess` is a pure function
of the view it is given; its report holds every duty's disposition, and
`reliance` reads the present verdict from it:

```sh python
python3 - "$D" <<'EOF'
import json, sys
import warrant
report = warrant.assess(warrant.Store("store").snapshot(), warrant.Trust.load("trust.json"),
                        2000, warrant.profile())
print(report["duties"][sys.argv[1]]["disposition"])
print(json.dumps(warrant.reliance(report, sys.argv[1], "act"), indent=2, sort_keys=True))
EOF
```

```output
DISCHARGED
{
  "assessment_id": "…",
  "causes": [
    "challenge f1ec32f54e57: parse(' ') is accepted"
  ],
  "state": "CHALLENGED",
  "target": "4e62067041dd27a8a4675fd0a9ae2e442569e20d6ec16b81e84cdfabf0ac32ff",
  "use": "act"
}
```

## Where next

- [SPEC.md](SPEC.md): the contract, each normative sentence backed by a test
  and a mutant that breaks it, or marked as not yet backed.
- `examples/`: five scenarios through the installed command (a service probed
  by an observer, a periodic duty, a replayed computation, changed grounds).
- [AGENT.md](AGENT.md): the agent interface (`warrant-agent`, and
  `warrant-agent-mcp` with the `mcp` extra), for handing work to another agent.
