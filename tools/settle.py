#!/usr/bin/env python3
"""Gate settlement: decide when an adversarial review has ended.

WHY THIS EXISTS
---------------
Measured on this repository, 2026-07-28: the release-surface item took EIGHT
consecutive Codex gates, every one returning AMEND, every one filing same-layer
P1s, and not one P0 in the whole chain. WRT-002 took SIX Codex rounds that found
only P1s; the first round that asked THREE families returned three REJECTs and
six P0s, nearly disjoint. Two lessons, both mechanical:

  1. One reviewer family, iterated, converges into its own blind spot. Diversity
     is not a courtesy to other vendors; it is the only thing that found the P0s.
  2. An adversarial reviewer with no termination rule never says "ship it". The
     eighth round of "one bounded, same-layer P1" is not a gate any more -- it is
     an argument with no stopping condition, and the queue behind it stops.

SPEC.md §7 already defines the stopping condition, for warrant records: a settled
question re-opens only on (a) evidence absent from the tunnel, or (b) a check
that re-runs to a previously absent OUTCOME FINGERPRINT. This tool points that
rule at the project's own review process, which is the one place it was never
applied.

WHAT DECIDES, AND WHAT DOES NOT
-------------------------------
Blocking power belongs to a reproduction that EXECUTED -- not to a signature, a
severity label, or a reviewer's confidence. `adversarial_gate.py` already runs
every counter-vector against a pristine copy and demotes anything that will not
run to a Question. This tool makes that demotion decisive: an assertion blocks
nothing. A repro that exits 0 and prints `VIOLATION:` blocks, whoever signed it.

That choice is deliberate, and it is what lets the roster tolerate co-located
keys. A signature says who wrote something down. A reproduction can be re-run by
a stranger on their own machine and will agree or not agree on its own. Only the
second is independent of custody, so only the second is allowed to decide.

NOVELTY IS PER CLAUSE, NOT PER TRANSCRIPT
-----------------------------------------
§7 warns that syntactic novelty alone is exploitable -- "a permissive-policy
store may accumulate unbounded fingerprint-distinct but irrelevant
re-litigations" -- and delegates relevance to the active settlement policy. This
is that policy choice: a finding is novel when it breaks a normative CLAUSE not
already broken in the tunnel. Re-deriving the same clause with different code is
recorded as a restatement. Without this, a reviewer can manufacture unlimited
"new" findings by perturbing the repro, and the loop we are trying to end simply
gets a hash on it.

A FIX MUST BE DEMONSTRATED, NEVER ASSUMED
------------------------------------------
A claim that reproduced against an older revision and was never re-run against
the current one is reported UNRESOLVED, never quietly dropped. Silently ageing a
finding out of the tunnel is exactly the failure this repository keeps finding in
its own gates: a green result covering less than it claims.

LIMITS (state them, do not launder them)
----------------------------------------
  * This decides whether the ARGUMENT has terminated. It does not decide that the
    design is correct. No count of non-reproducing attacks proves an absence.
  * Family diversity here means different model families were asked. It does not
    mean the reviews were independently custodied; the harness runs on one host.
  * Settlement authorises a merge under the gate policy. Governance ADOPTION is a
    separate threshold warrant signed by roster keys (AGENTS.md §2) and this tool
    neither performs nor substitutes for it.

USAGE
    python3 tools/settle.py --item wrt-002
    python3 tools/settle.py --item wrt-002 --json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "reviews" / "ledgers"
DEFAULT_POLICY = ROOT / "policies" / "gate-settlement.json"


def jcs(obj):
    """JCS-ish canonical JSON: sorted keys, no insignificant whitespace.

    Matches the canonicalisation discipline SPEC.md §4 requires of anything whose
    hash is load-bearing. A fingerprint that varied with key order would let the
    same outcome present as two different outcomes.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def outcome_fingerprint(subject, finding):
    """§7 cmd@v1 outcome fingerprint: {runtime, sorted evidence, verdict, transcript}.

    Evidence hashes are sorted because the `evidence` array is not ordered by
    JCS -- §7 says so explicitly, and an unsorted fingerprint would make two
    identical outcomes look distinct depending on emission order.
    """
    evidence = sorted([finding["repro_sha256"], subject])
    return sha256_hex(jcs({
        "runtime": "cmd@v1",
        "evidence": evidence,
        "verdict": "reproduced" if finding["reproduced"] else "not-reproduced",
        "transcript": finding["transcript_sha256"],
    }))


def claim_key(finding):
    """The relevance key: which normative clause this finding breaks.

    Falls back to the finding's own id when a reviewer did not name a clause. The
    fallback is deliberately WEAK -- an unnamed clause cannot be matched against
    prior rounds, so it always reads as novel. That errs toward blocking, which is
    the safe direction: an unclassifiable finding should stop the queue and get a
    human's eye, not slip through as a duplicate.
    """
    clause = (finding.get("clause") or "").strip()
    if not clause:
        return f"unclassified:{finding.get('id', '?')}"
    return f"clause:{clause.lower()}"


def load_policy(path):
    if not path.exists():
        sys.exit(f"no gate policy at {path} -- settlement has no rules to apply")
    pol = json.loads(path.read_text())
    if pol.get("gate_policy") != "0.1":
        sys.exit(f"unsupported gate_policy {pol.get('gate_policy')!r}")
    return pol


