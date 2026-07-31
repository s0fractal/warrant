# Listings — where this project can be found, and what each one costs

**Status: nothing here has been submitted. This project is listed nowhere.** The
MCP server and the GitHub Action are both invisible outside this repository.
This file is the prepared work; every remaining step is a human's, and each one
is named.

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
| **Status** | Manifest written and **validated**; namespace auth and publish are the maintainer's |

`description` is capped at **100 characters** — the single most common rejection.
Ours is 96.

**What was actually verified, and what was not.** The manifest was POSTed to the
registry's own `POST https://registry.modelcontextprotocol.io/v0/validate`
endpoint and came back `{"valid": true, "issues": []}`. That endpoint checks
*shape*, and nothing else: the same endpoint returns `valid: true` for a manifest
naming `this-package-does-not-exist-xyzzy-9999` as its package. It does not
check that a package exists, that you own the namespace, or that the server
runs. Read the green as "the JSON is well-formed", never as "this is ready".

**The registry is itself labelled "currently in preview"** — breaking changes and
data resets are on the table. Listing there is cheap and reversible, but it is
not a stable address yet.

#### The blocker: `warrant-verify` does not ship this server

The manifest deliberately carries **no `packages` block**, because there is no
honest one to write. `pyproject.toml` ships six flat modules out of `impl/`, and
`integrations/mcp-server/server.py` is not one of them. Nor is the existing
`warrant-mcp` console script a substitute: that is `warrant_mcp`, the sealing
proxy, which records another server's tool-calls from the outside — a different
program with a different job. So today the only install path is a clone, and a
`packages` block claiming otherwise would be a manifest that lies.

Publishing as-is is legitimate and still worth doing: it lists the server and
points at the repository. It just does not give anyone the two-lines-of-config
install that is this channel's whole advantage.

**Closing that gap is a substantive change and was deliberately not made here.**
It is: move `server.py` to `impl/` (it cannot be shipped from `integrations/`
under the current `package-dir = {"" = "impl"}`), add it to `py-modules`, add a
console script, update `test_server.py` and the two READMEs that name the path —
and then cut a release, because none of it exists for users until it is on PyPI.
That is a new public command on a published distribution; it wants a version
bump, the release-surface gates re-run, and a maintainer's decision on the
command's name. Suggested name: `warrant-mcp-server`, deliberately distinct from
the existing `warrant-mcp`.

Once that release is out, the manifest gains this block and `version` bumps:

```json
"packages": [
  {
    "registryType": "pypi",
    "registryBaseUrl": "https://pypi.org",
    "identifier": "warrant-verify",
    "version": "<the release that ships the console script>",
    "transport": { "type": "stdio" },
    "runtimeHint": "uvx",
    "runtimeArguments": [
      { "type": "named", "name": "--from", "value": "warrant-verify" }
    ],
    "environmentVariables": [
      { "name": "WARRANT_STORE", "description": "Absolute path to the warrant store", "isRequired": false },
      { "name": "WARRANT_KEY",   "description": "Ed25519 signing key; generated next to the store if unset", "isRequired": false, "isSecret": true }
    ]
  }
]
```

That exact block also validated `valid: true` against the same endpoint, so the
shape is known good in advance.

**And it needs one more thing, easy to miss.** The registry proves you own a
PyPI package by looking for an `mcp-name:` string **in the package's README as
published to PyPI**:

> The MCP Registry verifies ownership of PyPI packages by checking for the
> existence of an `mcp-name: $SERVER_NAME` string in the package README (which
> becomes the package description on PyPI). The string may be hidden in a
> comment, but the `$SERVER_NAME` portion **MUST** match the server name from
> `server.json`.

So `README.md` — the one `pyproject.toml` points `readme` at — must contain:

```
<!-- mcp-name: io.github.s0fractal/warrant -->
```

The token must be followed by a newline, whitespace, an HTML tag, or `-->`.
A trailing period glued to the name breaks the match. This lands in the same
release as the console script; adding it now would put a marker in the README
for a listing that cannot yet be published.

#### Remaining manual steps — the registry

1. `mcp-publisher login github` — device-code OAuth, proves `io.github.s0fractal`.
2. `mcp-publisher publish` from `integrations/mcp-server/`.

Both are the maintainer's: step 1 authenticates as a person, step 2 is an
outward-facing publication (AGENTS.md §5).

### Every other directory

| Directory | Mechanism | Hard requirements | Verdict |
|---|---|---|---|
| **PulseMCP** | none needed | — | **Free.** Its submit page redirects to the official registry, which it ingests daily. Publishing above gets this one at no extra cost. |
| **Glama** | GitHub OAuth; maintainer proves write/admin on the repo | Optional `glama.json` whose only field is `maintainers` | **Free-ish.** Declares itself a superset of the official registry and ingests it. Full analysis builds the repo in a microVM from a Dockerfile we do not have, so expect a listing without a build score. |
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
