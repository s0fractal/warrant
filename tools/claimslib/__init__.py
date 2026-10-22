"""SPEC claims as Warrant 2 records (pilot W; SPEC.md generated since W5).

The sentences of SPEC.md are claims filed as ordinary Warrant 2 records in this
repository's own store, `.warrant/store/` (records/<id>.json, blobs/<sha256>).
The records are the source. SPEC.md and SPEC-CLAIMS.md are views generated from
them by `project`, and `check` refuses either file when it says anything else:
nothing in SPEC.md is written by hand.

A claim is a `duty` (holder: the author; owed_to: readers; condition: attest;
accept_by: the reviewer) whose statement is the sentence, with an ATTESTED
`transition` that discharges it. The transition's evidence is one claim blob
carrying the sentence, its witness cases (tests/<file>_test.py) and its mutants
(tests/mutants.py, ids M…, or tests/agent_mutants.py, ids A…); its `established`
repeats the sentence. A sentence with no witness or no mutant is filed UNBACKED:
the transition closes nothing and opens the question, and the blob says why it is
open (`reason`). UNBACKED is an allowed status, listed in SPEC-CLAIMS.md as an open
question. A claim that was BACKED at the base revision and is UNBACKED now needs a
proof of the loss: its backing was already broken at the base (a cited case or
mutant absent there; removing it in the same change as the downgrade is refused),
or a transition after it cites a counter blob (warrant-claims/counter@1: a patch that
is confined to the code the claim's own mutants alter (scopes compared by AST, and only
statements one of those mutants changes, AMEND 1 of #169), under which every cited witness
still passes and some case fails), directly or through a challenge against the
replaced claim, and `check` replays that blob. An informative sentence is
a transition with no duty, its reason in the blob. A supersession is a transition
whose `supersedes` names the claim it replaces. A retirement is a `challenge`
carrying the counter-evidence plus a transition superseding the claim. Nothing is
ever deleted.

What SPEC.md holds besides sentences is one more record: the **document**, an
ATTESTED transition with no duty whose single evidence blob
(warrant-claims/document@1) lists SPEC.md's parts in order: headings, references
to claims (each with the whitespace layout it had when filed) and the literal
gaps between them, which hold only spaces and line breaks and, at a line's start,
a list marker (`- `, `3. `) or a table rule (`| --- | --- |`). A new version supersedes the
previous one. A claim renders in its recorded layout while its text is the one
that layout was taken from; a changed or new sentence is filled to 80 columns
(unwrapped inside a fence or a table row); a retired one is left out.

    python3 tools/claims.py keygen --out SEED            # once per author; the seed stays out of git
    python3 tools/claims.py bind --key SEED --actor NAME  # bind an existing key, with its proof of possession
    python3 tools/claims.py accept --key SEED --actor codex --claim SPEC-4.2-3 [--all]
    python3 tools/claims.py challenge --key SEED --actor NAME --claim SPEC-4.2-3 --because '...' \
        [--counter-file COUNTER.json]                    # anyone bound; a counter must replay
    python3 tools/claims.py trust                        # the admitted bindings, as a trust/2 document
    python3 tools/claims.py pin --key SEED --actor NAME   # pin a role's key in .warrant/roles.json (reviewed)
    python3 tools/claims.py add --key SEED --stanza STANZAS.json
    python3 tools/claims.py add --key SEED --id SPEC-4.2-9 --text '...' --after SPEC-4.2-8 \
        --witness contract_test:H1 --mutant M01           # a new sentence names its position
    python3 tools/claims.py add --key SEED --id SPEC-1-6 --text '...' --after SPEC-1-5 --paragraph \
        --unbacked-because '...'
    python3 tools/claims.py supersede --key SEED --id SPEC-4.2-3 --text '...' --because '...'
    python3 tools/claims.py supersede --key SEED --id SPEC-7-1 --text '...' --because '...' \
        --unbacked-because '...' --counter-file COUNTER.json --challenge   # a BACKED claim losing its backing
    python3 tools/claims.py retire --key SEED --id SPEC-4.2-3 --because '...' --counter HEX
    python3 tools/claims.py project                      # regenerate SPEC.md and SPEC-CLAIMS.md
    python3 tools/claims.py check [--base REV | --no-base]
    python3 tools/claims.py audit --matrix M.json [--matrix A.json] [--counters DIR] [--refuse]
    python3 tools/claims.py why warrant/engine.py:729 [--json]   # the claims, obligations, goals a statement serves
    python3 tools/claims.py why --uncovered [FILE] [--json]      # the statements no cited mutant changes
    python3 tools/claims.py --selftest                   # every refusal of `check`, burned on a copy
    python3 tools/claims.py migrate --key SEED --because '...'   # once (W5): the first document, from SPEC.md
    python3 tools/claims.py heading --key SEED --section 4.2 --because '...'   # after changing that pin

The open circle of witnesses (README.md): `.warrant/trust.json` holds bindings that
certify themselves (the key signs {actor, public, purpose}), admitted by `check`
with no admin, the first binding of an actor winning, except that a name the
configuration gives a role is pinned in `.warrant/roles.json` (a key, reserved, or
collective; AMEND 1); `accept` files an acceptance
signed by an acceptor the duty names; a challenge by anyone bound that carries a
counter blob which replays lowers the claim's backing (COUNTERED), while only the
claim's author supersedes or retires it; WITNESSES.md is a ledger derived from the
records that grants nothing.

`audit` hunts the class of defect a counter blob proves, before a reviewer does
(the six counters of the Gemini deep review, 2026-10-22, were all of it): from a
matrix written by `tests/mutants.py --matrix` (every case's result under every
mutant), it names each BACKED claim and each mutant outside the claim's mutants
whose AST scopes overlap theirs, under which some case fails and every witness of
the claim passes, and prints the would-be counter. It is a report, not a refusal
of `check`: an own-file matrix (what CI's mutant run gives for free) leaves most
witnesses unknown, and the full one costs every suite under every mutant.

`why` follows the links the other way, from code to records: a statement (the unit
changed_statements counts) is served by the current claims BACKED in the view (`standing`:
a COUNTERED claim is named, never backing) citing a mutant that changes it, by the roadmap obligations whose serves or requires name those claims'
duties, and by the goals those obligations answer; `why --uncovered` lists the
statements of warrant/ and warrant_agent/ no cited mutant changes.

A claim's text is whitespace-normalized: runs of whitespace compare as one space.
Refusals are printed one per line as `REFUSED <CODE> <detail>`.

The code is one module per responsibility (tools/claimslib/): base, bindings, statements,
repo, model, counters, document, views, check, author, audit, why, report_selftest,
selftest, cli; the replay checker (G4) is replay, its acceptances as `check` reads them by_replay.
tools/claims.py is the command, and `import claims` (tools/ on the path) gives every name below.
"""
import os
import sys
from pathlib import Path

# The packages under test: $WARRANT_IMPL (a mutant's copy) or this checkout, before any import of warrant.
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(Path(__file__).resolve().parents[2]))

from .base import *          # noqa: E402,F401,F403
from .bindings import *      # noqa: E402,F401,F403
from .statements import *    # noqa: E402,F401,F403
from .repo import *          # noqa: E402,F401,F403
from .model import *         # noqa: E402,F401,F403
from .counters import *      # noqa: E402,F401,F403
from .document import *      # noqa: E402,F401,F403
from .views import *         # noqa: E402,F401,F403
from .check import *         # noqa: E402,F401,F403
from .author import *        # noqa: E402,F401,F403
from .audit import *         # noqa: E402,F401,F403
from .why import *           # noqa: E402,F401,F403
from .report_selftest import *   # noqa: E402,F401,F403
from .selftest import *      # noqa: E402,F401,F403
from .cli import *           # noqa: E402,F401,F403
from . import by_replay, replay   # noqa: E402,F401  (modules: replay.replay is a function of its own)
