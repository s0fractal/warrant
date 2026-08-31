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
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGMA = ROOT.parent / "sigma-glyph" / "impl"
GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"

# Prerequisite tags used more than once, named so the string is defined in one
# place (a repeated literal is a silent way for two checks to drift apart).
SIGMA_GO = "sigma+go"

# (name, argv, needs) -- `needs` is checked BEFORE running so a missing
# prerequisite is reported as UNRUN rather than as a confusing failure.
CHECKS = [
    # The governance workflow was unparseable YAML for an unknown span (Codex
    # review): every run failed with no job and the gate did nothing. A control
    # plane that cannot be parsed is the purest control-that-does-not-control,
    # so a workflow that stops parsing now fails here instead of failing
    # invisibly on GitHub.
    ("workflows parse (the governance gate cannot silently break)",
     ["python3", "tools/lint_workflows.py"], "yaml"),
    ("map: every cited document is located",
     ["python3", "tools/repo_map.py", "--check-map"], None),
    # repo_map checks that a cited document exists; this checks that a document
    # counting something still agrees with the thing it counts. Two clean merges
    # each moved this list without moving the sentence describing it.
    ("doc counts: stated totals equal what they count",
     ["python3", "tools/doc_counts.py"], None),
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
     ["python3", "tests/settlement.py"], SIGMA_GO),
    ("hostile stores (cycles, malformed JSON, unsigned links)",
     ["python3", "tests/hostile.py"], "go"),
    ("evidence packs (demo packs verify; no private keys shipped)",
     ["python3", "tests/evidence_pack.py"], None),
    ("verify-report@v0 machine boundary",
     ["python3", "tests/verify_report.py"], "go"),
    ("json schemas vs the corpus (both directions)",
     ["python3", "tools/schema_check.py"], None),
    ("why/verify agree on what \"signed\" means (SPEC §5 co-signatures)",
     ["python3", "tests/why_signature_predicate.py"], None),
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
    # WRT-005 (design only): the outcome-fingerprint gate countervectors,
    # fail-closed. Every claimed relation, settlement verdict and subprocess
    # return code is asserted; the five re-openers are demonstrated on the
    # current spec and shown to collapse under the proposed rule. Needs the
    # Σ-GLYPH oracle and the Go settlement CLI (both implementations settle).
    # (The countervector's mutation self-test — proving it can go red — runs as
    # its own mandatory step in .github/workflows/wrt-005.yml, not here, so it
    # does not create a second WRT-005 entry in this list.)
    ("wrt-005 fingerprint gate countervectors (fail-closed)",
     ["python3", "tests/fixtures/wrt005_gate_countervectors.py"], SIGMA_GO),
    # WRT-005 (design only): the rev-4 rule mechanized in Lean 4 core. The guard
    # compiles Settlement.lean, pins each theorem's axiom cone to a sound set,
    # and denylists sorry/axiom/native_decide. UNRUN without a Lean toolchain,
    # so a machine with no Lean does not report a failure.
    ("wrt-005 fingerprint + admissibility mechanized (Lean; sound axiom cone)",
     ["python3", "proofs/check_settlement.py"], "lean"),
    ("merkle anchoring (RFC 6962 structure + inclusion proofs)",
     ["python3", "tests/anchor.py"], None),
    ("mcp sealing proxy (stdio round-trip -> verifiable pack)",
     ["python3", "tests/mcp_seal.py"], None),
    ("mcp server (stdio: file/verify/show tools + tamper control)",
     ["python3", "tests/mcp_server.py"], None),
    ("ed25519 differential (Rust vs Python)",
     ["python3", "tests/ed25519_differential.py", "--n", "50"], "rs"),
    ("in-toto bridge (Statement v1 shape + binding, tamper matrix)",
     ["python3", "tools/intoto.py", "selftest"], None),
    # Framework-free ON PURPOSE, and that is why it has no `needs` gate: gating
    # a check on an optional third-party package would make every clean run
    # report UNRUN, and an unrun check is not a passed one. The LangGraph
    # binding in integrations/approval/examples/ is therefore NOT wired in here
    # -- see docs/integration-study.md for why that is the recommendation and
    # not an omission.
    ("approval boundary (request/sanction pair, ski@v1 reason, tamper control)",
     ["python3", "integrations/approval/warrant_approval.py", "selftest"], None),
    # The hook binding IS testable on a clean checkout -- its contract is JSON on
    # stdin and stdout, so no vendor package has to be installed to exercise it.
    # That asymmetry against the LangGraph binding is the study's whole argument.
    ("pretooluse hook binding (wire format, fail-open recording, tamper control)",
     ["python3", "integrations/approval/examples/test_pretooluse_hook.py"], None),
    ("documented CLI surface exists",
     ["python3", "tools/check_release_surface.py"], None),
    ("gate settlement rule (47 cases)",
     ["python3", "tests/settlement_gate.py"], None),
    ("gate settlement fuzzer (randomised, 2000 draws)",
     ["python3", "tests/settlement_fuzz.py", "2000"], None),
    # The autonomy evaluator is itself governance-critical. Its countervectors
    # prove that policy/evaluator/workflow self-change, missing evidence, stale
    # head bindings, unsupported file modes, false authority trailers and
    # signature/policy drift all fail closed. An active policy still grants
    # nothing when the detached authorization is absent or invalid.
    ("agent autonomy envelope (41 fail-closed countervectors)",
     ["python3", "tests/autonomy_gate.py"], None),
    # The advisory workflow's trust binding (base-ref, head-snapshot, check
    # provenance) lives in tools/autonomy_advisory.py so it is testable Python,
    # not unreviewable YAML. These countervectors prove a same-repo non-default
    # base, a drifted head/base, and a foreign-app or untrusted-suite check all
    # fail closed before any base byte is trusted.
    ("autonomy advisory trust binding (P1a/P1b/P1c countervectors)",
     ["python3", "tests/autonomy_advisory.py"], None),
    # The write-capable actor has a second, immediately-before-merge boundary.
    # It binds the ELIGIBLE packet to live PR/base/head state and the exact
    # branch-protection app identities; GitHub's expected-head merge API is the
    # final transactional guard.
    ("autonomy merge actor (21 live-state/protection countervectors)",
     ["python3", "tests/autonomy_merge.py"], None),
    ("adversarial gate parser (bounded untrusted-output grammar)",
     ["python3", "tests/adversarial_gate_parser.py"], None),
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
    # SPEC §5 signature domain separation, in force since 0.6.0 (DEC-001).
    # The vectors pin the signed bytes; the suite drives all three binaries over
    # a pre-v1 store, so "the three agree" is executed rather than assumed.
    ("signature vectors reproduce (SPEC §8.5 warrant-sig-v1 construction)",
     ["python3", "tools/signature_vectors.py"], None),
    ("domain separation (PY/GO/RS agree; pre-v1 store diagnosed and migrated)",
     ["python3", "tests/domain_separation.py"], "go+rs"),
    # The conformance pack (SPEC §8.6): the artifact a third party runs against
    # THEIR implementation without cloning this repository. Three checks, because
    # three different things can rot independently -- the vectors can drift from
    # examples/, the digest a stranger compares against can go stale in the SPEC,
    # and the runner can stop being able to fail.
    ("conformance pack: regenerates from examples/, SPEC §8.6 pins the digest",
     ["python3", "tools/build_conformance_pack.py", "--check"], None),
    ("conformance runner: detects a broken implementation (negative control)",
     ["python3", "conformance/run.py", "--candidate",
      "python3 impl/warrant.py probe", "--self-check"], "sigma"),
    ("conformance runner: PY/GO/RS reach their declared grades",
     ["python3", "tests/conformance_runner.py"], "go+rs"),
    # The starter skeletons are the first thing an outside implementer runs, so
    # they are executed here rather than trusted. The suite asserts the shape of
    # an HONESTLY INCOMPLETE result -- canon green, the rest UNRUN, grade
    # withheld, exit 2 -- and then corrupts their output to prove it can go red.
    ("conformance skeletons: Go and TS pass canon and decline the rest",
     ["python3", "tests/conformance_skeletons.py"], "go+node"),
    # The outcomes being right is not the same as the report being readable. A
    # partial candidate was told "See the failures above" with no failures above
    # it, and `--self-check` called itself broken for not detecting mutations
    # that had nothing to corrupt -- both on the first two commands a stranger
    # runs. This asserts the wording, and that the self-check still goes red.
    ("conformance diagnosis: an incomplete candidate is told why, and "
     "--self-check can still fail",
     ["python3", "tests/conformance_diagnosis.py"], "go+node"),
    # W1 (implementation/security): the ski@v1 re-executor enforces Identity by
    # Hash. A blob store returning bytes under a FOREIGN address is an
    # inadmissible check with a stable, path-free reason ("content does not
    # match its address"), never an executed verdict; the negative control shows
    # the pre-refresh evaluator DID execute it, so the guard is non-vacuous.
    ("ski@v1 CAS identity (foreign key inadmissible; non-vacuous control)",
     ["python3", "tests/sigma_cas_identity.py"], "sigma"),
    # The Go evaluator mirrors the Python one: the same foreign-key fetch is
    # refused with the same reason class (a differential control, not decoration).
    ("go: ski@v1 CAS identity mirrors Python (foreign key refused)",
     ["go", "-C", "impl-go", "test", "./...", "-run", "TestSigmaCASIdentity", "-count=1"],
     "go-toolchain"),
    # The bundled Σ-GLYPH evaluator is bound to the exact frozen candidate wheel
    # and its authoritative build receipt (trust/sigma-evaluator-provenance.json).
    # Schema, module digest and mutation controls always run; the wheel REBUILD
    # is UNRUN off the official CI Python or without a Sigma checkout, and is
    # made mandatory in the dedicated CI job (`--require-rebuild`).
    ("sigma evaluator provenance (vendored module bound to the frozen wheel)",
     ["python3", "tools/sigma_provenance_check.py"], None),
    ("x1: cross-repo HEAD-vs-HEAD (regression canary, not a gate)",
     ["bash", "tools/x1_cross_repo.sh"], "sibling"),
]

