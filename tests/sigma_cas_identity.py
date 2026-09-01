#!/usr/bin/env python3
"""Reproducer: the ski@v1 re-executor enforces Identity by Hash at the CAS.

Warrant claims its blob store IS a Σ-GLYPH content-addressed store: the file
named `<h>` holds bytes whose SHA-256 is `<h>`. A store that returns bytes under
a FOREIGN key has lied about an address. Evaluating those bytes as the requested
node would let two conforming engines disagree on a WarrantID/verdict, so it must
be an INADMISSIBLE (unverified) check with a stable, path-free reason class —
never a computation that produced `pass`/`fail`, and never a traceback.

Before this change the bundled evaluator executed whatever bytes the store
returned (`foreign NodeHash -> bytes of I` ran, spent=1); the negative control
below reconstructs that unchecked fetch and shows it WOULD have executed, so the
positive assertions are not vacuous.

Failure class asserted here is Identity-by-Hash, distinguished from a merely
absent blob and from a JSON error.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "impl"))
os.environ.pop("SIGMA_GLYPH", None)          # exercise the BUNDLED, pinned engine
import warrant as W                          # noqa: E402

sg = W.load_sigma()
if sg is None:
    print("sigma-cas-identity: UNRUN — bundled Σ-GLYPH evaluator not found",
          file=sys.stderr)
    raise SystemExit(2)
assert getattr(sg, "WARRANT_SIGMA_UNPINNED", None) is False, \
    "bundled evaluator must be pinned"

_fail = []


def check(name, cond, detail=""):
    print(f"  {'ok ' if cond else 'BAD'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        _fail.append(name)


def _reason(store, check_hex):
    """run_ski_check's outcome as ('verdict', v) or ('unverified', reason)."""
    try:
        verdict, rh, spent = W.run_ski_check(store, check_hex)
        return ("verdict", verdict, rh, spent)
    except RuntimeError as ex:
        return ("unverified", str(ex))


def _store():
    td = tempfile.mkdtemp(prefix="cas-id-")
    st = W.Store(td)
    st.init()
    return st


def _put_check(st, term_hex, expect_hex, atp=64):
    blob = json.dumps({"ski": 1, "term": term_hex, "atp": atp,
                       "expect": expect_hex},
                      separators=(",", ":"), sort_keys=True).encode()
    return st.put_blob(blob)


def _write_blob_under(st, key_bytes, content):
    """Forge: write `content` into the file named by key_bytes.hex()."""
    (st.blobs / key_bytes.hex()).write_bytes(content)


I_BYTES = sg.I_BYTES
I_H = sg.node_hash(I_BYTES)                    # correct address of I
FOREIGN = hashlib.sha256(b"foreign-root-key").digest()
assert FOREIGN != I_H
EXPECT_I = I_H.hex()                            # evaluating I yields the I node

# ---- Case 1: foreign key on the ROOT term ---------------------------------
st = _store()
_write_blob_under(st, FOREIGN, I_BYTES)         # bytes of I under a foreign key
chk = _put_check(st, FOREIGN.hex(), EXPECT_I)
out = _reason(st, chk)
check("foreign key on root term -> unverified (not a verdict)",
      out[0] == "unverified", detail=str(out))
check("foreign root reason is Identity-by-Hash, path-free",
      out[0] == "unverified" and out[1] == "content does not match its address",
      detail=out[1] if out[0] == "unverified" else "")

# ---- Case 4 (same shape): forged result would MATCH expect ----------------
# expect == I_H, so an unchecked run returns "pass". The fix must refuse first.
check("forged blob whose result matches expect is NOT reported pass",
      not (out[0] == "verdict" and out[1] == "pass"), detail=str(out))

# ---- Case 2: foreign key on a NESTED thunk --------------------------------
st = _store()
app_bytes = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=I_H, right=FOREIGN)
app_h = sg.node_hash(app_bytes)
st.put_blob(app_bytes)                          # APPLY(I, foreign) correctly addressed
_write_blob_under(st, FOREIGN, I_BYTES)         # forged child
chk = _put_check(st, app_h.hex(), EXPECT_I)
out = _reason(st, chk)
check("foreign key on nested thunk -> unverified Identity-by-Hash",
      out[0] == "unverified" and out[1] == "content does not match its address",
      detail=str(out))

