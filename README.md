# Warrant

Warrant keeps work as signed records: what a thing is (one version of a claim,
an obligation, a pull request head), who accepted it, who objected and with
what counterexample. Each reader judges the same bytes under its own trust
(which keys are whose) and profile (who holds which role), and gets one answer:
what may be relied on now, what still waits, and for whom.

The core is small: one record envelope with four kinds (`schema`, `entity`,
`attest`, `challenge`), native lineage (a version names the one it replaces),
schemas that are records themselves, one guard (who must attest a version
before it counts), and one pure function, `assess`. The package `warrant` holds
the core and the `warrant` command and imports nothing but the Python standard
library and `cryptography`; `warrant_agent` is the interface for agents on top
of it (Python API, CLI, stdio MCP).

- **[Warrant in 15 minutes](https://github.com/s0fractal/warrant/blob/master/QUICKSTART.md)**:
  one obligation, its closure, an acceptance, a challenge; every command and
  output on the page is run by CI.
- Specification: [docs/V3.md](https://github.com/s0fractal/warrant/blob/master/docs/V3.md)
- Agents (Python API, CLI, stdio MCP): [AGENT.md](https://github.com/s0fractal/warrant/blob/master/docs/AGENT.md)
- What earlier generations were, and where they live: [HISTORY.md](https://github.com/s0fractal/warrant/blob/master/docs/HISTORY.md)
- The proof-space pilot (goal G9), outside the core: [PILOT.md](https://github.com/s0fractal/warrant/blob/master/docs/PILOT.md)

## Install

```bash
pip install --pre warrant-graph           # Warrant 3 (3.0.0a2); Python ≥ 3.10; depends on `cryptography`
pip install --pre "warrant-graph[mcp]"    # adds `warrant-agent-mcp` on the official MCP SDK (2.x, from 2.3)
```

This installs the commands `warrant`, `warrant-agent` and `warrant-agent-mcp`
and the packages `warrant` and `warrant_agent` (`pip install .` does the same
from a checkout). 3.0.0a2 is an alpha: pip installs it only with `--pre`, and the
record formats and interfaces may still change. `warrant-graph` 2.0.0a1 is
Warrant 2 and does not read Warrant 3 stores; `warrant-verify` (≤ 0.12.0) is the
retired 0.x generation.

## The model in one table

| Kind | Says |
| --- | --- |
| `schema` | the rules of one schema: its fields, its states, the minimal guard each state needs, who may enter which state |
| `entity` | one version of a thing in a lineage; `body.state` is its state |
| `attest` | an actor's statement about one record: an acceptance (`{"verdict": "accept"}`), a replay result |
| `challenge` | a counterexample or objection against one record |

A lineage's state is that of its newest version whose guard is met; a version
whose guard waits changes nothing yet. Two versions succeeding one version fork
the lineage. A challenge an actor with a role in the guard files (or one a
replayer reproduced) lowers reliance until a later version is accepted.
Reliance is `ELIGIBLE`, `PENDING`, `CHALLENGED` or `FORK`. A key authenticates;
it authorizes nothing: roles are the reader's profile.

## Status

**3.0.0a2 (alpha).** Warrant 3 replaced Warrant 2 in this repository on
2026-10-27 (3.0.0a1); 3.0.0a2 adds the review loop to the package.

- **What is backed.** The normative sentences of docs/V3.md are `claim@1`
  records, each with the test cases that witness it and the mutants of
  `tests/mutants.py` those cases kill; CI runs every mutant and refuses a
  survivor, and `python3 tools/claims.py check` holds every claim to the
  spec's text and the tests. A claim counts once the claims checker
  (`claims-checker`) has run its witnesses and mutants at a commit and signed
  its acceptance; `python3 tools/claims.py view` shows which claims are
  accepted, and whether at the current tree.
- **What is migrated.** The repository's Warrant 2 records were migrated, not
  re-signed: one `migration@1` attest of the migrator checker vouches for them,
  and the migration replays at the tag `history/warrant-2-2026-10-27`
  (docs/HISTORY.md).
- **Review.** Pull requests are reviewed by a model reviewer through the
  repository's review loop (signed records in the same store); no external
  security audit is recorded. There is one implementation, this Python one.

## Limits

A store cannot prove its own completeness, and every report says so
(`UNATTESTED`). An assessment has admission limits (records, bytes, references,
lineage depth, the depth of lineages requiring lineages): beyond one it is
refused, never answered in part. Not in this version: grants, schedules,
triggers, observe and compute conditions (a checker actor's attestation replaces
them), a merge rule for a forked lineage, threshold adoption, key rotation, and
any implementation besides this one. docs/V3.md §11 says what was dropped from
Warrant 2 and why; §12 what is open.

## The repository

The repository builds and checks Warrant with Warrant: the spec's claims, the
roadmap and the pull request reviews are records in `.warrant/records.jsonl`,
and a gate merges a pull request on a recorded acceptance. The review loop's
commands ship in the package (`warrant-review`, `warrant-gate`,
`warrant-claims`, `warrant-roadmap`, or `python -m warrant.<name>`), so that
another repository runs them on its own `.warrant/`; this repository's records
and machinery around them (`tools/`, `.warrant/`, `.github/`, `integrations/`)
are evidence behind the package, not part of it: `tests/boundary_test.py`
refuses a core module that imports it and a wheel or sdist that carries it.
[docs/REPOSITORY.md](https://github.com/s0fractal/warrant/blob/master/docs/REPOSITORY.md)
describes it, with the checks to run from a checkout;
[CHANGELOG.md](https://github.com/s0fractal/warrant/blob/master/CHANGELOG.md)
records what changed.

Licensed MIT. See [TRADEMARK.md](https://github.com/s0fractal/warrant/blob/master/docs/TRADEMARK.md) for the name.

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=s0fractal_warrant&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=s0fractal_warrant)
