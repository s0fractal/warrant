"""Sigma-GLYPH Book I reference implementation (oracle semantics v0.5.x, current release bundle v0.6.1), Book I.

Scope: SigmaNodeV2 canonical serialization/deserialization, validation,
SHA-256 NodeHash, CAS object store, genesis I/K/S (intrinsic), and the
v0.5 HASH-THUNK evaluator: lazy left-spine resolution (ADR-003) with
size-priced ATP under the hash-leaf size model (ADR-001 composition).
Every materialization is a priced step; unresolved hashes count as
size 1; genesis axioms are recognized by hash without any store.
Serialization and NodeHashes are UNCHANGED from v0.4.x — only
evaluation semantics and ATP accounting changed (see CHANGELOG v0.5.0
migration guide). Waves live in impl/sigma_wave.py (Book II).
"""
import hashlib
import sys

sha = lambda b: hashlib.sha256(b).digest()

# ---------- OpCodes / Flags ----------
LITERAL, REF, APPLY, RESERVED, DISSONANCE = 0x00, 0x01, 0x02, 0x03, 0xFF
F_ATOM, F_LEFT, F_RIGHT = 0x01, 0x02, 0x04
FLAGS_REQ = {LITERAL: F_ATOM, REF: F_ATOM, APPLY: F_LEFT | F_RIGHT, DISSONANCE: F_ATOM}

# ---------- Reason hashes ----------
R_INVALID = sha(b"Invalid Object")
R_ATP     = sha(b"ATP Exhausted")
R_UNRES   = sha(b"Unresolved Reference")

# ---------- Canonical serialization ----------
def ser(op, flags, atom=None, left=None, right=None):
    b = bytes([op, flags])
    for f in (atom, left, right):
        if f is not None:
            assert len(f) == 32
            b += f
    return b

def node_hash(b): return sha(b)

def deser(buf):
    """Validate + parse. Returns dict or None (caller maps None -> Invalid Object)."""
    if len(buf) < 2: return None
    op, flags = buf[0], buf[1]
    if flags & ~0x07: return None
    if op not in FLAGS_REQ: return None            # covers RESERVED 0x03
    if flags != FLAGS_REQ[op]: return None
    exp = 2 + 32 * bin(flags & 0x07).count("1")
    if len(buf) != exp: return None
    out, off = {"op": op, "flags": flags}, 2
    for bit, name in ((F_ATOM, "atom"), (F_LEFT, "left"), (F_RIGHT, "right")):
        if flags & bit:
            out[name] = buf[off:off + 32]; off += 32
    return out

INVALID_OBJECT = ser(DISSONANCE, F_ATOM, atom=R_INVALID)

# ---------- Genesis ----------
I_BYTES = ser(LITERAL, F_ATOM, atom=sha(b"I"))
K_BYTES = ser(LITERAL, F_ATOM, atom=sha(b"K"))
S_BYTES = ser(LITERAL, F_ATOM, atom=sha(b"S"))
I_H, K_H, S_H = map(node_hash, (I_BYTES, K_BYTES, S_BYTES))
FALSE_BYTES = ser(APPLY, F_LEFT | F_RIGHT, left=K_H, right=I_H)
FALSE_H = node_hash(FALSE_BYTES)

# ---------- CAS ----------
class Store:
    def __init__(self): self.m = {}
    def put(self, b):
        h = node_hash(b); self.m[h] = b; return h
    def get(self, h): return self.m.get(h)  # None => unresolved

class ResourceFault(Exception):
    """Local, NON-canonical implementation fault (limits breached). Not a DISSONANCE."""

# ---------- Terms (hash-thunk machine, v0.5) ----------
# term := ("thunk", h)                        unresolved hash (size 1)
#       | ("lit", atom) | ("ref", h) | ("dis", reason)
#       | ("app", t, t)                       children may be thunks
GENESIS = {I_H: I_BYTES, K_H: K_BYTES, S_H: S_BYTES}   # intrinsic axioms (Book I §5.1)
UINT32_MAX = 2**32 - 1

