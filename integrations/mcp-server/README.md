# warrant MCP server — file decision records from any MCP client

Give an agent the ability to **file signed, hash-addressed decision records**
and to **verify a store** — with two lines of config. This is the counterpart
of [`integrations/mcp/`](../mcp/) (the sealing *proxy*, which records another
server's tool-calls from the outside): here the agent files its **own**
decisions, deliberately, as first-class warrants.

Standard library only, stdio transport, no MCP SDK dependency. Everything runs
through the warrant CLI as a subprocess (never imported internals), so the
server tracks exactly the released command surface.

## Config

Claude Code:

```bash
claude mcp add warrant -- python3 /path/to/warrant/integrations/mcp-server/server.py --store .warrants
```

Generic MCP client (Claude Desktop and most agent runtimes take this shape):

```json
{ "mcpServers": { "warrant": {
    "command": "python3",
    "args": ["/path/to/warrant/integrations/mcp-server/server.py",
             "--store", "/path/to/project/.warrants"] } } }
```

A relative `--store` resolves against the server process's working directory —
prefer an absolute path unless you know your host launches servers in the
project root. Options (each also an env var): `--store`/`WARRANT_STORE`,
`--key`/`WARRANT_KEY`, `--actor`/`WARRANT_ACTOR`, `--warrant-cli`/`WARRANT_CLI`
(a `warrant.py` path or an installed `warrant` binary; defaults to this
checkout's `impl/warrant.py`, else `warrant` on PATH).

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
python3 integrations/mcp-server/test_server.py
```

Spawns the real server over stdio and checks: initialize/tools list, filing a
propose and an accept carrying a real compiled `ski@v1` check, `show_reason`
re-executing that check, a clean `verify-report@v0`, fail-closed verification
of a missing store, and the negative control — one tampered byte in a stored
record must flip the report to `ok:false` with an `ERR` finding. Also wired
into `python3 tools/check.py`.
