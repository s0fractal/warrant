# WRT-011: `all` / `any` / `count` over a pinned list

**Status:** DRAFT rev 1 (2026-09-09) — **design plus a runnable model.** No SPEC
edit, no change to `ski@v1`, no compiler change is made by this document. It has
had no adversarial gate. Nothing here is adopted.

**What it deliberately does not open.** The closed WRT-008 named *two*
constructs as its sibling: bounded aggregation, and **a digest fact kind
compared by identity**. This proposal takes only the first. §1 says why the
second is not free to take.

---

## 0. Provenance check, before any claim of novelty

Rev 1 of the fact-provenance proposal reused a proposal number without checking
the neighbouring work, in a document about checking claims. So this one starts
by saying what was searched and what was found.

**`sigma-glyph`** already owns work on the digest half:

- **ADR-011 — "Receipted Equality of Admitted Canonical Data by Normal-Form
  Address"** (merged as PR #36, status DRAFT, non-normative). It is the
  "compare two things by their address" idea, and it is **BLOCKED**: the
  `church@v0` profile admits Church numerals *written out* and refuses computed
  expressions. Its own text: *"`church@v0` cannot settle the motivating case."*
- **EXP-ADR011-01 — "a mechanical admission for computed Church naturals"**,
  the experiment designed to close exactly that gap. Status: **PRE-REGISTERED,
  not started.** Its own header: *"No result may be cited from this document
  until it carries one."*

So the digest half of the sibling sits on a blocked ADR with an unstarted
experiment beneath it. Taking it here would mean building on a gap someone has
already had the discipline to leave open rather than bridge by a guess. This
proposal does not touch it.

**The question this raised, and its answer:** does the aggregation half depend
on the same blocker? §4 measures that it does not, and the reason is specific
rather than lucky.

## 1. The measurement this stands on

Already collected, by the WRT-008 that was deferred (§1 of that document, ten
real decisions, 58 facts):

| | |
|---|---|
| derivations classified as `count` / `all` / `any` over a finite list | **15** |
| derivations that are equality of two digests, which WPL refuses (>32 bytes) | **5** |

This proposal addresses the 15. The 5 are §0's blocked territory.

That measurement is a classification by its author of what a pinned extractor
*could* read, not a set of executed derivations. It is retained here with the
same caveat it carried there.

## 2. `any` already exists, under another name

WPL has one collection operation, `in` over a literal list. It is not a special
case: it lowers to a chain of real comparisons in the term, and the model
measures that it produces **exactly** the term of a right-associated `||` chain.

```text
country in ["CA", "US", "MX"]
country == "CA" || (country == "US" || country == "MX")
        -> same term, same 3139 ATP, same 81 nodes

(country == "CA" || country == "US") || country == "MX"
        -> different term, same 3139 ATP, same 81 nodes
```

So association is observable in the address and free in the price, and **`in` is
sugar for a right-associated existential over equality**. What this proposal
asks for is the same unroll with an arbitrary predicate, plus its dual.

That reframes the request. This is not a new capability class; it is the
generalization of a lowering the compiler already performs.

## 3. What is proposed

Over a **pinned** list — the only kind WPL has, since every fact is a literal:

```
check any(amount > limit for amount in charges)
check all(country in allowed for country in itinerary)
check count(late for late in deliveries) >= 3
```

Lowering, all within existing primitives:

| Construct | Lowers to | Nodes |
|---|---|---|
| `any(P)` | right-associated `\|\|` chain of `P(item)` | O(n) |
| `all(P)` | right-associated `&&` chain | O(n) |
| `count(P) op k` | threshold circuit (§4) | O(n·k) |

`count` may appear **only** under a comparison. A bare `count(...)` is not a
boolean and a WPL check answers one boolean, so it is a compile-time refusal by
name, like every other construct the language lacks.

## 4. `count` needs no numeral — which is what makes it independent of §0

The obvious lowering of `count` invents a number, and a number in this calculus
means Church naturals, which is where ADR-011 is blocked. It is avoidable.

Since `count` only ever appears under a comparison, the question asked is never
"how many" but "at least *k*", and that is a boolean. The standard threshold
recurrence decides it:

```text
A[i][j]  =  "at least j of the first i hold"
A[i][0]  =  true
A[0][j]  =  false                                   (j > 0)
A[i][j]  =  A[i-1][j] || (P_i && A[i-1][j-1])
```

Every node is a boolean connective over the same comparison circuits WPL already
emits. No numeral is constructed, added, or compared. `== k` is
`>= k && !(>= k+1)`; `<= k` is `!(>= k+1)`.

**Therefore this proposal has no dependency on ADR-011 or EXP-ADR011-01.** The
two live in different representations: WPL encodes integers as fixed-width bit
vectors compared by circuit (`_bits`, `_encode_pair`), not as Church naturals.
The blocked work is about the equality of *computed naturals by address*; nothing
here computes a natural.

Measured, verdicts read from actual reductions through `warrant.run_ski_check`
off blobs on disk, never from the compiler's own opinion:

```text
count([1,5,9,2] > 4) >= 1  = True    800 ATP, 58 nodes
count([1,5,9,2] > 4) >= 2  = True   2118 ATP, 69 nodes
count([1,5,9,2] > 4) >= 3  = False  2662 ATP, 72 nodes
count([1,5,9,2] > 4) >= 4  = False  2662 ATP, 67 nodes
```

plus all 64 threshold cases over every subset of a four-element list.

## 5. Why this is a construct and not a convenience

The strongest argument for adding it is not that it is nicer to read. It is that
the semantics is **reachable today and the source is not writable by hand**.

The recurrence reuses `A[i-1][j]` twice, so the *term* is a DAG and the repeated
subexpression has one address. Written out in *source* it is a tree, and WPL caps
a check expression at 512 parts. Measured:

| n | k | source chars | ATP | term nodes | status |
|---|---|---|---|---|---|
| 2 | 1 | 50 | 539 | 44 | ok |
| 4 | 2 | 230 | 1898 | 61 | ok |
| 6 | 3 | 929 | 4883 | 86 | ok |
| 7 | 3 | 1420 | 4890 | 96 | ok |
| 8 | 4 | 3662 | — | — | **refused: expression cap** |

At n=7 the term is 96 nodes and 4890 ATP — entirely affordable. The source is
1420 characters of nested parentheses, and one more element makes it
uncompilable. The gap between what the machine can run and what a person can
write is the whole case.

**A degenerate threshold is a refusal, not a constant.** `count(P) >= 0` and
`>= n+1` collapse to `true`/`false`, and WPL then refuses the source because the
declared facts are never read: *"an unused fact looks like it constrains the
decision and does not."* That is the language being right, and the construct must
not paper over it.

## 6. Binding edges: none added

Under [`BINDING-EDGES.md`](wrt-010-model/BINDING-EDGES.md), every row is a claim
of the form *"A claims to be about B"*, and every new path that consumes an
existing object owes its own row.

**This proposal adds no such claim.** The list is a literal in the source; its
elements are lowered into the term as comparison operands; the verifier re-runs
all of it. Nothing is asserted to be *about* anything outside the term, so there
is no address to check, no record to resolve, and no provenance to bind.

That is the whole reason this front was chosen over its sibling. WRT-010 spent
five gate rounds on a defect family that only exists where something claims to
be about something else. This construct is in the other regime, and its risk is
correspondingly different: not trust, but **cost and totality**.

## 7. Cost, and where it is refused

`ski@v1` prices work and peak size with one integer, so an aggregate's cost is
bounded and known before anything ships:

- the compiler already computes the exact `atp` and refuses over `max_atp`;
- the node budget already refuses an over-large term;
- the expression cap already refuses an over-large source.

All three refusals are in place today and the model exercises them. What this
proposal changes is the *ratio*: the same three ceilings now bound a construct
whose cost grows with the list, so the useful question becomes what n a policy
author can afford rather than whether it compiles.

## 8. What this does not do

- **No unpinned collections.** Aggregating over something not in the term
  requires knowing where it came from, which is provenance, which is WRT-010's
  problem and not solved by adding a quantifier.
- **No digest fact kind.** §0.
- **No arithmetic.** `count` yields no value a policy can add to anything; only
  a threshold decision.
- **No `filter` or comprehension nesting.** One list, one predicate, one
  aggregate.
- **It does not claim the syntax is right.** The model shows the semantics is
  expressible and what it costs. Whether `count(P for P in xs) >= k` is the
  shape WPL should grow is exactly what a gate should argue about.
- **It has not been reviewed.** Rev 1 has had no adversarial gate.

## 9. Open questions

1. **Predicate scope.** May the predicate reference facts outside the iterated
   element? `any(x > limit for x in xs)` reads `limit` from outside. That is
   natural and it also means the unroll duplicates `limit`'s comparison circuit
   n times; the term shares it by address, but the cost model should say so.
2. **Which comparisons `count` admits.** `>=` and `>` are the recurrence above.
   `==` needs two circuits, `!=` needs a negation of one. Cheap, but the cost
   table must be written before it ships, not after.
3. **Is `in` re-expressed or left alone?** Making `in` compile through the new
   `any` would be tidier and would change the term of every existing check that
   uses it, breaking pinned `atp` and published pack hashes. Rev 1's position is
   to leave `in` exactly as it is; the tidiness is not worth re-signing records.
4. **Where the ceiling should sit.** §5 shows the source cap binds long before
   the ATP budget does. If the construct removes the source blow-up, the
   effective limit becomes ATP, and the default `max_atp` was chosen for
   hand-written checks, not for aggregates.

## 10. The model

[`proposals/wrt-011-model/aggregation.py`](wrt-011-model/aggregation.py), 19
checks. It extends nothing: every aggregate is written as ordinary WPL, compiled
by the real `policy_lang`, and its verdict read from an actual reduction. A green
run says the semantics is expressible today and costs what the tables above say.
It does **not** say the syntax should be added — that is this document's
argument, and the model is only its operand.

```sh
python3 proposals/wrt-011-model/aggregation.py
```
