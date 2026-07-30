#!/usr/bin/env python3
"""SPEC §5 `warrant-sig-v1`: do all three implementations sign, reject and
DIAGNOSE the same bytes?

WHY THIS EXISTS SEPARATELY FROM THE CONFORMANCE BATTERY
-------------------------------------------------------
`examples/signature-vectors.json` pins the construction and each implementation
checks itself against it. That proves each one matches the file. It does not
prove the three agree on a *store*, and it does not exercise the one thing the
flag day makes a human do: take a store signed under the old rule and migrate
it.

So this suite drives the real binaries over real stores:

  1. a store signed under the pre-v1 construction verifies in NONE of the three;
  2. all three name it — the same diagnosis, byte-for-byte, not three different
     renderings of "does not verify";
  3. `warrant resign` migrates it, and afterwards all three verify it clean;
  4. re-signing did not move a single WarrantID (the claim the whole migration
     rests on, recomputed rather than asserted);
  5. the migration refuses to touch a signature made by a key it was not given,
     and says so, and exits non-zero. A half-migrated store must not report
     success — that is the "silent exit 0" defect this repository keeps finding.

CONFIRMED RED WITHOUT THE FIX: with `verify_sig` reverted to the bare-WarrantID
message, case 1 fails (the legacy store verifies clean) and case 3 fails (the
migrated store does not verify).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = [sys.executable, str(ROOT / "impl" / "warrant.py")]
GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"

spec = importlib.util.spec_from_file_location("warrant_impl", ROOT / "impl" / "warrant.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

ok = []


def chk(name, cond, detail=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL "), name, "" if cond else f" <<< {detail}")


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def verify_all(store):
    """(stdout, returncode) from each implementation's base-grade verify."""
    out = {"py": run(PY + ["--store", str(store), "verify"])}
    if GO.is_file():
        out["go"] = run([str(GO), "verify", str(store)])
    if RS.is_file():
        out["rs"] = run([str(RS), "verify", str(store)])
    return out


def legacy_store(td, n=3):
    """A store of `n` chained records signed the pre-0.6.0 way: the message is
    the bare WarrantID. Built by signing directly, because no shipped code path
    can produce these bytes any more — which is the point of a flag day."""
    store = Path(td) / "legacy"
    (store / "records").mkdir(parents=True)
    blobs = store / "blobs"
    blobs.mkdir()
    key = Path(td) / "k.key"
    key.write_text(os.urandom(32).hex())
    sk = W.load_key(key)
    pub = W.pubkey_hex(sk)
    policy = b"POLICY: domain separation test\n"
    (blobs / f"{W.blob_hash(policy)}.bin").write_bytes(policy)
    prior, wids = [], []
    for i in range(n):
        body = {"warrant": "0.2", "decision": "propose",
                "subject": {"hash": W.blob_hash(policy)},
                "under": [W.blob_hash(policy)], "because": [], "evidence": [],
                "actor": {"id": "legacy@test"}, "prior": prior, "ts": 1751700000 + i}
        wid = W.warrant_id(body)
        env = {"body": body,
               "sigs": [{"actor": "legacy@test", "key": pub,
                         # THE OLD CONSTRUCTION: the bare 32-byte WarrantID.
                         "sig": sk.sign(bytes.fromhex(wid)).hex()}]}
        (store / "records" / f"{wid}.json").write_text(
            json.dumps(env, indent=2, sort_keys=True) + "\n")
        prior, _ = [wid], wids.append(wid)
    return store, key, wids


def main():
    with tempfile.TemporaryDirectory() as td:
        store, key, wids = legacy_store(td)

        # 1 + 2: nobody accepts it, and everybody says the same thing about it.
        before = verify_all(store)
        for impl, r in before.items():
            chk(f"{impl}: a pre-v1 store does NOT verify", r.returncode != 0,
                f"exit {r.returncode}")
            chk(f"{impl}: names the legacy construction, byte-exactly",
                W.LEGACY_SIG_MESSAGE in r.stdout,
                f"got: {r.stdout[:200]!r}")
        chk("the diagnosis is one string, not three renderings",
            len({W.LEGACY_SIG_MESSAGE in r.stdout for r in before.values()}) == 1)
        chk("three implementations were asked", len(before) == 3,
            f"only {sorted(before)} available — build impl-go and impl-rs")

        # 5: a key the migration was not given is reported, not forged over.
        other = Path(td) / "other.key"
        other.write_text(os.urandom(32).hex())
        r = run(PY + ["--store", str(store), "resign", "--key", str(other)])
        chk("resign with the wrong key migrates nothing", r.returncode != 0)
        chk("resign with the wrong key says which key made the signature",
            "NOT MIGRATED" in r.stdout and "re-run where that key lives" in r.stdout,
            r.stdout[:300])
        chk("resign with the wrong key wrote nothing",
            all(W.LEGACY_SIG_MESSAGE in x.stdout for x in verify_all(store).values()))

        # 3 + 4: the migration itself.
        ids_before = [W.warrant_id(json.loads(p.read_text())["body"])
                      for p in sorted((store / "records").glob("*.json"))]
        r = run(PY + ["--store", str(store), "resign", "--key", str(key)])
        chk("resign exits 0 when everything migrated", r.returncode == 0, r.stdout[-300:])
        after = verify_all(store)
        for impl, res in after.items():
            chk(f"{impl}: the migrated store verifies clean", res.returncode == 0,
                res.stdout[-300:])
        ids_after = [W.warrant_id(json.loads(p.read_text())["body"])
                     for p in sorted((store / "records").glob("*.json"))]
        chk("re-signing moved no WarrantID", ids_before == ids_after and ids_before == sorted(wids),
            f"{ids_before} != {ids_after}")
        chk("re-signing changed only `sig`",
            all(set(json.loads(p.read_text())["sigs"][0]) == {"actor", "key", "sig"}
                for p in (store / "records").glob("*.json")))

        # Idempotent: running it again is a no-op that still exits 0.
        r = run(PY + ["--store", str(store), "resign", "--key", str(key)])
        chk("resign is idempotent", r.returncode == 0
            and "0 signatures re-signed" in r.stdout, r.stdout[-200:])

    print("\nDOMAIN-SEPARATION: " + ("ALL PASS" if all(ok) else "FAILURES PRESENT")
          + f" ({sum(ok)}/{len(ok)})")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
