#!/usr/bin/env python3
"""Run every check this repository's claims rest on, in one command.

WHY THIS EXISTS
---------------
The README, SPEC and llms.txt all say the same thing to a reader: do not believe
this, run it. But there were fourteen test modules, `tests/agree_check.sh` ran
five of them, and the only place the full set appeared was a CI workflow. So a
stranger who took the invitation seriously had to read a YAML file to find out
what "run it" meant, and would have run a third of it.

One command, one verdict, and — the part that matters — a check that could not
run is reported as UNRUN, never as passed.

SILENCE IS NOT SUCCESS
----------------------
This project has produced the same defect ten times in a week: reading something
adjacent to the evidence instead of the evidence. A test harness that prints ALL
PASS while quietly skipping the Go suites because the binary was not built is
that defect in its purest form -- the summary would describe a world in which two
implementations agreed, on the strength of never having asked one of them.

So an unavailable prerequisite is a distinct outcome with its own exit status.
`--allow-unrun` says the operator accepted the gap deliberately; without it, a
gap fails, and either way the gap is named.

USAGE
    python3 tools/check.py                 # everything; UNRUN is a failure
    python3 tools/check.py --allow-unrun   # tolerate missing toolchains
    python3 tools/check.py --list          # what would run, and what it needs
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGMA = ROOT.parent / "sigma-glyph" / "impl"
GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"

# (name, argv, needs) -- `needs` is checked BEFORE running so a missing
# prerequisite is reported as UNRUN rather than as a confusing failure.
CHECKS = [
    ("map: every cited document is located",
     ["python3", "tools/repo_map.py", "--check-map"], None),
    ("python: conformance (SPEC §8 vectors, byte-exact)",
     ["python3", "impl/warrant.py", "conformance", "examples"], None),
    ("python: selftest (round-trip + tamper detection)",
     ["python3", "impl/warrant.py", "selftest"], None),
    ("python: verify own store (settlement grade)",
     ["python3", "impl/warrant.py", "verify", "--settlement",
      "--trust-config", "trust-config.json"], None),
    ("negative vectors (MUST-REJECT, Python vs Go)",
     ["python3", "tests/negative.py"], "go"),
    ("differential canonicalization (PY/GO[/RS])",
     ["python3", "tests/differential.py"], "go"),
    # Needs BOTH: it drives the Σ-GLYPH oracle and compares Python against Go.
    # Listing only sigma made a missing Go binary surface as a FileNotFoundError
    # traceback instead of UNRUN -- a gap wearing the costume of a failure, which
    # is the same confusion this file exists to prevent, in the safer direction.
    ("settlement semantics (§7 tunnels, novelty, key state)",
     ["python3", "tests/settlement.py"], "sigma+go"),
    ("hostile stores (cycles, malformed JSON, unsigned links)",
     ["python3", "tests/hostile.py"], "go"),
    ("evidence packs (demo packs verify; no private keys shipped)",
     ["python3", "tests/evidence_pack.py"], None),
    ("verify-report@v0 machine boundary",
     ["python3", "tests/verify_report.py"], "go"),
    ("json schemas vs the corpus (both directions)",
     ["python3", "tools/schema_check.py"], None),
    ("pedantic edges (parity on the awkward cases)",
     ["python3", "tests/pedantic_edges.py"], "go"),
    ("ski@v1 policy predicates (real re-execution)",
     ["python3", "tests/ski_policy.py"], "sigma"),
    # The WPL front end. Includes the tutorial gate: every command in
    # docs/authoring-checks.md is executed and its printed output compared, so
    # the documentation cannot drift from the compiler. Also mutates the
    # compiler on purpose and fails if the mutant survives -- a differential
    # that cannot go red is decoration.
    ("wpl policy language (differential vs the oracle, docs executed)",
     ["python3", "tests/policy_lang.py"], "sigma"),
    ("merkle anchoring (RFC 6962 structure + inclusion proofs)",
     ["python3", "tests/anchor.py"], None),
    ("mcp sealing proxy (stdio round-trip -> verifiable pack)",
     ["python3", "tests/mcp_seal.py"], None),
    ("mcp server (stdio: file/verify/show tools + tamper control)",
     ["python3", "integrations/mcp-server/test_server.py"], None),
    ("ed25519 differential (Rust vs Python)",
     ["python3", "tests/ed25519_differential.py", "--n", "50"], "rs"),
    ("in-toto bridge (Statement v1 shape + binding, tamper matrix)",
     ["python3", "tools/intoto.py", "selftest"], None),
    ("documented CLI surface exists",
     ["python3", "tools/check_release_surface.py"], None),
    ("gate settlement rule (47 cases)",
     ["python3", "tests/settlement_gate.py"], None),
    ("gate settlement fuzzer (randomised, 2000 draws)",
     ["python3", "tests/settlement_fuzz.py", "2000"], None),
    ("go: conformance", [str(GO), "conformance", "examples"], "go"),
    ("go: selftest", [str(GO), "selftest", "examples"], "go"),
    ("go: verify own store (settlement grade)",
     [str(GO), "verify", "--settlement", "--trust-config",
      "trust-config.json", ".warrants"], "go"),
    ("three-way store verification (PY/GO/RS agree on broken stores)",
     ["python3", "tests/verify_three_way.py"], "go+rs"),
    ("rust: verify own store (SPEC §6 base grade)",
     [str(RS), "verify", ".warrants"], "rs"),
    ("rust: conformance", [str(RS), "conformance", "examples"], "rs"),
    ("rust: ed25519 selftest", [str(RS), "edtest"], "rs"),
    # DRAFT artifact for an OPEN decision (proposals/DEC-001). It is here so the
    # vectors cannot rot while the decision is pending, NOT because anything in
    # it is in force: it touches no verifier and SPEC §5 is unchanged.
    ("DRAFT domain-separation vectors reproduce (decision pending, nothing in force)",
     ["python3", "tools/domain_separation_prototype.py"], None),
    ("x1: cross-repo HEAD-vs-HEAD (regression canary, not a gate)",
     ["bash", "tools/x1_cross_repo.sh"], "sibling"),
]

NEEDS = {
    "go+rs": (lambda: NEEDS["go"][0]() and NEEDS["rs"][0](),
              "needs impl-go/warrant-go and impl-rs built"),
    "sigma+go": (lambda: NEEDS["sigma"][0]() and NEEDS["go"][0](),
                 "needs both the Σ-GLYPH oracle and impl-go/warrant-go"),
    "go": (lambda: GO.is_file(),
           "impl-go/warrant-go not built  ->  (cd impl-go && go build -o warrant-go .)"),
    "rs": (lambda: RS.is_file(),
           "impl-rs not built  ->  (cd impl-rs && cargo build --release)"),
    "sigma": (lambda: (ROOT / "impl" / "sigma_glyph.py").exists() or SIGMA.exists(),
              "Σ-GLYPH oracle not found  ->  set SIGMA_GLYPH=<sigma-glyph>/impl"),
    "sibling": (lambda: (ROOT.parent / "sigma-glyph").is_dir(),
                "sibling repository sigma-glyph not beside this one"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-unrun", action="store_true",
                    help="exit 0 when a check could not run; it is still named")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for name, argv, needs in CHECKS:
            print(f"{name}\n    {' '.join(argv)}"
                  + (f"\n    needs: {needs}" if needs else ""))
        return 0

    env = dict(os.environ)
    env.setdefault("WARRANT_REQUIRE_SIGMA", "1")
    if SIGMA.exists():
        env.setdefault("SIGMA_GLYPH", str(SIGMA))

    failed, unrun, passed = [], [], 0
    for name, argv, needs in CHECKS:
        if needs and not NEEDS[needs][0]():
            print(f"UNRUN  {name}\n         {NEEDS[needs][1]}")
            unrun.append(name)
            continue
        t0 = time.time()
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, env=env)
        dt = time.time() - t0
        if r.returncode == 0:
            print(f"ok     {name}  ({dt:.1f}s)")
            passed += 1
        else:
            tail = (r.stdout + r.stderr).strip().splitlines()
            print(f"FAIL   {name}  ({dt:.1f}s)")
            for line in tail[-3:]:
                print(f"         {line[:110]}")
            failed.append(name)

    print(f"\n{passed} passed, {len(failed)} failed, {len(unrun)} unrun")
    for n in failed:
        print(f"  FAILED  {n}")
    for n in unrun:
        print(f"  UNRUN   {n}")
    if unrun and not failed:
        print("\nNOT a clean run: something could not be checked. An unrun check is\n"
              "not a passed one, and this summary refuses to imply otherwise.")
    if failed:
        return 1
    if unrun:
        return 0 if args.allow_unrun else 2
    print("\nCHECK: ALL PASS — every claim in this repository was executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