def term_bytes(t):
    if t[0] == "lit": return ser(LITERAL, F_ATOM, atom=t[1])
    if t[0] == "ref": return ser(REF, F_ATOM, atom=t[1])
    if t[0] == "dis": return ser(DISSONANCE, F_ATOM, atom=t[1])
    return ser(APPLY, F_LEFT | F_RIGHT, left=term_hash(t[1]), right=term_hash(t[2]))

def term_hash(t):
    if t[0] == "thunk": return t[1]           # hash-transparent
    return node_hash(term_bytes(t))

def size(t):
    """Hash-leaf size model (ADR-001×003): materialized nodes count 1 each,
    an unresolved hash leaf counts exactly 1, a materialized REF counts 2
    (node + target thunk)."""
    k = t[0]
    if k == "app": return 1 + size(t[1]) + size(t[2])
    if k == "ref": return 2
    return 1                                   # thunk, lit, dis

def depth(t):
    return 1 if t[0] != "app" else 1 + max(depth(t[1]), depth(t[2]))

def is_glyph(t, gh): return term_hash(t) == gh   # Identity by Hash (general, recursive)

def glyph_eq(t, gh):
    """O(1) glyph check for redex patterns: a thunk carries its hash; a
    materialized LITERAL hashes in constant time; APPLY/REF/DISSONANCE cannot
    equal a LITERAL's NodeHash short of a SHA-256 collision (out of scope)."""
    if t[0] == "thunk": return t[1] == gh
    if t[0] == "lit":   return node_hash(ser(LITERAL, F_ATOM, atom=t[1])) == gh
    return False

# ---------- Hash-thunk stepper (v0.5: lazy left-spine, size-priced ATP) ----------
class Unresolved(Exception): pass
class BudgetExhausted(Exception): pass

def force(h, store, stats, limits):  # NOSONAR python:S8495
    """Materialize ONE node from hash h; children stay thunks. Genesis axioms
    are intrinsic — synthesized without the store (Book I §5.1). Bytes failing
    §4.1 materialize the Canonical Invalid Object (§3.5b).

    Returns a Term, which is a tagged union: ``("lit", atom)`` and ``("app", l, r)``
    have different arities on purpose (see the Term grammar above). A rule that
    wants every return of a function to be the same length is reading a sum type
    as a record, so S8495 is suppressed here by name rather than by silence."""
    stats["fetches"] += 1
    if stats["fetches"] > limits["max_store_fetches"]: raise ResourceFault("fetches")
    b = GENESIS.get(h)
    if b is None: b = store.get(h)
    if b is None: raise Unresolved()
    # A mapping lookup is not, by itself, a content-addressed store.  The
    # public evaluator accepts any object with ``get`` (tests and downstream
    # callers use plain dicts), so verify the CAS relation at the boundary
    # instead of assuming only Store.put() can reach this function.  Treat a
    # wrong key as a local storage fault: the bytes may be a perfectly valid
    # SigmaNodeV2, but evaluating them as the requested hash would violate
    # Identity by Hash and could make two conforming engines disagree.
    if not isinstance(b, bytes):
        raise ResourceFault("store returned non-bytes")
    if node_hash(b) != h:
        raise ResourceFault("CAS key mismatch")
    n = deser(b)
    if n is None: return ("dis", R_INVALID)
    op = n["op"]
    if op == LITERAL:    return ("lit", n["atom"])
    if op == REF:        return ("ref", n["atom"])
    if op == DISSONANCE: return ("dis", n["atom"])
    return ("app", ("thunk", n["left"]), ("thunk", n["right"]))

_NO_REDUCTION = object()


def _require_budget(cost, remaining):
    if cost > remaining:
        raise BudgetExhausted()


