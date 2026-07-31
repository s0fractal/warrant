#!/usr/bin/env python3
"""The Warrant conformance runner: does YOUR implementation agree with the spec?

    python3 run.py --candidate "./my-verifier probe"

This runner never imports, links against, or subprocesses any Warrant reference
implementation. It knows one thing: how to hand a vector to a candidate program
and compare the answer to a pinned expectation. Everything it needs about your
program is in CONTRACT.md, which is roughly one page and implementable in an
afternoon in any language that can read stdin and print JSON.

WHAT THIS REPORTS, AND WHY IT IS NOT PASS/FAIL
----------------------------------------------
Four outcomes per vector, never three:

  PASS   the candidate's answer matched the pinned expectation
  FAIL   it answered, and the answer was wrong
  UNRUN  it declared the vector unsupported — NOT a pass, and it lowers the grade
  ERROR  it violated the contract (crashed, timed out, printed unparseable output)

A vector that did not run is reported by name. A green run with silent gaps is
the failure mode this project has produced most often, so the summary refuses to
say "all pass" when anything was skipped.

NEGATIVE VECTORS CARRY EQUAL WEIGHT
-----------------------------------
About half the pack is MUST-REJECT: bodies that must not validate, signatures
that must not verify, bytes that must not parse, stores whose defects must be
reported. An implementation whose validate() returns true unconditionally passes
every positive vector in this pack. When such an implementation is run here it is
not reported as a generic mismatch — it gets its own headline, because "accepts
everything" is a different diagnosis from "got one hash wrong".

GRADES
------
SPEC §6 (base) and §7 (settlement) are different amounts of implementation, and
a candidate declares which it claims. The runner tests exactly that and reports
the grade ACHIEVED, which may be lower than the one claimed. Claiming base and
achieving base is an honest, complete result — one of the reference
implementations (impl-rs) is deliberately base-only.

CAN THIS RUNNER ACTUALLY FAIL?
------------------------------
    python3 run.py --candidate "./my-verifier probe" --self-check

drives your own program through `stub/mutate.py`, a proxy that corrupts specific
answers, and asserts that this runner detects each corruption. Run it before you
believe a green run — a gate that cannot go red is decoration, and this project
has shipped that mistake more than once.
"""
import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACK = Path(__file__).resolve().parent
PROTOCOL = "1"
PACK_TAG = "warrant.conformance-pack@v1"
VECTOR_TAG = "warrant.conformance-vectors@v1"
MANIFEST = "MANIFEST.sha256"

PASS, FAIL, UNRUN, ERROR = "PASS", "FAIL", "UNRUN", "ERROR"
GRADE_ORDER = {"base": 1, "settlement": 2}

# Exit statuses. Distinct on purpose: a caller scripting this must be able to
# tell "wrong answers" from "did not answer" from "the pack itself is not the
# pack", and collapsing them into 1 is how an unrun check becomes a passed one.
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_GRADE_NOT_MET = 2
EXIT_PROTOCOL = 3
EXIT_PACK = 4


class ContractError(Exception):
    """The candidate did not honour CONTRACT.md for this request."""


