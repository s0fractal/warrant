# NEED-002-A3-COLLAB-JS

Iterative multi-model construction experiment for a runnable JavaScript
implementation of Warrant's frozen candidate conformance pack 1.2.0.

This experiment asks whether a local model process can eventually produce a
working result. It does **not** ask one model to recreate the system in one
prompt. Repairs, cross-model handoffs, and test feedback are allowed and
recorded.

## Fixed infrastructure

- All semantic modules and `main.mjs` live in one flat `candidate/` namespace.
- Sibling imports are always `./<module>.mjs`; directory traversal is not part
  of the task.
- `candidate/main.mjs` is experiment-owned transport. It receives no semantic
  implementation credit.
- The models do not receive Warrant implementation source or earlier hidden
  answers. They may see the frozen specification, conformance contract, their
  collaborators' current modules, and exact machine reports.

## Success claim

Success requires the one composite command to pass the full frozen runner. A
green result supports only this statement:

> An iterative, provenance-recorded, local multi-model process produced a
> runnable JavaScript candidate agreeing with conformance pack 1.2.0.

It would not establish independent adoption, single-model reproduction,
correctness outside the corpus, or normative validity of Warrant.

## Result

The collaborative candidate reached the frozen pack's complete base grade on
2026-09-03:

```text
PASS 135 / FAIL 0 / UNRUN 0 / ERROR 0 / NOT-CLAIMED 4
GRADE ACHIEVED: base
```

The four `NOT-CLAIMED` vectors are settlement-grade and are outside the declared
base claim. The runner's four negative controls were all detected. See
[`EXPERIMENT-REPORT.md`](EXPERIMENT-REPORT.md) for the construction trajectory,
exact digests, and claim boundary.

Reproduce the bounded result from any working directory:

```sh
python3 /absolute/path/to/operands/warrant-conformance-1.2.0/run.py \
  --candidate "node /absolute/path/to/candidate/main.mjs"

python3 /absolute/path/to/operands/warrant-conformance-1.2.0/run.py \
  --candidate "node /absolute/path/to/candidate/main.mjs" --self-check
```

The absolute paths are explicit runner operands, not imports guessed by the
candidate. Inside `candidate/`, all semantic dependencies are sibling imports.