def _head_reduction(function, argument, remaining):
    """Return an I/K/S head contraction, or the private no-redex sentinel."""
    if glyph_eq(function, I_H):
        _require_budget(1, remaining)
        return argument, 1
    if function[0] != "app":
        return _NO_REDUCTION
    if glyph_eq(function[1], K_H):
        _require_budget(1, remaining)
        return function[2], 1
    if function[1][0] != "app" or not glyph_eq(function[1][1], S_H):
        return _NO_REDUCTION
    x, y, z = function[1][2], function[2], argument
    cost = 1 + size(z)
    _require_budget(cost, remaining)
    return ("app", ("app", x, z), ("app", y, z)), cost


def _step_application(t, remaining, store, stats, limits):
    function, argument = t[1], t[2]
    reduced = _head_reduction(function, argument, remaining)
    if reduced is not _NO_REDUCTION:
        return reduced
    result = step5(function, remaining, store, stats, limits)
    if result is not None:
        return ("app", result[0], argument), result[1]
    result = step5(argument, remaining, store, stats, limits)
    if result is not None:
        return ("app", function, result[0]), result[1]
    return None


def step5(t, remaining, store, stats, limits):
    """One priced action, leftmost-outermost with lazy spine resolution.
    Returns (new_term, cost) with cost <= remaining, or None (normal form).
    Raises BudgetExhausted if the demanded action is unaffordable (checked
    BEFORE the action; a minimum-cost check of 1 precedes even the fetch,
    so exhaustion at budget 0 is decided without touching the store).
    Raises Unresolved if the demanded hash is absent (not charged)."""
    kind = t[0]
    if kind == "thunk":
        if t[1] in GENESIS: return None                      # NF leaf by hash
        _require_budget(1, remaining)
        v = force(t[1], store, stats, limits)                # may raise Unresolved
        c = size(v)                                          # 1 (lit/dis) / 2 (ref) / 3 (app)
        _require_budget(c, remaining)                         # fetched bytes discarded
        return v, c
    if kind == "ref":                                        # R-R: unwrap one level
        _require_budget(1, remaining)
        return ("thunk", t[1]), 1
    if kind == "app":
        return _step_application(t, remaining, store, stats, limits)
    return None                                              # lit / dis are normal forms

DEFAULT_LIMITS = {"max_node_depth": 4096,
                  "max_materialized_nodes": 1_000_000,
                  "max_store_fetches": 1_000_000,
                  # No admission cap: this module is the conformance oracle and
                  # must be able to answer for any budget the Book permits.
                  "max_atp": None}

# What a *verifier* should use instead. `eval` is total, so a stranger's term
# always terminates -- and `size <= atp + 1` means the budget they choose is also
# their licence over the verifier's memory. A 32-bit ATP is up to 4,294,967,295
# priced actions, so "finite" and "affordable" are different words. This cap is a
# local admission decision, made BEFORE any allocation or any store access, and
# it is NOT a canonical Sigma-GLYPH outcome (Book I s3.6): it says the verifier
# declined to run the computation, not what the computation evaluates to.
VERIFIER_LIMITS = dict(DEFAULT_LIMITS, max_atp=10_000_000)


class AdmissionRefused(Exception):
    """The verifier declined to begin. Distinct from ResourceFault, which is
    breached during evaluation, and from every DISSONANCE, which is a result.

    Kept a separate type on purpose: a caller that confuses "I would not run
    this" with "this is what it evaluates to" has let the party supplying the
    term decide what the verifier reports."""

    def __init__(self, claimed, allowed):
        super().__init__(f"claimed ATP {claimed} exceeds this verifier's "
                         f"admission limit {allowed}; refused before execution")
        self.claimed, self.allowed = claimed, allowed


def admit(atp, limits=None):
    """Decide whether to begin at all. Raises before anything is touched.

    Book I's consensus domain is ``uint32``.  Python's ``bool`` is an ``int``
    subclass and floats participate in numeric comparisons, so an ordinary
    range check is not enough to keep the API on that domain.
    """
    if type(atp) is not int or not 0 <= atp <= UINT32_MAX:
        raise ValueError("atp must be a uint32 integer")
    allowed = (limits or DEFAULT_LIMITS).get("max_atp")
    if allowed is not None and atp > allowed:
        raise AdmissionRefused(atp, allowed)


