# Provenance

Research experiment. **Not adopted, not published, not a standard, not
cross-vendor.** No push, no PR, no merge, no repository, no marketplace
submission.

## Base

```
repo: github.com/s0fractal/warrant
base: be4767a51dad5c3385fb591b6d9d71f0d8cb6c30   (== origin/master when branched)
branch: experiment/agent-plugin-skill-v0        (separate worktree)
```

Built from that exact base, not from the local checkout, which sat on a
closed research branch.

## Pins, verified by digest rather than cited

```
agentplugins/agent-plugins-spec @ bd383552095128f6effe895b9257cfd580a6d179

spec/1.0.0.md
  pinned  97a658b7dca3ce1b4c2266b95da300fa51d9dc4ade59d73168e5f9104272da18
  fetched 97a658b7dca3ce1b4c2266b95da300fa51d9dc4ade59d73168e5f9104272da18   MATCH

schemas/1.0.0/plugin.schema.json
  pinned  0a4aad95ce337878ad38802ebf0daa3fde76abe3f65400c86bcbb1ec0b3ab883
  fetched 0a4aad95ce337878ad38802ebf0daa3fde76abe3f65400c86bcbb1ec0b3ab883   MATCH
```

`plugin.json` carries the canonical `$schema` identifier
`https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`. The commit and
digests above exist for provenance; the canonical identifier was not replaced
with a local path.

Agent Skills frontmatter follows <https://agentskills.io/specification>
(`name`, `description` required; `license`, `compatibility` optional and
used).

## Package digest

Over the package tree, `sha256` of the sorted per-file `sha256` list:

```
d9fa299e2be4585eec3c48235ceb410916f76687ccf28bfab9f84a2ffc24bede
```

The bytes Codex installed into its plugin cache hash to the same value — the
client copied the package, it did not rewrite it.

## What was not done

No `mcp.json`, no MCP server, no hooks, no commands, no client-specific
extension directory, no scripts, no installer, no network access from the
skill, no copy of Warrant verification logic, no SPEC change, no new
contract.
