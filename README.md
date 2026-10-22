# Warrant

Warrant records transitions of work: what was done, on what basis, what it
established, which exact conditions it closed, which questions it opened, and
what it leaves unestablished. The next agent reads a short capsule instead of a
transcript, and cannot credit the work with more than its grounds support.

Review is one use. Ordinary decisions, running services, periodic obligations
and reproducible computations are others.

- Contract: [SPEC.md](SPEC.md)
- What the rebuild retired, and where the previous generation lives: [HISTORY.md](HISTORY.md)
- Handing work to another agent (Python API, CLI, stdio MCP): [AGENT.md](AGENT.md)

## Install

```bash
pip install ./                # from a checkout; Python ≥ 3.10, depends on `cryptography`
```

This installs the commands `warrant` and `warrant-agent` and the packages
`warrant` and `warrant_agent`; `pip install "./[mcp]"` adds `warrant-agent-mcp`
on the official MCP SDK ([AGENT.md](AGENT.md)). There is no
release of this generation yet. The package published as `warrant-verify` (≤ 0.12.0)
is the retired 0.x generation.

### Compute

Attest and observe need nothing else. `compute` conditions are replayed by the
Sigma provider, the `sigma_provider` module of the `sigma-glyph` distribution
(PyPI `0.8.0`, provider identity `0caff793…`):

```bash
pip install "./[compute]"                    # warrant + sigma-glyph==0.8.0 from PyPI
# or, offline, from a wheelhouse built once:
pip download --no-deps -d wheelhouse 'sigma-glyph==0.8.0'
pip install --no-index -f wheelhouse ./ sigma-glyph
warrant compute --store S provider           # the provider's identity
```

A recipient accepts a provider by putting that identity in its profile's
`providers`; without an accepted, installed provider every REPLAYED basis is
UNVERIFIED.

## Start here

Two agents, one condition, one transition, one exact acceptance, one capsule:

```bash
W=$(mktemp -d); S=$W/store; T=$W/trust.json
warrant init --store $S
for a in claude codex; do warrant key --out $W/$a.key; warrant trust --trust $T --actor $a --key $W/$a.key; done

# claude takes on a condition that codex must accept
warrant file --store $S --key $W/claude.key --actor claude --type duty '{"statement":"parse() rejects empty input","holder":"claude","owed_to":["codex"],"accept_by":["codex"],"release_by":[],"condition":{"attest":{}},"schedule":null,"requires":[],"serves":[],"answers":null,"subject":null}'
# -> {"record": "<DUTY>"}

# claude records the work, with what it does not establish and a new question
warrant file --store $S --key $W/claude.key --actor claude --type transition '{"basis":"ATTESTED","evidence":[],"relied_on":[],"established":["parse(\"\") raises ValueError"],"residual":["non-ASCII input not examined"],"opened":[{"text":"reject whitespace-only input too?","scope":null}],"closes":[{"duty":"<DUTY>","act":"discharge","evidence":[]}],"subject":null,"supersedes":[],"triggers":[]}'
# -> {"record": "<TRANSITION>"}

warrant frontier --store $S --trust $T codex          # codex owes an acceptance
warrant accept --store $S --key $W/codex.key --actor codex <TRANSITION> --item 0
warrant capsule --store $S --trust $T <DUTY>          # result, basis, limits, when to revisit, evidence ids
warrant questions --store $S --trust $T               # the open question: nobody's duty yet
```

The same loop, with assertions, is `examples/1-work-loop.sh`.

A duty or transition body may omit its structural members; `warrant file` fills
them with empty values (`[]`, `null`; a transition's `evidence` becomes exactly
what its items cite), so the short body files the same record as the full one.
The meaning is never filled: a missing `statement`, `holder`, `owed_to`,
`accept_by`, `condition`, `basis`, `established`, `residual` or `closes` is
refused. `--id` prints only the new record id:

```bash
D=$(warrant file --id --store $S --key $W/claude.key --actor claude --type duty \
  '{"statement":"parse() rejects empty input","holder":"claude","owed_to":["codex"],"accept_by":["codex"],"condition":{"attest":{}}}')
```

## Scenarios

Each script uses only the installed `warrant` command and checks what it
claims. Run them all with `bash examples/run-all.sh`.

| Script | Shows |
| --- | --- |
| `1-work-loop.sh` | condition → transition with evidence and residual → exact acceptance → capsule and frontier; a new question leaves the result standing |
| `2-service.sh` | "the endpoint answers ok": the holder's "done" is refused; a named observer's probe record closes it; two hours later it is stale |
| `3-periodic.sh` | one period covered, one lapsed, one open; a past discharge covers no other period; every answer names its time |
| `4-computation.sh` | pause → resume → result, replayed by the recipient with the pinned Sigma kernel; a verified cycle makes `M M` impossible, while `K I (M M)` still computes |
| `5-changed-grounds.sh` | a changed file makes relying on a closure STALE; a counterexample makes it CHALLENGED; history stays DISCHARGED; an accepted revalidation restores it |

## The model in one table

