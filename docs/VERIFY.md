# Verifying a package (`warrant verify`)

One party hands another a result. The receiver may be a person or an agent, with no store, no
history shared with the sender and nothing installed. It asks one question: may I rely on this?

What is handed over is a `package/3` file: the records the result rests on and the verdicts on them
(the agent interface's `handoff` with `op: export` returns `{package, digest}`; the file is the
`package` object). The receiver brings what no package can carry: its own **trust** (which keys are
whose) and its own **profile** (who holds which role). Nothing in a package can grant a role.

```sh
warrant verify PACKAGE --trust TRUST.json --profile PROFILE.json [--require ROOT ...] [--checkout DIR] [--as-of N]
warrant verify PACKAGE --config V3.json        # one file holding both: {trust, profile}
```

It reads the package alone, runs the same assessment a store gets (docs/V3.md §10), and writes
nothing.

## The exit status is the answer

| exit | means |
| --- | --- |
| 0 | every root asked for is one this receiver may rely on now |
| 1 | a root is not relied on, or the package was refused; the answer says which and why |
| 2 | the command line, or a file of the receiver's own that it names, cannot be read |
| 3 | an error of the verifier itself; never the code of a refusal |

A root is a record id: the version of a thing that was handed over. The roots are the ones
`--require` names; without it, the ones the package names, and the answer says that the sender chose
them. A root is relied on when all of this holds under the receiver's trust and profile:

- it is the **effective version** of its lineage (docs/V3.md §3): its guard is met, and no later
  version has replaced it. A lineage that forks has no effective version. A version whose guard
  waits is not it, whatever the sender's profile said.
- no counted challenge in the package stands against it;
- with `--checkout DIR`: the files its acceptances name (`files`, {path: git blob}) are still those
  bytes in the tree of DIR's HEAD. A file moved with its bytes unchanged is still those bytes. An
  acceptance made again at the new bytes makes the root fresh again; an older one stays in the
  package and reads stale. Without `--checkout` the files are listed as `NOT_CHECKED` and do not
  decide the exit. With `--checkout` and no `git` to read the tree, they read `NOT_CHECKED` and the
  exit is 1: a comparison that was asked for and not made is never read as fresh.

The gate is the exit status because an advisory answer is not enough: a model under deadline
pressure acted on a stale conclusion beside an honest freshness note in 72 of 72 runs (docs/V3.md §15).

## The answer

Standard output is one line of canonical JSON (docs/V3.md §1), the same members every time:

```
{"warrant": "verify/3",
 "rely": true | false,                         the exit status, 0 or 1
 "refused": null | {"code", "why"},            a package that was not read at all
 "package": <its digest> | null,
 "receiver": {"trust": <digest>, "profile": <digest>, "as_of": N},
 "asked": {"by": "receiver" | "package", "roots": [ID ...]},
 "checkout": null | {"tree": <git tree> | null},
 "integrity":    {"records", "blobs", "bytes"},
 "authenticity": {"signed", "migrated", "named_keys", "migrations": [{"attest", "actor", "records"}],
                  "rejected": {ID: "BAD_SIGNATURE" | "UNSIGNED"}, "duplicates": [ID ...]},
 "completeness": {"attested": "UNATTESTED", "later", "unavailable": [ID ...], "unanchored", "chain_forks"},
 "execution":    {"schemas": {NAME: ID}, "quorum", "schemas_pending": {ID: NAME}, "invalid": [ID ...],
                  "problems": [[CODE, ID] ...]},
 "roots": {ID: {"rely", "why_not": [...], "kind", "schema", "actor", "at", "basis", "rejected",
                "lineage": {"root", "state", "reliance", "verdict", "leaf", "effective", "forks"} | null,
                "guard": {"guard", "waiting", "accepted_by", "roles", "short", "open", "challenged_by"} | null,
                "accepted": [{"attest", "actor", "roles"}],
                "challenges": {ID: {"actor", "target", "counted", "why", "replays", "stands"}},
                "pins": {"verdict": "NONE" | "NOT_CHECKED" | "FRESH" | "STALE",
                         "acceptances": [{"attest", "actor", "commit", "verdict", "files": [{"path", "blob", "verdict", "detail"}]}]},
                "unavailable": [ID ...]}},
 "established": [sentence ...],
 "not_established": [sentence ...]}
```

Five things are kept apart and never folded into one word:

