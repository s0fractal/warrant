# Warrant in 15 minutes

Warrant keeps work as signed records in one store. One pure function, `assess`,
reads the store under the reader's own trust (which keys are whose) and profile
(who holds which role) and answers what may be relied on now and what still
waits, and for whom. This page walks one example with the `warrant` command: an
obligation, the version that closes it, the acceptance it waits for, a
challenge, and the verdict changing. The contract behind each step is
[docs/V3.md](docs/V3.md).

The page is executable. CI runs every command block below, in order, in a fresh
directory, under `bash -eu -o pipefail` (`tests/quickstart_test.py`), and
compares what each block prints with the output shown after it, byte for byte.
One substitution is made first: the value of `assessment` reads `…` here. It
names the exact assessment, which includes the identity of the installed
engine's code, so it differs between installs.

Install it with `pip install --pre warrant-graph` (3.0.0a1, an alpha; Python 3.10 or
later; the only dependency is `cryptography`), or `pip install .` from a checkout.

## The four kinds of record

| Kind | Says |
| --- | --- |
| `schema` | the rules of one record schema: its fields, its states and the guard each state needs |
| `entity` | one version of a thing (an obligation, a claim, a pull request head) in a lineage |
| `attest` | an actor's statement about one record: an acceptance, a replay result |
| `challenge` | a counterexample or objection against one record |

Every record names its kind, actor, time, schema, the version it succeeds
(`lineage`), the records and blobs it rests on (`refs`) and its `guard`: who
must attest it before it counts.

## 1. A store, two signers, a trust and a profile

```sh setup
warrant init --store store
printf '%064x\n' 1 > alice.key
printf '%064x\n' 2 > bob.key
warrant trust --trust trust.json --bind alice=alice.key --bind bob=bob.key > /dev/null
cat > profile.json <<'EOF'
{"warrant": "profile/3", "roles": {"schema/author": ["alice"], "roadmap/acceptor": ["bob"]}}
EOF
id() { python3 -c 'import json, sys; print(json.load(sys.stdin)["record"])'; }
```

```output
{
 "store": "store"
}
```

The trust binds each key to its actor and authorizes nothing. The profile is
this reader's own: alice may write schemas, bob accepts roadmap work. Another
reader with another profile gets other verdicts from the same bytes.

## 2. The schemas

`bootstrap` files the five schemas this repository uses (claims, goals,
obligations, pull request heads, findings) as alice. A schema counts only when
enough `schema/author` actors stand behind it (here one).

```sh bootstrap
warrant bootstrap --store store --actor alice --key alice.key --trust trust.json --at 1000 | python3 -c 'import json, sys; print(len(json.load(sys.stdin)["schemas"]), "schemas")'
```

```output
5 schemas
```

## 3. An obligation, and the version that closes it

alice owes something. Its first version is `open`; the closing version, `done`,
carries the guard `obligation@1` requires for that state: one attest by a
`roadmap/acceptor` with `{"verdict": "accept"}`.

```sh obligation
o=$(warrant put --store store --actor alice --key alice.key --trust trust.json --at 1010 --kind entity --schema obligation@1 '{"state": "open", "statement": "the quickstart runs", "serves": []}' | id)
d=$(warrant put --store store --actor alice --key alice.key --trust trust.json --at 1020 --kind entity --schema obligation@1 --lineage "$o" --guard '{"quorum": 1, "roles": ["roadmap/acceptor"], "match": {"verdict": "accept"}, "requires": []}' '{"state": "done", "statement": "the quickstart runs", "serves": []}' | id)
warrant assess --store store --trust trust.json --profile profile.json --lineage "$o" | python3 -c 'import json, sys; r = json.load(sys.stdin); l = r["lineage"]; print(l["state"], l["reliance"], r["versions"][l["leaf"]]["guard"], r["versions"][l["leaf"]]["waiting"])'
```

```output
open ELIGIBLE PENDING ['1 attest(s) by roadmap/acceptor matching {"verdict":"accept"}']
```

The lineage is still `open`: the closing version is its leaf, but it is not
effective until its guard is met.

## 4. The acceptance

```sh accept
warrant attest --store store --actor bob --key bob.key --trust trust.json --at 1030 "$d" > /dev/null
warrant assess --store store --trust trust.json --profile profile.json --lineage "$o" | python3 -c 'import json, sys; r = json.load(sys.stdin); l = r["lineage"]; print(l["state"], l["reliance"], r["versions"][l["leaf"]]["accepted_by"])'
```

```output
done ELIGIBLE ['bob']
```

alice could not have done this herself: the version's own actor never meets its
guard.

## 5. A challenge

bob finds the work wrong after all. A challenge by an actor holding a role of
the version's guard counts, and while it stands the lineage cannot be relied on.
It does not rewrite the guard's verdict: the closure stays `done`, its reliance
drops.

```sh challenge
warrant put --store store --actor bob --key bob.key --trust trust.json --at 1040 --kind challenge --ref "$d" "{\"target\": \"$d\", \"statement\": \"the quickstart fails on Python 3.10\"}" > /dev/null
warrant assess --store store --trust trust.json --profile profile.json --lineage "$o" | python3 -c 'import json, sys; l = json.load(sys.stdin)["lineage"]; print(l["state"], l["reliance"])'
```

```output
done CHALLENGED
```

alice answers with a new version; once bob accepts it, the challenge no longer
stands (docs/V3.md §5).

## 6. The whole report

`assess` without `--lineage` prints the whole report: the snapshot digest, every
lineage, every version's guard, every challenge, the rejected lines, the actor
chains and the graph. `completeness` is always `UNATTESTED`: nothing shows that
the store holds every record that exists.

```sh report
warrant assess --store store --trust trust.json --profile profile.json | python3 -c 'import json, sys; r = json.load(sys.stdin); print(json.dumps({k: r[k] for k in ("assessment", "basis", "canonical", "completeness")}))'
```

```output
{"assessment": "…", "basis": {"MIGRATED": 0, "SIGNED": 9}, "canonical": true, "completeness": "UNATTESTED"}
```

## Next

- The rules, normatively: [docs/V3.md](docs/V3.md).
- Agents: `warrant-agent-mcp` serves the same operations over MCP ([AGENT.md](AGENT.md)).
- How this repository runs on its own records: [docs/REPOSITORY.md](docs/REPOSITORY.md).
