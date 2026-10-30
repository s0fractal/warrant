# warrant-review: a Codex plugin and the review waker

The reviewer's half of the review loop (docs/REPOSITORY.md, "Reviews as records"): Codex is woken
when a pull request is due for review, reviews it, and files its verdict (findings, or an
acceptance of the head version) as signed Warrant 3 records through the warrant MCP server. The merge
gate (`.github/workflows/merge-on-acceptance.yml`) merges a pull request whose accepted head
it can verify; nobody else has to act.

| Part | What it is |
| --- | --- |
| `../../.agents/plugins/marketplace.json` | the marketplace (Codex's format: `.agents/plugins/marketplace.json` at the marketplace root, a local `./` source) |
| `.codex-plugin/plugin.json` | the plugin manifest: `mcpServers` and `skills` |
| `.mcp.json`, `scripts/warrant-mcp` | the MCP server `warrant`: `warrant-agent-mcp --config ${WARRANT_AGENT_CONFIG:-~/.warrant/codex-warrant.json}` |
| `skills/warrant-review/SKILL.md` | the blind review instruction: what to look at and where, and how to file findings or accept through MCP |
| `scripts/warrant-mcp-call` | a stdio client of the same server for another configuration, one tool per call: a file, or `--repo <worktree> --actor codex --seed <seed>`, which the server holds in memory (no file per review) |
| `waker/waker.py` | the waker: for each repository it serves, fetches the base branch into a bare mirror, writes the base's tree once, refuses a base whose `.warrant/v3.json` names another repository, runs THAT tree's `python -m warrant.review due`, replays the mechanical findings of each due head with the review replay checker (below), and starts `codex exec` with the skill once per pull request head that is due (a memo per head), in that wake's own detached worktree of the mirror (`<trees>/<n>-<head12>`, removed after the run unless Codex left changes); a non-zero exit is retried after 15, then 30 minutes, three attempts in all |
| `install.py` | installs all of it on a Mac and loads the waker as a launchd agent (every five minutes) |

The repositories are `~/.warrant/codex-waker/repositories.json` (`{"warrant": "codex-waker/1",
"repositories": [entry, ...]}`), each entry `{repository: owner/name, branch: its base branch, home: its
state, mirror: its bare mirror, trees: its wakes' worktrees, checkout: the operator's checkout, never a
wake's directory}`, absolute paths, none shared. `install.py` writes it with this checkout's repository
(s0fractal/warrant on master, its state in `~/.warrant/codex-waker` itself, as before) as the only entry
when it is absent and keeps an existing one; add an entry by hand to serve another repository. Each
repository is served in turn, its wakes naming that repository and branch; one whose run fails is
reported and the next served. A base that does not carry the `warrant` package runs the warrant-graph
installed in the waker's Python (`install.py` builds it from the checkout's HEAD).

After the pull requests, the waker runs the base tree's `python -m warrant.roadmap due --actor codex` on the
base's own records: the roadmap versions due for Codex's verdict (the leaf of a goal or obligation
lineage whose guard waits only for an attest by a role codex holds, nothing it requires open, which codex
has neither accepted nor challenged). It starts `codex exec` once per version (a memo
`accepts/<version>-0.json`, the same retries), in a detached worktree of the base
(`<trees>/accept-<version12>-0-<base12>`), telling him what the lineage owes, the
version, its evidence and the pull requests and commits it names, not what it says it established. He
accepts the version or challenges it through MCP and leaves that record in his worktree. The waker
publishes it, not Codex: it checks the lines new in the worktree's `.warrant/records.jsonl` and the new
blobs with the base's own package (only codex's acceptances and challenges of that version, under the keys
the base's `.warrant/v3.json` binds to codex, and the blobs they cite; anything else and nothing is
published), adds those bytes on the base (records and blobs only, G11), pushes `codex/verdicts/<version12>-0`
and opens a pull request whose description is Codex's last message. It signs nothing. The merge gate merges
a pull request of verdicts only (`warrant/gate.py`). A wake is done
only once its verdict reached GitHub: a pull request from that branch exists, in any state, or the base
holds codex's verdict on that item. A run that exited 0 and left nothing publishable is retried like a
failed one, in a clean worktree; a publication that failed (Git, GitHub) is retried with the same backoff. At most one closure is woken per run, and none while a
pull request from a `codex/verdicts/` branch is open (until G11 two of them rendered the same views
from different bases; they carry records only now, and the hold remains a limit of one at a time). A closure whose prerequisite is accepted meanwhile is due in the next run that reads
that base.