# ---- Case 3: store returns a NON-bytes object -----------------------------
class _NonBytesStore:
    def get(self, h):
        return 12345                            # not bytes
try:
    sg.eval_hash(FOREIGN, 8, _NonBytesStore())
    check("non-bytes store value -> ResourceFault", False)
except sg.ResourceFault as rf:
    check("non-bytes store value -> ResourceFault (non-bytes)",
          "non-bytes" in str(rf), detail=str(rf))

# ---- distinguish from a genuinely ABSENT blob (not Identity-by-Hash) -------
st = _store()
absent = hashlib.sha256(b"never-stored").digest()
chk = _put_check(st, absent.hex(), EXPECT_I)
out = _reason(st, chk)
check("absent blob is a DISSONANCE result, not a CAS mismatch",
      out[0] == "verdict",                       # unresolved -> canonical result
      detail=str(out))

# ---- distinguish from a JSON-malformed check blob -------------------------
st = _store()
bad = st.put_blob(b"{not json")
out = _reason(st, bad)
check("malformed check blob reason is JSON, not Identity-by-Hash",
      out[0] == "unverified" and "JSON" in out[1], detail=str(out))

# ---- P1: the check blob's OWN address is verified (the ROOT fetch) ----------
# Term thunks are checked inside BlobCAS; the root check blob must be too, or a
# valid check filed under a FOREIGN name is executed as if it were addressed.
st = _store()
good_blob = json.dumps({"ski": 1, "term": I_H.hex(), "atp": 64,
                        "expect": EXPECT_I},
                       separators=(",", ":"), sort_keys=True).encode()
foreign_name = hashlib.sha256(b"not-the-check-content").digest()
assert foreign_name != hashlib.sha256(good_blob).digest()
_write_blob_under(st, foreign_name, good_blob)   # valid check, foreign address
out = _reason(st, foreign_name.hex())
check("check blob filed under a foreign name -> unverified Identity-by-Hash",
      out[0] == "unverified" and out[1] == "content does not match its address",
      detail=str(out))
# control: filed under its TRUE address, the identical check verifies
st = _store()
true_name = st.put_blob(good_blob)
out = _reason(st, true_name)
check("the same check at its true address is admissible (pass)",
      out[0] == "verdict" and out[1] == "pass", detail=str(out))

# ---- P0: an UNPINNED evaluator never yields a settlement-grade verdict ------
# A byte-divergent $SIGMA_GLYPH override is flagged WARRANT_SIGMA_UNPINNED. Its
# ski@v1 result must be refused at the choke point (run_ski_check), so it cannot
# reach filing / fingerprint / settlement — UNLESS an operator EXPLICITLY enters
# differential mode, which is never settlement-grade (verify --settlement bars it).
st = _store()
valid = st.put_blob(good_blob)                    # the same valid I -> I check


class _Unpinned:                                  # behaves exactly like the real
    WARRANT_SIGMA_UNPINNED = True                 # engine, but is flagged unpinned

    def __getattr__(self, n):
        return getattr(sg, n)


os.environ.pop("WARRANT_SIGMA_DIFFERENTIAL", None)
try:
    W.run_ski_check(st, valid, sg=_Unpinned())
    check("unpinned evaluator is REFUSED (no verdict)", False)
except RuntimeError as ex:
    check("unpinned evaluator refused with a non-settlement-grade reason",
          "unpinned" in str(ex), detail=str(ex))
os.environ["WARRANT_SIGMA_DIFFERENTIAL"] = "1"    # deliberate differential opt-in
try:
    v = W.run_ski_check(st, valid, sg=_Unpinned())
    check("explicit WARRANT_SIGMA_DIFFERENTIAL=1 runs the unpinned engine",
          v[0] == "pass", detail=str(v))
finally:
    os.environ.pop("WARRANT_SIGMA_DIFFERENTIAL", None)