def resource_check(t, limits):
    """Raise ResourceFault (local, non-canonical §3.6) if the term breaches a
    configured maximum. Called on the 256-step in-flight sample AND before any
    normal-form return, so a `max_*` control is never exceeded on a completed
    return (Codex v0.6.4 hardening audit P1)."""
    if size(t) > limits["max_materialized_nodes"]:
        raise ResourceFault("term growth")
    if depth(t) > limits["max_node_depth"]:
        raise ResourceFault("term depth")


EXITS = ("normal_form", "atp_exhausted", "unresolved_reference")


class Receipt(tuple):
    """What `eval` returns: {exit, result_hash, atp_spent} (Book I §3.4).

    `result_hash` alone does not identify the exit and never did:
    ``DISSONANCE(ATP Exhausted)`` is an ordinary term that can sit in a content
    environment and evaluate to a normal form, so one hash means "finished" or
    "ran out" depending on how it was reached. A caller that must tell them apart
    reads `exit`.

    A tuple subclass so that a receipt still unpacks as a pair for the
    compatibility profile below, which is why nothing that used the two-value
    form has to change at once."""

    def __new__(cls, term, spent, exit_kind):
        if exit_kind not in EXITS:
            raise ValueError(f"exit must be one of {EXITS}, not {exit_kind!r}")
        return super().__new__(cls, (term, spent))

    def __init__(self, term, spent, exit_kind):
        super().__init__()
        self.term, self.atp_spent, self.exit = term, spent, exit_kind

    def __repr__(self):
        return (f"Receipt(exit={self.exit!r}, "
                f"result_hash={self.result_hash.hex()[:12]}…, "
                f"atp_spent={self.atp_spent})")

    @property
    def result_hash(self):
        return term_hash(self.term)

    def as_dict(self):
        return {"exit": self.exit, "result_hash": self.result_hash.hex(),
                "atp_spent": self.atp_spent}


def eval_receipt(h, atp, env, limits=None):
    """eval(term_hash, uint32 atp, content environment) -> Receipt (Book I §3.4).

    The three inputs the Book states. `env` is a partial map from NodeHash to
    bytes whose entries hash to their own key (§3.5); bytes under a foreign key
    are refused locally rather than executed."""
    term, spent, exit_kind = _eval_hash_raw(h, atp, env, limits)
    return Receipt(term, spent, exit_kind)


def eval_hash(h, atp, store, limits=None):
    """Compatibility profile (Book I §3.4): -> (result_term, atp_spent).

    Loses no guarantee and is not deprecated; the one question it cannot answer
    is which exit occurred. `eval_receipt` answers it.
    Canonical outcomes: normal form | DISSONANCE(ATP Exhausted) | DISSONANCE(Unresolved Reference).
    v0.5 discipline (Book I §3.4): every action — rule firing OR thunk
    materialization — is priced; an unaffordable action yields ATP Exhausted
    BEFORE it happens; spent never exceeds atp; a failed action (resolve
    failure) is not charged; eval is total over canonical outcomes.
    The memory bound is semantic: materialized size - initial size < spent.
    Resource limit breach -> ResourceFault (local, non-canonical).
    Claimed ATP above `limits["max_atp"]` -> AdmissionRefused, raised before any
    allocation or store access (local, non-canonical)."""
    term, spent, _ = _eval_hash_raw(h, atp, store, limits)
    return term, spent


