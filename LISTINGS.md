# Listings — where this project can be found, and what each one costs

**Status, 2026-08-01: one listing is live, and it now installs.**
`io.github.s0fractal/warrant` 0.8.0 is published to the official MCP Registry
with a real install path. The GitHub Marketplace step is **still unticked** — the
action remains invisible outside this repository.

> **This paragraph has now been wrong twice, in opposite directions.** It first
> said "nothing here has been submitted. This project is listed nowhere," and
> survived the publish that falsified it. It was then corrected to describe a
> 0.1.0 entry offering only a clone — and survived the 0.8.0 publish that
> falsified *that*, for most of a day. Both are the same defect: a status line
> outliving the event it describes. Recorded rather than overwritten, because
> this file's whole job is to say what is true outside the repository, and a file
> with that job should show its own error rate.

What the live entry offers, exactly:

| | |
|---|---|
| Listed | official MCP Registry, `io.github.s0fractal/warrant`, `status: active` |
| Version published | **`0.8.0`**, `isLatest: true`, published 2026-08-01T13:12:30Z |
| Install path it offers | **`pip`.** The manifest carries a `packages` block naming `warrant-verify` 0.8.0, transport `stdio` |
| | `pip install warrant-verify` |
| | `claude mcp add warrant -- warrant-mcp-server --store .warrants` |
| Ownership proven by | the `mcp-name: io.github.s0fractal/warrant` marker in the package README on PyPI — the registry reads `info.description` and requires that literal |
| Superseded entry | `0.1.0`, published 2026-07-31T18:19:25Z, `isLatest: false`. It carried **no** `packages` block deliberately: at 0.7.1 the distribution did not ship the server, so there was no honest package to name. It stays in the version history rather than being retracted |
| Verified how | the registry's own search API returned both records; a real MCP host (`claude mcp add` → `✔ Connected`) was driven before the first publish |
| Not verified | that anyone has found it, installed it, or run it. **Zero known users.** A listing is a shelf, not a reader |

**What closed the gap.** 0.8.0 ships `warrant-mcp-server` as a console script, so
`pip install warrant-verify` yields a working server. Publishing the manifest was
blocked until 0.8.0 was on PyPI — the ownership section below is the ordering
constraint, not a formality — and then blocked again on something more ordinary:
the working tree sat on a stale branch, so the file the publisher was asked for
was not the file on disk.

Two surfaces, in order of cheapness:

