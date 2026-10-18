"""Resumable Book I computation: DRAFT reference for phases P1/P2 of the
sigma-warrant redesign (Documents/Codex/2026-10-17/sigma-warrant-redesign).

NOT NORMATIVE. Book I `eval_receipt`/`eval_hash` are unchanged and remain the
specification; this module runs the same transition (`sigma_glyph.step5`) and
adds what the redesign asks of a kernel:

- a ComputationRoot that names the task (term, runtime, cost model, environment),
  separate from any budget;
- a canonical MachineState: the term tree with thunks and materialized nodes kept
  apart, so a paid force is never forgotten (a cold thunk and its materialized
  APPLY share a term_hash; they do not share a state_id);
- Checkpoints with accumulating credit: an unaffordable action leaves the state
  and `spent` untouched (PAUSED), and a later grant adds to what is left;
- three kernel outcomes, NORMAL_FORM / PAUSED / BLOCKED_REFERENCE, kept apart from
  local host outcomes (EVIDENCE_UNAVAILABLE, CAS_MISMATCH, RESOURCE_FAULT,
  ADMISSION_REFUSED) that never stand in for an answer;
- replay verification of a foreign checkpoint (REPLAYED / UNVERIFIED / INVALID),
  with a local cache keyed by verifier identity;
- a CycleWitness verifier: replay to the entry, replay the period, require
  positive cost, no terminal state on the way, and the same state at the end.

Why no control state: `step5` re-derives the leftmost-outermost demanded action
from the tree on every step, and which action it picks does not depend on the
remaining budget (only whether it is affordable). So the tree IS the whole
operational state, and segmentation invariance follows from determinism plus
atomic, pre-checked charging.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sigma_glyph as G  # noqa: E402

SCHEMA_ROOT = "sigma-resume.root@draft-1"
SCHEMA_ENV = "sigma-resume.environment@draft-1"
SCHEMA_CHECKPOINT = "sigma-resume.checkpoint@draft-1"
STATE_MAGIC = b"SGS1"
RUNTIME_SEMANTICS_ID = "sigma-book1-0.6.0/hash-thunk/leftmost-outermost"
COST_MODEL_ID = "atp/size-priced/adr-001+adr-003"
VERIFIER_ID = hashlib.sha256(
    (RUNTIME_SEMANTICS_ID + "|" + COST_MODEL_ID + "|" + SCHEMA_CHECKPOINT).encode()).hexdigest()
MAX_INT = 2**53 - 1          # one integer domain for JCS and JS (redesign §7)

# Kernel outcomes (canonical answers of `advance`).
NORMAL_FORM, PAUSED, BLOCKED_REFERENCE = "NORMAL_FORM", "PAUSED", "BLOCKED_REFERENCE"
KERNEL = (NORMAL_FORM, PAUSED, BLOCKED_REFERENCE)
# Local outcomes: what this host could or would not do. Never an answer.
EVIDENCE_UNAVAILABLE, CAS_MISMATCH = "EVIDENCE_UNAVAILABLE", "CAS_MISMATCH"
RESOURCE_FAULT, ADMISSION_REFUSED = "RESOURCE_FAULT", "ADMISSION_REFUSED"
INCOMPLETE = "INCOMPLETE"           # an action limit / deadline stopped the run; last atomic state kept (N62)
LOCAL = (EVIDENCE_UNAVAILABLE, CAS_MISMATCH, RESOURCE_FAULT, ADMISSION_REFUSED, INCOMPLETE)
MAX_STATE_BYTES = 64 * 1024 * 1024  # admission before decoding (N61); the same ceiling as impl-rs resume mode
# Verification bases.
REPLAYED, ATTESTED, UNVERIFIED = "REPLAYED", "ATTESTED", "UNVERIFIED"


class InvalidEncoding(ValueError):
    """Bytes that are not the canonical encoding of anything this module emits."""


class IntegerOverflow(ValueError):
    """A credit or count left the integer domain. Never wrapped, never clamped."""


class EvidenceUnavailable(Exception):
    """The environment names this hash, but its bytes were not delivered here."""


def _canon(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(doc):
    return hashlib.sha256(_canon(doc)).hexdigest()


def _check_int(name, v):
    if type(v) is not int or not 0 <= v <= MAX_INT:
        raise InvalidEncoding(f"{name} must be an integer in 0..2^53-1, not {v!r}")
    return v


# ---------------------------------------------------------------- environment

class Environment:
    """A frozen manifest of the hashes a computation may demand, plus wherever
    their bytes happen to live. The manifest is identity; delivery is not.

    - a hash outside the manifest (and not genesis) is a semantic BLOCKED_REFERENCE;
    - a hash in the manifest whose bytes are absent is local EVIDENCE_UNAVAILABLE;
    - bytes under a hash they do not have are refused (CAS_MISMATCH)."""

    def __init__(self, hashes, delivered):
        self.hashes = frozenset(hashes)
        for h in self.hashes:
            if not (isinstance(h, bytes) and len(h) == 32):
                raise InvalidEncoding("environment hashes must be 32 bytes")
        self.delivered = delivered          # anything with .get(h) -> bytes | None
        self.missing = None                 # last hash outside the manifest

    @property
    def environment_id(self):
        return _digest({"schema": SCHEMA_ENV, "hashes": sorted(h.hex() for h in self.hashes)})

    def get(self, h):
        """The `store` step5 sees: None means unresolved (semantic)."""
        if h not in self.hashes:
            self.missing = h
            return None
        b = self.delivered.get(h)
        if b is None:
            raise EvidenceUnavailable(h.hex())
        return b                             # step5's force() checks the CAS relation


def root(input_term_hash, env, runtime=RUNTIME_SEMANTICS_ID):
    """ComputationRoot: the task, without any budget or segmentation. The
    runtime profile is part of the task: the same term under another profile is
    another computation."""
    if not (isinstance(input_term_hash, bytes) and len(input_term_hash) == 32):
        raise InvalidEncoding("input term hash must be 32 bytes")
    if runtime not in PROFILES:
        raise InvalidEncoding(f"unknown runtime profile {runtime!r}")
    doc = {"schema": SCHEMA_ROOT, "runtime_semantics_id": runtime,
           "cost_model_id": PROFILES[runtime][1], "input_term_hash": input_term_hash.hex(),
           "environment_id": env.environment_id}
    return doc, _digest(doc)


# ---------------------------------------------------------------- state codec

_TAG = {"thunk": b"T", "lit": b"L", "ref": b"R", "dis": b"D"}
_KIND = {v[0]: k for k, v in _TAG.items()}


def encode_state(computation_id, term):
    """Canonical bytes of a machine state: preorder, one tag per node, 32-byte
    payloads. Iterative (no recursion limit) and independent of Python object
    identity or sharing: two equal trees encode to the same bytes."""
    out = bytearray(STATE_MAGIC + bytes.fromhex(computation_id))
    stack = [term]
    while stack:
        t = stack.pop()
        if t[0] == "app":
            out += b"A"
            stack.append(t[2])
            stack.append(t[1])
        else:
            out += _TAG[t[0]] + t[1]
    return bytes(out)


def decode_state(b):
    """(computation_id, term) from canonical bytes, or InvalidEncoding."""
    if not isinstance(b, bytes) or len(b) < 4 + 32 + 33 or b[:4] != STATE_MAGIC:
        raise InvalidEncoding("not a sigma-resume state")
    cid, i = b[4:36].hex(), 36
    # Build with an explicit stack: each frame collects the children of one APPLY.
    frames, result = [], None
    while True:
        if i >= len(b):
            raise InvalidEncoding("truncated state")
        tag = b[i:i + 1]
        if tag == b"A":
            frames.append([])
            i += 1
            continue
        kind = _KIND.get(tag[0])
        if kind is None:
            raise InvalidEncoding(f"unknown node tag {tag!r} at {i}")
        if i + 33 > len(b):
            raise InvalidEncoding("truncated payload")
        node = (kind, bytes(b[i + 1:i + 33]))
        i += 33
        while frames:
            frames[-1].append(node)
            if len(frames[-1]) < 2:
                break
            left, right = frames.pop()
            node = ("app", left, right)
        else:
            result = node
            break
    if i != len(b):
        raise InvalidEncoding("trailing bytes after state")
    return cid, result


def state_id(state_bytes):
    return hashlib.sha256(state_bytes).hexdigest()


# ---------------------------------------------------------------- checkpoints

def checkpoint(computation_id, state_bytes, credit, spent, peak, parent, actions):
    doc = {"schema": SCHEMA_CHECKPOINT, "computation_id": computation_id,
           "state_id": state_id(state_bytes), "credit_total": _check_int("credit_total", credit),
           "spent_total": _check_int("spent_total", spent),
           "peak_semantic_size": _check_int("peak_semantic_size", peak),
           "parent_checkpoint_id": parent,
           "transition_claim": {"actions": _check_int("actions", actions)}}
    return doc, _digest(doc)


def parse_checkpoint(raw):
    """A checkpoint from canonical JSON bytes; anything else is InvalidEncoding.
    Duplicate names, floats, bools, unknown fields and non-canonical bytes are
    refused, not normalized."""
    try:
        doc = json.loads(raw, object_pairs_hook=_no_duplicates, parse_float=_no_float)
    except (ValueError, TypeError) as e:
        raise InvalidEncoding(f"checkpoint is not JSON: {e}") from None
    want = {"schema", "computation_id", "state_id", "credit_total", "spent_total",
            "peak_semantic_size", "parent_checkpoint_id", "transition_claim"}
    if not isinstance(doc, dict) or set(doc) != want or doc["schema"] != SCHEMA_CHECKPOINT:
        raise InvalidEncoding("checkpoint fields are not exactly the schema's")
    for k in ("credit_total", "spent_total", "peak_semantic_size"):
        _check_int(k, doc[k])
    for k in ("computation_id", "state_id"):
        if not _is_digest(doc[k]):
            raise InvalidEncoding(f"{k} must be 64 lowercase hex characters")
    if doc["parent_checkpoint_id"] is not None and not _is_digest(doc["parent_checkpoint_id"]):
        raise InvalidEncoding("parent_checkpoint_id must be null or 64 lowercase hex characters")
    claim = doc["transition_claim"]
    if not isinstance(claim, dict) or set(claim) != {"actions"}:
        raise InvalidEncoding("transition_claim must be {actions}")
    _check_int("actions", claim["actions"])
    if doc["spent_total"] > doc["credit_total"]:
        raise InvalidEncoding("spent exceeds credit")
    if _canon(doc) != raw:
        raise InvalidEncoding("checkpoint bytes are not canonical")
    return doc, hashlib.sha256(raw).hexdigest()


def _is_digest(v):
    return isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)


def _no_duplicates(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError(f"duplicate name {k!r}")
        seen[k] = v
    return seen


def _no_float(s):
    raise ValueError(f"non-integer number {s}")


# ---------------------------------------------------------------- the machine

class Result:
    """What one advance returns: an outcome, and the checkpoint of the last
    completed atomic action (for a local outcome too: the state is still valid,
    because no action is ever half-applied)."""

    def __init__(self, outcome, ckpt, ckpt_id, state_bytes, missing=None, detail=None):
        self.outcome, self.checkpoint, self.checkpoint_id = outcome, ckpt, ckpt_id
        self.state_bytes, self.missing, self.detail = state_bytes, missing, detail

    @property
    def kernel(self):
        return self.outcome in KERNEL

    def term(self):
        return decode_state(self.state_bytes)[1]


def start(computation_id, input_term_hash):
    """Initial checkpoint: the cold input thunk, no credit, nothing spent."""
    sb = encode_state(computation_id, ("thunk", input_term_hash))
    doc, cid = checkpoint(computation_id, sb, 0, 0, 1, None, 0)
    return doc, cid, sb


# The transition. Book I's `step5` in production; tests may substitute another
# deterministic transition (same contract: (term, remaining, env, stats, limits)
# -> (term, cost) | None, raising BudgetExhausted/Unresolved) to exercise the
# cycle verifier, because no Sigma term with a state cycle is known (REVIEW §4).
STEP = G.step5


def _run(term, available, env, limits, max_actions=None, step=None):
    """Advance until normal form, an unaffordable or unresolved action, or
    `max_actions`. Returns (term, spent, actions, peak, outcome, detail)."""
    stats, spent, actions, peak = {"fetches": 0}, 0, 0, 0
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 3 * limits["max_node_depth"] + 2000))
    try:
        # Measure the incoming state only once the fence is up and inside the
        # handler: a deep foreign state is a local fault, never a host exception
        # (independent review SG04).
        peak = G.size(term)
        while max_actions is None or actions < max_actions:
            try:
                r = (step or STEP)(term, available - spent, env, stats, limits)
            except G.BudgetExhausted:
                return term, spent, actions, peak, PAUSED, None
            except G.Unresolved:
                return term, spent, actions, peak, BLOCKED_REFERENCE, None
            except EvidenceUnavailable as e:
                return term, spent, actions, peak, EVIDENCE_UNAVAILABLE, str(e)
            except G.ResourceFault as e:
                kind = CAS_MISMATCH if "CAS" in str(e) or "non-bytes" in str(e) else RESOURCE_FAULT
                return term, spent, actions, peak, kind, str(e)
            if r is None:
                # As Book I's evaluator does: a configured ceiling must hold on a
                # completed return, so no NORMAL_FORM is ever larger than allowed.
                try:
                    G.resource_check(term, limits)
                except G.ResourceFault as e:
                    return term, spent, actions, peak, RESOURCE_FAULT, str(e)
                return term, spent, actions, peak, NORMAL_FORM, None
            term, spent, actions = r[0], spent + r[1], actions + 1
            peak = max(peak, G.size(term))
            if actions % 256 == 0:
                try:
                    G.resource_check(term, limits)
                except G.ResourceFault as e:
                    return term, spent, actions, peak, RESOURCE_FAULT, str(e)
        return term, spent, actions, peak, None, "action limit"
    except RecursionError:
        return term, spent, actions, peak, RESOURCE_FAULT, "python recursion depth"
    finally:
        sys.setrecursionlimit(old)


def advance(ckpt, ckpt_id, state_bytes, env, additional_credit, limits=None, runtime=RUNTIME_SEMANTICS_ID,
            max_actions=None):
    """Add credit to a checkpoint and run. The caller vouches for the input
    checkpoint (its own, or one `verify` REPLAYED); advance checks only that the
    state bytes are the ones the checkpoint names."""
    limits = limits or G.VERIFIER_LIMITS
    _check_int("additional_credit", additional_credit)
    if len(state_bytes) > MAX_STATE_BYTES:
        return Result(ADMISSION_REFUSED, ckpt, ckpt_id, state_bytes, detail="state larger than admitted")
    if state_id(state_bytes) != ckpt["state_id"]:
        raise InvalidEncoding("state bytes are not the checkpoint's state")
    credit = ckpt["credit_total"] + additional_credit
    if credit > MAX_INT:
        raise IntegerOverflow(f"credit {credit} exceeds 2^53-1")
    allowed = limits.get("max_atp")
    if allowed is not None and credit - ckpt["spent_total"] > allowed:
        return Result(ADMISSION_REFUSED, ckpt, ckpt_id, state_bytes,
                      detail=f"available {credit - ckpt['spent_total']} exceeds {allowed}")
    cid, term = decode_state(state_bytes)
    env.missing = None
    term, spent, actions, peak, outcome, detail = _run(term, credit - ckpt["spent_total"], env, limits,
                                                       max_actions, step=PROFILES[runtime][0]())
    if outcome is None:                 # _run's action limit; verify_cycle reads it as None
        outcome = INCOMPLETE
    sb = encode_state(cid, term)
    doc, new_id = checkpoint(cid, sb, credit, ckpt["spent_total"] + spent,
                             max(ckpt["peak_semantic_size"], peak), ckpt_id, actions)
    missing = env.missing.hex() if outcome == BLOCKED_REFERENCE and env.missing else None
    return Result(outcome, doc, new_id, sb, missing=missing, detail=detail)


# ---------------------------------------------------------------- runtime profiles

# A DRAFT richer basis, as its own profile (its own runtime id, so its own
# computations): Y and M are primitives because their SKI encodings behave
# differently (leftover `(I a)` wrappers: no SKI term with a state cycle is known,
# while Y I and M M cycle), W because it duplicates the way M does. Pricing keeps
# Book I's rule for S: duplicating costs 1 + the size of what is duplicated, so
# `semantic size <= initial size + spent` still holds. B, C, T are left out until
# measured: they only shorten terms.
RICH_RUNTIME_ID = "sigma-resume-draft/ski+Y+M+W/hash-thunk/leftmost-outermost"
RICH_COST_MODEL_ID = "atp/size-priced/adr-001+adr-003+duplication-priced(Y,M,W)"


def _genesis_literal(name):
    b = G.ser(G.LITERAL, G.F_ATOM, atom=G.sha(name))
    return G.node_hash(b), b


Y_H, _Y_BYTES = _genesis_literal(b"Y")
M_H, _M_BYTES = _genesis_literal(b"M")
W_H, _W_BYTES = _genesis_literal(b"W")
RICH_GENESIS = {Y_H: _Y_BYTES, M_H: _M_BYTES, W_H: _W_BYTES}


def _dup(cost, remaining):
    if cost > remaining:
        raise G.BudgetExhausted()
    return cost


def _rich_head(t, remaining):
    f, a = t[1], t[2]
    if G.glyph_eq(f, Y_H):                                   # Y f -> f (Y f)
        return ("app", a, ("app", f, a)), _dup(1 + G.size(a), remaining)
    if G.glyph_eq(f, M_H):                                   # M x -> x x
        return ("app", a, a), _dup(1 + G.size(a), remaining)
    if f[0] == "app" and G.glyph_eq(f[1], W_H):              # W g x -> g x x
        return ("app", ("app", f[2], a), a), _dup(1 + G.size(a), remaining)
    return None


def rich_step(t, remaining, env, stats, limits):
    """One priced action under the rich profile, in Book I's order: a head
    contraction (rich rules, then S/K/I), else the function part, else the
    argument. Same contract as `step5`."""
    if t[0] == "thunk" and t[1] in RICH_GENESIS:
        return None                                          # intrinsic leaf, never fetched
    if t[0] != "app":
        return G.step5(t, remaining, env, stats, limits)
    r = _rich_head(t, remaining)
    if r is not None:
        return r
    r = G._head_reduction(t[1], t[2], remaining)
    if r is not G._NO_REDUCTION:
        return r
    r = rich_step(t[1], remaining, env, stats, limits)
    if r is not None:
        return ("app", r[0], t[2]), r[1]
    r = rich_step(t[2], remaining, env, stats, limits)
    if r is not None:
        return ("app", t[1], r[0]), r[1]
    return None


# runtime id -> (transition, cost model id). The Book I entry reads STEP late, so
# a test may substitute it.
PROFILES = {RUNTIME_SEMANTICS_ID: (lambda: STEP, COST_MODEL_ID),
            RICH_RUNTIME_ID: (lambda: rich_step, RICH_COST_MODEL_ID)}


# ---------------------------------------------------------------- verification

class VerifiedCache:
    """Checkpoints THIS verifier replayed, keyed by verifier identity, so a
    change of engine, cost model or schema invalidates every entry."""

    def __init__(self, verifier_id=None):
        self.verifier_id = verifier_id or VERIFIER_ID
        self.entries = {}

    def put(self, computation_id, ckpt_id, ckpt, state_bytes):
        self.entries[(self.verifier_id, computation_id, ckpt_id)] = (ckpt, state_bytes)

    def get(self, computation_id, ckpt_id, verifier_id=None):
        return self.entries.get((verifier_id or VERIFIER_ID, computation_id, ckpt_id))


PREFIX = "PREFIX"      # verified reachable atomic prefix; its credit allows more actions (not terminal)


def _context_error(root_doc, env):
    """The context a recipient selected: the environment, runtime and cost
    model of THEIR root. Shared by checkpoint and cycle verification, so a
    producer cannot swap the environment under either (review R1)."""
    runtime = root_doc.get("runtime_semantics_id")
    if root_doc.get("environment_id") != env.environment_id or runtime not in PROFILES \
            or root_doc.get("cost_model_id") != PROFILES[runtime][1]:
        return "CONTEXT_MISMATCH"
    return None


def _replay_base(cid, root_doc, doc, cache):
    """Where replay starts: a parent this verifier replayed before, else the root.
    Returned with credit equal to its spent, so replay adds exactly the spent
    the claim needs."""
    base = cache.get(cid, doc["parent_checkpoint_id"]) if cache is not None and doc["parent_checkpoint_id"] else None
    if base is None:
        b_doc, b_id, b_state = start(cid, bytes.fromhex(root_doc["input_term_hash"]))
    else:
        (b_doc, b_state), b_id = base, doc["parent_checkpoint_id"]
    b_doc = dict(b_doc, credit_total=b_doc["spent_total"])
    return b_doc, b_id, b_state


def verify(expected_root, env, raw_checkpoint, state_bytes, cache=None, limits=None):
    """Is this checkpoint reachable from the root WE expect, under OUR semantics?

    Returns (basis, code, replay_actions). basis is REPLAYED only after this
    verifier reproduced the state, spent and peak by running the machine, from
    the root or from a checkpoint it replayed before (cache). A signature is
    never consulted here: whoever signed it, an unreplayed checkpoint is
    UNVERIFIED.

    Replay goes to the claimed SPENT, not the claimed credit: spent strictly
    increases, so exactly one state has it, and an atomic prefix taken with
    credit left over (an action limit, a deadline) is still verifiable (review
    R2). The code then says what the checkpoint is at its own credit: a kernel
    outcome if no further action fits, else PREFIX, a verified reachable prefix
    that is not terminal. `transition_claim.actions` is segment-local and
    informational; reachability does not rest on it."""
    limits = limits or G.VERIFIER_LIMITS
    try:
        doc, ckpt_id = parse_checkpoint(raw_checkpoint)
        cid_in_state, _ = decode_state(state_bytes)
    except InvalidEncoding as e:
        return UNVERIFIED, f"INVALID_ENCODING: {e}", 0
    root_doc, cid = expected_root
    ctx = _context_error(root_doc, env)
    if ctx:
        return UNVERIFIED, ctx, 0
    runtime = root_doc["runtime_semantics_id"]
    if doc["computation_id"] != cid or cid_in_state != cid:
        return UNVERIFIED, "ROOT_MISMATCH", 0
    if state_id(state_bytes) != doc["state_id"]:
        return UNVERIFIED, "STATE_MISMATCH", 0
    b_doc, b_id, b_state = _replay_base(cid, root_doc, doc, cache)
    if doc["spent_total"] < b_doc["spent_total"]:
        return UNVERIFIED, "INVALID_TRANSITION: spent decreased", 0
    replay = advance(b_doc, b_id, b_state, env, doc["spent_total"] - b_doc["spent_total"], limits, runtime)
    actions = replay.checkpoint["transition_claim"]["actions"]
    if not replay.kernel:
        return UNVERIFIED, f"NOT_ASSESSED: replay stopped locally ({replay.outcome})", actions
    got = replay.checkpoint
    same = (got["state_id"] == doc["state_id"] and got["spent_total"] == doc["spent_total"]
            and got["peak_semantic_size"] == doc["peak_semantic_size"])
    if not same:
        return UNVERIFIED, "UNVERIFIED_PREFIX: replay does not reach this state", actions
    if cache is not None:
        cache.put(cid, ckpt_id, doc, state_bytes)
    # What is the checkpoint at its own credit? Probe from the verified state.
    probe_doc = dict(got, credit_total=doc["spent_total"])
    probe = advance(probe_doc, ckpt_id, state_bytes, env, doc["credit_total"] - doc["spent_total"], limits,
                    runtime, max_actions=1)
    if probe.outcome in KERNEL and probe.checkpoint["transition_claim"]["actions"] == 0:
        return REPLAYED, probe.outcome, actions
    return REPLAYED, PREFIX if probe.checkpoint["transition_claim"]["actions"] else probe.outcome, actions


# ---------------------------------------------------------------- cycles

def cycle_witness(computation_id, entry_ckpt, entry_state_bytes, actions, cost):
    """A claim: from this entry, `actions` affordable actions costing `cost`
    lead back to the same machine state. Accounting is not part of the claim's
    projection; it only says how far to replay."""
    return {"schema": SCHEMA_CYCLE, "computation_id": computation_id,
            "entry_spent_total": _check_int("entry_spent_total", entry_ckpt["spent_total"]),
            "entry_state_id": state_id(entry_state_bytes),
            "cycle_action_count": _check_int("cycle_action_count", actions),
            "cycle_cost": _check_int("cycle_cost", cost)}


WITNESS_FIELDS = {"schema", "computation_id", "entry_spent_total", "entry_state_id",
                  "cycle_action_count", "cycle_cost"}
SCHEMA_CYCLE = "sigma-resume.cycle@draft-1"


def _witness_shape_problem(witness):
    """Structural validation BEFORE any replay: exact fields, schema, integer
    domain, digest format. A malformed witness is refused by name, never a host
    exception (independent re-review N2)."""
    if not isinstance(witness, dict) or set(witness) != WITNESS_FIELDS:
        return "fields are not exactly the witness schema's"
    if witness["schema"] != SCHEMA_CYCLE:
        return "unknown witness schema"
    if not (_is_digest(witness["computation_id"]) and _is_digest(witness["entry_state_id"])):
        return "computation_id and entry_state_id must be 64 lowercase hex characters"
    try:
        for k in ("entry_spent_total", "cycle_action_count", "cycle_cost"):
            _check_int(k, witness[k])
    except InvalidEncoding as e:
        return str(e)
    return None


def verify_cycle(expected_root, env, witness, limits=None):
    """CYCLE_PROVEN, or a named refusal. The verifier replays the prefix from the
    root it chose to exactly the entry's spent (spent is strictly increasing, so
    the state there is unique), then the period one action at a time."""
    limits = limits or G.VERIFIER_LIMITS
    root_doc, cid = expected_root
    shape = _witness_shape_problem(witness)
    if shape:
        return f"INVALID_CYCLE_WITNESS: {shape}"
    if witness["computation_id"] != cid:
        return "PREFIX_MISMATCH"
    entry_spent, n, cost = witness["entry_spent_total"], witness["cycle_action_count"], witness["cycle_cost"]
    if n == 0 or cost == 0:
        return "INVALID_CYCLE_WITNESS: a cycle needs at least one priced action"
    if n > cost:
        return "INVALID_CYCLE_WITNESS: more actions than cost (every action costs at least 1)"
    allowed = limits.get("max_atp")
    if allowed is not None and cost > allowed:
        # The same per-call ceiling advance() applies: replaying the period is
        # work this host would not admit for an ordinary run. A local refusal,
        # NOT a judgement on the witness (independent re-review N1).
        return f"NOT_ASSESSED: {ADMISSION_REFUSED} (period cost {cost} exceeds this host's {allowed})"
    ctx = _context_error(root_doc, env)
    if ctx:
        return ctx
    runtime = root_doc["runtime_semantics_id"]
    s_doc, s_id, s_state = start(cid, bytes.fromhex(root_doc["input_term_hash"]))
    pre = advance(s_doc, s_id, s_state, env, entry_spent, limits, runtime)
    if pre.outcome != PAUSED or pre.checkpoint["spent_total"] != entry_spent:
        return f"PREFIX_MISMATCH: replay to spent {entry_spent} ends {pre.outcome} at {pre.checkpoint['spent_total']}"
    if pre.checkpoint["state_id"] != witness["entry_state_id"]:
        return "PREFIX_MISMATCH: the entry is not the state the root reaches"
    _, entry = decode_state(pre.state_bytes)
    term, spent, done, _, outcome, _ = _run(entry, cost, env, limits, max_actions=n, step=PROFILES[runtime][0]())
    if done != n or outcome is not None and outcome != PAUSED:
        return f"INVALID_CYCLE_WITNESS: the period stops after {done} actions ({outcome})"
    if spent != cost:
        return f"INVALID_CYCLE_WITNESS: the period costs {spent}, not {cost}"
    if encode_state(cid, term) != pre.state_bytes:
        return "INVALID_CYCLE_WITNESS: the period does not return to the entry state"
    return "CYCLE_PROVEN"
