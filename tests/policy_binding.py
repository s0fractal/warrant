#!/usr/bin/env python3
"""WRT-020 profile (impl/policy_binding.py): one store per case, one verdict each.

Every case is filed with the real CLI and checked twice: by the profile, and by
`warrant verify`. The second column is the point of the proposal: today verify
reports 0 errors for every case here, including the two the profile calls
CONTRADICTED and UNBOUND. If verify ever starts refusing them, this test fails on
purpose and becomes the witness of that rule.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import policy_binding as PB  # noqa: E402

WARRANT = [sys.executable, str(ROOT / "impl" / "warrant.py")]
COMPILE = [sys.executable, str(ROOT / "impl" / "policy_lang.py"), "compile"]
SKI = ROOT / "examples" / "ski"
ALLOW = b"# allow: the refund is within the desk limit\nfact refund_amount_cents: int = 12000\ncheck refund_amount_cents <= 50000\n"
DENY = b"# deny: the refund is over the desk limit\nfact refund_amount_cents: int = 65088\ncheck refund_amount_cents <= 50000\n"
DENY_ALL_PROSE = b"DENY_ALL: no change may be accepted under this policy.\n"
THRESHOLD = json.dumps({"warrant_policy": "0.3", "threshold": {"actors": ["a@x"], "min_sigs": 1}}).encode()
results = []


def w(store, *args):
    r = subprocess.run(WARRANT + ["--store", str(store), *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]}: {r.stderr.strip()}")
    return r.stdout.strip()


def blob(store, tmp, data, name):
    p = Path(tmp) / name
    p.write_bytes(data)
    return w(store, "blob", "add", str(p))


def compiled(store, tmp, src, name, *extra):
    p = Path(tmp) / name
    p.write_bytes(src)
    r = subprocess.run(COMPILE + [str(p), "--store", str(store), "--json", *extra],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["check"]


def variant(store, tmp, src, **change):
    """The policy's own check with some fields replaced: a near miss."""
    doc = json.loads((Path(store) / "blobs" / compiled(store, tmp, src, "policy.wpl")).read_bytes())
    doc.update(change)
    return blob(store, tmp, json.dumps(doc, sort_keys=True, separators=(",", ":")).encode(), "variant.json")




def unrelated_ski(store):
    for b in sorted(SKI.glob("*.bin")):
        w(store, "blob", "add", str(b))
    return w(store, "blob", "add", str(SKI / "check.json"))


def file(decision, policy_bytes, reason):
    """reason: 'own' (the policy's compilation), 'unrelated' (examples/ski) or None."""
    tmp = tempfile.mkdtemp(prefix="wrt020-")
    store = Path(tmp) / "s"
    w(store, "init")
    key = Path(tmp) / "a.key"
    key.write_text("44" * 32 + "\n")
    subject = blob(store, tmp, b"PR-1: refund\n", "subject")
    policy = blob(store, tmp, policy_bytes, "policy.wpl")
    args = ["--under", policy, "--actor", "a@x", "--key", str(key)]
    ski = ["--runtime", "ski@v1", "--verdict", "pass"]
    if reason == "own":
        args += ["--check", compiled(store, tmp, policy_bytes, "policy.wpl"), *ski]
    elif reason == "headroom":
        args += ["--check", compiled(store, tmp, policy_bytes, "policy.wpl", "--headroom", "1"), *ski]
    elif reason == "other-answer":
        allow = json.loads((Path(store) / "blobs" / compiled(store, tmp, ALLOW, "allow.wpl")).read_bytes())
        # The CLI refuses to file `pass` for a check that does not reproduce it,
        # so the near misses are filed honestly, as `fail`.
        args += ["--check", variant(store, tmp, policy_bytes, expect=allow["expect"]),
                 "--runtime", "ski@v1", "--verdict", "fail"]
    elif reason == "low-budget":
        args += ["--check", variant(store, tmp, policy_bytes, atp=1), "--runtime", "ski@v1", "--verdict", "fail"]
    elif reason == "unrelated":
        args += ["--check", unrelated_ski(store), "--runtime", "ski@v1", "--verdict", "pass"]
    prop = w(store, "propose", "--subject", subject, "--note", "refund", *(["--under", policy]),
             "--actor", "a@x", "--key", str(key))
    if decision == "propose":
        rec = prop
    else:
        rec = w(store, decision, prop, *args)
    return store, rec


def verify_errors(store):
    r = subprocess.run(WARRANT + ["--store", str(store), "verify", "--json"], capture_output=True, text=True, check=False)
    return json.loads(r.stdout)["errors"]


def case(name, decision, policy_bytes, reason, want, why=None, verify_clean=True):
    store, rec = file(decision, policy_bytes, reason)
    rows = [r for r in PB.classify_store(store) if r["record"] == rec]
    got = [r["status"] for r in rows]
    errs = verify_errors(store)
    ok = (got == [want] and (verify_clean is None or (errs == 0) == verify_clean)
          and (why is None or why in rows[0]["why"]))
    results.append(ok)
    print(("ok  " if ok else "FAIL"), f"{name}: profile {got}, verify {errs} errors",
          "" if ok else f"(want [{want}], verify clean={verify_clean}, why~{why!r}; got {rows[0]['why']!r})")


def main():
    case("Monday's countermodel: prose DENY_ALL + unrelated replayed reason + accept",
         "accept", DENY_ALL_PROSE, "unrelated", "OPAQUE")
    case("accept whose reason is the policy's own compilation, which answers FALSE",
         "accept", DENY, "own", "CONTRADICTED")
    case("accept under a WPL policy, reason an unrelated computation",
         "accept", ALLOW, "unrelated", "UNBOUND", why="no ski@v1 reason runs this policy's term")
    case("accept under a WPL policy, no reason at all", "accept", ALLOW, None, "UNBOUND")
    case("accept whose reason is the policy's compilation, answering TRUE", "accept", ALLOW, "own", "BOUND")
    # Codex review (2026-10-17, P2): headroom is a permitted compile option that
    # raises `atp` and changes the check hash. Same term, same answer: BOUND.
    case("accept whose reason was compiled with headroom (same term and answer, more budget)",
         "accept", ALLOW, "headroom", "BOUND")
    case("near miss: the policy's term, but a different pinned answer",
         "accept", DENY, "other-answer", "UNBOUND", why="pins a different answer", verify_clean=None)
    case("near miss: the policy's term and answer, but too little budget to reach it",
         "accept", ALLOW, "low-budget", "UNBOUND", why="less than", verify_clean=None)
    case("reject where the policy denies (consistent)", "reject", DENY, "own", "BOUND")
    case("reject where the policy would allow (discretion, not a contradiction)", "reject", ALLOW, "own", "BOUND")
    case("propose with no reason: UNBOUND (nothing computed), never CONTRADICTED", "propose", DENY, None, "UNBOUND")
    case("a v0.3 threshold policy governs signatures, not a computation", "accept", THRESHOLD, None, "SIGNATURES")
    # The profile reads; it must not write. A store hashed before and after is unchanged.
    store, _ = file("accept", DENY, "own")
    before = sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file())
    PB.classify_store(store)
    after = sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file())
    results.append(before == after)
    print(("ok  " if before == after else "FAIL"), "the profile does not write to the store it reads")
    print("POLICY BINDING PROFILE:", "ALL PASS" if all(results) else "FAILURES")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