def _eval_hash_raw(h, atp, store, limits=None):
    """The machine. Returns (term, spent, exit); the two public forms wrap it."""
    limits = limits or DEFAULT_LIMITS
    admit(atp, limits)
    if not isinstance(h, bytes) or len(h) != 32:
        raise ValueError("term_hash must be exactly 32 bytes")
    stats = {"fetches": 0}
    old_rl = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_rl, 3 * limits["max_node_depth"] + 2000))
    try:
        t = ("thunk", h)
        spent = 0
        steps = 0
        while True:
            # Memory fence guards on ACTUAL materialized size, not on `spent`.
            # The ADR-001 bound `size <= 1 + spent` is only an UPPER bound, so
            # `spent` is not a valid size proxy: a divergent term (e.g. Omega)
            # keeps its size tiny while `spent` grows without bound, so guarding
            # on `spent` would wrongly fault it instead of returning the canonical
            # DISSONANCE(ATP Exhausted) that TV-7 mandates for all n. Both size and
            # depth need a traversal — amortize them (non-canonical local faults,
            # so the check cadence is an implementation choice, s3.6).
            steps += 1
            if steps % 256 == 0:
                resource_check(t, limits)          # in-flight runaway fence
            try:
                r = step5(t, atp - spent, store, stats, limits)
            except BudgetExhausted:
                return ("dis", R_ATP), spent, "atp_exhausted"
            except Unresolved:
                return ("dis", R_UNRES), spent, "unresolved_reference"
            if r is None:
                # normal form: a `max_*` limit MUST hold on the returned term,
                # even for evaluations that finish before the 256-step sample
                # (Codex v0.6.4 hardening audit P1 — a completed return must
                # never exceed the configured maximum). DISSONANCE returns
                # above are size-1 leaves and cannot breach.
                resource_check(t, limits)
                return t, spent, "normal_form"
            t = r[0]
            spent += r[1]
    except RecursionError:
        raise ResourceFault("python recursion depth") from None
    finally:
        sys.setrecursionlimit(old_rl)



# ---------- Canonical Lambda->SKI Compiler, Profile C1 ----------
# lambda term := ("var", name) | ("lam", name, body) | ("lapp", f, a) | SKI term (passthrough)
IG, KG, SG = ("lit", sha(b"I")), ("lit", sha(b"K")), ("lit", sha(b"S"))

def _fv(t):
    k = t[0]
    if k == "var": return {t[1]}
    if k == "lam": return _fv(t[2]) - {t[1]}
    if k in ("lapp", "app"): return _fv(t[1]) | _fv(t[2])
    return set()

def c1(t):
    k = t[0]
    if k == "var": return t
    if k == "lapp": return ("app", c1(t[1]), c1(t[2]))
    if k == "lam": return _abstract(t[1], c1(t[2]))
    return t  # SKI passthrough

def _abstract(x, m):
    if m == ("var", x): return IG                                   # A-1
    if x not in _fv(m): return ("app", KG, m)                       # A-2
    if m[0] == "app":                                                # A-3
        return ("app", ("app", SG, _abstract(x, m[1])), _abstract(x, m[2]))
    raise ValueError("free variable escapes abstraction")

