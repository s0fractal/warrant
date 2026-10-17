#!/usr/bin/env python3
"""Counter-vectors for tools/proof_attestation.py --check, one attack per case.

Each case copies the minimum the check reads (impl/, proofs/creusot without
target/, the proved impl-rs files, the tool), changes one thing, and expects the
verdict named. The clean copy must be CLAIMED; every attack must be refused, with
the reason the case is about (a changed file must be NAMED, not just "red").
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import proof_attestation as PA  # noqa: E402

ATT = PA.ATT
results = []


def copy_root(tmp):
    dst = Path(tmp) / "repo"
    shutil.copytree(ROOT / "impl", dst / "impl", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / PA.PROOFS, dst / PA.PROOFS, ignore=shutil.ignore_patterns("target", ".why3find"))
    for f in PA.proved_files(ROOT):
        (dst / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, dst / f)
    (dst / "tools").mkdir()
    shutil.copy2(ROOT / "tools" / "proof_attestation.py", dst / "tools")
    return dst


def run(root):
    r = subprocess.run([sys.executable, str(root / "tools" / "proof_attestation.py"), "--check"],
                       capture_output=True, text=True, check=False)
    return r.returncode, r.stdout + r.stderr


def case(name, mutate, want_code, want_text):
    with tempfile.TemporaryDirectory() as tmp:
        root = copy_root(tmp)
        mutate(root)
        code, out = run(root)
    ok = code == want_code and want_text in out
    results.append(ok)
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"| exit {code}: {out.strip()[:300]}")


def append(rel):
    def f(root):
        with open(root / rel, "a") as fh:
            fh.write("\n// changed\n")
    return f


def other_key(root):
    (root / ATT / "trust.json").write_text(json.dumps(
        {"actors": {PA.ACTOR: ["5e06999f4dd20f375c9292e39f722a77a67a5c5cf8a5fd74bbb35f99dc4a8cc5"]}}))


def evidence_blobs(root):
    for p in (root / ATT / "store" / "records").glob("*.json"):
        b = json.loads(p.read_text())["body"]
        if b["subject"]["hash"] == __import__("hashlib").sha256(PA.manifest(root)).hexdigest():
            return b["evidence"]
    return []


def tamper_evidence(root):
    h = evidence_blobs(root)[0]
    p = root / ATT / "store" / "blobs" / h
    p.chmod(0o644)
    p.write_bytes(p.read_bytes() + b"forged line\n")


def delete_evidence(root):
    (root / ATT / "store" / "blobs" / evidence_blobs(root)[1]).unlink()


def forged_actor(root):
    """mallory signs a record about the CURRENT manifest; the trusted records go."""
    for p in (root / ATT / "store" / "records").glob("*.json"):
        p.unlink()
    key = Path(root) / "mallory.key"
    key.write_text("66" * 32 + "\n")
    man = PA.blob(root, PA.manifest(root))
    pol = PA.blob(root, b"policy\n")
    r = PA.warrant(root, "propose", "--subject", man, "--under", pol, "--note", "forged",
                   "--actor", "mallory@x", "--key", str(key), text=True)
    assert r.returncode == 0, r.stderr


def main():
    case("clean copy: CLAIMED, and says it was not re-run", lambda r: None, 0, "not re-run here")
    case("prose changed (README.md): still CLAIMED, no new proof run needed",
         append("proofs/creusot/README.md"), 0, "not re-run here")
    case("a proved impl-rs file changed: refused, file named", append("impl-rs/src/bounds.rs"),
         1, "impl-rs/src/bounds.rs")
    case("the proof crate changed: refused, file named", append("proofs/creusot/src/lib.rs"),
         1, "proofs/creusot/src/lib.rs")
    case("a proof certificate changed: refused, file named",
         append("proofs/creusot/verif/warrant_creusot_proofs_rlib/jcsquote/push_esc/proof.json"),
         1, "jcsquote/push_esc/proof.json")
    case("trust binds another key: the record is unbound, refused", other_key, 1, "no bound signature")
    # warrant itself refuses edited bytes; a DELETED blob is only a warning there,
    # which is why --check looks at the evidence itself (next case).
    case("an evidence log edited after signing: refused by the store", tamper_evidence, 1,
         "does not match its address")
    case("an evidence log deleted: refused", delete_evidence, 1, "evidence")
    case("an untrusted actor attests the current manifest: refused", forged_actor, 1, "error")
    print("PROOF ATTESTATION VECTORS:", "ALL PASS" if all(results) else "FAILURES")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
