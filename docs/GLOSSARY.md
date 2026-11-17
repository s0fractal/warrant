# Glossary

The words Warrant uses, in plain terms, with where each lives. A status word an
answer carries (ELIGIBLE, PENDING, STALE, UNATTESTED, ...) is explained by the
agent's `explain` operation (`warrant_explain` over MCP), which also says what it
does not establish.

## Records

- **record**: one signed line of the store. Four kinds: `schema`, `entity`, `attest`, `challenge`.
- **lineage**: the versions of one thing, each naming the one it replaces; its root is its first version.
- **version, leaf, effective**: a version is one entity record of a lineage; the leaf is the newest; the effective version is the newest whose guard is met.
- **guard**: who must attest a version before it counts: roles, a quorum, a verdict to match, lineages it requires.
- **acceptance**: an attest of verdict `accept`. An acceptance may name what its signer saw (`seen`), so a reader can tell what it did not see (its **horizon**).
- **challenge**: an objection or counterexample against one record; **counted** when its actor holds a role the receiver counts.
- **reliance**: whether a lineage may be relied on now: ELIGIBLE, PENDING, CHALLENGED, FORK, and beside a checkout STALE or PINS_NOT_CHECKED.
- **grounded**: a version and everything it rests on, transitively, is effective and ELIGIBLE.
- **frontier**: what waits for one actor: versions it may attest, its own pending ones, schemas it may back, what was asked of it.

## The reader's side

- **receiver**: the trust (which key is whose) and the profile (who holds which role) a store is read under. Each reader has its own; `.warrant/v3.json` is the publisher's.
- **identity of a store**: the root of its one `rules@1` lineage, signed under its own binding; not the `repository` string, which a store gives itself.
- **overlay**: several stores read as one under the reader's own receiver (`warrant_agent/overlay.py`), so a challenge one publisher never took in still counts for the reader who found it.
- **across**: one read over every repository registered in Home, each assessed alone under its own rules (`warrant across`).
- **resolve**: where the bytes a cited hash names are: present, found elsewhere, located, or missing (`warrant resolve`).
- **Home**: the operator's registry of this machine's repositories and identities (`warrant home`, [HOME.md](HOME.md)).
- **drift**: whether the files an acceptance pinned are still the bytes of a checkout; a claim whose files changed reads STALE.

## Pages a person reads

- **reader, desk**: browser pages in `site/` that read a store and assess it in the browser, with no server.
- **serve**: the same pages from a local server (`python -m warrant_agent.serve`), each a pure function of one store's assessment.
- **lens**: how a lineage page is laid out, kept as a `lens@1` record the reader chooses (`warrant_agent/lens.py`). Its card is data, never code.
- **scene**: a lineage drawn as a map, each visual channel bound to a named field, so the legend is derived, not drawn (`warrant_agent/scene.py`).
- **floor**: what every page shows whatever the lens: the state, the reliance, the counted challenges that stand, UNATTESTED.
- **changes, view**: what changed for a reader between two states of a store, and the comparison of two views of one lineage (`changes.py`, `view.py`).
- **fragile**: where attention went (others saw, accepted or reacted) and where one objection holds against it (`warrant_agent/fragile.py`).

## Voices and observations

- **observation**: a reader's signed word about a record that no guard counts: a reaction (`react`), a view (`seen`), an adoption of a lens (`adopt`) (`warrant_agent/observe.py`).
- **decline**: an attest of verdict `decline` with a reason, an actor's "I cannot" to what was asked of it; no guard counts it, and the frontier lists it apart from no answer.
- **voice, commons**: a store that trusts nobody and gives nobody a role, where anyone files a voice on any record with no rights against it (`warrant init --voices`, `warrant say`).
- **who a voice is**: the keys behind a name, not the name: two names on one key are one source (`warrant_agent/voices.py`).

## This repository's own loop

- **pr-head, duty, closure**: a pull request is a `pr-head@1` lineage (its duty); each pushed head a version; an obligation's closing version is its closure.
- **finding, replay**: a reviewer's finding is a challenge with a test; the replay checker reruns it at each head and files what it observed.
- **gate**: the workflow that merges a pull request on a recorded acceptance and green checks ([REPOSITORY.md](REPOSITORY.md)).
- **tier, solo, brake**: watched and constitutional paths need more acceptances or a longer window; solo is the gate merging after a window when no second model family reviewed; the owner's brake can revert a merge while its brake is open.
- **claims checker**: the actor that accepts a claim of the specification when its tests pass and its mutants are killed, naming the files it ran on.