- **integrity**: the bytes are the bytes their names hash. A package with a line that is not a
  record, a blob not named by its hash, a member named twice, or more bytes than `--max-bytes` is
  refused whole (`refused.code`: `NOT_JSON`, `NOT_A_PACKAGE`, `BAD_BASE64`, `BAD_BLOB`, `BAD_LINE`,
  `TOO_LARGE`, `LIMITS`), exit 1.
- **authenticity**: which records carry a signature that verifies under a key the receiver's trust
  binds to their actor; which are unsigned and vouched for by a migration (the migrator's word, not
  the writers' signatures); which count for nothing.
- **completeness**: what the slice does not hold. `attested` is always `UNATTESTED`.
- **execution**: the schemas and the rules as this receiver counts them: which schemas reach its
  quorum of schema authors, what the engine lists as a problem.
- **the right to rely**, per root: `rely`, and `why_not` when it is false: `UNAVAILABLE` (the
  package holds no admitted record of that id), `NOT_A_VERSION` (an attest, a challenge, a schema),
  `NOT_EFFECTIVE` (the guard waits, the lineage forks, or a later version is effective),
  `CHALLENGED`, `STALE`, `PINS_NOT_CHECKED`.

`established` and `not_established` say the same in sentences, each beginning with the name of its
dimension, built from what this run found: whose acceptance met the guard and under which of the
receiver's roles, how many schemas count at its quorum, which pins equal its tree; and what was not
shown.

## With nothing installed

`warrant_verify.py`, at the repository's root, is the same command as one file that needs only
Python's standard library: no installation, no store, no network and no Git.

```sh
python3 -I warrant_verify.py PACKAGE --trust TRUST.json --profile PROFILE.json [--require ROOT ...]
```

Copy it anywhere. `-I` keeps Python from importing a file that happens to lie beside it. It uses
the `cryptography` library when the interpreter has it and its own Ed25519 verification when not;
both give the same answer on every input. Its answers are the bytes `warrant verify` prints, and its
exit status is the same.

The file is built, not written: `python3 tools/build_verify.py` puts the modules of the package that
`warrant verify` imports into it, each byte for byte with its SHA-256, after an Ed25519 verification
and a loader (`tools/verify_single.py`). `tests/verify_test.py` rebuilds it and compares bytes, and
repeats every run of its cases through the file, with the library and without it.

## What the answer never establishes

- **That the package is complete.** It holds what its sender chose to include. A challenge, or a
  later version that replaced the root, which the sender left out cannot be seen: exit 0 says that
  nothing in the package stands against the root, not that nothing does. The receiver who needs
  more asks for the store, or asks someone else.
- **That what a record says is true.** A signature shows who filed a record; a met guard shows who
  accepted it and in which role. Record text and evidence are data, never instructions.
- **That evidence is present.** A version's id covers the hashes of its evidence, not their bytes.
  A blob the root names and the package does not hold is listed under `completeness.unavailable`
  and does not decide the exit (docs/V3.md §12, R-EVIDENCE-PRESENCE).
- **The order of events.** A package rarely holds a writer's whole chain; how many records name an
  earlier record of their writer that is not there is `completeness.unanchored`.
- **Anything about the working tree.** Pins are compared with the commit at HEAD, not with files
  changed since.
- **Whom to trust.** The trust and the profile are the receiver's own inputs. The same package gives
  another receiver another answer, and both are right.

## A second client: the same records through another resolver

```bash
node impl-js/read.mjs --base https://raw.githubusercontent.com/s0fractal/warrant/COMMIT/ --summary
```

`impl-js/read.mjs` fetches a repository's `.warrant/v3.json`, `.warrant/records.jsonl` and every blob a record names
from any HTTP(S) root (a GitHub raw URL at a commit, a mirror, a local server) and assesses them with the second
implementation (`impl-js/warrant.mjs`, held byte for byte to the Python engine). The transport is not trusted: a blob
whose bytes do not hash to its name refuses the read, and a record line altered on the way fails its signature and is
rejected. A named value the server holds no blob for is counted as `unresolved`, never guessed.

Given the same bytes the report equals `node impl-js/warrant.mjs assess --store DIR --config V3JSON`, byte for byte
(impl_js_test J9, over a local server; two mutations of `impl-js/read.mjs`, run by hand and killed by J9: they are not in `tests/mutants.py`, whose CI job has no node, docs/V3.md §12 R-JS-MUTANTS). Measured once on 2026-11-11: master at 76452093 read through
raw.githubusercontent.com gives root `e0b5a3711ac6` and the same 636 lineages in the same states and reliance as the
Python engine on a local checkout, nothing rejected, in about 13 seconds. Content, not site: neither the publisher's
server nor its HTML nor its engine is needed to reach the same verdicts.