# ---- P0 control: settlement is PINNED-ONLY, even WITH the differential flag ---
# The flag unlocks a direct run_ski_check; it must NEVER buy a settlement verdict.
# Point $SIGMA_GLYPH at a byte-divergent evaluator, set the flag, and run the real
# CLI settlement verification of this repo's own store: it must emit exactly one
# settlement ERR and exit nonzero — no masquerading clean settlement.
REPO = Path(__file__).resolve().parents[1]
_warrants, _tcfg = REPO / ".warrants", REPO / "trust-config.json"
if _warrants.is_dir() and _tcfg.is_file():
    _div = Path(tempfile.mkdtemp(prefix="cas-div-"))
    (_div / "sigma_glyph.py").write_text(
        (REPO / "impl" / "sigma_glyph.py").read_text() + "\n# divergent\n")
    _env = dict(os.environ, SIGMA_GLYPH=str(_div), WARRANT_SIGMA_DIFFERENTIAL="1")
    _r = subprocess.run(
        [sys.executable, str(REPO / "impl" / "warrant.py"), "--store",
         str(_warrants), "verify", "--settlement", "--trust-config", str(_tcfg)],
        capture_output=True, text=True, env=_env)
    _blob = _r.stdout + _r.stderr
    check("verify --settlement + unpinned + FLAG exits nonzero",
          _r.returncode != 0, detail=f"rc={_r.returncode}")
    check("verify --settlement + unpinned refuses (settlement ERR, flag ignored)",
          "settlement requires the pinned" in _blob,
          detail=next((ln for ln in _blob.splitlines() if "ERR" in ln), _blob[:80]))
    check("exactly ONE settlement ERR (a global refusal, not per-record noise)",
          _blob.count("settlement requires the pinned") == 1)
else:
    check("settlement-unpinned control (repo store present)", True,
          detail="repo .warrants/trust-config.json absent; control skipped")

# ---- NEGATIVE CONTROL: the guard is what refuses the forged bytes ----------
# Non-vacuity must not depend on git history: once the fix is committed, HEAD
# carries the guard, and a `git show HEAD` control would silently go vacuous.
# Instead, derive the UNGUARDED evaluator from the CURRENT vendored module by
# deleting EXACTLY the two-line CAS check from force(), then show that identical
# evaluator runs `foreign NodeHash -> bytes of I` to a result (spent>=1). That
# it now executes proves those two lines — nothing else — are load-bearing.
BUNDLED_SRC = (Path(__file__).resolve().parents[1] / "impl" / "sigma_glyph.py").read_text()
GUARD = ('    if not isinstance(b, bytes):\n'
         '        raise ResourceFault("store returned non-bytes")\n'
         '    if node_hash(b) != h:\n'
         '        raise ResourceFault("CAS key mismatch")\n')
guard_present = BUNDLED_SRC.count(GUARD)
check("negative control: the Identity-by-Hash guard is present exactly once",
      guard_present == 1, detail=f"found {guard_present} occurrence(s)")


class _DictCAS(dict):
    def get(self, h, default=None):            # a plain mapping: no address check
        return dict.get(self, h, default)


if guard_present == 1:
    unguarded = {}
    exec(compile(BUNDLED_SRC.replace(GUARD, "", 1),   # noqa: S102
                 "sigma_glyph@unguarded", "exec"), unguarded)
    cas = _DictCAS({FOREIGN: I_BYTES})         # bytes of I under a foreign key
    r, spent = unguarded["eval_hash"](FOREIGN, 64, cas)
    unguarded_rh = unguarded["term_hash"](r).hex()
    check("negative control: WITHOUT the guard the forged bytes EXECUTE",
          unguarded_rh == EXPECT_I and spent >= 1,
          detail=f"rh={unguarded_rh[:12]} spent={spent}")
else:
    check("negative control: WITHOUT the guard the forged bytes EXECUTE",
          False, detail="guard block not found verbatim; cannot form the control")

print(f"\n{'FAIL' if _fail else 'PASS'} — ski@v1 CAS Identity-by-Hash: a foreign "
      f"key is an inadmissible check, and the guard is demonstrably non-vacuous.")
raise SystemExit(1 if _fail else 0)
