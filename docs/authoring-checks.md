# Authoring checks — write a policy a stranger can re-run

You are about to write a rule that anybody can execute on their own machine,
offline, and get the same answer you got. Not a log line saying what your system
decided — the decision procedure itself, pinned by hash, with a proven bound on
how much work re-running it can cost.

This page takes about half an hour. You need Python 3.9+, this repository, and
no other tools. **You do not need to know what a combinator is** — nothing you
write will contain one, and nothing below asks you to read one.

---

## 0. What you are writing, and what it proves

A warrant records a decision (`accept`, `reject`, `propose`, `supersede`) and
the reasons for it. A reason can be prose — which a reader has to take on faith
— or a **check**: a program the reader runs themselves.

A `ski@v1` check is the strong kind. It is a closed, total, budget-bounded
program: it cannot loop, cannot read your disk, cannot reach the network, and
its work *and* peak memory are bounded by a number stored in the check itself.
That is why re-running a stranger's `ski@v1` reason is safe, and re-running a
stranger's shell script is not (SPEC §3.1).

You write these in **WPL** — facts and one boolean expression:

```wpl
# examples/policies/1-threshold.wpl
#
# A refund is auto-approved only at or under the desk limit.
# The facts are what this decision was made on; the limit is the policy.

fact refund_amount_cents: int = 65088

check refund_amount_cents <= 50000
```

Be clear about what this proves and what it does not. It proves **the rule's
verdict, given those facts**. It does not prove the facts are true in the world
— that is what evidence blobs and signatures are for — and it does not
reproduce any model's reasoning. Pinning the *deterministic policy rule* around
a decision is the thing a regulator, a counterparty or a court can actually
check, and it is the thing that is normally missing.

---

## 1. A threshold — zero to a working check

Compile the file above. Nothing is written anywhere; this just tells you what
you are asking a verifier to run:

```
$ python3 impl/policy_lang.py compile examples/policies/1-threshold.wpl
policy    1-threshold.wpl
language  wpl@v1
formula   (refund_amount_cents <= 50000)
facts     refund_amount_cents: int = 65088
result    false
term      9fd6ab7a0261d1f38658c390c842505d24076b0eb993986f6a924415bedb7c04
expect    65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  (Church FALSE)
atp       495  (budget 1000000)
nodes     47
          compare refund_amount_cents <= 50000  (17 bits)
check     (not stored — pass --store to write it)
```

Read that as: the rule is false for these facts (65088 cents is over the 50000
limit, so no auto-approval); re-running it costs **495 units of metered work**;
it adds **47 blobs** to a store; and the one comparison in it was decided on a
17-bit-wide number, because 17 bits is all it takes to tell 65088 from 50000.

`term` is the program. `expect` is the answer it reduces to. A verifier runs the
first and compares it to the second. Do that now — this runs the check through
`warrant`'s own re-execution path, the same code a stranger's verifier uses:

```
$ python3 impl/policy_lang.py verify examples/policies/1-threshold.wpl
check     8323aba3f8af859d3409103ccca578dc45d6cb46d2ba8bb78f11a893520c9b85
verdict   pass
result    65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  (Church FALSE)
atp_spent 495  (pinned atp 495)
```

`verdict pass` means "re-execution reproduced the pinned answer". It does **not**
mean the policy said yes. Those are two different questions and WPL keeps them
apart on purpose: `result` is the policy's answer (here, `false` — deny), and
`verdict` is whether the recorded claim survives being re-run.

`65cd957f…` is worth recognising: it is the hash of "false" and it will show up
in every denial you write.

---

## 2. Set membership — one fact against a list

```wpl
# examples/policies/2-membership.wpl
#
# Self-serve refunds are available only where the desk operates.

fact ticket_origin_country: string = "MX"

check ticket_origin_country in ["CA", "US"]
```

```
$ python3 impl/policy_lang.py compile examples/policies/2-membership.wpl
policy    2-membership.wpl
language  wpl@v1
formula   (ticket_origin_country in ["CA", "US"])
facts     ticket_origin_country: string = "MX"
result    false
term      cb21dd1f18ba98adb6f8bc58dcfe09e0e6347b574738d283091abdba2c9779f4
expect    65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  (Church FALSE)
atp       1148  (budget 1000000)
nodes     63
          compare ticket_origin_country == "CA"  (16 bits)
          compare ticket_origin_country == "US"  (16 bits)
check     (not stored — pass --store to write it)
```