def load_ledgers(item, ledger_dir=None):
    ledger_dir = ledger_dir or LEDGER_DIR
    if not ledger_dir.exists():
        return []
    out = []
    for p in sorted(ledger_dir.glob("*.json")):
        led = json.loads(p.read_text())
        if led.get("item") == item:
            led["_path"] = p.name
            out.append(led)
    return out


def settle(item, policy, ledger_dir=None):
    ledgers = load_ledgers(item, ledger_dir)
    if not ledgers:
        # Same shape as every other outcome. A report that drops fields when it
        # has nothing to say invites a consumer to read "absent" as "clean".
        return {"item": item, "state": "NO-GATES",
                "reason": f"no ledgers for {item!r} in reviews/ledgers/",
                "current_subject": "", "subject_label": "", "families_on_current": [],
                "gates_total": 0, "blocking": [], "unresolved": [],
                "restatements": [], "claims_total": 0, "policy_sha256": None}

    # The current subject is the newest revision any gate examined. Everything is
    # judged against THAT -- a verdict on superseded text settles nothing about
    # the text on the branch.
    subjects = {}
    for led in ledgers:
        subjects.setdefault(led["subject_sha256"], led.get("subject_label", "?"))
    current = max(ledgers, key=lambda l: l.get("produced_at", ""))["subject_sha256"]

    claims = {}          # claim_key -> best-known state
    restatements = []
    for led in ledgers:
        for f in led.get("findings", []):
            key = claim_key(f)
            rec = claims.setdefault(key, {"key": key, "seen": [], "fingerprints": set()})
            fp = outcome_fingerprint(led["subject_sha256"], f)
            if fp in rec["fingerprints"]:
                continue                      # byte-identical outcome, already counted
            if rec["seen"] and f["reproduced"]:
                restatements.append({"claim": key, "family": led["family"],
                                     "id": f.get("id"), "fingerprint": fp[:12]})
            rec["fingerprints"].add(fp)
            rec["seen"].append({
                "family": led["family"], "id": f.get("id"),
                "severity": (f.get("severity") or "P?").upper(),
                "title": f.get("title", ""), "reproduced": bool(f["reproduced"]),
                "subject": led["subject_sha256"], "ledger": led["_path"],
            })

    blocking, unresolved = [], []
    for key, rec in sorted(claims.items()):
        on_current = [s for s in rec["seen"] if s["subject"] == current]
        blocked_ever = [s for s in rec["seen"] if s["reproduced"]]
        sev = max((s["severity"] for s in blocked_ever), default="P?")
        if sev not in policy["blocking_severities"]:
            continue
        if any(s["reproduced"] for s in on_current):
            blocking.append({"claim": key, "severity": sev,
                             "title": blocked_ever[-1]["title"],
                             "family": blocked_ever[-1]["family"]})
        elif blocked_ever and not on_current:
            # Reproduced once, never re-run against the text now on the branch.
            # Not a pass. Not a failure. A gap, and it is named as one.
            unresolved.append({"claim": key, "severity": sev,
                               "title": blocked_ever[-1]["title"],
                               "last_seen_subject": blocked_ever[-1]["subject"][:12]})

    families = sorted({l["family"] for l in ledgers if l["subject_sha256"] == current})
    enough_families = len(families) >= policy["min_families"]

    if blocking:
        state, reason = "BLOCKED", f"{len(blocking)} reproduced claim(s) on current subject"
    elif unresolved:
        state, reason = "UNRESOLVED", (
            f"{len(unresolved)} claim(s) reproduced on earlier text and never re-run "
            f"against the current subject -- re-gate before settling")
    elif not enough_families:
        state, reason = "OPEN", (
            f"only {len(families)} family/families gated the current subject; "
            f"policy requires {policy['min_families']}")
    else:
        state, reason = "SETTLED", (
            f"{len(families)} families gated the current subject; no reproduced claim "
            f"remains")

    return {
        "item": item, "state": state, "reason": reason,
        "current_subject": current, "subject_label": subjects.get(current, "?"),
        "families_on_current": families,
        "gates_total": len(ledgers),
        "blocking": blocking, "unresolved": unresolved,
        "restatements": restatements,
        "claims_total": len(claims),
        "policy_sha256": None,      # filled by main(), see note there
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--ledger-dir", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    policy = load_policy(args.policy)
    report = settle(args.item, policy, args.ledger_dir)
    # The policy is pinned BY HASH in the report, the way `under` pins a policy
    # in a warrant body (SPEC.md §2): a settlement decided under different rules
    # must not be mistakable for this one.
    report["policy_sha256"] = sha256_hex(args.policy.read_text())

    if args.json:
        print(jcs(report))
    else:
        print(f"{report['state']}: {report['item']} — {report['reason']}")
        print(f"  subject   {report['current_subject'][:16]}  ({report['subject_label']})")
        print(f"  families  {', '.join(report['families_on_current']) or '(none)'}")
        print(f"  gates {report['gates_total']}   claims {report['claims_total']}"
              f"   restatements {len(report['restatements'])}")
        for b in report["blocking"]:
            print(f"  BLOCK  [{b['severity']}] {b['claim']}  {b['title']}  ({b['family']})")
        for u in report["unresolved"]:
            print(f"  STALE  [{u['severity']}] {u['claim']}  {u['title']}"
                  f"  last seen on {u['last_seen_subject']}")
    return 0 if report["state"] == "SETTLED" else 1


if __name__ == "__main__":
    sys.exit(main())
