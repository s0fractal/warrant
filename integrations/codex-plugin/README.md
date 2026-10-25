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
| `waker/waker.py` | the waker: fetches master into a bare mirror, writes master's tree once, runs THAT tree's `tools/review.py due`, replays the mechanical findings of each due head with the review replay checker (below), and starts `codex exec` with the skill once per pull request head that is due (a memo per head), in that wake's own detached worktree of the mirror (`~/Projects/.worktrees/codex-review/<n>-<head12>`, removed after the run unless Codex left changes); a non-zero exit is retried after 15, then 30 minutes, three attempts in all |
| `install.py` | installs all of it on a Mac and loads the waker as a launchd agent (every five minutes) |

After the pull requests, the waker runs the base tree's `tools/roadmap.py due --actor codex` on the
base's own records: the roadmap obligations' closures due for Codex's verdict (an obligation's latest
closure the engine holds PENDING for codex, so every duty it requires is DISCHARGED, which codex has
neither accepted nor challenged). It starts `codex exec` once per closure item (a memo
`accepts/<closure>-<item>.json`, the same retries), in a detached worktree of the base
(`~/Projects/.worktrees/codex-review/accept-<closure12>-<item>-<base12>`), telling him the duty's text, the
closure, its evidence ids and the pull requests and commits that evidence names, not what the closure
says it established. He accepts the closure or challenges it through MCP, commits that record and the
views on `codex/verdicts/<closure12>-<item>` and opens a pull request of it; the merge gate merges a pull
request of verdicts only (`eligibility.py`). At most one closure is woken per run, and none while a
pull request from a `codex/verdicts/` branch is open: two of them would render the same views from
different bases. A closure whose prerequisite is accepted meanwhile is due in the next run that reads
that base.

Before Codex is woken for a head, the waker runs the review replay checker: the base tree's
`tools/review.py replay --key -` (an actor named by the hash of `tools/claimslib/review_replay.py`,
which signs only from code with that hash) in a detached worktree of the head, under `sandbox-exec`
(no network, writes only in that worktree, its git directory and a scratch directory, no read of the
seeds or the usual credential directories), with the checker's seed on standard input. It replays
every mechanical finding of the head's store at each of its heads that no adopted replayer observed
(another pull request's too: a finding nobody replayed is replayed on the next due head), the head's
own `project` commands regenerate the views, and the waker pushes one commit of exactly those
observation records, their probe blobs and the views on the pull request's branch, only while the
branch is still at that head. Codex is woken on the next run, at the new head, once its checks are
green. A pull request that changes the checker is not replayed; a failed replay is logged and Codex
is woken as without it. CI's `replay --verify` re-executes every observation new since the base.

The waker reads one key, the checker's seed, from `~/.warrant-review-replayer/<H>.seed` for the
checker `checker sha256:<H>` that master's `.warrant/reviews.json` names last (a regular file of this
user, mode 0600; outside `~/.warrant`, which Codex's sandbox may write). Without it nothing is
replayed. No agent is given that seed or runs `replay` with it: the observations are the checker's,
filed by the waker. To place it:

```bash
mkdir -m 700 -p ~/.warrant-review-replayer
```

```bash
install -m 600 SEED ~/.warrant-review-replayer/HASH.seed
```

Its state lives in `~/.warrant/codex-waker`: `warrant.git` (the mirror), `code/<commit>` (the base
trees it ran), `wakes/<n>-<head>.json` (one memo per head with every attempt's exit status; delete it
to wake that head again), `accepts/<closure>-<item>.json` (the same, one per obligation closure item),
`replays/<n>-<head>.json` (one replay per head; delete it to replay that
head again), `replay-work/`, `logs/`, `results/` (Codex's last message of each wake).
`WARRANT_WAKER_HOME`, `WARRANT_WAKER_TREES`, `WARRANT_WAKER_REPLAYERS`, `WARRANT_WAKER_PYTHON`,
`WARRANT_WAKER_REPLAY_PYTHON` and `WARRANT_WAKER_CODEX` override the defaults.

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
configuration edit, a dry install that changes nothing, one wake per head, the wake's own worktree, retries, and the stdio client,
with no Codex and no GitHub. `tests/review_replay_test.py` (W1-W11, mutants M609-M624 with
`tests/review_gate_test.py` G34-G36) checks the replay: what it files and pushes, the seed only on
standard input, the sandbox profile (and the sandbox itself on a Mac), and what it refuses to push.
