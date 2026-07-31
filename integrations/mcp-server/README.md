# warrant-mcp-server — file decision records from any MCP client

Give an agent the ability to **file signed, hash-addressed decision records**
and to **verify a store** — with two lines of config.

The code is [`impl/warrant_mcp_server.py`](../../impl/warrant_mcp_server.py);
this directory holds the registry manifest and this page. Standard library only,
stdio transport, no MCP SDK dependency. Everything runs through the warrant CLI
as a subprocess (never imported internals), so the server tracks exactly the
released command surface.

## Which one is this? (`warrant-mcp-server`, not `warrant-mcp`)

Two programs ship in the same distribution and their names are one word apart:

| Command | What it is | Wraps another server? |
|---|---|---|
| `warrant-mcp-server` | **this one.** An MCP *server*. The agent connects to it and files **its own** decisions, deliberately. | no — it refuses a downstream command |
| [`warrant-mcp`](../mcp/) | a sealing *proxy*. It sits between a host and **someone else's** MCP server and seals the tool-calls passing through, from the outside. | yes — it requires one after `--` |

`--help` on each says which you started, and neither answers to the other's
prefix (`allow_abbrev=False` on both). If you meant to record what an existing
server is doing, you want the proxy, and this is the wrong page.

## Where this is listed

**The official [MCP Registry](https://registry.modelcontextprotocol.io), as
`io.github.s0fractal/warrant`**, published 2026-07-31 and live — query it with
`?search=io.github.s0fractal/warrant`. PulseMCP and Glama ingest that registry,
so the entry propagates without a second submission.
[`LISTINGS.md`](../../LISTINGS.md) has the full state, including what is still
unticked and what the registry's green does and does not mean.

The listing that went live carried **no `packages` block**: at 0.7.1 the
distribution did not ship this server, so a clone was the only install path.
[`server.json`](server.json) here now names the PyPI package — and cannot be
published until **0.8.0 is on PyPI**, because the registry fetches
`pypi.org/pypi/warrant-verify/0.8.0/json` and looks for an
`mcp-name: io.github.s0fractal/warrant` marker in that release's README before
it will accept the claim.

## Install and config

```bash
pip install warrant-verify        # 0.8.0 or newer
warrant-mcp-server --store /abs/path/.warrants
```

Claude Code:

```
claude mcp add warrant -- warrant-mcp-server --store /abs/path/.warrants
```

Generic MCP client (Claude Desktop and most agent runtimes take this shape):

```json
{ "mcpServers": { "warrant": {
    "command": "warrant-mcp-server",
    "args": ["--store", "/path/to/project/.warrants"] } } }
```

From a checkout, without installing anything:

```bash
python3 impl/warrant_mcp_server.py --store .warrants
```

A relative `--store` resolves against the server process's working directory —
prefer an absolute path unless you know your host launches servers in the
project root. Options (each also an env var): `--store`/`WARRANT_STORE`,
`--key`/`WARRANT_KEY`, `--actor`/`WARRANT_ACTOR`, `--warrant-cli`/`WARRANT_CLI`
(a `warrant.py` path or an installed `warrant` binary; defaults to the
`warrant.py` sitting beside the module — `impl/` in a checkout, site-packages
once installed — else `warrant` on PATH).

## Tools

**`warrant_file_decision`** — file a `propose` / `accept` / `reject` /
`supersede` into the store; returns the warrant id (the record's hash) and a
summary. Subject is a file path, a hex64 hash, or inline `subject_text`;
`policy` (path or hash) pins the rules in force as `under`; `reasons` are prose;
a re-runnable reason is `check` + `runtime` (`cmd@v1`|`ski@v1`) + `verdict` —
a `ski@v1` verdict is re-executed at filing time and the filing is refused if
it does not reproduce. `accept`/`reject` normally answer a `prior` warrant and
inherit its subject and policy. The store is initialized on first use.

**`warrant_verify_store`** — verify every hash, signature and link; returns the
[`warrant.verify-report@v0`](../../README.md#machine-readable-output---json)
object exactly as the CLI emits it (`verify --store-mode --json`): closed
schema, `ok == (errors == 0)`, missing/uninitialized store fails closed
(`ok:false`). Takes an optional `store_path`.

**`warrant_show_reason`** — given a warrant id: its decision, actor, reasons,
and the verified `why` chain (`chain_verified:false` when a link is missing or
a signature fails). Every `ski@v1` check reason is **re-executed locally** and
the fresh verdict is returned beside the filed one (`reproduced: true|false`);
`cmd@v1` checks are not re-run (they name a command in an environment, not a
portable term).

## Trust model, honestly

- **The server signs with a local key.** If none is configured it generates one
  next to the store (never inside it — a store is an [evidence
  pack](../../EVIDENCE-PACK.md), and packs must not ship keys) and says so in
  the first filing's result. **Any process on the same host that can read that
  file can sign as this actor** — same-host custody is one custody, not a
  quorum. Pass `--key` to control custody yourself.
- A warrant proves the record is intact, signed by the key's holder, and that
  its `ski@v1` reasons re-execute to the claimed verdicts. It does **not**
  prove the agent's prose claims are true in the world, and it does not gate
  anything — the server files what it is asked to file.
- The MCP client decides what gets filed; a hostile client can file junk. Junk
  is still signed, hash-addressed junk: `verify` stays honest about integrity,
  not about wisdom.
- Reporting a vulnerability: [SECURITY.md](../../SECURITY.md).

## Tests

```bash
python3 tests/mcp_server.py
```

Spawns the real server over stdio and checks: initialize/tools list, filing a
propose and an accept carrying a real compiled `ski@v1` check, `show_reason`
re-executing that check, a clean `verify-report@v0`, fail-closed verification
of a missing store, and the negative control — one tampered byte in a stored
record must flip the report to `ok:false` with an `ERR` finding. Also wired
into `python3 tools/check.py`.

The same suite can be pointed at an **installed** copy instead of the checkout,
which is the only way to find out whether what PyPI ships actually starts:

```bash
python3 tests/mcp_server.py --server-cmd /tmp/tv/bin/warrant-mcp-server \
    --impl /tmp/tv/lib/python3.13/site-packages
```