- **[Part 1](#part-1--the-mcp-server)** — the MCP server (`integrations/mcp-server/`).
- **[Part 2](#part-2--the-github-action-on-the-marketplace)** — the composite action (`action.yml`).

---

## Part 1 — the MCP server

### The directory that no longer takes submissions

`modelcontextprotocol/servers` is the obvious first stop and it is **closed**.
Its `CONTRIBUTING.md` says so verbatim:

> The README no longer contains a list of third-party MCP servers — that list
> has been retired in favor of the
> [MCP Server Registry](https://github.com/modelcontextprotocol/registry).

and, under "We don't accept":

> **New server implementations** — We encourage you to publish them to the MCP
> Server Registry instead.

**Do not open a PR there.** It will be closed. Most third-party guidance still
describes the old community list; it is out of date.

### The one that matters: the official MCP Registry

| | |
|---|---|
| **Mechanism** | `mcp-publisher` CLI (`brew install mcp-publisher`, or a release tarball) |
| **Manifest** | [`integrations/mcp-server/server.json`](integrations/mcp-server/server.json) |
| **Required fields** | `name`, `description`, `version` — that is all the schema demands |
| **Namespace** | `io.github.s0fractal/*`, proven by GitHub OAuth device flow |
| **Status** | **PUBLISHED at manifest version `0.8.0`** on 2026-08-01, `packages` block naming `warrant-verify` 0.8.0. The earlier `0.1.0` publish (2026-07-31, no `packages` block) remains in the version history as `isLatest: false` |

`description` is capped at **100 characters** — the single most common rejection.
Ours is 96.

**What the registry's green means, and what it does not.** The manifest was
POSTed to the registry's own `POST https://registry.modelcontextprotocol.io/v0/validate`
endpoint and came back `{"valid": true, "issues": []}`. That endpoint checks
*shape*, and nothing else. Re-measured on 2026-07-31 against the current
`0.8.0` manifest and against a copy of it with the package identifier replaced
by `this-package-does-not-exist-xyzzy-9999` at version `1.2.3`:

```
$ curl -sS -X POST https://registry.modelcontextprotocol.io/v0/validate \
    -H 'Content-Type: application/json' --data @integrations/mcp-server/server.json
{"valid":true,"issues":[]}

$ # same manifest, identifier replaced with a package that does not exist
{"valid":true,"issues":[]}
```

**Both are `valid: true`.** The endpoint does not check that the package exists,
that you own the namespace, or that the server runs; the ownership and existence
checks happen at `publish`, against a token you had to authenticate to get. Read
the green as "the JSON is well-formed", never as "this is ready" — a manifest
that validates can still be a manifest naming nothing.

**The registry is itself labelled "currently in preview"** — breaking changes and
data resets are on the table. Listing there is cheap and reversible, but it is
not a stable address yet.

#### The blocker that was published around, and how 0.8.0 removed it

The first manifest to go live carried **no `packages` block**, because at 0.7.1
there was no honest one to write: `pyproject.toml` ships flat modules out of
`impl/`, and the server lived in `integrations/mcp-server/server.py`, which is
not one of them. Nor was the existing `warrant-mcp` console script a substitute:
that is `warrant_mcp`, the sealing proxy, which records another server's
tool-calls from the outside — a different program with a different job.

So for one day the live entry listed the server and pointed at the repository,
and a clone was the only install path it offered. That was honest and it was the
weak version: the two-lines-of-config install is this channel's whole advantage,
and the entry did not have it. Registry entries are mirrored by PulseMCP and
Glama, so the weak version propagates — which is why the re-publish was worth
doing rather than waiting for a later release to carry it.

**0.8.0 closed it, and it is now the published entry.** `impl/warrant_mcp_server.py` is the module (moved there
because `package-dir = {"" = "impl"}` gives the flat namespace exactly one root
— a file under `integrations/` cannot be in the wheel at all), listed in
`py-modules`, and exposed as the console script **`warrant-mcp-server`**. The
name is the one this file proposed before the command existed, and the collision
with `warrant-mcp` is handled where it can be executed rather than only
described: both parsers set `allow_abbrev=False`, `warrant-mcp` refuses to start
without a downstream command after `--`, `warrant-mcp-server` **refuses one**,
and `tools/check_release_surface.py --selftest` asserts all of that against the
built wheel's own parsers.

The manifest in the tree now carries the block below, `version` bumped to
`0.8.0` to match:

```json
"packages": [
  {
    "registryType": "pypi",
    "registryBaseUrl": "https://pypi.org",
    "identifier": "warrant-verify",
    "version": "0.8.0",
    "transport": { "type": "stdio" },
    "environmentVariables": [ … WARRANT_STORE, WARRANT_KEY, WARRANT_ACTOR … ]
  }
]
```

**`runtimeHint: "uvx"` was dropped, and this is the interesting part.** A client
composes the runtime hint, the runtime arguments and then the *identifier* — and
the identifier is the distribution name, `warrant-verify`, not the console
script. Measured against the built 0.8.0 wheel:

```
$ uvx --from ./warrant_verify-0.8.0-py3-none-any.whl warrant-verify --help
An executable named `warrant-verify` is not provided by package `warrant-verify`.
The following executables are available:
- warrant
- warrant-anchor
- warrant-mcp
- warrant-mcp-server
```

The schema has no field that names which console script to run, so a
`runtimeHint` here would encode a command that does not start. It is omitted
rather than guessed — as it is in 262 of the 267 PyPI entries currently in the
registry. The command a human needs is in `websiteUrl`'s README and in the entry
text below; the manifest claims only what it can honestly claim, which is that
this server is in this PyPI package at this version.

**And the ownership marker, which gates the whole thing.** Verified against the
registry's **source**, not only its documentation —
`internal/validators/registries/pypi.go` and `mcpname.go` on `main`:

- `ValidatePyPI` fetches `https://pypi.org/pypi/<identifier>/<version>/json` and
  reads `info.description`, which for a `text/markdown` upload is the **raw
  README** of that exact release;
- `containsMCPNameToken` looks for the literal `mcp-name: <server-name>` —
  **one space after the colon** — and requires a trailing boundary
  (`isMCPNameBoundary`: end of content, any character outside `[A-Za-z0-9._/-]`,
  or the start of `-->` / `--!>`). A prefix match is rejected on purpose, so
  `…/warrant-pro` cannot satisfy a claim to `…/warrant`;
- a 404 on that URL is a hard failure with its own message — the version in the
  manifest **must already be on PyPI**;
- `registryBaseUrl` must be exactly `https://pypi.org`.

Measured on the published `warrant-verify` 0.7.1: `info.description` is 18 225
characters of raw markdown and contains **no** `mcp-name:` token. So a
`packages` block naming 0.7.1 would be rejected today.

`README.md` — the one `pyproject.toml` points `readme` at — therefore now
carries, in the "Use it from an MCP client" section:

```
<!-- mcp-name: io.github.s0fractal/warrant -->
```

on its own line. A trailing period glued to the name breaks the match; the
comment form is safe because the validator special-cases `-->`.

**And the marker is now gated rather than remembered.** `tools/doc_counts.py`
carries a port of `containsMCPNameToken`/`isMCPNameBoundary` and fails if
`README.md` loses the token, gains a glued period, or gets a second space after
the colon — all three demonstrated red. It has to be checked at the source file,
because the registry reads the README *as published to PyPI*: a marker deleted
here still publishes to PyPI perfectly happily, and only fails the registry
afterwards, for a release that has already shipped.

#### Remaining manual steps — the registry

**Order matters and is enforced by the registry, not by good manners.**

1. Cut and publish **0.8.0 to PyPI** — with the `mcp-name:` marker in the README
   that ships with it. Until this exists, step 3 fails with a 404 on
   `pypi.org/pypi/warrant-verify/0.8.0/json`.
2. `mcp-publisher login github` — device-code OAuth, proves `io.github.s0fractal`.
3. `mcp-publisher publish` from `integrations/mcp-server/`. This is a
   **re-publish** of an existing live entry, not a first listing; the registry
   takes the new version and marks it `isLatest`.

All three are the maintainer's: step 1 and step 3 are outward-facing
publications and step 2 authenticates as a person (AGENTS.md §5).

### Every other directory

| Directory | Mechanism | Hard requirements | Verdict |
|---|---|---|---|
| **PulseMCP** | none needed | — | **Free, and now in flight.** Its submit page redirects to the official registry, which it ingests daily; the 2026-07-31 publish should surface here without another step. **Not confirmed** — nobody has looked for the entry, so treat it as expected rather than observed. |
| **Glama** | GitHub OAuth; maintainer proves write/admin on the repo | Optional `glama.json` whose only field is `maintainers` | **Free-ish, same caveat.** Declares itself a superset of the official registry and ingests it, so the publish should propagate; unconfirmed. Full analysis builds the repo in a microVM from a Dockerfile we do not have, so expect a listing without a build score. |
| **punkpeye/awesome-mcp-servers** | PR | Alphabetical within category, one line per server | **Cheapest direct win.** Also syncs into Glama. Entry text below. |
| **mcpservers.org** | Web form at `/submit` — name, short description, link, category, contact email. Explicitly *"We do not accept PRs"* | none | **Worth it.** ~5 minutes. |
| **mcp.so** | Form at `/submit?type=server` — repository URL and name | Sign-in + review on the free tier | **Worth it.** ~5 minutes. |
| **Cline Marketplace** | GitHub issue from their template | Repo URL, a **400×400 PNG logo**, confirmation you tested setup in Cline | **Deferred.** We have no logo, and the template asks you to attest you tested it in Cline — which nobody has. |

#### Rejected, and why

- **`modelcontextprotocol/servers`** — closed to new servers, as quoted above.
  Rejected because submitting is impossible, not because it is unattractive.
- **Docker MCP Catalog** — requires a `Dockerfile` in the source repo and a
  `server.yaml` PR reviewed by Docker. Its licence gate (MIT/Apache-2.0, no GPL)
  we pass on MIT. Rejected for now because a container image is a second
  distribution artifact to keep in sync with PyPI, and a stale image is exactly
  the failure this project exists to make visible.
- **Smithery** — its three documented paths are an HTTPS URL (needs Streamable
  HTTP transport), an MCPB bundle, or a container listening on `$PORT`. A
  stdio server distributed via PyPI maps onto none of them. Rejected as a
  transport mismatch, not a quality judgement.
- **Continue Hub** — rejected as unverifiable. Its MCP blocks documentation page
  returns 404 and no primary source could be found describing current
  requirements. Revisit when it documents itself.

### The entry text

Reusable across the registry, the awesome-list and the two forms. **No adoption
claims: this server has no users, and nothing below says otherwise.**

This is the first thing most readers will ever see of this project, so the lead
is the differentiator and not the file format. **This is not audit logging.** An
audit log asks you to trust it; the point here is a verifier that recomputes the
argument instead.

> **warrant** — record an agent's decisions with a reason anyone can re-execute
> offline.
>
> The difference from a log is what verification does. A `ski@v1` reason is a
> content-addressed, deterministic, budget-bounded check, so `warrant_show_reason`
> **re-runs the check on your machine and hands you the fresh verdict next to the
> filed one**. You are not asked to believe the record; you recompute the claim
> and compare. Work and peak memory are bounded by the check's own budget, which
> is what makes re-executing a stranger's reason safe rather than reckless. No
> network is involved in any of it.
>
> Three tools. `warrant_file_decision` files a propose / accept / reject /
> supersede into a local store and returns the record's hash.
> `warrant_verify_store` verifies every hash, signature and link and returns a
> closed-schema JSON report. `warrant_show_reason` returns a decision's reasons
> with those checks re-executed.
>
> Standard library only: no MCP SDK, no network, no account, no database. The
> server drives the `warrant` CLI as a subprocess rather than importing its
> internals, so it tracks the released command surface and nothing else.
>
> `pip install warrant-verify`, then
> `claude mcp add warrant -- warrant-mcp-server --store /abs/path/.warrants`.
> (`warrant-mcp-server` is the server; the distribution's other MCP command,
> `warrant-mcp`, is a sealing proxy for somebody else's server — different
> program.)
>
> **What the signature is worth, and what it is not.** The server signs with an
> Ed25519 key held on the same host, generating one next to the store if none is
> configured and saying so in the first filing's result. **Any process on that
> host that can read that key file can sign as this actor** — same-host custody
> is one custody, not a quorum. Pass `--key` to hold custody yourself. So a
> warrant proves a record is intact, that it was signed by that key's holder, and
> that its `ski@v1` reasons re-execute to the claimed verdicts. It does not prove
> the agent's prose is true, and it gates nothing: the server files what it is
> asked to file. A hostile client can file junk, and junk is still signed,
> hash-addressed junk — `verify` is honest about integrity, not about wisdom. The
> re-executable reason is the part that survives not trusting the signer.

One-liner, for forms with a length limit (96 chars — under the registry's 100 cap
and the same string as `server.json`'s `description`):

> Record an agent's decisions with reasons anyone can re-execute offline — verify recomputes them.

`punkpeye/awesome-mcp-servers` line, in that list's format:

```
- [s0fractal/warrant](https://github.com/s0fractal/warrant/tree/master/integrations/mcp-server) 🐍 🏠 🍎 🐧 - Record agent decisions with a reason anyone can re-execute offline; the verifier recomputes the check rather than trusting the record.
```

The legend markers are deliberately incomplete: 🐍 Python, 🏠 local, 🍎 macOS,
🐧 Linux. **🪟 is omitted on purpose.** The server is stdlib-only and has no
obvious Windows obstacle, but it has been run on macOS and on `ubuntu-latest`
and nowhere else, and an untested platform claim in a directory entry is the
cheapest possible false claim to make.

---

## Part 2 — the GitHub Action on the Marketplace

`action.yml` has never been listed. Publishing is **instant and unreviewed** once
the requirements are met:

> Actions are published to GitHub Marketplace immediately and aren't reviewed by
> GitHub as long as they meet these requirements.

### Requirements, checked against the action as it stands

| Requirement | Status |
|---|---|
| Public repository | met |
| A single metadata file (`action.yml` or `action.yaml`) **at the root** | met — exactly one `action.yml`, at the root, is the only one in the repo |
| `name` unique across the Marketplace; must not collide with a GitHub user, org, or category | `Warrant verify` — **unverifiable in advance.** The release form validates it and says so before you publish; if it collides, rename there |
| `branding.icon` — a Feather **v4.28.0** icon from GitHub's supported list | met — `check-circle` is on the list |
| `branding.color` | met — `gray-dark` is one of the nine accepted values |
| Composite actions eligible | met — GitHub's own comparison table states composite actions can be published, unlike reusable workflows |
| README | **not required.** Recommended only. We have one |
| LICENSE | **not required** for Actions. (The "requirements for listing an app" page that search engines surface is about GitHub Apps and does not apply) |
| Semver release tag | **not required.** Recommended. `v0.6.0` already satisfies it |

`branding` is documented as *optional*, and whether the publish form hard-blocks
without it could not be confirmed from primary sources. It is present, so the
question does not arise.

**Nothing in `action.yml` needed changing.** It already carries both branding
fields, and both values are valid. This row of the job produced no diff, which is
the correct outcome rather than a missing one.

One caveat worth knowing before clicking: the docs also say *"you'll need to
ensure that the repository only includes the metadata file, code, and files
necessary for the action."* This repository is a protocol project with an action
in it, not an action repository. That sentence sits under Prerequisites rather
than under the enumerated requirements, and publication is automated and
unreviewed, so it is unlikely to block — but it is the one item that could
surprise, and it is not something to fix by deleting the project around the
action.

### The exact publish step

It is a checkbox on a release, and it is the maintainer's — it requires accepting
an agreement as the account owner and completing 2FA, neither of which is
delegable:

1. Open `action.yml` in the repository on github.com. A banner offers **Draft a release**.
2. Under **Release Action**, tick **Publish this Action to the GitHub Marketplace**.
   - The checkbox is **disabled** until the account owning the repository has
     accepted the **GitHub Marketplace Developer Agreement**. The form links to it.
3. Fix anything the validator flags until it shows **"Everything looks good!"**.
4. Choose a **Primary Category**, and optionally one secondary category. Two is the maximum.
5. Use the existing tag **`v0.6.0`**, give the release a title, and **Publish release**.
   **Publishing requires two-factor authentication.**

Reversible: un-ticking the box on each published release removes the listing.

### Pinning the action in the README — already done

The README's CI-gate example already reads `s0fractal/warrant@v0.6.0`, and
already tells the reader to pin **0.6.0 or newer** with the reason why. Nothing
was needed here.

This is recorded because the opposite was believed at the start of this work:
the checkout was sitting on a stale feature branch, where the example still said
`@master # or pin a release tag once one is cut`. `master` had moved on. Read
docs from the branch you are about to change, not from whatever the tree happens
to be on.