# ---------- Test suite ----------
# Linear self-test orchestration shares one store and intentionally keeps each
# conformance assertion visible in execution order; runtime logic lives above.
def run_tests():  # NOSONAR python:S3776
    st = Store()
    for b in (I_BYTES, K_BYTES, S_BYTES, FALSE_BYTES): st.put(b)

    A = lambda l, r: ("app", l, r)
    i_glyph, k_glyph, s_glyph = (("lit", sha(b"I")),
                                 ("lit", sha(b"K")),
                                 ("lit", sha(b"S")))

    def put_tree(t):
        if t[0] == "app": put_tree(t[1]); put_tree(t[2])
        return st.put(term_bytes(t))

    ok = []
    def chk(name, cond): ok.append(cond); print(("OK  " if cond else "FAIL"), name)

    # Genesis hashes
    chk("I hash",     I_H.hex() == "2f33694d09810641fa5b8c47a7c0dc42e1b99eb8c9784a00aaee9a66330f4162")
    chk("K hash",     K_H.hex() == "bc0c2fe26e44e2aed8ce500a74963bc270fd4a49ec0c2e4837ce7a64bb0a486c")
    chk("S hash",     S_H.hex() == "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6")
    chk("FALSE hash", FALSE_H.hex() == "65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098")

    # Validation / negative
    chk("invalid: flags high bits", deser(bytes([0x00, 0x09]) + b"\x00"*32) is None)
    chk("invalid: reserved 0x03",   deser(bytes([0x03, 0x02]) + b"\x00"*32) is None)
    chk("invalid: bad length",      deser(bytes([0x02, 0x06]) + b"\x00"*33) is None)
    chk("invalid object bytes",     INVALID_OBJECT.hex() ==
        "ff01" + R_INVALID.hex())

    # Bare genesis thunk: NF by hash, zero cost, no store needed
    r, sp = eval_hash(I_H, 10, Store())
    chk("bare genesis I -> NF, 0 ATP, empty store", term_hash(r) == I_H and sp == 0)

    # Genesis intrinsic: REF(K_H) on an EMPTY store resolves (force 2 + R-R 1)
    st_empty = Store()
    refk = st_empty.put(ser(REF, F_ATOM, atom=K_H))
    r, sp = eval_hash(refk, 10, st_empty)
    chk("genesis intrinsic: REF(K_H), empty store -> K (3 ATP)", term_hash(r) == K_H and sp == 3)

    # TV-4: APPLY(I,K) -> K: force root (3) + R-I (1) = 4 ATP
    h = put_tree(A(i_glyph, k_glyph))
    r, sp = eval_hash(h, 4, st);  chk("I·K -> K (4 ATP)", term_hash(r) == K_H and sp == 4)
    r, sp = eval_hash(h, 0, st);  chk("I·K budget 0 -> ATP, 0 spent (no fetch)", r == ("dis", R_ATP) and sp == 0)
    r, sp = eval_hash(h, 3, st);  chk("I·K budget 3 -> ATP after root force", r == ("dis", R_ATP) and sp == 3)
    r, sp = eval_hash(h, 2, st);  chk("I·K budget 2 -> ATP, fetch discarded", r == ("dis", R_ATP) and sp == 0)

    # TV-5: SKK·I -> I: 3 forces (9) + R-S (1+size(z)=2) + R-K (1) = 12 ATP
    h = put_tree(A(A(A(s_glyph, k_glyph), k_glyph), i_glyph))
    r, sp = eval_hash(h, 100, st); chk("SKK·I -> I (12 ATP)", term_hash(r) == I_H and sp == 12)
    r, sp = eval_hash(h, 11, st);  chk("SKK·I budget 11 -> ATP", r == ("dis", R_ATP))

    # TV-6: duplication — S I I (I K); hash-leaf pricing; NF unchanged from v0.4
    term_t = A(A(A(s_glyph, i_glyph), i_glyph), A(i_glyph, k_glyph))
    term_t_hash = put_tree(term_t)
    r, sp = eval_hash(term_t_hash, 100, st)
    nf = term_hash(r)
    print("      SII(IK): normal form =", "APPLY(K,K)" if nf == node_hash(
        ser(APPLY, 0x06, left=K_H, right=K_H)) else nf.hex(), "| ATP =", sp,
        "| T hash =", term_t_hash.hex())
    chk("SII(IK) normal form APPLY(K,K)", nf == node_hash(ser(APPLY, 0x06, left=K_H, right=K_H)))
    chk("SII(IK) size-priced cost = 21", sp == 21)

    # TV-7: Omega — non-terminating, deterministic exhaustion at any budget
    omega_half = A(A(s_glyph, i_glyph), i_glyph)
    omega = A(omega_half, omega_half)
    omega_hash = put_tree(omega)
    r, sp = eval_hash(omega_hash, 500, st)
    print("      Omega hash =", omega_hash.hex(), "| result:",
          "ATP Exhausted" if r == ("dis", R_ATP) else r)
    chk("Omega -> ATP Exhausted", r == ("dis", R_ATP) and sp <= 500)
    # TV-7 "for all n": Omega's materialized size stays tiny, so even a budget
    # far past max_materialized_nodes MUST still yield canonical ATP Exhausted,
    # NOT a size ResourceFault. (Regression guard: the memory fence must key on
    # actual size, never on `spent` — see eval_hash. Opus 4.8 review 2026-07, M1.)
    tiny_mem = {"max_node_depth": 4096, "max_materialized_nodes": 1000,
                "max_store_fetches": 10**6}
    r2, sp2 = eval_hash(omega_hash, 5000, st, limits=tiny_mem)
    chk("Omega, budget >> mem-limit -> ATP Exhausted (not size fault)",
        r2 == ("dis", R_ATP) and sp2 <= 5000)

    # TV-8: unresolved child — APPLY(I, missing): R-I fires lazily, THEN the
    # missing hash becomes the demanded root and fails to force
    ghost = sha(b"this node was never stored")
    hb = st.put(ser(APPLY, 0x06, left=I_H, right=ghost))
    r, sp = eval_hash(hb, 10, st)
    chk("missing child -> Unresolved Reference (4 spent: force+R-I)", r == ("dis", R_UNRES) and sp == 4)

    # TV-9: REF chain: force ref2 (2) + R-R (1) + force ref1 (2) + R-R (1) = 6
    r1 = st.put(ser(REF, F_ATOM, atom=K_H))
    r2 = st.put(ser(REF, F_ATOM, atom=r1))
    r, sp = eval_hash(r2, 10, st)
    chk("REF chain -> K (6 ATP)", term_hash(r) == K_H and sp == 6)
    r, sp = eval_hash(r2, 1, st)
    chk("REF chain budget 1 -> ATP, 0 spent (force costs 2)", r == ("dis", R_ATP) and sp == 0)

    # ADR-003 divergence class: dead missing arguments MUST NOT block reduction
    hkd = st.put(ser(APPLY, 0x06, left=FALSE_H, right=ghost))       # (K I) ghost
    r, sp = eval_hash(hkd, 100, st)
    chk("K-dead-missing -> I (lazy; was Unresolved in v0.4)", term_hash(r) == I_H and sp == 7)
    inner = put_tree(A(A(s_glyph, A(k_glyph, i_glyph)),
                       A(k_glyph, k_glyph)))
    hsd = st.put(ser(APPLY, 0x06, left=inner, right=ghost))         # S (K I) (K K) ghost
    r, sp = eval_hash(hsd, 100, st)
    chk("S(KI)(KK)-dead-missing -> K (divergence class)", term_hash(r) == K_H and sp == 20)

    # Memory bound (ADR-001): materialized size - 1 < spent along any evaluation
    limits = dict(DEFAULT_LIMITS)
    stats = {"fetches": 0}
    t, spent, smax = ("thunk", term_t_hash), 0, 1
    while True:
        rr = step5(t, 10_000, st, stats, limits)
        if rr is None: break
        t = rr[0]; spent += rr[1]; smax = max(smax, size(t))
    chk("memory bound: size_max - 1 <= spent", smax - 1 <= spent)


    # TV-10 (C1 canonical compiler)
    lam_id = ("lam", "x", ("var", "x"))
    chk("C1[lx.x] = I", term_hash(c1(lam_id)) == I_H)
    lam_k = ("lam", "x", ("lam", "y", ("var", "x")))
    ck = c1(lam_k)   # expected S (K K) I
    exp = A(A(s_glyph, A(k_glyph, k_glyph)), i_glyph)
    chk("C1[lxy.x] = S(KK)I", term_hash(ck) == term_hash(exp))
    print("      C1[lxy.x] hash =", term_hash(ck).hex())
    # behaves as K: (C1[lxy.x] S) K -> S
    ht = put_tree(A(A(ck, s_glyph), k_glyph))
    r, sp = eval_hash(ht, 64, st)
    chk("C1[lxy.x] S K -> S (20 ATP)", term_hash(r) == S_H and sp == 20)

    # Resource guard: tiny depth limit trips as FAULT, not dissonance
    try:
        eval_hash(omega_hash, 10_000, st, limits={"max_node_depth": 8,
                  "max_materialized_nodes": 10**6,
                  "max_store_fetches": 10**6})
        chk("resource fault raised", False)
    except ResourceFault:
        chk("resource fault raised (non-canonical)", True)

    # Deep left spine: materialization is PRICED, so a small budget exhausts
    # deterministically instead of materializing the whole spine (ADR-001 point)
    hd = I_H
    for _ in range(1500):
        hd = st.put(ser(APPLY, 0x06, left=hd, right=I_H))
    try:
        r, sp = eval_hash(hd, 3, st)
        chk("depth-1500 spine, atp 3 -> exhausted after root force", r == ("dis", R_ATP) and sp == 3)
    except RecursionError:
        chk("depth-1500 spine, atp 3 -> exhausted after root force", False)

    # Deep spine BEYOND max_node_depth with a big budget -> ResourceFault,
    # never RecursionError (s3.6 guard still the second fence; tight custom
    # limits keep the O(depth^2) spine walk fast)
    tight = {"max_node_depth": 512, "max_materialized_nodes": 10**6,
             "max_store_fetches": 10**6}
    try:
        eval_hash(hd, 100_000, st, limits=tight)
        chk("depth-1500 spine, depth limit 512 -> resource fault", False)
    except ResourceFault:
        chk("depth-1500 spine, depth limit 512 -> resource fault (non-canonical)", True)
    except RecursionError:
        chk("depth-1500 spine, depth limit 512 -> resource fault", False)

    # Codex v0.6.4 hardening audit P1: a `max_*` control must hold on a
    # COMPLETED normal-form return, even for evaluations that finish before
    # the 256-step in-flight sample. FALSE = APPLY(K,I): size 3, depth 2.
    stf = Store(); hf = stf.put(FALSE_BYTES)
    def _lim(d, m):
        return {"max_node_depth": d, "max_materialized_nodes": m,
                "max_store_fetches": 100}
    try:
        eval_hash(hf, 10, stf, _lim(1, 100))
        chk("early-NF over depth limit -> ResourceFault", False)
    except ResourceFault:
        chk("early-NF over depth limit -> ResourceFault (not an over-limit return)", True)
    try:
        eval_hash(hf, 10, stf, _lim(100, 1))
        chk("early-NF over size limit -> ResourceFault", False)
    except ResourceFault:
        chk("early-NF over size limit -> ResourceFault (not an over-limit return)", True)
    try:
        r, sp = eval_hash(hf, 10, stf, _lim(2, 3))     # exact bound: must return
        chk("early-NF at exact bound (depth=2,size=3) returns normally",
            size(r) == 3 and depth(r) == 2 and sp == 3)
    except ResourceFault:
        chk("early-NF at exact bound returns normally", False)

    print("\nALL PASS" if all(ok) else "\nFAILURES PRESENT")
    return all(ok)

# This module declares no verbs beyond the default self-test. The constant is
# what tools/check_release_surface.py reads to build its RUNNABLE /
# NOT_RUNNABLE table, so a verb added below without being classified there
# fails the release gate instead of shipping unexercised.
VERBS = ()

if __name__ == "__main__":
    # `run_tests()` used to be called for its printing only: the process exited
    # 0 while stdout said FAILURES PRESENT, so `python -m sigma_glyph && echo ok`
    # — what CI does by default — reported success on a failing Book I oracle.
    # The two sibling modules always propagated their verdict; this one did not.
    if sys.argv[1:]:
        print(f"usage: {sys.argv[0]} (no arguments; runs the Book I self-test)\n"
              f"  unknown verb {sys.argv[1]!r} — this module declares no verbs. "
              f"Refusing rather than silently running the self-test and "
              f"reporting success for a command that does not exist.",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if run_tests() else 1)
