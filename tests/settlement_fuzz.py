#!/usr/bin/env python3
"""Randomised search for a false SETTLED. Free, and it never gets tired.

WHY THIS EXISTS
---------------
Every defect found in `settle.py` so far cost a reviewer round: the severity
sort order, the timestamp-inferred subject, the hash-without-preimage. All three
were reachable by a machine with no understanding of the code at all — they are
properties, and properties can be searched for by brute force at the price of
electricity.

That matters beyond tidiness. A reviewer family costs money, so it is rationed,
so the cheap path is another round of the family already paid for — which is how
one item in this repository collected eight same-family gates and no P0. Anything
a fuzzer can find is a thing no paid round should ever be spent on again.

WHAT IS ASSERTED
----------------
Four properties, each a way the tool could lie:

  P1  SETTLED implies no reproduced blocking finding on the current subject.
      The direct false settlement -- a merge authorised over a live defect.
  P2  SETTLED implies no claim reproduced on ANY revision without being re-run
      and refuted on the current one. A fix must be demonstrated, never assumed.
  P3  The verdict does not depend on ledger filenames or on the order the files
      are read. Any such dependence is a defect that hides until the day the
      directory listing changes.
  P4  Adding a ledger that reproduces nothing never turns BLOCKED into SETTLED.
      Silence must not be able to clear a finding; only evidence may.

These are oracles, not examples: they hold for every input, so the search may
run as long as there is time for it.

LIMITS
------
Non-reproduction is not proof. A green run means this search did not reach a
counterexample in this many draws, which is a weaker statement than "correct" and
must not be reported as the stronger one.

USAGE
    python3 tests/settlement_fuzz.py            # 2000 draws
    python3 tests/settlement_fuzz.py 50000      # longer hunt
    python3 tests/settlement_fuzz.py 2000 7     # fixed seed, reproducible
"""
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "tools"), str(HERE)]
import settle as S                                          # noqa: E402

_pol = next(p for p in (ROOT / "policies" / "gate-settlement.json",
                        HERE / "gate-settlement.json") if p.exists())
POLICY = json.loads(_pol.read_text())

SUBJECTS = [c * 64 for c in "abc"]
FAMILIES = ["codex@openai", "kimi@moonshot", "gemini@google", "qwen3-coder@local"]
CLAUSES = ["D.3", "d.3 ", "D.4", "7", "unstated", "UNSTATED", "n/a", ""]
SEVERITIES = ["P0", "P1", "P2", "P?", ""]


def draw_ledgers(rng):
    """A random gate history: several families, several revisions, mixed results."""
    out = []
    for _ in range(rng.randint(1, 6)):
        findings = []
        for j in range(rng.randint(0, 3)):
            code = f"print({rng.randint(0, 999)})"
            out_s = f"VIOLATION: {rng.randint(0, 999)}\n"
            findings.append({
                "id": f"F{j}", "severity": rng.choice(SEVERITIES),
                "clause": rng.choice(CLAUSES), "title": "t",
                "repro": code, "repro_sha256": S.sha256_hex(code),
                "transcript": {"stdout": out_s, "stderr": "", "exit": 0},
                "transcript_sha256": S.sha256_hex(out_s + "" + "0"),
                "exit": 0, "reproduced": rng.random() < 0.5,
            })
        out.append({
            "item": "x", "family": rng.choice(FAMILIES), "model": "m", "host": "h",
            "produced_at": f"2026-07-{rng.randint(1, 28):02d}T00:00:00Z",
            "subject_sha256": rng.choice(SUBJECTS), "subject_label": "L",
            "review": "r.md", "findings": findings,
        })
    return out


def run(ledgers, current, names=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for i, led in enumerate(ledgers):
            name = names[i] if names else f"{i:02d}"
            (d / f"{name}.json").write_text(json.dumps(led))
        return S.settle("x", POLICY, d, current)


def blocking_severity(sev):
    label, unknown = S.claim_severity([sev])
    return unknown or label in POLICY["blocking_severities"]


def main():
    draws = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    rng = random.Random(seed)
    failures = []

    for n in range(draws):
        leds = draw_ledgers(rng)
        current = rng.choice(SUBJECTS)
        r = run(leds, current)

        if r["state"] == "SETTLED":
            for led in leds:
                for f in led["findings"]:
                    if not f["reproduced"] or not blocking_severity(f["severity"]):
                        continue
                    if led["subject_sha256"] == current:
                        failures.append(("P1 live defect settled", leds, current))
                    else:
                        # Cleared only if some gate re-ran this claim on the
                        # current subject and it did not reproduce there.
                        key = S.claim_key(f)
                        # Must be the SAME claim, keyed exactly as settle keys it
                        # -- comparing on the raw clause string would let a
                        # collision the tool makes hide from the property meant
                        # to catch collisions.
                        retested = any(
                            S.claim_key(g) == key and not g["reproduced"]
                            for l2 in leds if l2["subject_sha256"] == current
                            for g in l2["findings"])
                        if not retested:
                            failures.append(("P2 assumed fix settled", leds, current))

        # P3: identity must not depend on how the files happen to be named.
        shuffled = list(range(len(leds)))
        rng.shuffle(shuffled)
        r2 = run(leds, current, names=[f"z{i:03d}" for i in shuffled])
        if r2["state"] != r["state"]:
            failures.append(("P3 order-dependent verdict", leds, current))

        # P4: an empty gate is silence, and silence must not clear anything.
        if r["state"] == "BLOCKED":
            quiet = leds + [{**leds[0], "family": "quiet@none",
                             "subject_sha256": current, "findings": []}]
            if run(quiet, current)["state"] == "SETTLED":
                failures.append(("P4 silence cleared a blocker", quiet, current))

        if failures:
            break
        if draws >= 5000 and n % 1000 == 0 and n:
            print(f"  {n}/{draws} draws, no counterexample", file=sys.stderr)

    if failures:
        what, leds, current = failures[0]
        print(f"COUNTEREXAMPLE — {what}\ncurrent={current[:8]}")
        print(json.dumps(leds, indent=2)[:4000])
        print("\nSETTLE-FUZZ: FAILED")
        return 1
    print(f"SETTLE-FUZZ: {draws} draws, no counterexample (seed {seed}). "
          f"Not a proof — only a search that did not reach one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