`x in [a, b]` is exactly `x == a || x == b`, and the cost report shows it as the
two comparisons it is. Two-letter strings are 16 bits wide — one byte each.
Strings cost 8 bits per byte, so `"CA"` is cheap and `"bereavement"` is not;
that matters in the next example.

Membership stops at the first match. Put the common case first if you care about
the number.

---

## 3. Two inputs — comparing facts against each other

Real policies rarely compare a fact to a constant. They compare facts to each
other, and combine several rules:

```wpl
# examples/policies/3-two-inputs.wpl
#
# Bereavement fare, the rule Air Canada's chatbot got wrong: the discount is
# granted only when it is requested with at least the required notice BEFORE
# travel, and never as a retroactive claim.
#
# days_until_travel is negative when the flight has already been taken.

fact days_until_travel: int = -12
fact min_notice_days:   int = 0
fact fare_basis:        string = "bereavement"
fact retroactive:       bool = true

check fare_basis == "bereavement"
      && days_until_travel >= min_notice_days
      && !retroactive
```

Three things are new: an expression may span lines; `&&` chains; and integers
may be negative. Compile it:

```
$ python3 impl/policy_lang.py compile examples/policies/3-two-inputs.wpl
policy    3-two-inputs.wpl
language  wpl@v1
formula   (((fare_basis == "bereavement") && (days_until_travel >= min_notice_days)) && !retroactive)
facts     days_until_travel: int = -12
          min_notice_days: int = 0
          fare_basis: string = "bereavement"
          retroactive: bool = true
result    false
term      aeb650dad27323ce42864591372173475c85940eadfcfd2bce80a9a20d32a93b
expect    65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  (Church FALSE)
atp       11014  (budget 1000000)
nodes     134
          compare fare_basis == "bereavement"  (88 bits)
          compare days_until_travel >= min_notice_days  (5 bits)
check     (not stored — pass --store to write it)
```

`formula` is how the compiler read your expression, fully parenthesised. Check
it against what you meant: `!` binds tightest, then comparisons, then `&&`, then
`||` — so `a || b && c` is `a || (b && c)`.

Note the cost. `fare_basis == "bereavement"` is 88 bits — eleven bytes — and it
is almost the whole 11014 ATP. `days_until_travel >= min_notice_days` needed 5
bits. **If a check is expensive, it is nearly always a long string.** Pin a
short tag (`"BRV"`) instead of a sentence and the cost falls by an order of
magnitude.

If you only want to know what a file *means*, without compiling anything:

```
$ python3 impl/policy_lang.py explain examples/policies/3-two-inputs.wpl
formula   (((fare_basis == "bereavement") && (days_until_travel >= min_notice_days)) && !retroactive)
fact      days_until_travel: int = -12
fact      min_notice_days: int = 0
fact      fare_basis: string = "bereavement"
fact      retroactive: bool = true
result    false
```

---

## 4. Refusals are the feature

WPL refuses far more than it accepts, and it refuses at *authoring* time — in
front of you, where a message is useful — rather than emitting something that
dies inside somebody else's verifier six months later.

There is no arithmetic:

```wpl
# examples/policies/refused-arithmetic.wpl
#
# This file does NOT compile, on purpose: it is the example the tutorial uses
# to show what a refusal looks like. WPL has no arithmetic, so a total refund
# has to be computed where the facts are gathered and pinned as a fact.

fact base_fare_cents: int = 55000
fact tax_cents:       int = 10088

check base_fare_cents + tax_cents <= 50000
```

```
$ python3 impl/policy_lang.py compile examples/policies/refused-arithmetic.wpl
REFUSED   arithmetic (`+`) is not in WPL v1. WPL has no arithmetic on purpose: every operand must be a literal or a pinned fact, so the verifier re-executes every step of the decision instead of trusting a number the compiler worked out. Compute the value where the facts are gathered and pin the result as a fact. (line 10, column 23)
```

That is not laziness. If the compiler were allowed to add two numbers, the
verifier would be re-running a term built around a sum *the compiler* computed
and nobody re-checks. Because there is no arithmetic, every operand in a
compiled term is a literal you wrote or a fact you pinned, and every operator is
re-executed. Add `total_cents` where you gather the facts, and pin it.

