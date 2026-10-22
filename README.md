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
python3 tools/claims.py check   # SPEC.md and SPEC-CLAIMS.md against the records and the tests
python3 tools/claims.py --selftest
bash examples/run-all.sh        # needs `warrant` on PATH
for t in agent_handoff agent_write agent_compute agent_mcp; do python3 tests/${t}_test.py; done
python3 tests/agent_mutants.py  # needs [compute,mcp]
python3 examples/agent/acceptance.py --door mcp   # also python, cli
```

Green checks are not an independent review (AGENTS.md rule 3).

## Changing a normative sentence

The sentences of SPEC.md are claims filed as Warrant 2 records in this
repository's own store, `.warrant/store/`. **The records are the source;
[SPEC.md](SPEC.md) and [SPEC-CLAIMS.md](SPEC-CLAIMS.md) are views generated
from them**, and CI refuses either file when it says anything else. Each claim
is a `duty` whose statement is the sentence, discharged by an ATTESTED
`transition` whose evidence names the witness cases (`tests/<file>_test.py`)
and the mutants (`tests/mutants.py`, ids M…, or `tests/agent_mutants.py`, ids
A…) that back it. A normative sentence that no case and mutant back yet is
filed UNBACKED with the reason it is open: it closes nothing, and
SPEC-CLAIMS.md lists it under "Open questions". An open question is allowed; a
stretched witness is not. Everything else in SPEC.md (headings, the order of
the sentences, line breaks, list markers, table rules) is one more signed
record, the **document**: a version lists SPEC.md's parts in order, each
sentence by its claim id with the layout it had when filed, and a new version
supersedes the last. Its literal gaps hold spaces and line breaks and, at a
line's start, a list marker or a table rule, never a word. Headings are not
claims: `.warrant/claims.json` pins each section's heading line (and the
title, as section 0), and the document may hold only those lines, once each
and in order. A title is still free text that no witness backs, so a
rule-shaped title is a review matter; the pin makes every change of one a
reviewed diff. To change a heading: edit its pin, then `tools/claims.py
heading --section N --because '...'`.
`.warrant/claims.json` pins which sentences of which sections must be claimed;
`.warrant/trust.json` holds the claim authors' public keys (seeds stay out of
git). **Do not edit SPEC.md**: `check` refuses it (`SPEC_NOT_PROJECTION`). A
change to a rule is made like this:

1. Add the witness case and the mutant that burns it, in the same change
   (AGENTS.md rule 6).
2. File the change, signed by an author key:
   - a changed sentence: `tools/claims.py supersede --id SPEC-4.2-3 --text '...' --because '...'`
     (a BACKED claim that loses its backing also needs a counter blob, below:
     losing a proof needs a proof);
   - a new sentence: `tools/claims.py add --id SPEC-4.2-9 --text '...' --after SPEC-4.2-8`
     (`--paragraph` to start a new paragraph after it) with `--witness
     file_test:CASE --mutant MNN`, or `--unbacked-because REASON` for a rule
     nothing backs yet, or `--informative REASON` for a sentence that states no
     rule. The position is filed as a new document version;
   - a sentence that leaves: `tools/claims.py retire --id ... --because ... --counter ID`.
3. `tools/claims.py project` regenerates SPEC.md and SPEC-CLAIMS.md; then
   `tools/claims.py check`.
4. Say the because in the commit message as well.

A sentence renders in its recorded layout while its text is the one that
layout was taken from. A changed or new sentence is filled to 80 columns under
its line's indentation and list marker (unwrapped inside a fenced block or a
table row, where a fenced field line keeps its alignment); a retired one is left
out, with its line if nothing else is on it. The claim and its history stay in
the store and in SPEC-CLAIMS.md. `tools/claims.py migrate` filed the first
document version once (W5), from SPEC.md as it was at 849cbfa, and only because
its rendering reproduced that file byte for byte; it refuses to run again.

`check` refuses: SPEC.md or SPEC-CLAIMS.md that differs from its rendering; a
document version that is malformed, has a literal gap with anything but layout
in it, holds a heading the pins do not name (or a pinned one twice, or out of
order), places a current claim nowhere or twice, names a claim no record
states, puts a claim under another section's heading, or lacks a pinned
section's heading, and two current document versions; a pinned sentence with no
claim; an UNBACKED claim that does not say why it is open; a cited case or
mutant that does not exist, a mutant id defined twice in one harness, in both
harnesses, or without its harness's prefix (M, A), a mutant whose target is not
a case of an existing test file, or one that targets none of the cited cases; a
record file not named by its id, non-canonical or unauthentic; a standing
challenge against a current claim; and, against the base revision, a record
that was deleted or changed, a claim that disappeared without a record that
supersedes or retires it, or a claim BACKED at the base and UNBACKED now with
no counter blob that replays (below). Nothing is deleted: a retired claim stays
in the store with its counter-evidence. `tools/claims.py --selftest` burns each
of these refusals on a copy.

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
if the patch is confined to the scopes the BACKED claim's cited mutants change
(it changes at least one of them and no other), every case in `passes` passes,
every case in `fails` fails, `fails` is not empty, and `passes` covers every
witness case the claim cited. A scope is a function (qualified by its classes)
or a file's module-level code, and it counts as changed only if its AST changes:
a comment, whitespace or a docstring changes nothing. The mutants' scopes are
computed the same way, from their own (old, new) edits applied to the file. So
the FAIL comes from the change in the claim's own code, never from a foreign
hunk next to a cosmetic local one. The claim's mutants are the
repository's own statement of which code the sentence is about, so what the
replay proves is: under this patch, which alters the same code the claim's own
mutants alter, at least one case fails and every witness of the claim passes;
the witnesses are blind to a change in the code the sentence is about. `why` is
shown, not checked. To write one: in a scratch copy, make the edit that
falsifies the sentence inside the functions the claim's mutants alter and
nowhere else; keep it if the cited witnesses still pass and some case fails;
take `diff -u` of the edited files with `a/` and `b/` prefixes. Name as few test
files as you can: each one is run once per check. A claim whose cited case or
mutant was already absent at the base revision has lost its backing on its own
and needs no counter blob; removing the witness in the same change as the
downgrade is refused (`WITNESS_REMOVED_WITH_DOWNGRADE`), since a case renamed
away with its mutants would otherwise carry the downgrade through. A
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
