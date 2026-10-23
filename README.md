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
for t in contract compute conditions assessment primitives records roadmap circle; do python3 tests/${t}_test.py; done
python3 tests/mutants.py        # every critical rule has a mutant that must fail its own case
python3 tools/claims.py check   # SPEC.md and SPEC-CLAIMS.md against the records and the tests
python3 tools/claims.py --selftest
python3 tools/roadmap.py check  # ROADMAP.md against the goal and obligation records
bash examples/run-all.sh        # needs `warrant` on PATH
for t in agent_handoff agent_write agent_compute agent_mcp; do python3 tests/${t}_test.py; done
python3 tests/agent_mutants.py  # needs [compute,mcp]
python3 examples/agent/acceptance.py --door mcp   # also python, cli
```

Both mutant runners first run each targeted test file once unmutated and refuse
with BASELINE_RED (exit 2) when a target case already fails there, since every
mutant on it would read KILLED. CI runs these checks as parallel jobs installed
from one wheelhouse; the mutants run in parts (`--shard K/N --matrix F`), and
the required `test` job joins them with `--merge`, which refuses unless every
mutant of the list was run in exactly one part and killed on its target.
A matrix names the whole tree it ran over: the git tree id of a clean checkout,
or a digest of every tracked and untracked file of a dirty one. Any change
anywhere makes it stale for `--merge` and `tools/claims.py audit`; re-run the
mutants with `--matrix` before an audit.

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
and in order, each on a line of its own; and the headings a reader sees in
the rendered SPEC.md (ATX `#` lines and setext underlines, inside fences too)
must be exactly those, so no sentence can render as a heading and no heading
inline. A title is still free text that no witness backs, so a
rule-shaped title is a review matter; the pin makes every change of one a
reviewed diff. To change a heading: edit its pin, then `tools/claims.py
heading --section N --because '...'`. A new section is the same two steps: pin
the section and its heading, then `heading --section N` files the heading
before the next pinned section (at the end if there is none); its first
sentence is placed with `add --after N` (§10, the agent interface, was added
this way).
`.warrant/claims.json` pins which sentences of which sections must be claimed;
`.warrant/trust.json` holds self-certifying key bindings (below, "The circle of
witnesses"; seeds stay out of git). **Do not edit SPEC.md**: `check` refuses it (`SPEC_NOT_PROJECTION`). A
change to a rule is made like this:

1. Add the witness case and the mutant that burns it, in the same change
   (AGENTS.md rule 6).
2. File the change, signed by an author key:
   - a changed sentence: `tools/claims.py supersede --id SPEC-4.2-3 --text '...' --because '...'`
     (a BACKED claim that loses its backing also needs a counter blob, below:
     losing a proof needs a proof);
   - a new sentence: `tools/claims.py add --id SPEC-4.2-9 --text '...' --after SPEC-4.2-8`
     (`--paragraph` to start a new paragraph after it, `--item` a list item;
     `--after 4.2` places it first under §4.2's heading) with `--witness
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
in it, holds a heading the pins do not name (or a pinned one twice, out of
order, or not on a line of its own), renders other headings than its own, places a current claim nowhere or twice, names a claim no record
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
computed the same way, from their own (old, new) edits applied to the file. And
the patch must change only statements that ONE of the claim's mutants changes:
a statement is a simple statement or a compound statement's header, compared by
AST and aligned between the two versions, and an inserted statement is a change
of its own. So the FAIL comes from the change in the claim's own code, never
from a foreign hunk next to a cosmetic local one, nor from another rule of the
same function (per function, 892 existing mutants were counters `check`
admitted, SPEC-3.6-7 by M29; per statement, 47 were, AMEND 1 of #169). The claim's mutants are the
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

A counter that replays proves the witnesses blind; the usual answer is to
re-back the claim, not to downgrade it: turn the patch into a mutant in
`tests/mutants.py`, cite (or write) the case whose assertion it fails, and
`supersede` with the same text, the counter as `--counter-file` (stored as
history in the transition's evidence) and a `--because` naming it. Against the
new claim the counter no longer replays: a cited witness fails under its patch.

**Hunting blind witnesses before a reviewer does.** `tests/mutants.py --matrix
M.json --matrix-tests all` (and `tests/agent_mutants.py --matrix A.json
--matrix-tests agent_handoff_test,...`) records every case's result under every
mutant; `tools/claims.py audit --matrix M.json --matrix A.json [--counters DIR]`
(files directly in `$TMPDIR` only) then lists, for each BACKED claim, each mutant whose scopes overlap those of the
claim's mutants, under which some case fails and every witness of the claim
passes, with the would-be counter blob (it replays when the mutant is confined
to the claim's scopes). Tier `line`: the mutant edits a line one of the claim's
mutants edits; tier `function`: only the same function, most often another rule
of it. A candidate is `confined` when its would-be counter replays: within the
claim's scopes and the statements of one of its mutants. CI writes own-file
matrices from its mutant run and prints the audit as a report; it refuses
nothing, since with one test file per mutant most witnesses are unknown. The
price of statement locality: a claim whose mutants miss the statement the
sentence turns on cannot be downgraded by a counter at all (SPEC-7-1's recorded
downgrade would be refused today, as would four of the six Gemini counters
against their claims as they stood); re-backing such a claim is the remedy, and
`audit` is what finds it.

**From a statement to its claims.** `tools/claims.py why FILE:LINE [--json]`
answers which claims, roadmap obligations and goals a statement of `warrant/`,
`warrant_agent/` or `tools/` serves: the statement owning that line (statement
granularity as for counters: a simple statement whole, a compound one by its
header), the mutants of both harnesses whose changed statements include it, the
claims citing those mutants that are BACKED in the view, the obligations whose
`serves` or `requires` name those claims' duties, and the goals they answer. A
claim a replaying counter lowered (COUNTERED) is never backing: `why` names it
with its challenge and counter, as evidence that the statement's witnesses were
blind, and `audit` skips it (re-backing is its remedy). Every consumer reads the
status SPEC-CLAIMS.md shows (`standing` in tools/claims.py). A blank line, a
comment or a docstring is `NOT_A_STATEMENT`; a statement no cited mutant changes
is `NO_CLAIM`. A mutant that only inserts code before a statement is shown and
not counted: it changes no existing statement. `why --uncovered [FILE|DIR]` lists
the statements of `warrant/` and `warrant_agent/` (or of FILE, or of the files under DIR) that no cited
mutant changes, the functions none of whose statements is covered (largest
first) and the counts: the map of code that no claim explains, and the input of
the next re-backing. It reads the files and records as they are; it refuses
nothing in CI.

**The repository's own hunt (G7).** The mutants above are written by hand and
each guards a rule; `tests/generated_mutants.py` makes mutants nobody chose, to
find what no witness notices. It applies fixed AST operators to every statement
of `warrant/`, `warrant_agent/` and `tools/claimslib/`: negate a condition,
swap a comparison (`<` and `<=`, `==` and `!=`, `in`, `is`), swap `and` and
`or`, replace a simple statement with `pass`, return `None`, `True` or an empty
value, flip a boolean, add or subtract 1 from an integer. A mutant's id is a
hash of its file, scope, the statement's syntax (statement units as `why` reads
them), the occurrence of that statement in its scope, the operator and the
operator's site, so an edit elsewhere keeps every id. `coverage` runs each test
file once, unmutated, under a standard-library line tracer (subprocesses
included), and refuses the map if a case fails; `run` gives each mutant only
the test files that execute its statement, cheapest first, and stops at the
first that notices it. Outcomes: KILLED (by a case, named), CRASHED (a test
file wrote no results), TIMEOUT, SURVIVED, NOT_RUN (no test executes the
statement) and INVALID. The controller, shards, merge and tree identity are
`tests/mutants.py`'s (`run_all` in hunt mode: any outcome is a result, and
`--merge` recomputes each one from its row instead of requiring KILLED).
`.github/workflows/survivors.yml` runs it weekly and on demand, in 16 parts, and
publishes the artifact `survivors`: `survivors.json` keyed by mutant id and
`report.md`. Compared with the previous run's list on the same branch, BLIND (a
mutant KILLED or CRASHED before survives now: a witness went blind; a
TIMEOUT depends on the runner's load and counts for neither side) and NEW (a
survivor of a statement the previous run did not have) are the signal. It is
never a check: not on pull requests, not required, and it fails only on its own
errors, never because something survives; it commits nothing.

A generated mutant is a discovery tool and never backs a claim: `claims.py`
knows the two curated harnesses only, and refuses a generated id as a claim's
mutant (`UNKNOWN_MUTANT`). A survivor is closed by a witness case that kills it
on an assertion and, where a SPEC sentence is concerned, a curated mutant the
claim cites. A survivor that changes no behaviour is not a blind spot: list it
in `tests/equivalent_mutants.json` with its reason, in a reviewed change; the
report then counts it apart, and names an entry some test notices
(`EQUIVALENT_NOTICED`) or whose id is gone (`EQUIVALENT_STALE`).

Every reader of a matrix that states what it says goes through one validation,
`check_matrices` in `tests/mutants.py`: `--merge`, `report` and `claims.py audit`.
A matrix is read only over this checkout's sources, with each row the current
definition of its mutant and labelled with the outcome its own runs give, and,
for `--merge` and `report`, with every id of the list exactly once; otherwise
nothing is written. The previous list is untrusted input too: one of another
shape, or whose commit is not an ancestor of this checkout's HEAD, is not
compared with, and the report says so instead of an empty comparison.

```bash
python3 tests/generated_mutants.py coverage --out MAP.json
python3 tests/generated_mutants.py run --coverage MAP.json --matrix G.json [--shard K/N] [ID ...]
python3 tests/generated_mutants.py report G.json --coverage MAP.json --out DIR [--previous OLD/survivors.json] [--audit A.json]
python3 tests/generated_mutants.py --selftest
```

## The circle of witnesses

Who may sign into this store is not decided by anyone. `.warrant/trust.json` is
a list of bindings, `{"bindings": "warrant-claims/bindings@1", "keys": [{"actor",
"public", "proof"}]}`, and each one certifies itself: `proof` is the bound key's
Ed25519 signature over the canonical JSON `{"actor", "public", "purpose":
"warrant-claims/binding@1"}`. `check` admits a binding mechanically, in file
order, iff the proof verifies under that key (`BINDING_PROOF_FORGED`; signed by
another key of the file: `BINDING_PROOF_OTHER_KEY`; absent: `BINDING_UNPROVEN`),
the actor id has SPEC-3-21's shape (`BINDING_ACTOR_SHAPE`), the key binds no
other actor (`BINDING_KEY_TWICE`), and the actor is not bound already to another
key: the first binding wins (`BINDING_ACTOR_TAKEN`). A second key for an actor
would need a record signed by the first one; rotation is not implemented, so it
is refused. Against the base revision, a binding admitted there must still be
admitted (`BINDING_REMOVED`): it can be neither dropped nor preceded by another
binding of its actor.

First-come holds only for a name nobody has given a role. A name the
repository's own configuration gives one (the claims' author, an acceptor, a
creditor: every actor `.warrant/claims.json` or `.warrant/roadmap.json` names,
or the refusal is `ROLE_UNPINNED`) is pinned in `.warrant/roles.json`, the way
a receiver's profile pins the keys it trusts. The pin is one of three values:

- a public key: a binding of that actor is admitted with exactly that key,
  else `BINDING_ROLE_KEY`;
- `null`, reserved: not bindable until a pin names its key,
  `BINDING_ROLE_RESERVED`;
- `"collective"`: a role no key signs as, never bindable,
  `BINDING_ROLE_COLLECTIVE`.

Today `claude` and `codex` are pinned to their keys, `s0fractal` is reserved,
and `readers` is collective. `readers` is owed every claim (the public that
reads the spec), so its challenges would always count (SPEC §4.6); since no key
signs as it, none can exist. Who a role is changes only by a diff of
`roles.json` (`tools/claims.py pin`). Against the base, a pin that contradicts a
binding admitted there is refused (`ROLE_PIN_CONFLICT`), since a binding is
never removed. Taking a reserved role is three steps:

1. `keygen --out SEED --actor NAME --no-bind`;
2. `pin --key SEED --actor NAME`;
3. `bind --key SEED --actor NAME`.

What a binding grants is only "this key signs as this
actor" (SPEC §6); who may act is the duty's, and whose acceptance or challenge
counts is each receiver's profile (SPEC §4.6). A receiver may bind keys of its own
choosing for itself, outside the repository, in a trust/2 file named by
`$WARRANT_CLAIMS_TRUST` (CI sets none); `tools/claims.py trust` prints the
admitted bindings as a trust/2 file for `warrant --trust`.

```bash
python3 tools/claims.py bind --key MY.seed --actor NAME      # your binding, with its proof
python3 tools/claims.py accept --key MY.seed --actor codex --claim SPEC-4.2-3 [--claim ...] [--all]
python3 tools/roadmap.py accept --key MY.seed --actor codex --duty 57cf328ea761
python3 tools/claims.py challenge --key MY.seed --actor NAME --claim SPEC-4.2-3 --because '...' \
    --counter-file COUNTER.json
```

**Acceptance.** `accept` files an `accept` record of exactly a claim's closure
(transition, item 0, its evidence), signed by the acceptor's own key. It is
refused when the signer is not in the claim duty's `accept_by`
(`NOT_AN_ACCEPTOR`: an acceptance by anyone else admits nothing, SPEC §4.2 rule
5, in every profile), when the claim closes nothing (`NOT_A_CLOSURE`), when the
signer accepted it already (`NOT_PENDING`), or when a counter that replays
lowers it (`COUNTERED`); one refusal refuses the whole batch. `--all` takes every
BACKED claim awaiting the signer, none countered. `roadmap.py accept` does the
same for an obligation's filed closure. SPEC-CLAIMS.md and ROADMAP.md name who
accepted. Nobody can accept for an acceptor: the record is signed by its key.

**Counters from anyone.** A challenge against a claim's current transition,
filed by any actor whose binding is admitted (one added in the same change
included), that carries a counter blob which replays (the rules above) lowers
the claim's backing: SPEC-CLAIMS.md shows it COUNTERED and lists it among the
open questions, and it no longer counts as backed. Nobody's permission is
involved. A new challenge whose counter does not replay is refused
(`COUNTER_NOT_REPLAYED`). Without a counter that replays, a challenge by the
claim's author, or by an actor its duty is owed to or accepted by, stands and
`check` refuses it (`CHALLENGED`) until the author answers; one by anyone else
is a thesis: listed under "Challenges", it lowers and blocks nothing. A counter
lowers backing, never authorship: only a claim's author supersedes or retires
it, and only the document's author files its next version
(`LINEAGE_NOT_AUTHOR`). A claim's duty is held by its author, owed to and
accepted by whom `.warrant/claims.json` pins (`CLAIM_DUTY_TERMS`), and an
obligation's by whom `.warrant/roadmap.json` names (`OBLIGATION_TERMS`), so a
key anyone may bind cannot file a claim only its own accomplice has to accept.
The author answers a counter by re-backing the claim (a witness that sees the
patch) or by a downgrade that cites it.

**Acceptance by replay (G4).** A BACKED claim's backing is mechanical, so its
acceptance can be a replay. The **replay checker** is
[tools/claimslib/replay.py](tools/claimslib/replay.py). It is an actor whose id names
its code: `checker sha256:<H>`, where H is SHA-256 over
`canon({"checker": "warrant-claims/replay@1", "files": {"tools/claimslib/replay.py":
sha256(bytes)}})`, the form of the Sigma provider identity (SPEC §7). Its key is
pinned in `.warrant/roles.json`. `.warrant/claims.json` adopts it in `checkers`,
and a new BACKED claim's duty then names it as the only acceptor. A thesis
(UNBACKED or informative) keeps the pinned `accept_by`: a checker named in its
duty is refused (`CLAIM_DUTY_TERMS`). A duty is never superseded, so
`claims.py rehome` moves every BACKED lineage to a new duty that names the
checker. The old duty stays in the store, OPEN, as history; SPEC-CLAIMS.md,
`why` and the roadmap follow the lineage's current duty.

`claims.py replay` runs the checker at HEAD of a clean checkout:

- the exact tree is extracted (`git archive`);
- each cited witness file runs once, and every cited case must PASS;
- each cited mutant is applied to a copy, and a case of its test file **that
  the claim cites** must fail;
- the transition must be current and unchallenged, and its duty must name the
  checker.

Only then does it file `accept` with a replay report
(`warrant-claims/replay-report@1`: commit, tree, claim, every result) as
`support`. The view names such an acceptance for what it checked, "accepted by
replay of its witnesses and mutants at tree T (checker H)". It is not a
review, and says nothing about whether the sentence is true.

`check` reads every report against its claim (`CHECKER_REPORT_FAILS`, …). For
acceptances new since the base, it also reads the reported commit:

- an ancestor of HEAD with the reported tree;
- the claim in its store;
- no challenge against the claim (`CHECKER_ACCEPTED_CHALLENGED`);
- its replay.py hashes to H (`CHECKER_CODE_MISMATCH`: the same id with other
  code is another checker).

Pins that name a checker the checkout's code is not are `CHECKER_PIN_STALE`.
**Custody**: whoever holds the checker's seed can sign as it without running
it. CI's `replay` job runs `claims.py replay --verify`, which re-executes each
acceptance new since the base with its commit's own replay.py and refuses a
report it does not reproduce (`CHECKER_REPLAY_DIFFERS`). Codex reviews the
checker's code and the pin of its key once per version, not each claim.

```bash
python3 tools/claims.py rehome --key CLAIMS.seed --because '...'   # once per adopted checker
python3 tools/claims.py replay --key CHECKER.seed [--claim ID ...] [--jobs N]
python3 tools/claims.py replay --verify --base REV
```

**The witness ledger.** [WITNESSES.md](WITNESSES.md) is generated by `project`
from the records and the admitted bindings: per actor, claims authored,
acceptances filed and those later refuted (a counter against the accepted claim
replays now or a downgrade cites one, or the accepted closure was challenged
and then revalidated), challenges, counters filed (credited to the record that
cited one first), of those lowering a claim now or cited by a downgrade, and
re-backs. It grants nothing and no rule reads it; `check` refuses it only when
it is not the rendering (bytes: `WITNESSES_STALE`, `WITNESSES_MISSING`).

## The roadmap

Where the project is going lives in the same store as ordinary records, not in
SPEC.md: [ROADMAP.md](ROADMAP.md) is generated from them by `tools/roadmap.py
project`, and `check` refuses a stale or hand-edited one. No record type is
added. The terms are those of the ontology
(manifesto `artifacts/ONTOLOGY-FORMALIZATION-0.1.md`):

| Ontology | Recorded as |
| --- | --- |
| Goal (row 0041; the target G of §4.3) | a question opened with scope `roadmap:G<n>` by a vision transition. Opening assigns it to nobody (SPEC §3.2). It proves nothing: it sets the direction of path search. It is reformulated, shown met (the transition *establishes* its text) or withdrawn only by a transition that supersedes the vision transition, counted once the results acceptors in `.warrant/roadmap.json` accept it (SPEC §4.7) |
| Obligation (row 0041; §7.2, an open loop) | a duty whose `answers` names the goal. Settlement is a discharge, forgiveness a release by whom it is owed to. Repair is `impossible`, accepted by whom it is owed to, plus a compensating duty. A revalidation repairs a closure, not the obligation |
| Commitment (§7.3.1) | filing that duty: the holder narrows its own options. `requires` makes the narrowing visible: a duty cannot close before its prerequisites (SPEC §4.2, rule 4) |
| Purpose (row 0041) | `serves`, a purpose link that grants nothing; to a SPEC claim it names the claim's duty |
| Value (row 0041) | a SPEC claim and its latches: a constraint on admissible paths, not a roadmap item |
| Conclusion (§4.3, the backward cone) | a transition whose `relied_on` names the transitions whose results it uses |
| Ledger (§7.2) | the store and its assessment |

Desire (row 0041) and Intent (row 0033: pre-authorship, a direction toward an
act) are not recorded: once signed, a direction is authored and is a goal.
Meaning (row 0041) is not recorded either. §4.3 calls the target "Target
Intent"; that is the goal, not row 0033's Intent. `path G<n>` prints the goal,
the obligations that answer it and, under each, its prerequisites, with the
engine's disposition and what its frontier asks of the holder. When every
obligation of a goal that is still open is DISCHARGED, `path` adds a mark,
"obligations met, goal not shown met". This is the Forward Attack of §4.3: the
claims hold and the goal is not shown. Either the decomposition missed
something (§4.2: the gap is not empty), or the showing is still owed. The mark
is evidence, not a refutation.

## Limits

Not in this version: threshold adoption, key rotation, P-256, policy
compilation, grants for acts other than release, goals as a distinct kind, and
any independent implementation besides this Python one. The process boundary
around the Sigma kernel isolates module names; it is not an OS sandbox. A view
cannot prove its own completeness, and every report says so. An assessment
has aggregate admission limits (records, bytes, `requires` edges, periods;
SPEC §9): beyond one it is refused, never answered in part.

Licensed MIT. See [TRADEMARK.md](TRADEMARK.md) for the name.
