# warrant-mcp — seal your MCP server's actions into a verifiable evidence pack

Wrap any MCP server with one command. Every consequential tool-call (class A2 and
above) the agent makes gets sealed as a signed warrant: **what** was called,
**under which effect policy**, with the **result** as evidence and the previous
action as `prior`. The `.warrants/` store it produces is an
[evidence pack](../../EVIDENCE-PACK.md) — a stranger can verify the whole agent
session offline with `warrant verify`, trusting nothing but the tool.

This turns the [Air Canada demo](../../demos/air-canada/) from "here's a pack we
built" into "here's a pack **your agent** produces, live."

## Install

```bash
pip install .              # from the warrant repo — gives the `warrant` verifier
```

The proxy runs from the repo (`python3 integrations/mcp/warrant_mcp.py …`); it
imports the installed `warrant`. A `warrant-mcp` console command is a documented
follow-up (see [`../../PUBLISHING.md`](../../PUBLISHING.md)).

## Use

```bash
warrant keygen --out agent.key                    # once: the agent's signing key

python3 integrations/mcp/warrant_mcp.py \
    --store ./session \                            # the evidence pack lands here
    --actor coding-agent@acme \
    --key agent.key \
    --effects effects.json \                       # optional; see below
    -- <your MCP server command>                   # e.g. npx @modelcontextprotocol/server-github
```

Point your MCP host (Claude Desktop, an agent runtime) at *this* command instead
of the server directly. Traffic is forwarded untouched; sealing happens on the
side. When the session ends, verify it:

```bash
warrant --store ./session/.warrants verify        # 0 errors = the session is intact
warrant --store ./session/.warrants why <wid>     # walk the agent's actions
```

## What gets sealed

Each `tools/call` is classified A0–A4 by its **effects**, and only **A2+** is
sealed (read-only chatter stays out of the pack):

| Class | Examples | Sealed? |
|------|----------|---------|
| A0 read / list / search / get | `db.query`, `fs.read_file` | no |
| A1 format / cache / render | | no |
| **A2 source_change / write / create / comment** | `repo.write_file`, `gh.create_issue` | **yes** |
| **A3 push / publish / fetch_public / dispatch** | `git.push`, `http.fetch` | **yes** |
| **A4 delete / deploy / spend / transfer / key** | `db.delete`, `stripe.charge` | **yes** |

Effects come from `--effects effects.json` (authoritative, and pinned by hash
into every warrant's `under`, so a verifier sees exactly which table classified
the actions):

```json
{ "repo.write_file": ["source_change"],
  "db.delete_row":   ["delete"],
  "stripe.charge":   ["spend"] }
```

A tool absent from the config is classified by a name heuristic; a tool the
heuristic can't place is treated as **A4 (fail-closed)** — an unrecognized action
is consequential until proven otherwise, so it gets sealed. A successful call is
sealed `accept`; an errored one, `reject`.

## Honest scope

- **Provenance, not gating.** This proxy *observes and seals*; it does not block.
  Fail-closed *authorization* (refusing an A4 call) is a separate concern —
  trinity/autonomy-kernel's job.
- **Rejections are prose-only** (the error result is the evidence), so `verify`
  marks them `UNVERIFIABLE` — an honest flag that a failed call's reasoning isn't
  a re-executable check, only a recorded fact. It's a warning, never an error.
- The A0–A4 table here is a light MIT subset for the sealing use-case; the
  canonical authority taxonomy lives in trinity/autonomy-kernel.

Tests: `python3 tests/mcp_seal.py` (classifier, sealer, and a full stdio-proxy
round-trip against a mock server).