Cost is refused the same way. Ask for a check the budget will not cover and you
get a number and a refusal, not a term:

```
$ python3 impl/policy_lang.py compile examples/policies/1-threshold.wpl --max-atp 100
REFUSED   this check costs more than the 100 ATP compile budget. Raise --max-atp only if the verifiers that will re-run it agree to spend that much (SPEC §3.1: a verifier MAY refuse an over-budget reason, and then reports it as unverified, not as a verdict).
```

Both exit non-zero, so a build that produces an unauthorable policy fails.

Other things WPL will tell you it does not have: floating point (use cents),
function calls, `? :`, chained comparisons (`a < b < c`), ordering on strings,
comparisons between different types, and lists that are empty. It also refuses a
fact you declare and never use — that reads like a constraint and is not one.

Size is refused too, and for a duller reason: an expression over 512 parts, a
term over 4096 nodes, a term more than 1024 deep, a string over 32 bytes, or
more than 64 nested parentheses. Those bounds exist because a compiler whose
job is to refuse what it cannot compile must not instead crash — the first
three were added after a 300-clause policy produced a Python traceback rather
than a message. A policy that large should be several checks, each cited as its
own reason, which is also easier to read.

---

## 5. Putting a check in a warrant

Compile with `--store` to write the blobs into a warrant store, then cite the
check hash as a reason. Here is the shape, using the Air Canada demo's policy:

```wpl
# demos/air-canada/policy.wpl
#
# Moffatt v. Air Canada, 2024 BCCRT 149 — bereavement policy clauses 2 and 3:
# the discount must be requested before travel and can never be claimed
# retroactively. These are the facts of the passenger's request.
#
# This is the source the shipped pack's ski@v1 check is compiled from. It
# reproduces the check blob b423b6a82c34…, result 65cd957f… (Church FALSE) and
# atp_spent 17 that demos/air-canada/README.md tells a reader to expect.

fact within_window: bool = true
fact retroactive:   bool = true

check within_window && !retroactive
```

```
$ python3 impl/policy_lang.py compile demos/air-canada/policy.wpl
policy    policy.wpl
language  wpl@v1
formula   (within_window && !retroactive)
facts     within_window: bool = true
          retroactive: bool = true
result    false
term      1b56d81b4378a2c4cc1965453db5edb9c6ab39fec7d91822a0e91e521dd06a8d
expect    65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  (Church FALSE)
atp       17  (budget 1000000)
nodes     5
check     (not stored — pass --store to write it)
```

A boolean-only policy costs 17 ATP and five blobs. That is the check the demo
pack ships and the README invites you to re-run; `demos/air-canada/build.py`
compiles it from this source and asserts it is byte-identical to the hand-built
term the pack was signed against.

In Python:

```python
import policy_lang as pl, warrant as w
store = w.Store(".warrants")
check = pl.compile_file("demos/air-canada/policy.wpl", store.put_blob)
source = store.put_blob(open("demos/air-canada/policy.wpl","rb").read())
# ... then file a warrant whose `because` includes check.reason()
#     and whose `evidence` includes `source`.
```

**Put the source blob in the record's `evidence`.** It is what lets a reader
recompile the rule and confirm the term the record cites is the term this
source produces. See §6.

Then anyone with the store re-runs it:

```
warrant --store .warrants check <check-hash>
pass  result=65cd957f…  atp_spent=17
```

---

## 6. What the compiler is trusted for (almost nothing)

This is the part to be pedantic about, because it is the part that makes the
record worth anything.

**A verifier never runs this compiler.** It re-runs the *term*, off the blobs,
and compares the result to `expect` (SPEC §6(7)). So nobody has to trust the
compiler for the *verdict* to be checkable — you cannot record "pass" for a
check that does not reduce to what you claimed. That failure mode is closed by
re-execution, not by faith.

What re-execution does *not* establish is that the term means what your source
says. Three things narrow that gap:

1. **The compiler checks itself against the oracle before emitting anything.**
   Every compile evaluates the term it just built on the Σ-GLYPH Book I oracle
   and compares the answer to a plain-Python interpreter of the same source. On
   disagreement it raises and emits nothing. Because a WPL check is a closed
   term over facts pinned in the source, that single comparison covers the
   check's *entire* input space — there is no other input it can be run on.

