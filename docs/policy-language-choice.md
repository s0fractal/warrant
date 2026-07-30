# Why WPL and not CEL — the surface-language decision

**Status:** an engineering decision recorded by its author, not an adopted
governance position. It binds nothing; it explains what was built and what was
given up, so a reviewer can disagree with the reasoning rather than guess at it.

## The problem

`ski@v1` is the strongest thing this format has: a reason a stranger can re-run
offline, bounded in work and memory by construction. Until now, authoring one
meant hand-building Σ-GLYPH combinator terms — `impl/ski_policy.py`, 185 lines,
whose entire surface is `And`, `Or`, `Not` over booleans **you** had already
decided. No working engineer writes policy that way. Inviting people to evaluate
a feature nobody can use guarantees they bounce off it, so a readable front end
is a prerequisite for evaluation rather than an extension of it.

Three options were on the table.

## (a) A CEL subset — considered first, not chosen

CEL is the obvious candidate: familiar from Kubernetes admission policies and
Envoy, side-effect-free by design, and shaped exactly like a boolean policy
predicate. Its syntax is what anyone would want here. Two things decided
against calling this a CEL subset.

**The name is a compatibility promise, and this target cannot keep it.** CEL is
a specified language with a conformance suite: `int` is 64-bit with *overflow
errors*, values are dynamically typed with an error/unknown lattice that
propagates non-strictly (`false && <error>` is `false`, and `&&` is
commutative in errors), and the standard library has macros (`has`, `all`,
`exists`, `filter`), string functions, timestamps and durations. The evaluation
target here — Book I, total, no error values, every action priced — has no way
to represent an error value at all, and arithmetic in it costs ATP proportional
to the circuit, so int64 addition is not something to offer casually. A subset
that omits all of that is not "CEL with features missing"; on the constructs it
*does* share it agrees, but a reader who knows CEL would reasonably expect the
rest, and the parts we would have to leave out are precisely the parts that
carry CEL's semantics.

**And the claim could not be tested.** This repository values dependency-free
verification paths; there is no CEL implementation available to differentially
test against, offline, with stdlib only. So "this is a CEL subset" would be an
*unverified compatibility claim* — exactly the kind of upgrade from "we
implemented something similar" to "we are compatible with X" that this project
treats as a provenance defect. Shipping the claim without the differential
would be the defect; shipping the differential would mean taking a dependency
this repo has spent a long time not taking.

## (b) A small purpose-built expression language — chosen

**WPL v1** (`impl/policy_lang.py`, `docs/authoring-checks.md`): `fact`
declarations plus one boolean expression over `==` `!=` `<` `<=` `>` `>=` `in`
`&&` `||` `!`, on `bool`, `int` and `string`.

Its **syntax is deliberately the shape a CEL user already reads**: `&&`, `||`,
`!`, `in [ … ]`, dotted names, C-style comparison. Someone arriving from a
Kubernetes `ValidatingAdmissionPolicy` will read a WPL check correctly on first
sight. What is *not* claimed is conformance — and everything CEL has that WPL
does not is refused at compile time, by name, with a message saying why it is
absent and what to do instead. A `size(x)` or a `+` gets a refusal, never a
silent misinterpretation.

That is the trade this decision makes: **familiarity without a promise.**

### What (b) gives up

- **No ecosystem.** No CEL editors, linters, playgrounds, or existing policies
  to port. Everything an author needs is one page of documentation, which is
  the compensating design constraint, not an excuse.
- **No reuse of a specified semantics.** WPL's meaning is defined by
  `impl/policy_lang.py` and its tests. That is a smaller, weaker artifact than
  citing a specification with a conformance suite, and it is an honest
  description of what a ~900-line compiler in one repository is.
- **A migration cost if CEL is adopted later.** If a real CEL subset is ever
  worth doing, WPL sources will need translating. They are small and
  mechanical, and the compiled terms are what records cite, so this is a
  documentation-and-tooling cost, not a records-compatibility break.
- **Expressive power.** No arithmetic, no aggregation, no quantifiers, no time,
  no maps, no string matching. See "What WPL v1 cannot express" in the
  tutorial; the list is long and deliberate.

## (c) `wasm@v1` as a second reason kind — not chosen

Maximum power, and it destroys the property that makes `ski@v1` worth having.
`ski@v1`'s trusted computing base is a few hundred lines of evaluator that three
independent implementations agree on, with work *and* peak memory bounded by
`size − 1 ≤ spent`. A Wasm runtime is a large TCB with its own CVE history, and
"budget-bounded" becomes a property of a fuel meter in someone's engine rather
than of the calculus. It also splits the format: a verifier without a Wasm
runtime reports every such reason unverified. The gap it would close — real
computation over structured inputs — is not the gap that is blocking adoption.
The gap blocking adoption was that a threshold comparison was unwritable, and
(b) closes that.

## What the choice does not change

The compiler is not part of the trust base, and the front end does not widen it.
A verifier still re-runs the *term* against the pinned `expect` (SPEC §6(7)) and
never runs the compiler. The compiler's job is to make a term an engineer would
otherwise not have written, and to refuse — loudly, at authoring time — anything
it cannot compile inside the ATP model. How a mis-compilation is made detectable
is documented at the top of `impl/policy_lang.py` and gated by
`tests/policy_lang.py`.
