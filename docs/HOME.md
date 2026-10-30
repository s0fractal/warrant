# Warrant Home

Install Warrant once for the machine, and keep one operator configuration under your home
directory. Each repository keeps only its own `.warrant/`.

```sh
pip install --pre warrant-graph          # or: uv tool install --prerelease allow warrant-graph
warrant home identity claude --seed ~/.warrant/claude.seed
warrant home add ~/Projects/warrant --signer claude
warrant home add ~/Projects/minds   --signer claude
warrant home                             # what is registered, and whether each trust binds its signer
warrant status --repo minds              # any registered repository, from any directory
warrant-agent-mcp                        # with no --config: one MCP server for every registered repository
```

## The file

`$WARRANT_HOME`, else `$XDG_CONFIG_HOME/warrant/home.json`, else `~/.config/warrant/home.json`:

```json
{"warrant": "warrant-home/1",
 "identities": {"claude": {"seed": "/Users/me/.warrant/claude.seed", "public": "fc176e4b…"}},
 "repositories": {"warrant": {"path": "/Users/me/Projects/warrant", "signer": "claude"},
                  "minds":   {"path": "/Users/me/Projects/minds",   "signer": "claude",
                              "operations": ["context", "read", "graph"]}}}
```

- **A repository** is a directory that holds `.warrant/v3.json`. It is registered under a plain
  name, which is also its workspace name for the agent interface. `signer` names the identity
  that files records there. `operations` (default: all) limits what the agent may do there.
- **An identity** is an actor and the path of its seed. `warrant home identity` reads the seed
  once, to record its public key. `warrant home` then says, for each repository, whether that
  repository's trust binds the key to the actor.

## Rules

1. **Each repository keeps its own `.warrant/`.**
   - Its records, blobs and receiver configuration (`v3.json`: trust and profile) live in it and
     are merged under its own rules.
   - Home lists where they are and who signs in each. It writes nothing into any of them and
     holds no record of its own.
2. **Home is the operator's.**
   - It is never read from a repository, and no request names it.
   - A Home that is a link, or one other users may write, is refused.
   - It is written whole with mode 0600, in a 0700 directory.
3. **A seed is named, never copied.**
   - It never lies inside a registered repository, whichever is registered first.
   - It is refused at registration when others may read or write it.
4. **`--repo NAME` and `--store DIR` exclude each other.**
   - With neither, a command uses the nearest `.warrant/` upward from the current directory.
   - With no `--trust` or `--profile`, a command uses that store's `v3.json`.

## The agent

`warrant-agent` and `warrant-agent-mcp` without `--config` read Home. Each registered repository
becomes one workspace: it uses that repository's trust and profile, signs as its signer with the
identity's seed, and offers its operations. An explicit `--config` file works as before
(docs/AGENT.md).

## Not yet

These are the next steps of the plan:

- **Review worktrees.** A call will name a worktree of a registered repository, so that a review
  of a pull request head no longer needs a configuration of its own.
- **The waker.** It will read its repositories from Home.
- **A resolver for hashes cited across repositories.** Each cited hash will get one of four
  states, `PRESENT`, `RESOLVED`, `LOCATED` or `MISSING`, from local stores and Git history only.
- **`warrant drift`.**
