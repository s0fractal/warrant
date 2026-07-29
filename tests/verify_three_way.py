#!/usr/bin/env python3
"""Do all THREE implementations agree on whether a store verifies?

WHY
---
The strongest claim this project could previously make about store verification
was that two implementations agree. Three agreed on canonicalization and on the
§8 vectors, but only Python and Go ever looked at a store -- so on the surface
where being wrong matters most, "independent agreement" was a pair.

A clean store agreeing proves almost nothing: every implementation returns zero
errors on a store with no defects. Parity is a claim about the BROKEN cases, so
every case here is a store that has been damaged in a specific way, including
each defect found and fixed on 2026-07-29.

SCOPE, STATED
-------------
Rust implements SPEC §6 at BASE grade only: no settlement, no key state, no trust
config. Python is therefore run with its oracle made unreachable and without a
trust config, so all three are being asked the same question. Comparing Rust
against settlement-grade Python would be comparing two different questions and
calling the difference a divergence.

`ski@v1` re-execution is not available in Rust, and it reports
`ski@v1 unverified: runtime unavailable` -- exactly what Python prints when its
oracle is absent. That is why the counts are comparable at all, and it is the
reason "was not executed" must never look like "ran and matched".
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"
SUMMARY = re.compile(r"verify:\s*(\d+) records?,\s*(\d+) errors?,\s*(\d+) warnings?")

# Python must be asked the BASE-grade question: a copy with no bundled oracle
# beside it, an empty HOME so the conventional checkout is not found, and no
# SIGMA_GLYPH. Anything less and the comparison is between different questions.
_PY_DIR = tempfile.mkdtemp(prefix="threeway-py-")
shutil.copy2(ROOT / "impl" / "warrant.py", _PY_DIR)
_HOME = tempfile.mkdtemp(prefix="threeway-home-")
_ENV = {k: v for k, v in os.environ.items() if k != "SIGMA_GLYPH"}
_ENV["HOME"] = _HOME


def counts(text):
    m = SUMMARY.search(text)
    return tuple(int(x) for x in m.groups()) if m else None


def run_all(store):
    out = {}
    r = subprocess.run([sys.executable, os.path.join(_PY_DIR, "warrant.py"),
                        "--store", str(store), "verify"],
                       capture_output=True, text=True, env=_ENV)
    out["py"] = counts(r.stdout + r.stderr)
    r = subprocess.run([str(GO), "verify", str(store)], capture_output=True, text=True)
    out["go"] = counts(r.stdout + r.stderr)
    r = subprocess.run([str(RS), "verify", str(store)], capture_output=True, text=True)
    out["rs"] = counts(r.stdout + r.stderr)
    return out


def main():
    for name, path in (("warrant-go", GO), ("warrant-rs", RS)):
        if not path.is_file():
            print(f"SKIP  three-way verify: {name} not built ({path})")
            return 0

    src = ROOT / ".warrants"
    ok = True

    def case(label, mutate=None, expect_errors=None):
        nonlocal ok
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "s"
            shutil.copytree(src, store)
            if mutate:
                mutate(store)
            got = run_all(store)
            agree = got["py"] is not None and got["py"] == got["go"] == got["rs"]
            good = agree
            if good and expect_errors is not None:
                # A case that produces no error proves nothing about the defect it
                # was written for: three implementations agreeing on "fine" is not
                # agreement that something is broken.
                good = (got["py"][1] > 0) if expect_errors else (got["py"][1] == 0)
            print(("OK   " if good else "FAIL "), f"{label:44s}",
                  f"py={got['py']} go={got['go']} rs={got['rs']}")
            ok &= good

    case("clean store", None, expect_errors=False)

    def swap_blob(s):
        b = sorted((s / "blobs").glob("*"))[0]
        b.write_bytes(b"a completely different policy\n")
    case("blob swapped at its own address", swap_blob, expect_errors=True)

    def swap_subject(s):
        for f in sorted((s / "records").glob("*.json")):
            h = json.loads(f.read_text())["body"]["subject"]["hash"]
            if (s / "blobs" / h).is_file():
                (s / "blobs" / h).write_bytes(b"a different subject\n")
                return
    case("subject blob swapped", swap_subject, expect_errors=True)

    def tamper_sig(s):
        f = sorted((s / "records").glob("*.json"))[0]
        env = json.loads(f.read_text())
        sig = env["sigs"][0]["sig"]
        env["sigs"][0]["sig"] = ("0" if sig[0] != "0" else "1") + sig[1:]
        f.write_text(json.dumps(env, indent=2, sort_keys=True))
    case("signature tampered", tamper_sig, expect_errors=True)

    def drop_prior(s):
        for f in sorted((s / "records").glob("*.json")):
            prior = json.loads(f.read_text())["body"].get("prior") or []
            if prior:
                p = s / "records" / f"{prior[0]}.json"
                if p.is_file():
                    p.unlink()
                    return
    case("a prior removed from the store", drop_prior, expect_errors=True)

    def rename_records(s):
        a, b = sorted((s / "records").glob("*.json"))[:2]
        da, db = a.read_text(), b.read_text()
        a.write_text(db)
        b.write_text(da)
    case("two record filenames swapped", rename_records, expect_errors=True)

    def malform(s):
        sorted((s / "records").glob("*.json"))[0].write_text("{not json")
    case("a record is malformed JSON", malform, expect_errors=True)

    def empty_sigs(s):
        f = sorted((s / "records").glob("*.json"))[0]
        env = json.loads(f.read_text())
        env["sigs"] = []
        f.write_text(json.dumps(env, indent=2, sort_keys=True))
    case("a record carries no signatures", empty_sigs, expect_errors=True)

    # Not a store at all. Here the comparable thing is the VERDICT, not a summary
    # line: all three refuse with a diagnostic and a non-zero status, and README
    # says human-oriented prose may differ between implementations. Requiring an
    # identical summary was comparing output shape and calling it a divergence.
    with tempfile.TemporaryDirectory() as tmp:
        missing = str(Path(tmp) / "nope")
        rcs = {
            "py": subprocess.run([sys.executable, os.path.join(_PY_DIR, "warrant.py"),
                                  "--store", missing, "verify"],
                                 capture_output=True, env=_ENV).returncode,
            "go": subprocess.run([str(GO), "verify", missing],
                                 capture_output=True).returncode,
            "rs": subprocess.run([str(RS), "verify", missing],
                                 capture_output=True).returncode,
        }
        good = all(v != 0 for v in rcs.values())
        print(("OK   " if good else "FAIL "), f"{'not a store: all three fail closed':44s}",
              f"exit={rcs}")
        ok &= good

    shutil.rmtree(_PY_DIR, ignore_errors=True)
    shutil.rmtree(_HOME, ignore_errors=True)
    print(f"\nTHREE-WAY VERIFY: {'ALL AGREE' if ok else 'DIVERGENCE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
