# warrant-review: a Codex plugin and the review waker

The reviewer's half of the review loop (README.md, "Reviews as records"): Codex is woken
when a pull request is due for review, reviews it, and files its verdict (findings, or an
accept of the head closure) as signed records through the warrant MCP server. The merge
gate (`.github/workflows/merge-on-acceptance.yml`) merges a pull request whose accepted head
it can verify; nobody else has to act.

| Part | What it is |
| --- | --- |
| `../../.agents/plugins/marketplace.json` | the marketplace (Codex's format: `.agents/plugins/marketplace.json` at the marketplace root, a local `./` source) |
| `.codex-plugin/plugin.json` | the plugin manifest: `mcpServers` and `skills` |
| `.mcp.json`, `scripts/warrant-mcp` | the MCP server `warrant`: `warrant-agent-mcp --config ${WARRANT_AGENT_CONFIG:-~/.warrant/codex-warrant.json}` |
| `skills/warrant-review/SKILL.md` | the blind review instruction: what to look at and where, and how to file findings or accept through MCP |
| `scripts/warrant-mcp-call` | a stdio client of the same server for another configuration (a review worktree's, made by `warrant-agent-mcp init` with Codex's own seed), one tool per call |
| `waker/waker.py` | the waker: fetches master into a bare mirror, writes master's tree once, runs THAT tree's `tools/review.py due`, and starts `codex exec` with the skill once per pull request head that is due (a memo per head) |
| `install.py` | installs all of it on a Mac and loads the waker as a launchd agent (every five minutes) |

The waker signs nothing and reads no key. Its state lives in `~/.warrant/codex-waker`:
`warrant.git` (the mirror), `code/<commit>` (the base trees it ran), `wakes/<n>-<head>.json`
(one memo per woken head; delete it to wake that head again), `logs/`, `results/` (Codex's
last message of each wake).

```bash
python3 integrations/codex-plugin/install.py
```

```bash
python3 integrations/codex-plugin/waker/waker.py --dry-run
```

Hold it without uninstalling (nothing is woken while the file exists):

```bash
touch ~/.warrant/codex-waker/HOLD
```

Stop it:

```bash
launchctl bootout gui/$(id -u)/dev.s0fractal.warrant-codex-waker
```

Remove it (`~/.codex/config.toml` keeps its backups as `config.toml.warrant-backup-*`):

```bash
python3 integrations/codex-plugin/install.py --uninstall
```

`test_plugin.py` (CI, examples job) checks the manifests' paths, the launcher, the
configuration edit, one wake per head and the stdio client, with no Codex and no GitHub.
