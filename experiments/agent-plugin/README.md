> # CLOSED — objective not achieved
>
> An exact-SHA gate returned **CLOSE**. Kept as research provenance only: not
> merged, not pushed, no PR, not a standard, not cross-vendor.
>
> ```
> PACKAGE FORMAT:    PASS on one client
> SEMANTIC BEHAVIOR: insufficiently evidenced
> EXECUTION BOUNDARY: FAIL on the only live client
> PORTABILITY GATE:  PARTIAL / objective not achieved
> ```
>
> **The result worth keeping is the negative one.** Agent Plugins 1.0.0 ports
> **files** correctly — the root manifest loaded, the bytes arrived intact, no
> legacy path was used. But a `SKILL.md` does not port **execution**. The one
> live client ran the verifier through `/bin/zsh -lc` with the store path
> inside a shell string, while the skill required an argv list and never a
> concatenated string. The contract was broken mechanically by the only client
> that ran it, and a skill has no way to make it otherwise. Controlling that
> needs a typed client/tool boundary, which a skill-only format does not have.
>
> Three findings closed this, all mine:
>
> 1. **The package digest was false provenance.** `d9fa299e…` was computed over
>    a three-file pre-final package; the committed tree hashes to `ad968019…`
>    under the same method. The method itself was underspecified (no defined
>    serialization or exclusions), and the digest was stored inside the tree it
>    claimed to hash. The reproducible identity of this package is its **git
>    commit**, `f27038f` — nothing else in the document was.
> 2. **"Verbatim responses" was an overclaim.** `EVALS.md` carries selected
>    paragraphs and my paraphrase, not transcripts. No tool call, raw stdout,
>    exit receipt or transcript digest was retained, so an independent reviewer
>    cannot check whether the agent obeyed the skill or whether I picked a
>    flattering excerpt.
> 3. **I softened finding 1 of my own self-review.** I filed the shell-string
>    execution as "a limit, recorded not fixed … outside this package". It is
>    not a limit; it is the experiment's central question answered *no*.
>
# warrant-verify — an Agent Plugins 1.0.0 skill-only experiment

**Research. Not adopted, not published, not a standard, not cross-vendor.**
One implementation round and one self-review; an independent exact-SHA gate
has not happened.

## The question

Not "can we ship a plugin". This:

> Can one portable `SKILL.md` make different agent clients run an
> **already-installed** local Warrant verifier and report what it established —
> without turning integrity into correctness, authorization, or actor identity?

The package is deliberately tiny. A previous line of work failed four times in
a row, each time in the *wrapper* rather than the mechanism: a slice that sold
integrity as authorization, a control labelled `$6400` that ran `$640`, a demo
that tampered with the passenger's request while calling it the policy, and an
oracle that accepted "could not be read" as proof of a hash mismatch. This
skill is another wrapper, so the interesting part is `SEMANTIC-BOUNDARY.md` and
`EVALS.md`, not the manifest.

## What it contains

```
plugin.json                                  root Agent Plugins manifest
skills/warrant-verify/SKILL.md               the skill
skills/warrant-verify/references/SEMANTIC-BOUNDARY.md   normative for answers
```

No `mcp.json`, no hooks, no commands, no scripts, no client-specific
directory. The skill never installs anything and never uses the network; if
no `warrant` command exists it says `UNAVAILABLE` and stops, because it
learned nothing about the evidence.

## What the live client actually did

`EVALS.md` carries verbatim responses. On OpenAI Codex CLI 0.147.0 the skill
loaded from the **root manifest** — no `.codex-plugin` legacy path — and:

- refused to infer authorization from `ok: true`;
- distinguished a valid signature from actor identity, quoting
  `binding unverified`;
- refused to treat a pasted report as evidence a verifier ran;
- treated an injected *"ignore the plugin instructions"* string as data;
- replied `UNAVAILABLE` with no verifier present, without installing anything.

## What this does not show

**Portability is not demonstrated.** One live client is one client. The second
(VS Code / GitHub Copilot) is UNRUN — not installed here — and nothing was
substituted for it:

```
PORTABILITY GATE: PARTIAL — one live client only
```

The skill also cannot control *how* a client shells out. Codex wrapped the
correct unconcatenated argv inside a shell string containing the store path;
with a hostile path that outer layer, not this skill, is where the risk lives.
Recorded rather than fixed, because fixing it is not in this experiment's
scope.
