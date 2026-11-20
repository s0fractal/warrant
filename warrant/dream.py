"""Deterministic offline lossless recipe synthesizer & diagnostic prescriptions (`warrant.dream`).

Turns `pact@1` + `warrant.witness` from a passive checker into a bounded, fail-closed planner:
  1. Given a pool of `Recipe`s (or resolved `ACTIVE`/`SETTLED` `pact@1` entries) and a target
     guarantee set `goal_gives` (plus optional `required_witnesses` and `boundary`), searches
     finite compositions `R_1 ; ... ; R_k` via deterministic BFS under explicit `max_steps` and
     `max_expansions` budgets.
  2. Every candidate chain is checked strictly through `pact.compose_recipes` — admitting ONLY
     `well_typed=True` and `lossless=True` chains whose output guarantees, witness specs, and
     boundary satisfy the goal. Lossy or ill-typed prefixes are pruned immediately (safe because
     `lossless` is anti-monotonic under the anti-laundering frame law).
  3. When no lossless chain is found (or when budget runs out), emits deterministic diagnostic
     `prescriptions` naming the exact missing goal supplier, missing witness spec, silent drop
     blocking a candidate chain, verifier mismatch, or budget exhaustion (honest partiality).
"""
from collections import deque

from . import pact as P
from . import records as R
from . import witness as W

MAX_STEPS_LIMIT = 16
MAX_EXPANSIONS_LIMIT = 10000
MAX_SOLUTIONS_LIMIT = 100
MAX_PRESCRIPTIONS = 64
SEED_ID = "__initial__"


def _parse_witness_map(raw, allowed_labels, name):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be an object mapping label -> witness spec")
    allowed = set(allowed_labels)
    out = {}
    for lbl in sorted(raw):
        if lbl not in allowed:
            raise ValueError(f"{name} key {lbl!r} not in allowed labels")
        parsed, err = W.parse_witness_spec(raw[lbl], lbl)
        if err:
            raise ValueError(f"{name}: {err}")
        out[lbl] = parsed
    return out


def _canon_req_labels(raw, name, *, allow_empty=False):
    if isinstance(raw, (set, frozenset, tuple)):
        raw = sorted(raw)
    labels, err = P._canon_labels(raw, name, allow_empty=allow_empty)
    if err:
        raise ValueError(err)
    return labels


def _goal_satisfied(comp, goal_set, req_w_keys, goal_boundary):
    if not (goal_set <= set(comp["gives"])):
        return False
    if goal_boundary is not None and not (goal_boundary & set(comp["boundary"])):
        return False
    out_ws = comp.get("witness_specs", {})
    for lbl, exp_key in req_w_keys.items():
        got = out_ws.get(lbl)
        if got is None or tuple(got) != exp_key:
            return False
    return True


