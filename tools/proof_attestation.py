#!/usr/bin/env python3
"""Creusot proofs: attested where they ran, checked where they did not.

    python3 tools/proof_attestation.py --attest   # run the proofs + mutants here, sign
    python3 tools/proof_attestation.py --check    # CI: is THIS tree's proof input attested?

The Creusot proofs (proofs/creusot/) take half an hour to install, so CI does not
run them. Instead whoever ran them signs a warrant record. Its subject is a
MANIFEST: the SHA-256 of every proof input, meaning the proved impl-rs files
(read from the crate's #[path] lines) and the files of proofs/creusot itself.
`--check` recomputes that manifest from the checkout and looks for a record about
exactly it, signed by a key that proofs/creusot/attestation/trust.json binds.

What a green --check means: CLAIMED. A trusted key says `cargo creusot` and
mutants.py passed on these exact inputs; the logs are attached as evidence. It is
not a re-run, and the output says so. It turns red when a proved file changes
without a new attestation, and it names the files that changed since the last one.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOFS = Path("proofs/creusot")
ATT = PROOFS / "attestation"
ACTOR = "claude@warrant-proofs"
DEFAULT_KEY = Path.home() / ".warrant" / "keys" / "claude-warrant-proofs.key"
CHECK_SCRIPT = b"cd proofs/creusot && cargo creusot && python3 mutants.py\n"
NOTE = "Creusot proofs and mutants.py ran locally; logs attached as evidence"
LOGS = PROOFS / "target" / "attestation-logs"


def proved_files(root):
    lib = (root / PROOFS / "src" / "lib.rs").read_text()
    names = re.findall(r'#\[path = "\.\./\.\./\.\./(impl-rs/src/[\w.]+\.rs)"\]', lib)
    return sorted(set(names))


def manifest(root):
    """`sha256  path` per proof input, sorted by path, as the bytes the record names.

    Inputs are what can change the result: the proved impl-rs files, the proof
    crate's sources and pins, the mutant list, and the proof certificates
    (verif/**/proof.json). Prose (README.md) and this attestation directory are
    not inputs, so editing them does not demand a new proof run."""
    crate = root / PROOFS
    paths = [Path(p) for p in proved_files(root)]
    paths += [(crate / f).relative_to(root) for f in ("Cargo.toml", "Cargo.lock", "why3find.json", "mutants.py")]
    paths += [q.relative_to(root) for q in sorted((crate / "src").rglob("*.rs"))]
    paths += [q.relative_to(root) for q in sorted((crate / "verif").rglob("proof.json"))]
    lines = [f"{hashlib.sha256((root / p).read_bytes()).hexdigest()}  {p.as_posix()}"
             for p in sorted(set(paths), key=lambda q: q.as_posix())]
    return ("\n".join(lines) + "\n").encode()


def warrant(root, *args, **kw):
    return subprocess.run([sys.executable, str(root / "impl" / "warrant.py"),
                           "--store", str(root / ATT / "store"), *args],
                          capture_output=True, check=False, **kw)


def blob(root, data):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
    try:
        r = warrant(root, "blob", "add", f.name, text=True)
    finally:
        os.unlink(f.name)
    if r.returncode != 0:
        sys.exit(f"blob add failed: {r.stderr}")
    return r.stdout.strip()


def run_logged(argv, cwd):
    r = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    return r.returncode, r.stdout + r.stderr


def attest(root, key, reuse_logs=False):
    if not key.is_file():
        sys.exit(f"no key at {key} (set WARRANT_PROOFS_KEY)")
    logs = root / LOGS
    if reuse_logs:
        # Only logs written by a passing run of THIS manifest are reused (a failed
        # propose should not cost another proof run); anything else reruns.
        saved = json.loads((logs / "run.json").read_text())
        if saved["manifest"] != hashlib.sha256(manifest(root)).hexdigest():
            sys.exit("saved logs are for other proof inputs; run --attest without --reuse-logs")
        proof_log, mutant_log = (logs / "creusot.log").read_text(), (logs / "mutants.log").read_text()
    else:
        code, proof_log = run_logged(["cargo", "creusot"], root / PROOFS)
        if code != 0 or "Proved" not in proof_log:
            sys.exit("cargo creusot did not prove everything; nothing attested\n" + proof_log[-2000:])
        code, mutant_log = run_logged([sys.executable, "-u", "mutants.py"], root / PROOFS)
        if code != 0:
            sys.exit("mutants.py: not every mutant was killed; nothing attested\n" + mutant_log[-2000:])
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "creusot.log").write_text(proof_log)
        (logs / "mutants.log").write_text(mutant_log)
        (logs / "run.json").write_text(json.dumps({"manifest": hashlib.sha256(manifest(root)).hexdigest()}))
    creusot = subprocess.run(["git", "-C", str(Path.home() / "Projects" / "creusot"), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=False).stdout.strip() or "unknown"
    env = json.dumps({"creusot_commit": creusot, "platform": platform.platform(),
                      "why3find_json": json.loads((root / PROOFS / "why3find.json").read_text())},
                     indent=2, sort_keys=True).encode()
    if not (root / ATT / "store").is_dir():
        warrant(root, "init")
    man = blob(root, manifest(root))
    policy = blob(root, (root / ATT / "POLICY.md").read_bytes())
    check = blob(root, CHECK_SCRIPT)
    evidence = [blob(root, proof_log.encode()), blob(root, mutant_log.encode()), blob(root, env)]
    summary = proof_log.strip().splitlines()[-1] + "; " + mutant_log.strip().splitlines()[-1]
    args = ["propose", "--subject", man, "--under", policy, "--note", NOTE,
            "--check", check, "--runtime", "cmd@v1", "--verdict", "pass",
            "--actor", ACTOR, "--key", str(key)]
    for e in evidence:
        args += ["--evidence", e]
    r = warrant(root, *args, text=True)
    if r.returncode != 0:
        sys.exit(f"propose failed: {r.stderr}")
    print(f"attested manifest {man} as {r.stdout.strip()}: {summary}")
    return 0


def records(root):
    out = []
    for p in sorted((root / ATT / "store" / "records").glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return out


def changed_since(old, new):
    def parse(text):
        return {line[66:]: line[:64] for line in text.splitlines() if len(line) > 66}
    a, b = parse(old), parse(new)
    return sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))


def check(root):
    trust_path = root / ATT / "trust.json"
    trusted = set(json.loads(trust_path.read_text()).get("actors", {}))
    want = hashlib.sha256(manifest(root)).hexdigest()
    r = warrant(root, "verify", "--settlement", "--require-bound", "--trust-config", str(trust_path),
                "--json", text=True)
    try:
        report = json.loads(r.stdout)
    except ValueError:
        print(f"FAIL  the attestation store does not verify: {r.stderr.strip()[:300]}")
        return 1
    if report.get("errors") != 0:
        errs = [f for f in report.get("findings", []) if f.get("level") == "ERR"]
        print(f"FAIL  the attestation store has {report.get('errors')} error(s): {errs[:3]}")
        return 1
    blobs = root / ATT / "store" / "blobs"
    mine = [e for e in records(root) if e["body"].get("actor", {}).get("id") in trusted
            and e["body"].get("decision") == "propose"]
    for e in mine:
        b = e["body"]
        if b["subject"]["hash"] != want:
            continue
        missing = [h for h in b.get("evidence", []) + [b["subject"]["hash"]]
                   if not (blobs / h).is_file() or hashlib.sha256((blobs / h).read_bytes()).hexdigest() != h]
        if missing:
            print(f"FAIL  the record for this manifest lacks intact evidence: {missing}")
            return 1
        print(f"PROOFS: CLAIMED by {b['actor']['id']} (ts {b['ts']}) for manifest {want[:16]}…; "
              f"not re-run here. {b['subject'].get('note', '')}")
        return 0
    print(f"FAIL  no trusted attestation for this tree's proof inputs (manifest {want[:16]}…).")
    if mine:
        last = max(mine, key=lambda e: e["body"]["ts"])["body"]["subject"]["hash"]
        if (blobs / last).is_file():
            diff = changed_since((blobs / last).read_text(), manifest(root).decode())
            print("      changed since the last attestation: " + ", ".join(diff[:12]))
    print("      run the proofs where Creusot is installed: python3 tools/proof_attestation.py --attest")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--attest", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--manifest", action="store_true", help="print the manifest of this tree")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--reuse-logs", action="store_true",
                    help="with --attest: sign the logs a passing run saved for these same inputs")
    args = ap.parse_args()
    if args.manifest:
        sys.stdout.write(manifest(args.root).decode())
        return 0
    if args.attest:
        return attest(args.root, Path(os.environ.get("WARRANT_PROOFS_KEY", DEFAULT_KEY)), args.reuse_logs)
    return check(args.root)


if __name__ == "__main__":
    sys.exit(main())