# ---------------------------------------------------------------- pack integrity
def verify_pack(pack=PACK):
    """Check every file against MANIFEST.sha256 and return the pack digest.

    The digest is SHA-256 of the manifest file itself: ONE hex string that pins
    the whole pack. Compare it against the value published in the Warrant SPEC
    (§8.6) and you have checked the vectors independently of wherever you got
    them — a tarball from a mirror, a colleague's USB stick, a fork.
    """
    mpath = pack / MANIFEST
    if not mpath.is_file():
        raise SystemExit(f"pack integrity: no {MANIFEST} in {pack}")
    raw = mpath.read_bytes()
    listed, problems = {}, []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        listed[rel] = digest
    for rel, want in sorted(listed.items()):
        p = pack / rel
        if not p.is_file():
            problems.append(f"missing: {rel}")
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != want:
            problems.append(f"modified: {rel}")
    for p in sorted(pack.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(pack).as_posix()
        if rel == MANIFEST or "__pycache__" in rel:
            continue
        if rel not in listed:
            problems.append(f"unlisted: {rel}")
    return hashlib.sha256(raw).hexdigest(), problems


# ---------------------------------------------------------------- vector loading
def load_vectors(pack=PACK):
    index = json.loads((pack / "vectors" / "index.json").read_text(encoding="utf-8"))
    if index.get("tag") != PACK_TAG:
        raise SystemExit(f"vectors/index.json is not a {PACK_TAG} document")
    docs = []
    for entry in index["files"]:
        doc = json.loads((pack / "vectors" / entry["file"]).read_text(encoding="utf-8"))
        if doc.get("tag") != VECTOR_TAG:
            raise SystemExit(f"{entry['file']} is not a {VECTOR_TAG} document")
        if len(doc["vectors"]) != entry["vectors"]:
            # A count in one file describing another file is exactly the kind of
            # number that drifts silently, so it is checked rather than trusted.
            raise SystemExit(f"{entry['file']}: index says {entry['vectors']} "
                             f"vectors, file holds {len(doc['vectors'])}")
        docs.append(doc)
    return index, docs


# ---------------------------------------------------------------- the candidate
def ask(argv, request, timeout):
    """One request in, one response out. Raises ContractError on any violation."""
    payload = json.dumps(request, ensure_ascii=True).encode("utf-8")
    try:
        proc = subprocess.run(argv, input=payload, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout)
    except FileNotFoundError:
        raise ContractError(f"candidate not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        raise ContractError(f"no response within {timeout}s")
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        hint = tail[-1][:160] if tail else "(no stderr)"
        raise ContractError(f"exit status {proc.returncode}: {hint}")
    text = proc.stdout.decode("utf-8", "replace").strip()
    if not text:
        raise ContractError("exit 0 but no output — a silent success is not an answer")
    try:
        resp = json.loads(text)
    except ValueError as e:
        raise ContractError(f"stdout is not one JSON object: {e}")
    if not isinstance(resp, dict):
        raise ContractError("stdout is not a JSON object")
    if resp.get("warrant_conformance") != PROTOCOL:
        raise ContractError(f"response protocol {resp.get('warrant_conformance')!r} "
                            f"(expected {PROTOCOL!r})")
    if resp.get("id") != request["id"]:
        raise ContractError(f"response id {resp.get('id')!r} does not echo "
                            f"{request['id']!r}")
    if "unsupported" in resp:
        return None, str(resp["unsupported"])
    if not isinstance(resp.get("output"), dict):
        raise ContractError("response has neither an `output` object nor `unsupported`")
    return resp["output"], None


def capabilities(argv, timeout):
    out, unsupported = ask(argv, {"warrant_conformance": PROTOCOL,
                                  "id": "capabilities",
                                  "class": "capabilities", "input": {}}, timeout)
    if unsupported is not None:
        raise ContractError("the `capabilities` class is mandatory and cannot be "
                            "declared unsupported")
    grade = out.get("grade")
    if grade not in GRADE_ORDER:
        raise ContractError(f"capabilities.grade must be one of "
                            f"{sorted(GRADE_ORDER)}, got {grade!r}")
    if not isinstance(out.get("classes"), list):
        raise ContractError("capabilities.classes must be an array of class names")
    return out


# ---------------------------------------------------------------- comparison
def brief(value, width=44):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= width else text[:width - 1] + "…"


def compare(expect, output):
    """Return None when the answer matches, else a one-line explanation.

    `{"at_least": n}` is the only matcher beyond equality, and it exists because
    SPEC §6 fixes WHICH conditions are errors without fixing how many an
    implementation reports for one broken record.
    """
    for key in sorted(expect):
        want = expect[key]
        got = output.get(key)
        if isinstance(want, dict) and list(want) == ["at_least"]:
            if not isinstance(got, int) or isinstance(got, bool) or got < want["at_least"]:
                return f"{key}: expected at least {want['at_least']}, got {brief(got)}"
            continue
        # `0 == False` in Python; a candidate answering 0 for a boolean field has
        # not answered the question, so the types must match too.
        if isinstance(want, bool) and not isinstance(got, bool):
            return f"{key}: expected the boolean {want}, got {brief(got)}"
        if got != want:
            return f"{key}: expected {brief(want)}, got {brief(got)}"
    return None


# ---------------------------------------------------------------- running
def materialize(vector, workdir, pack):
    """Turn a vector's file references into absolute paths for the candidate.

    A store fixture ships as a real directory of records and blobs. It is copied
    per vector so a candidate cannot damage the pack, and so two vectors over the
    same fixture cannot see each other's damage.
    """
    inp = dict(vector["input"])
    store_dir = inp.pop("store_dir", None)
    if store_dir is not None:
        dest = workdir / vector["id"].replace("/", "_")
        shutil.copytree(pack / "vectors" / store_dir, dest)
        inp["store_path"] = str(dest)
    trust = inp.pop("trust_config", None)
    if trust is not None:
        # Passed as an absolute path WITHOUT checking that it exists: two of the
        # settlement vectors are about a trust configuration that is missing.
        inp["trust_config_path"] = str(pack / "vectors" / trust)
    return inp


def run_vectors(argv, docs, claim, timeout, pack, workdir, on_result=None):
    results = []
    for doc in docs:
        in_claim = GRADE_ORDER[doc["grade"]] <= GRADE_ORDER[claim]
        for vector in doc["vectors"]:
            row = {"id": vector["id"], "class": doc["class"], "grade": doc["grade"],
                   "polarity": vector["polarity"], "spec": vector["spec"],
                   "why": vector["why"]}
            if not in_claim:
                row["outcome"] = "NOT-CLAIMED"
                row["detail"] = f"{doc['grade']} grade was not claimed"
                results.append(row)
                continue
            request = {"warrant_conformance": PROTOCOL, "id": vector["id"],
                       "class": doc["class"],
                       "input": materialize(vector, workdir, pack)}
            try:
                output, unsupported = ask(argv, request, timeout)
            except ContractError as e:
                row["outcome"], row["detail"] = ERROR, str(e)
            else:
                if unsupported is not None:
                    row["outcome"], row["detail"] = UNRUN, unsupported
                else:
                    mismatch = compare(vector["expect"], output)
                    if mismatch is None:
                        row["outcome"], row["detail"] = PASS, ""
                    else:
                        row["outcome"], row["detail"] = FAIL, mismatch
            results.append(row)
            if on_result:
                on_result(row)
    return results


def grade_achieved(results):
    """The highest grade with no FAIL, ERROR or UNRUN among its vectors."""
    achieved = None
    for grade in sorted(GRADE_ORDER, key=lambda g: GRADE_ORDER[g]):
        rows = [r for r in results
                if GRADE_ORDER[r["grade"]] <= GRADE_ORDER[grade]
                and r["outcome"] != "NOT-CLAIMED"]
        covered = {r["grade"] for r in rows}
        needed = {g for g in GRADE_ORDER if GRADE_ORDER[g] <= GRADE_ORDER[grade]}
        if covered != needed:
            break
        if all(r["outcome"] == PASS for r in rows):
            achieved = grade
        else:
            break
    return achieved


def summarize(results, claim, declared, digest, argv, out=sys.stdout):
    def w(line=""):
        print(line, file=out)

    counts = {}
    for r in results:
        key = (r["class"], r["grade"])
        c = counts.setdefault(key, {PASS: 0, FAIL: 0, UNRUN: 0, ERROR: 0,
                                    "NOT-CLAIMED": 0})
        c[r["outcome"]] += 1

    w(f"warrant conformance pack — {len(results)} vectors")
    w(f"pack digest : {digest}")
    w(f"candidate   : {' '.join(shlex.quote(a) for a in argv)}")
    w(f"declared    : {declared.get('name', '?')} {declared.get('version', '')} "
      f"— grade {declared.get('grade')}, {len(declared.get('classes', []))} classes")
    w(f"tested at   : {claim} grade")
    w()
    w(f"{'class':<16}{'grade':<12}{'pass':>6}{'fail':>6}{'unrun':>7}{'error':>7}"
      f"{'not-claimed':>13}")
    for (cls, grade) in sorted(counts, key=lambda k: (GRADE_ORDER[k[1]], k[0])):
        c = counts[(cls, grade)]
        w(f"{cls:<16}{grade:<12}{c[PASS]:>6}{c[FAIL]:>6}{c[UNRUN]:>7}"
          f"{c[ERROR]:>7}{c['NOT-CLAIMED']:>13}")

    bad = [r for r in results if r["outcome"] in (FAIL, ERROR)]
    unrun = [r for r in results if r["outcome"] == UNRUN]
    not_claimed = [r for r in results if r["outcome"] == "NOT-CLAIMED"]

    if bad:
        w()
        for r in bad[:40]:
            tag = ("MUST-REJECT VECTOR ACCEPTED"
                   if r["outcome"] == FAIL and r["polarity"] == "negative"
                   else r["outcome"])
            w(f"  {tag:<28} {r['id']}")
            w(f"  {'':<28} SPEC {r['spec']}: {r['why'][:100]}")
            w(f"  {'':<28} -> {r['detail'][:140]}")
        if len(bad) > 40:
            w(f"  … and {len(bad) - 40} more")

    # Negative coverage, stated whether or not anything failed. A pack run whose
    # MUST-REJECT half never executed proves nothing, and silence about that is
    # the failure this section exists to prevent.
    negatives = [r for r in results if r["polarity"] == "negative"
                 and r["outcome"] != "NOT-CLAIMED"]
    accepted = [r for r in negatives if r["outcome"] == FAIL]
    neg_unrun = [r for r in negatives if r["outcome"] == UNRUN]
    w()
    if not negatives:
        w("NEGATIVE COVERAGE: NONE. No MUST-REJECT vector ran. Every positive "
          "vector here\n  is also passed by an implementation that accepts "
          "everything, so this run\n  establishes nothing about correctness.")
    elif accepted:
        w(f"PERMISSIVE IMPLEMENTATION: {len(accepted)} of {len(negatives)} "
          f"MUST-REJECT vectors were ACCEPTED.")
        w("  These are the vectors that separate a verifier from a program that "
          "returns\n  true. Failing them is not one bug among many; the "
          "positives cannot detect it.")
        for r in accepted[:12]:
            w(f"    accepted: {r['id']}  ({r['why'][:70]})")
        if len(accepted) > 12:
            w(f"    … and {len(accepted) - 12} more")
    else:
        w(f"negative coverage: {len(negatives)} MUST-REJECT vectors ran, "
          f"{len(negatives) - len(neg_unrun)} rejected as required"
          + (f", {len(neg_unrun)} UNRUN" if neg_unrun else ""))

    if unrun:
        w()
        w(f"UNRUN ({len(unrun)}): the candidate declared these unsupported. "
          f"An unrun vector is\n  not a passed one and does not count toward a grade.")
        for r in unrun[:12]:
            w(f"    {r['id']}  — {r['detail'][:80]}")
        if len(unrun) > 12:
            w(f"    … and {len(unrun) - 12} more")

    if not_claimed:
        classes = sorted({r["class"] for r in not_claimed})
        w()
        w(f"NOT CLAIMED ({len(not_claimed)}): vectors above the claimed grade were "
          f"not sent\n  (classes: {', '.join(classes)}). This is an honest result, "
          f"not a gap —\n  the candidate claimed {claim} grade and was tested at "
          f"{claim} grade.")

    achieved = grade_achieved(results)
    w()
    w(f"GRADE CLAIMED : {claim}")
    w(f"GRADE ACHIEVED: {achieved or 'none'}")
    if achieved is None:
        w("  Not even base grade. See the failures above.")
    elif GRADE_ORDER[achieved] < GRADE_ORDER[claim]:
        w(f"  CLAIM NOT MET: the candidate claimed {claim} and reached {achieved}.")
    return achieved, bad, unrun


def exit_status(results, claim):
    achieved = grade_achieved(results)
    if any(r["outcome"] == ERROR for r in results):
        return EXIT_PROTOCOL
    if any(r["outcome"] == FAIL for r in results):
        return EXIT_FAIL
    if achieved is None or GRADE_ORDER[achieved] < GRADE_ORDER[claim]:
        return EXIT_GRADE_NOT_MET
    return EXIT_OK


# ---------------------------------------------------------------- self-check
SELF_CHECK_CASES = [
    ("accept-all",
     "answers true to every validity question — the 'accepts everything' "
     "implementation the negative vectors exist to catch",
     lambda res: [r for r in res if r["polarity"] == "negative" and r["outcome"] == FAIL]),
    ("legacy-sig",
     "builds the SPEC §5 signed message the pre-0.6.0 way (bare WarrantID)",
     lambda res: [r for r in res
                  if r["class"] in ("sig-message", "verify-sig") and r["outcome"] == FAIL]),
    ("false-unsupported",
     "claims its grade but declares whole classes unsupported — the gap that "
     "must be reported as UNRUN rather than passed over in silence",
     lambda res: [r for r in res if r["outcome"] == UNRUN]),
    ("crash",
     "exits nonzero instead of answering — a contract violation, which is "
     "neither a pass nor a legitimate skip",
     lambda res: [r for r in res if r["outcome"] == ERROR]),
]


def self_check(argv, docs, claim, timeout, pack, out=sys.stdout):
    """Prove this runner can fail before anyone trusts it passing.

    Every case wraps the SAME candidate the operator is about to test, so the
    negative control is not a claim about our reference implementation — it is a
    claim about theirs: "if your verifier were permissive, this runner would say
    so, and here is it saying so."
    """
    def w(line=""):
        print(line, file=out)

    mutate = pack / "stub" / "mutate.py"
    if not mutate.is_file():
        raise SystemExit(f"self-check needs {mutate}")
    ok = True
    w("SELF-CHECK — can this runner detect a broken implementation?")
    w()
    for mutation, why, detector in SELF_CHECK_CASES:
        wrapped = [sys.executable, str(mutate), "--mutation", mutation, "--"] + argv
        with tempfile.TemporaryDirectory() as td:
            try:
                declared = capabilities(wrapped, timeout)
                grade = declared.get("grade", claim)
            except ContractError:
                # `crash` breaks capabilities too; that is itself detection.
                grade = claim
                declared = {}
            results = run_vectors(wrapped, docs, min(grade, claim,
                                                     key=lambda g: GRADE_ORDER[g]),
                                  timeout, pack, Path(td))
        caught = detector(results)
        status = exit_status(results, claim)
        good = bool(caught) and status != EXIT_OK
        ok &= good
        w(f"  {'DETECTED' if good else 'MISSED  '}  mutation={mutation}")
        w(f"            {why}")
        w(f"            -> {len(caught)} vectors flagged, exit status {status}")
        if not good:
            w("            THIS RUNNER DID NOT NOTICE. Do not trust a green run.")
    w()
    w("SELF-CHECK: " + ("the runner detected every deliberate defect."
                        if ok else "FAILED — the runner missed a defect."))
    return ok


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="run.py", allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    ap.add_argument("--candidate", help="the command to invoke, e.g. "
                                        "\"./my-verifier probe\"")
    ap.add_argument("--claim", choices=sorted(GRADE_ORDER),
                    help="test at this grade instead of the one the candidate "
                         "declares (never raises what the candidate can reach; "
                         "it only changes what is asked)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="seconds per vector (default 30)")
    ap.add_argument("--pack", default=str(PACK), help="pack directory")
    ap.add_argument("--json", action="store_true",
                    help="emit one machine-readable result object")
    ap.add_argument("--self-check", action="store_true",
                    help="prove this runner detects deliberately broken behaviour")
    ap.add_argument("--verify-pack", action="store_true",
                    help="check the pack against MANIFEST.sha256 and stop")
    ap.add_argument("--list", action="store_true",
                    help="list the vector classes and counts, then stop")
    ap.add_argument("--skip-pack-check", action="store_true",
                    help="run against a pack whose manifest does not match "
                         "(for authoring vectors; never for a conformance claim)")
    args = ap.parse_args(argv)
    pack = Path(args.pack).resolve()

    digest, problems = verify_pack(pack)
    if problems and not args.skip_pack_check:
        print(f"PACK INTEGRITY: {len(problems)} problem(s) — this is not the pack "
              f"its manifest describes.")
        for p in problems[:20]:
            print(f"  {p}")
        print("  A conformance result from a modified pack means nothing. "
              "Re-download,\n  or pass --skip-pack-check if you are authoring "
              "vectors.")
        return EXIT_PACK
    if args.verify_pack:
        print(f"pack digest: {digest}")
        print("PACK INTEGRITY: every file matches MANIFEST.sha256"
              if not problems else "PACK INTEGRITY: PROBLEMS (see above)")
        return EXIT_OK if not problems else EXIT_PACK

    index, docs = load_vectors(pack)
    if args.list:
        print(f"warrant conformance pack {index['pack_version']} "
              f"({index['total_vectors']} vectors)")
        print(f"pack digest: {digest}")
        for entry in index["files"]:
            doc = next(d for d in docs if d["class"] == entry["class"]
                       and d["grade"] == entry["grade"])
            neg = sum(1 for v in doc["vectors"] if v["polarity"] == "negative")
            print(f"  {entry['class']:<16}{entry['grade']:<12}"
                  f"{entry['vectors']:>4} vectors ({neg} MUST-REJECT)")
        return EXIT_OK

    if not args.candidate:
        ap.error("--candidate is required (see CONTRACT.md)")
    cand = shlex.split(args.candidate)
    if not cand:
        ap.error("--candidate is empty")

    try:
        declared = capabilities(cand, args.timeout)
    except ContractError as e:
        print(f"CONTRACT VIOLATION on `capabilities`: {e}")
        print("  Every candidate must answer the mandatory `capabilities` class. "
              "See CONTRACT.md.")
        return EXIT_PROTOCOL

    claim = args.claim or declared["grade"]
    if docs and args.self_check:
        return EXIT_OK if self_check(cand, docs, claim, args.timeout, pack) else EXIT_FAIL

    with tempfile.TemporaryDirectory(prefix="warrant-conformance-") as td:
        results = run_vectors(cand, docs, claim, args.timeout, pack, Path(td))

    if args.json:
        achieved = grade_achieved(results)
        print(json.dumps({
            "tag": "warrant.conformance-result@v1",
            "pack_version": index["pack_version"], "pack_digest": digest,
            "candidate": cand, "declared": declared,
            "grade_claimed": claim, "grade_achieved": achieved,
            "counts": {k: sum(1 for r in results if r["outcome"] == k)
                       for k in (PASS, FAIL, UNRUN, ERROR, "NOT-CLAIMED")},
            "negatives_run": sum(1 for r in results if r["polarity"] == "negative"
                                 and r["outcome"] != "NOT-CLAIMED"),
            "negatives_accepted": sum(1 for r in results
                                      if r["polarity"] == "negative"
                                      and r["outcome"] == FAIL),
            "results": results,
        }, separators=(",", ":"), ensure_ascii=True))
    else:
        summarize(results, claim, declared, digest, cand)
    return exit_status(results, claim)


if __name__ == "__main__":
    sys.exit(main())