def dream_recipes(
    recipes,
    *,
    goal_gives,
    initial_gives=(),
    initial_witnesses=None,
    required_witnesses=None,
    boundary=None,
    max_steps=4,
    max_expansions=256,
    max_solutions=16,
    allow_reuse=False,
):
    """Synthesize lossless, witness-typed compositions of `recipes` satisfying `goal_gives`.

    Pure, deterministic, and bounded by `(max_steps, max_expansions, max_solutions)`.
    """
    if not (R.is_int(max_steps) and 1 <= max_steps <= MAX_STEPS_LIMIT):
        raise ValueError(f"max_steps must be an int in 1..{MAX_STEPS_LIMIT}")
    if not (R.is_int(max_expansions) and 1 <= max_expansions <= MAX_EXPANSIONS_LIMIT):
        raise ValueError(f"max_expansions must be an int in 1..{MAX_EXPANSIONS_LIMIT}")
    if not (R.is_int(max_solutions) and 1 <= max_solutions <= MAX_SOLUTIONS_LIMIT):
        raise ValueError(f"max_solutions must be an int in 1..{MAX_SOLUTIONS_LIMIT}")
    if type(allow_reuse) is not bool:
        raise ValueError("allow_reuse must be a bool")

    goal_tuple = _canon_req_labels(goal_gives, "goal_gives", allow_empty=False)
    goal_set = set(goal_tuple)
    init_tuple = _canon_req_labels(initial_gives, "initial_gives", allow_empty=True)
    init_set = set(init_tuple)
    init_w = _parse_witness_map(initial_witnesses, init_set, "initial_witnesses")
    req_w = _parse_witness_map(required_witnesses, goal_set, "required_witnesses")
    req_w_keys = {lbl: W.witness_spec_key(spec) for lbl, spec in sorted(req_w.items())}
    goal_boundary = None
    if boundary is not None:
        goal_boundary = set(_canon_req_labels(boundary, "boundary", allow_empty=False))

    # Validate & deterministically sort input recipes by unique id
    by_id = {}
    for rec in recipes:
        if not isinstance(rec, P.Recipe):
            raise ValueError(f"expected pact.Recipe, got {type(rec).__name__}")
        if rec.id == SEED_ID:
            raise ValueError(f"reserved recipe id {SEED_ID!r}")
        if rec.id in by_id:
            raise ValueError(f"DUPLICATE_RECIPE_ID:{rec.id}")
        by_id[rec.id] = rec
    ordered = [by_id[k] for k in sorted(by_id)]

    prescriptions = []
    seen_presc = set()

    def _add_presc(code, **fields):
        if len(prescriptions) >= MAX_PRESCRIPTIONS:
            return
        entry = {"code": code, **fields}
        key = tuple(sorted((k, str(v)) for k, v in entry.items()))
        if key not in seen_presc:
            seen_presc.add(key)
            prescriptions.append(entry)

    # Pre-flight reachability diagnostics (goal suppliers & required witness specs)
    all_supplied = set(init_set)
    supplied_witness_keys = {lbl: {W.witness_spec_key(spec)} for lbl, spec in init_w.items()}
    for rec in ordered:
        all_supplied.update(rec.gives)
        for lbl, ver, pdig in rec.witness_specs:
            supplied_witness_keys.setdefault(lbl, set()).add((ver, pdig))

    for lbl in goal_tuple:
        if lbl not in all_supplied:
            _add_presc("MISSING_GOAL_SUPPLIER", label=lbl)
    for lbl, exp_key in sorted(req_w_keys.items()):
        if exp_key not in supplied_witness_keys.get(lbl, set()):
            _add_presc("MISSING_GOAL_WITNESS", label=lbl, verifier=exp_key[0])

    # Always build a synthetic seed recipe representing initial_gives (empty when none supplied)
    # so compose_recipes enforces that step 0 cannot leave unmet external prerequisites or witnesses.
    if goal_boundary is not None:
        seed_bnd = sorted(goal_boundary)
    else:
        union_bnd = set()
        for rec in ordered:
            union_bnd.update(rec.boundary)
        seed_bnd = sorted(union_bnd) if union_bnd else ["default"]
    seed_recipe = P.make_recipe(
        SEED_ID,
        requires=[],
        gives=list(init_tuple),
        boundary=seed_bnd,
        witnesses=init_w,
    )

    solutions = []
    expansions = 0
    budget_exhausted = False

    # Check trivial 0-step satisfaction from initial_gives alone
    if init_set:
        comp0 = P.compose_recipes([seed_recipe])
        if comp0["well_typed"] and comp0["lossless"] and _goal_satisfied(comp0, goal_set, req_w_keys, goal_boundary):
            solutions.append({"steps": [], "composition": comp0})

    # BFS queue stores tuples of user Recipe objects (excluding synthetic seed_recipe)
    queue = deque([()])
    while queue and len(solutions) < max_solutions:
        prefix = queue.popleft()
        if len(prefix) >= max_steps:
            continue
        used = {r.id for r in prefix}
        for cand in ordered:
            if not allow_reuse and cand.id in used:
                continue
            if expansions >= max_expansions:
                budget_exhausted = True
                break
            expansions += 1
            next_user = prefix + (cand,)
            comp = P.compose_recipes([seed_recipe] + list(next_user))

            if not comp["well_typed"]:
                for err in comp["errors"]:
                    if err.get("code") == "VERIFIER_SPEC_MISMATCH":
                        _add_presc(
                            "VERIFIER_SPEC_MISMATCH",
                            step=cand.id,
                            chain=[r.id for r in next_user],
                            guarantee=err.get("guarantee"),
                            expected=err.get("expected"),
                            actual=err.get("actual"),
                        )
                continue

            if not comp["lossless"]:
                if comp["silent_drops"]:
                    _add_presc("SILENT_DROP_BLOCKED", step=cand.id, dropped=list(comp["silent_drops"]))
                elif comp["declared_losses"]:
                    _add_presc("DECLARED_LOSS_BLOCKED", step=cand.id, lost=list(comp["declared_losses"]))
                continue

            if _goal_satisfied(comp, goal_set, req_w_keys, goal_boundary):
                solutions.append({
                    "steps": [r.id for r in next_user],
                    "composition": comp if init_set else P.compose_recipes(list(next_user)),
                })
                if len(solutions) >= max_solutions:
                    break
            elif len(next_user) < max_steps:
                queue.append(next_user)
        if budget_exhausted:
            break

    if budget_exhausted:
        _add_presc("BUDGET_EXHAUSTED", max_expansions=max_expansions, expansions=expansions)

    return {
        "warrant": "dream/1",
        "goal_gives": list(goal_tuple),
        "solutions": solutions,
        "solution_count": len(solutions),
        "expansions": expansions,
        "budget_exhausted": budget_exhausted,
        "prescriptions": sorted(prescriptions, key=lambda p: (p["code"], str(p))),
    }


def dream_pacts(
    snap,
    trust,
    as_of,
    *,
    goal_gives,
    initial_gives=(),
    initial_witnesses=None,
    required_witnesses=None,
    boundary=None,
    max_steps=4,
    max_expansions=256,
    max_solutions=16,
    allow_reuse=False,
    verifiers=None,
):
    """Resolve `ACTIVE`/`SETTLED` `pact@1` contracts at `as_of` and synthesize lossless goal chains."""
    pacts = P.resolve_pacts(snap, trust, as_of, verifiers=verifiers)
    recipes = []
    skipped = {}
    for pid in sorted(pacts):
        entry = pacts[pid]
        if entry.get("status") not in ("ACTIVE", "SETTLED"):
            skipped[pid] = f"STATUS_{entry.get('status')}"
            continue
        try:
            recipes.append(P.pact_to_recipe(entry))
        except ValueError as exc:
            skipped[pid] = str(exc)
    out = dream_recipes(
        recipes,
        goal_gives=goal_gives,
        initial_gives=initial_gives,
        initial_witnesses=initial_witnesses,
        required_witnesses=required_witnesses,
        boundary=boundary,
        max_steps=max_steps,
        max_expansions=max_expansions,
        max_solutions=max_solutions,
        allow_reuse=allow_reuse,
    )
    out["as_of"] = as_of
    out["considered_pacts"] = [r.id for r in recipes]
    out["skipped_pacts"] = skipped
    return out