Before Codex is woken for a head, the waker runs the review replay checker: the base tree's
`python -m warrant.review replay --key -` (the actor `review-replayer`; each replay names the digest of the
checker's whole import closure that ran and its environment) in a detached worktree of the head, under `sandbox-exec`
(no network, writes only in that worktree, its git directory and a scratch directory, no read of the
seeds or the usual credential directories), with the checker's seed on standard input. It replays
every mechanical finding of the head's store at each of its heads that no adopted replayer observed
(another pull request's too: a finding nobody replayed is replayed on the next due head), and the
waker pushes one commit of exactly those replay attests (new lines of `records.jsonl`) on the pull
request's branch (no generated view: they are build artifacts, G11), only while the
branch is still at that head. Codex is woken on the next run, at the new head, once its checks are
green. A pull request that changes the checker is not replayed. A failed checker run is retried after a
backoff, at most three runs, and Codex is not woken at that head meanwhile; once the replay gave up,
Codex is woken and told so in the prompt. A pull request that is no longer due (a verdict moved its
tip) keeps its incomplete replay retried. CI's `warrant.review verify` re-executes every replay new since the base.

The waker reads one key, the checker's seed, from `~/.warrant-review-replayer/<actor>.seed` for the
actor the base's `warrant.review identity` names (`review-replayer`), which the base's `.warrant/v3.json`
must name a `replayer` (a regular file of this user, mode 0600; outside `~/.warrant`, which Codex's
sandbox may write). Without it nothing is replayed. No agent is given that seed or runs `replay` with
it: the observations are the checker's, filed by the waker. The owner creates it once
(docs/REPOSITORY.md, Checker keys).

Each repository's state lives in its `home` (s0fractal/warrant's: `~/.warrant/codex-waker`): its `mirror`
(s0fractal/warrant's: `warrant.git`), `code/<commit>` (the base
trees it ran), `wakes/<n>-<head>.json` (one memo per head with every attempt's exit status; delete it
to wake that head again), `accepts/<closure>-<item>.json` (the same, one per obligation closure item),
`replays/<n>-<head>.json` (one replay per head; delete it to replay that
head again), `replay-work/`, `logs/`, `results/` (Codex's last message of each wake).
`~/.warrant/codex-waker` itself holds the configuration, the lock, `venv/` and `HOLD`.
`WARRANT_WAKER_HOME`, `WARRANT_WAKER_REPLAYERS`, `WARRANT_WAKER_PYTHON`, `WARRANT_WAKER_REPLAY_PYTHON` and
`WARRANT_WAKER_CODEX` override the defaults.

```bash
python3 integrations/codex-plugin/install.py
```

```bash
python3 integrations/codex-plugin/waker/waker.py --dry-run
```

Hold it without uninstalling (nothing is woken in any repository while the file exists; a `HOLD` in an
entry's `home` holds that repository alone):

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
the repositories it serves (W9-W12: a head due in the second of two wakes Codex naming that repository and
branch; a foreign base wakes nobody; a failing repository does not stop the next; the configuration's
rules) and install's default configuration (C14), with no Codex and no GitHub. `tests/review_replay_test.py` (W1-W11, mutants M609-M624 with
`tests/review_gate_test.py` G34-G36) checks the replay: what it files and pushes, the seed only on
standard input, the sandbox profile (and the sandbox itself on a Mac), and what it refuses to push.