| Record | Says |
| --- | --- |
| `duty` | a condition someone owes someone: attest, observe, or compute; optionally scheduled |
| `transition` | work done: basis, evidence, established, residual, opened questions, exact closures |
| `accept` | acceptance of one exact closure item (or of a transition's results) |
| `observation` | what an observer saw, when, with which probe |
| `grant` | permission to release named duties, attenuable |
| `challenge` | a counterexample against a closure or a result |

Assessment is a pure function of one view: the store's bytes read once, the
recipient's trust file and profile, a time, and the current revision. It
answers `reliance` (ELIGIBLE, STALE, CHALLENGED, SUPERSEDED, UNASSESSED,
NOT_CLOSED, ...), `frontier`, `questions` and `capsule`. A key authenticates; it
does not authorize. A computation is credited only by the recipient's own replay.

## Checks

```bash
for t in contract compute conditions assessment primitives records; do python3 tests/${t}_test.py; done
python3 tests/mutants.py        # every critical rule has a mutant that must fail its own case
python3 tools/claims.py check   # SPEC §1-§9 claims against SPEC.md, the tests and the view
python3 tools/claims.py --selftest
bash examples/run-all.sh        # needs `warrant` on PATH
for t in agent_handoff agent_write agent_compute agent_mcp; do python3 tests/${t}_test.py; done
python3 tests/agent_mutants.py  # needs [compute,mcp]
python3 examples/agent/acceptance.py --door mcp   # also python, cli
```

Green checks are not an independent review (AGENTS.md rule 3).

## Changing a normative sentence

The sentences of SPEC §1–§9 are claims filed as Warrant 2 records
in this repository's own store, `.warrant/store/`. **The records are the source;
[SPEC-CLAIMS.md](SPEC-CLAIMS.md) is a view generated from them**, and CI refuses
it when it says anything else. Each claim is a `duty` whose statement is the
sentence, discharged by an ATTESTED `transition` whose evidence names the
witness cases (`tests/<file>_test.py`) and the mutants (`tests/mutants.py`, ids
M…, or `tests/agent_mutants.py`, ids A…) that back it. A normative sentence that
no case and mutant back yet is filed UNBACKED with the reason it is open: it
closes nothing, and SPEC-CLAIMS.md lists it under "Open questions". An open
question is allowed; a stretched witness is not. `.warrant/claims.json` pins which sentences of which sections must be
claimed; `.warrant/trust.json` holds the claim authors' public keys (seeds stay
out of git). A change to a rule is made like this:

1. Edit SPEC.md.
2. Add the witness case and the mutant that burns it, in the same change
   (AGENTS.md rule 6).
3. File the claim, signed by an author key:
   `tools/claims.py add` for a new sentence (`--witness file_test:CASE --mutant MNN`,
   `--unbacked-because REASON` for a rule nothing backs yet, or
   `--informative REASON` for a sentence that states no rule),
   `tools/claims.py supersede --because ...` for a changed one (a BACKED claim
   that loses its backing also needs a counter blob, below: losing a proof needs
   a proof),
   `tools/claims.py retire --because ... --counter ID` for one that leaves.
4. `tools/claims.py project` to regenerate SPEC-CLAIMS.md, then `tools/claims.py check`.
5. Say the because in the commit message as well.

`check` refuses: a quoted sentence that is not in its section of SPEC.md
(compared modulo line wrapping); text of a pinned section that no claim quotes;
a pinned sentence with no claim; an UNBACKED claim that does not say why it is
open; a cited case or mutant that does not exist, a mutant id defined twice in
one harness, in both harnesses, or without its harness's prefix (M, A), a mutant
whose target is not a case of an existing test file, or one that targets none of
the cited cases; a record file not named by its id, non-canonical or
unauthentic; a standing challenge against a current claim; a projection that
differs from the regenerated one; and, against the base revision, a record that
was deleted or changed, a claim that disappeared without a record that
supersedes or retires it, or a claim BACKED at the base and UNBACKED now with
no counter blob that replays (below). Nothing is deleted: a retired claim
stays in the store with its counter-evidence. `tools/claims.py --selftest` burns
each of these refusals on a copy.

**A counter blob** is the proof that a BACKED claim's witnesses do not test its
sentence. It is a JSON file passed as `supersede --counter-file COUNTER.json`
(add `--challenge` to also file a challenge, carrying it, against the replaced
claim's discharge item, so that closure cannot later be accepted as if nothing
had been found):

```json
{"counter": "warrant-claims/counter@1", "claim": "SPEC-7-1",
 "against": "<transition id of the BACKED claim>",
 "patch": "<unified diff of warrant/ or warrant_agent/, paths a/warrant/... b/warrant/...>",
 "passes": ["compute_test:C5", "compute_test:C11"],
 "fails": ["compute_test:C4"],
 "why": "<why the patch makes the sentence false>"}
```

`check` replays it against the base: it applies the patch to a copy of the
packages, runs the named test files against the copy, and admits the loss only
if every case in `passes` passes, every case in `fails` fails, `fails` is not
empty, and `passes` covers every witness case the BACKED claim cited. The patch
changes behaviour, yet the claim's witnesses do not notice. `why` is shown, not
checked. To write one: make the edit that falsifies the sentence in a scratch
copy, keep it if the cited witnesses still pass and some case fails, and take
`diff -u` of the edited files with `a/` and `b/` prefixes. Name as few test files
as you can: each one is run once per check. A claim whose cited case or mutant
no longer exists has lost its backing on its own and needs no counter blob. A
challenge or a blob that is not a counter blob admits nothing
(`LOST_BACKING_WITHOUT_COUNTER`); a counter blob that does not replay is
refused with its reason (`COUNTER_NOT_REPLAYED`).

## Limits

Not in this version: threshold adoption, key rotation, P-256, policy
compilation, grants for acts other than release, goals as a distinct kind, and
any independent implementation besides this Python one. The process boundary
around the Sigma kernel isolates module names; it is not an OS sandbox. A view
cannot prove its own completeness, and every report says so. An assessment
has aggregate admission limits (records, bytes, `requires` edges, periods;
SPEC §9): beyond one it is refused, never answered in part.

Licensed MIT. See [TRADEMARK.md](TRADEMARK.md) for the name.