2. **Compilation is reproducible.** The same source bytes give the same term
   hash. Pin the source as a blob, list it in `evidence`, and any reader can
   re-run the compiler and confirm the record cites the term this source
   produces. The compiler is auditable rather than trusted.

3. **The compiler evaluates nothing the verifier does not re-evaluate** (§4).

The gap that remains: nothing here proves the *parser* reads your text the way
you read it — a compiler and its own interpreter could misread the same source
identically. `tests/policy_lang.py` narrows that too, by generating programs as
Python expressions first and rendering them to WPL second, so the expected
answer comes from Python's operators and every layer of WPL sits between it and
the answer; and by mutating the compiler on purpose and failing if the mutant
survives. It does not close it. Read the `formula` line the compiler prints —
that is the tree it built, fully parenthesised — and read it against what you
meant.

---

## 7. The whole language

```
source     := (fact | check)*          -- exactly one `check`, facts before use
fact       := "fact" name ":" type "=" literal
check      := "check" expression
type       := "bool" | "int" | "string" | "list<int>" | "list<string>"
name       := ident ("." ident)*       -- e.g. request.amount
```

| Level | Operators | Notes |
|---|---|---|
| loosest | `\|\|` | left-associative |
| | `&&` | left-associative |
| | `==` `!=` `<` `<=` `>` `>=` `in` | do not chain |
| tightest | `!` | |

| Type | Compares with | Cost |
|---|---|---|
| `bool` | `==` `!=`, and `&&` `\|\|` `!` | ~1 ATP per operator |
| `int` | all six, and `in` | ~125 ATP per bit; width is the minimum that separates the operands (int64 range) |
| `string` | `==` `!=` `in` | 8 bits per UTF-8 byte, padded to the longer side; ≤ 32 bytes; no NUL |

Parentheses group. `#` starts a comment. An expression may span lines. An
integer literal may be negative wherever a value is expected — `x >= -5`,
`x in [-1, 0, 1]` — but `-` between two values is subtraction and is refused,
so there is never a question of which one you meant.

`--max-atp N` sets the compile-time ceiling (default 1,000,000; the reference
verifiers will re-run up to 100,000,000). `--headroom N` pins a larger `atp` than
the check actually spends; `N` must be `>= 0` and the pinned total must stay
inside both uint32 and the verifier's re-execution budget, because a check whose
`atp` is under its own cost is not rejected as malformed — the verifier runs out
of budget and reports **`fail`**, a wrong verdict from a correct term. The
compiler re-executes the serialized check under its pinned `atp` before writing
it and refuses anything a verifier would not accept. `--json` prints the same
report as machine-readable JSON.

---

## 8. What WPL v1 cannot express

Honest boundaries, so you find them here rather than three days in:

- **No arithmetic, no aggregation, no functions.** No `+`, no `sum`, no
  `size()`, no `startsWith`. Derive the number upstream and pin it.
- **No quantifiers over collections.** `all`/`exists`/`filter` are not in the
  language. `in` over a literal list is the only collection operation.
- **No time.** No timestamps, no durations, no `now`. A policy about a deadline
  is written as an integer comparison over a day or second count you computed.
- **No maps, no nested structures, no null.** `request.amount` is a *name* with
  a dot in it, not a field access; there is no object to traverse.
- **No string ordering, matching or case folding.** Equality and membership on
  exact UTF-8 bytes only.
- **The facts are pinned into the term.** A compiled check is specific to one
  set of fact values. There is no reusable "policy term" you can apply to a new
  case — recompile per decision. (The source is the thing you reuse and review;
  the term is per-decision.)
- **A check answers one boolean.** No scores, no partial orders, no reasons
  emitted from inside the check. If you need to know *which* clause failed,
  compile several checks and cite them all.
- **Nothing about the facts is proven.** `fact retroactive: bool = true` is an
  assertion by whoever compiled it. Its trustworthiness comes from the signature
  on the record and the evidence blobs cited beside it, not from the check.

If your rule needs something in this list, the honest answers are: compute it
upstream and pin the result; split it into several checks; or use `cmd@v1`,
which can run anything and correspondingly proves much less.

---

→ SPEC §3.1 (`ski@v1`) · `impl/policy_lang.py` (the compiler) ·
`tests/policy_lang.py` (what is actually checked) ·
`docs/policy-language-choice.md` (why this language and not CEL) ·
`demos/air-canada/` (a worked case end to end)
