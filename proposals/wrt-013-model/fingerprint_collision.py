#!/usr/bin/env python3
"""One term, one §7 outcome fingerprint, two exits — the case `ski@v2` answers.

    python3 proposals/wrt-013-model/fingerprint_collision.py /path/to/sigma_glyph.py

`/path/to/sigma_glyph.py` is the Book I 0.6.0 module — the one inside PyPI
`sigma-glyph==0.7.0`, sha256
`f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4`.

WHAT THIS ASSERTS, AND WHY IT IS NOT THE EARLIER SCRIPT'S CLAIM
--------------------------------------------------------------
rev 1 of WRT-013 showed two runs with equal `result_hash` and equal `atp_spent`
and called it a fingerprint collision. It was not: the two runs used different
TERMS, and `term` is the second member of the §7 `ski@v1` tuple
(`impl/warrant.py:972`), so Warrant computes two different fingerprints for them.
The script never called `fingerprint()` and so could not have noticed. Codex's
review of PR #78 (R1) found this and supplied the corrected case; this script is
the repaired control.

The real collision needs ONE term whose evaluation reaches the same node by two
different routes, under two budgets:

    term T  = APPLY(I, APPLY(I, DISSONANCE("ATP Exhausted")))
    expect  = H(DISSONANCE("ATP Exhausted"))

    atp 0 -> the machine cannot afford its first action: it exits
             `atp_exhausted` and its result IS the canonical DISSONANCE node.
    atp 9 -> the machine reduces T to normal form, and that normal form IS the
             same DISSONANCE node.

Both re-runs answer `expect`, so both verdicts are `pass`; `term` and `expect`
are identical by construction; `atp_spent` is not in the tuple. Therefore the
two reasons carry the SAME §7 fingerprint, computed here by Warrant's own
`fingerprint()` over a real `Store` and its real `ski@v1` evaluator — while Book
I 0.6.0 reports `atp_exhausted` for one and `normal_form` for the other.

Under §7 the second reason is then "nothing new" and cannot re-open a settled
question, although it demonstrates something the first did not: that the term
HAS a normal form. That is the representational gap `ski@v2` closes — and it is
a gap in this repository's own settlement arithmetic, not a claim about any
outside consumer's demand.

Exit status: 0 iff the fingerprints are equal AND the exits differ; 1 otherwise.

    --rev1   rebuild the DIFFERENT-term pair rev 1 called a collision, and assert
             that Warrant computes two DIFFERENT fingerprints for it. That is the
             falsification control for this script: if the assertion above could
             not fail, it would not be measuring anything.

    --isolate
             hold the CLAIMED exit fixed and vary only the ACTUAL one, so the
             proposed ski@v2 tuple is separated from the claim it carries. See
             `isolating_control` below for why the default pair cannot do this.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the checkout this file is in
sys.path.insert(0, str(ROOT / "impl"))
import warrant as W                                  # noqa: E402  (real fingerprint path)

EXPECTED_V06_SHA = "f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rev1_control(e06):
    """rev 1's pair: equal result hash, equal spend, DIFFERENT terms.

    Warrant's §7 tuple starts (runtime, term, expect, …), so two terms can never
    share a fingerprint. Asserting that here is what makes `main`'s equality
    assertion a measurement rather than a slogan.
    """
    store = W.Store(tempfile.mkdtemp(prefix="wrt013-rev1-"))
    store.init()
    dis_bytes = e06.ser(e06.DISSONANCE, e06.F_ATOM, atom=e06.sha(b"ATP Exhausted"))
    dis_h = e06.node_hash(dis_bytes)
    store.put_blob(dis_bytes)
    node = dis_h
    for _ in range(2):
        b = e06.ser(e06.APPLY, e06.F_LEFT | e06.F_RIGHT, left=e06.I_H, right=node)
        node = e06.node_hash(b)
        store.put_blob(b)
    # A: the §8.2 specimen term, exhausting at atp 9. Its blobs live in examples/ski.
    spec = json.loads((ROOT / "examples/ski/check.json").read_text())
    for f in sorted((ROOT / "examples/ski").glob("*.bin")):
        store.put_blob(f.read_bytes())
    pairs = [("A §8.2 term", spec["term"], 9), ("B APPLY(I,·)² term", node.hex(), 9)]
    expect = dis_h.hex()
    reasons = []
    for _label, term, atp in pairs:
        blob = store.put_blob(W.canon({"ski": 1, "term": term, "atp": atp,
                                       "expect": expect}))
        reasons.append({"kind": "check", "check": blob, "runtime": "ski@v1",
                        "verdict": "pass"})
    body = {"warrant": "0.2", "decision": "accept", "subject": {"hash": "11" * 32},
            "under": ["22" * 32], "because": reasons, "evidence": [],
            "actor": {"id": "a@x"}, "prior": [], "ts": 0}
    fps = [W.fingerprint(r, body, store) for r in reasons]
    for (label, term, atp), fp in zip(pairs, fps):
        print(f"  {label:20s} atp={atp}  term={term[:16]}…  fingerprint={'None' if fp is None else fp[1][:16] + '…'}")
    if fps[0] is not None and fps[1] is not None and fps[0] != fps[1]:
        print("\n=> different terms, different fingerprints: rev 1's pair was an "
              "output collision, NOT a settlement collision. The corrected case is "
              "the default mode of this script.")
        return 0
    print("\n=> control failed: expected two distinct fingerprints", file=sys.stderr)
    return 1


def v2_fingerprint(term, expect, expect_exit, receipt, omit_actual_exit=False):
    """The §7 tuple WRT-013 §3.6 PROPOSES for ski@v2 — a model, not an implementation.

    No ski@v2 verifier exists; this function is the design's arithmetic written
    down so the vectors can be checked against it before anything is built.
    `omit_actual_exit` is the mutant: an implementation that adopted the contract
    but forgot to put the RE-RUN's exit in the tuple.
    """
    verdict = "pass" if (receipt.exit == expect_exit
                         and receipt.result_hash.hex() == expect) else "fail"
    tup = ("ski@v2", term, expect, expect_exit, verdict, receipt.result_hash.hex())
    return tup if omit_actual_exit else tup + (receipt.exit,)


def isolating_control(e06):
    """Same term, same expect, same CLAIMED exit — only the ACTUAL exit differs.

    Vector 19's two-pass authoring example varies `expect_exit` (atp_exhausted →
    normal_form) as well as the actual exit, so its two fingerprints differ even
    for an implementation that never put the actual exit in the tuple: the
    claimed member alone separates them. Codex's review of rev 2 (P2) asked for
    a case that isolates the field, and this is it.

    Holding `expect_exit = unresolved_reference` for both checks makes both
    verdicts `fail` (neither run reaches that exit) and leaves term, expect,
    verdict and result hash identical. What remains is the actual exit —
    `atp_exhausted` at atp 0, `normal_form` at atp 9. The full proposed tuples
    MUST differ; the mutant's tuples MUST be equal. `normal_form` as the fixed
    claim would not isolate anything: the verdict would move from fail to pass
    and carry the difference by itself.
    """
    store = W.Store(tempfile.mkdtemp(prefix="wrt013-isolate-"))
    store.init()
    term, expect = _build_m5_term(store, e06)
    claimed = "unresolved_reference"
    rows = []
    for atp in (0, 9):
        rec = e06.eval_receipt(bytes.fromhex(term), atp, _BlobCAS(store))
        rows.append((atp, rec,
                     v2_fingerprint(term, expect, claimed, rec),
                     v2_fingerprint(term, expect, claimed, rec, omit_actual_exit=True)))
    print(f"term    {term}\nexpect  {expect}\nclaimed exit (both)  {claimed}\n")
    for atp, rec, full, mutant in rows:
        print(f"  atp={atp:<2} actual exit={rec.exit:<20} verdict={full[4]}")
        print(f"         proposed ski@v2 tuple : {full}")
        print(f"         mutant (no actual exit): {mutant}")
    full_differ = rows[0][2] != rows[1][2]
    mutant_equal = rows[0][3] == rows[1][3]
    verdicts_equal = rows[0][2][4] == rows[1][2][4] == "fail"
    print(f"\nproposed tuples differ: {full_differ}   "
          f"mutant tuples equal: {mutant_equal}   both verdicts fail: {verdicts_equal}")
    if full_differ and mutant_equal and verdicts_equal:
        print("=> the difference is carried by the RE-RUN's exit and by nothing "
              "else. An implementation that omits that member loses exactly the "
              "distinction ski@v2 is being registered for.")
        return 0
    print("=> the isolating control did NOT reproduce", file=sys.stderr)
    return 1


def _build_m5_term(store, e06):
    """APPLY(I, APPLY(I, DISSONANCE("ATP Exhausted"))) and H(that node), in `store`."""
    dis_bytes = e06.ser(e06.DISSONANCE, e06.F_ATOM, atom=e06.sha(b"ATP Exhausted"))
    dis_h = e06.node_hash(dis_bytes)
    store.put_blob(dis_bytes)
    node = dis_h
    for _ in range(2):
        b = e06.ser(e06.APPLY, e06.F_LEFT | e06.F_RIGHT, left=e06.I_H, right=node)
        node = e06.node_hash(b)
        store.put_blob(b)
    return node.hex(), dis_h.hex()


def main(v06_path, rev1=False, isolate=False):
    import hashlib
    v06_path = Path(v06_path)
    got = hashlib.sha256(v06_path.read_bytes()).hexdigest()
    if got != EXPECTED_V06_SHA:
        print(f"REFUSING: {v06_path} is sha256 {got}, expected {EXPECTED_V06_SHA} "
              f"(the published sigma-glyph 0.7.0 module)", file=sys.stderr)
        return 1
    e06 = load(v06_path, "sigma_v06")
    if rev1:
        return rev1_control(e06)
    if isolate:
        return isolating_control(e06)

    store = W.Store(tempfile.mkdtemp(prefix="wrt013-store-"))
    store.init()
    # The Warrant blob store IS the Σ-GLYPH CAS, so the nodes go in as blobs.
    term, expect = _build_m5_term(store, e06)

    reasons, receipts = [], []
    for atp in (0, 9):
        doc = {"ski": 1, "term": term, "atp": atp, "expect": expect}
        blob = store.put_blob(W.canon(doc))
        reasons.append({"kind": "check", "check": blob, "runtime": "ski@v1",
                        "verdict": "pass"})
        receipts.append(e06.eval_receipt(bytes.fromhex(term), atp, _BlobCAS(store)))

    body = {"warrant": "0.2", "decision": "accept",
            "subject": {"hash": "11" * 32}, "under": ["22" * 32],
            "because": reasons, "evidence": [], "actor": {"id": "a@x"},
            "prior": [], "ts": 0}

    fps = [W.fingerprint(r, body, store) for r in reasons]
    print(f"term    {term}")
    print(f"expect  {expect}\n")
    for r, fp, rec, atp in zip(reasons, fps, receipts, (0, 9)):
        print(f"  atp={atp:<2} ski@v1 fingerprint: {fp}")
        print(f"         Book I 0.6.0 receipt: exit={rec.exit} "
              f"result={rec.result_hash.hex()[:16]} atp_spent={rec.atp_spent}")
    equal = fps[0] is not None and fps[0] == fps[1]
    exits_differ = receipts[0].exit != receipts[1].exit
    print(f"\nfingerprints equal: {equal}   exits differ: {exits_differ}")
    if equal and exits_differ:
        print("=> §7 sees one outcome; Book I 0.6.0 sees two. The second reason "
              "is inadmissible as 'nothing new' although it establishes that the "
              "term has a normal form.")
        return 0
    print("=> the control did NOT reproduce", file=sys.stderr)
    return 1


class _BlobCAS:
    """The same adapter shape `run_ski_check` uses: warrant blobs as a Σ-GLYPH CAS."""

    def __init__(self, store):
        self.store = store

    def get(self, h):
        p = self.store.blobs / h.hex()
        return p.read_bytes() if p.exists() else None


if __name__ == "__main__":
    flags = {"--rev1", "--isolate"}
    args = [a for a in sys.argv[1:] if a not in flags]
    if len(args) != 1 or {"--rev1", "--isolate"} <= set(sys.argv[1:]):
        sys.exit(__doc__)
    sys.exit(main(args[0], rev1="--rev1" in sys.argv[1:],
                  isolate="--isolate" in sys.argv[1:]))
