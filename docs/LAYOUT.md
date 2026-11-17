# What is where in this repository

This repository holds three things in one tree. The boundary between them is
enforced, not only described: `tests/boundary_test.py` refuses a core module
that imports anything outside the package, and a wheel or sdist that carries it.

## 1. The package (what `pip install warrant-graph` gives you)

| Path | What it is |
| --- | --- |
| `warrant/` | the core: records, the store, `assess`, the graph, the `warrant` command, and the review loop's commands (`warrant review`, `gate`, `claims`, `roadmap`) any repository can run on its own `.warrant/` |
| `warrant_agent/` | the interface for agents over the core: one backend (`api.py`) behind a Python API, the `warrant-agent` command and a stdio MCP server; reader pages, lenses and observations ([GLOSSARY.md](GLOSSARY.md)) |
| `warrant_verify.py` | one file, the standard library only, that verifies a handed-over package with no install ([VERIFY.md](VERIFY.md)). It is generated from `warrant/` by `tools/build_verify.py`; CI holds the two equal, so it is the same code, not a second implementation |

The package imports nothing but the Python standard library and `cryptography`.

## 2. This repository governing itself with Warrant

| Path | What it is |
| --- | --- |
| `.warrant/` | this repository's own store: its specification's claims, its roadmap, its pull request reviews, its rules |
| `tools/` | thin entry points (`gate.py`, `claims.py`, `review.py`, `roadmap.py`) that run the package's commands from a checkout: the merge workflow runs them from the base commit, so they decide nothing themselves. `build_verify.py` builds `warrant_verify.py`; `graph.py` answers queries and renders the views |
| `.github/` | CI, the merge gate's workflow, releases. Owner paths: only the owner merges a change to them |
| `integrations/` | the review waker that wakes a model reviewer on what is due, and the Claude Code plugin |
| `experiments/` | measurements kept as data with their scripts (adoption, union-on-forge), cited by roadmap closures |
| `tests/` | the suites, the mutants that show each claim's tests necessary, and the executable QUICKSTART |

## 3. Products built on the protocol

| Path | What it is |
| --- | --- |
| `site/` | the browser reader and desk: a store read and assessed in the browser, its verdicts and its pins checked against GitHub, with no server |
| `impl-js/` | the JavaScript implementation of the assessment the reader runs, held byte for byte to the Python one |
| `third_party/primitives/` | shared test vectors both implementations are checked against |

## Why one tree

One change of the protocol often touches the core, the reader and the gate at
once. In one tree it is one pull request, one review and one CI run; split
across repositories it would be three of each. The boundary test keeps the
package clean, so splitting stays possible when a consumer needs one part
alone.
