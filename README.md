# Warrant

Warrant records transitions of work: what was done, on what basis, what it
established, which exact conditions it closed, which questions it opened, and
what it leaves unestablished. The next agent reads a short capsule instead of a
transcript, and cannot credit the work with more than its grounds support.

Review is one use. Ordinary decisions, running services, periodic obligations
and reproducible computations are others.

The core is small: six signed record types and one pure function, `assess`,
that reads one view of a store (its bytes, the reader's own trust file and
profile, a time) and answers what may be relied on now, what is still owed and
by whom. The package `warrant` holds the core and the `warrant` command, and
imports nothing but the Python standard library and `cryptography`;
`warrant_agent` is an interface for agents on top of it.

- **[Warrant in 15 minutes](https://github.com/s0fractal/warrant/blob/master/QUICKSTART.md)**:
  one duty, its closure, an acceptance, a challenge; every command and output on
  the page is run by CI.
- Contract: [SPEC.md](https://github.com/s0fractal/warrant/blob/master/SPEC.md)
- Handing work to another agent (Python API, CLI, stdio MCP): [AGENT.md](https://github.com/s0fractal/warrant/blob/master/AGENT.md)
- What the rebuild retired, and where the previous generation lives: [HISTORY.md](https://github.com/s0fractal/warrant/blob/master/HISTORY.md)
- The proof-space pilot (goal G9), its contract and resolution layer, outside SPEC.md: [PILOT.md](https://github.com/s0fractal/warrant/blob/master/PILOT.md)

## Install

```bash
pip install --pre warrant-graph               # Python ≥ 3.10; depends on `cryptography`
pip install --pre "warrant-graph[mcp]"        # adds `warrant-agent-mcp` on the official MCP SDK
pip install --pre "warrant-graph[compute]"    # adds the Sigma provider (sigma-glyph==0.8.0)
```

This installs the commands `warrant` and `warrant-agent` and the packages
`warrant` and `warrant_agent`. The package published as `warrant-verify`
(≤ 0.12.0) is the retired 0.x generation.

Attest and observe need nothing else. `compute` conditions are replayed by the
Sigma provider, the `sigma_provider` module of the `sigma-glyph` distribution
(PyPI `0.8.0`, provider identity `0caff793…`; `warrant compute --store S
provider` prints it). A recipient accepts a provider by putting that identity
in its profile's `providers`; without an accepted, installed provider every
REPLAYED basis is UNVERIFIED.

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

## Status

**2.0.0a1 is an alpha**, the first publication of `warrant-graph`. A
pre-release may still change the record formats, the command line, the Python
API and the agent interface.

- **What is backed.** Every normative sentence of SPEC.md is a signed claim
  record. Of 361 sentences, 284 are BACKED: each names the test cases that
  witness it and the mutants those cases kill. 20 are UNBACKED, each with the
  reason it is still open, and 57 are informative.
  `python3 tools/graph.py path SPEC-<n>-<m>` answers for one claim, and
  `python3 tools/graph.py views` renders SPEC-CLAIMS.md, every claim with its
  witnesses and mutants, into `build/views/` (a build artifact, never
  committed; CI keeps it as the `views` artifact of each run). A change to a rule is filed
  as a new record that supersedes the old one and says why; the old one stays.
- **What is not.** Most of the code is exercised by tests but not tied to a
  claim. At 7c6d80b, 304 of the 2317 statements of `warrant/` (13%), and 431 of
  the 3980 statements of `warrant/` and `warrant_agent/` together (11%), are
  changed by a mutant that a BACKED claim cites (`tools/claims.py why
  --uncovered`). Raising that is the open goal G6. The other open goals,
  among them an agent with no preparation using Warrant correctly (G2) and
  admission of witnesses without an admin (G3), are records
  too: `python3 tools/graph.py path G<n>` follows a goal to its obligations.
- **Review.** Pull requests are reviewed by a model reviewer through the
  repository's review loop (signed records in the same store);
  no external security audit is recorded. There is one implementation, this
  Python one.

## Limits

Not in this version: threshold adoption, key rotation, P-256, policy
compilation, grants for acts other than release, goals as a distinct kind, and
any independent implementation besides this Python one. The process boundary
around the Sigma kernel isolates module names; it is not an OS sandbox. A view
cannot prove its own completeness, and every report says so. An assessment
has aggregate admission limits (records, bytes, `requires` edges, periods;
SPEC §9): beyond one it is refused, never answered in part.

## The repository

The repository also builds and checks Warrant with Warrant: SPEC.md is
generated from the claim records, the roadmap and the pull request reviews are
records in the same store, and a gate merges a pull request on a recorded
acceptance. That machinery (`tools/`, `.warrant/`, `.github/`) is evidence
behind the package, not part of it: `tests/boundary_test.py` refuses a core
module that imports it and a wheel or sdist that carries it.
[docs/REPOSITORY.md](https://github.com/s0fractal/warrant/blob/master/docs/REPOSITORY.md)
describes it, with the checks to run from a checkout;
[CHANGELOG.md](https://github.com/s0fractal/warrant/blob/master/CHANGELOG.md)
records what changed.

Licensed MIT. See [TRADEMARK.md](https://github.com/s0fractal/warrant/blob/master/TRADEMARK.md) for the name.