NEEDS = {
    "go+rs": (lambda: NEEDS["go"][0]() and NEEDS["rs"][0](),
              "needs impl-go/warrant-go and impl-rs built"),
    "sigma+go": (lambda: NEEDS["sigma"][0]() and NEEDS["go"][0](),
                 "needs both the Σ-GLYPH oracle and impl-go/warrant-go"),
    # The skeletons need the toolchains themselves, not the built binaries: they
    # are `go run` and `node` one-file programs with no build step, which is the
    # property that makes them a starting point rather than a project.
    "go+node": (lambda: shutil.which("go") and shutil.which("node"),
                "needs the go and node toolchains on PATH (the skeletons are "
                "run, not compiled)"),
    "go": (lambda: GO.is_file(),
           "impl-go/warrant-go not built  ->  (cd impl-go && go build -o warrant-go .)"),
    "go-toolchain": (lambda: shutil.which("go") is not None,
                     "the Go toolchain is not on PATH  ->  install Go (the "
                     "in-repo Go test is UNRUN without it, never passed)"),
    "rs": (lambda: RS.is_file(),
           "impl-rs not built  ->  (cd impl-rs && cargo build --release)"),
    "sigma": (lambda: (ROOT / "impl" / "sigma_glyph.py").exists() or SIGMA.exists(),
              "Σ-GLYPH oracle not found  ->  set SIGMA_GLYPH=<sigma-glyph>/impl"),
    "sibling": (lambda: (ROOT.parent / "sigma-glyph").is_dir(),
                "sibling repository sigma-glyph not beside this one"),
    "yaml": (lambda: importlib.util.find_spec("yaml") is not None,
             "PyYAML not installed  ->  pip install pyyaml"),
    "lean": (lambda: shutil.which("lean") is not None,
             "the Lean 4 toolchain is not on PATH  ->  install via elan "
             "(https://leanprover.github.io); the mechanized proof is UNRUN "
             "without it, never reported as passed"),
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
