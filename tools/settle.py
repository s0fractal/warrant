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

    §7 sorts the `evidence` array because it is unordered THERE. Sorting subject
    and repro together here was a misreading: they are different roles, not two
    interchangeable members of a set, so (subject=X, repro=Y) and (subject=Y,
    repro=X) collapsed to one fingerprint. Codex reproduced it -- a live finding
    discarded as an already-seen outcome. Named fields, sorted keys via jcs().
    """
    return sha256_hex(jcs({
        "runtime": "cmd@v1",
        "subject": subject,
        "repro": finding["repro_sha256"],
        "verdict": "reproduced" if finding["reproduced"] else "not-reproduced",
        "transcript": finding["transcript_sha256"],
    }))


# Values that name no clause. `unstated` is the worst of them because the repro
# rules INSTRUCT reviewers to write it for a property the document never states --
# so without this list every distinct unwritten-property defect shares one claim
# key by design, and refuting any one of them clears all the others.
NON_IDENTIFYING = {"", "unstated", "unknown", "none", "n/a", "-", "?"}


def claim_key(finding, document="", family=""):
    """The relevance key: which normative clause this finding breaks.

    A named clause is the unit of a claim: re-deriving it with different code is a
    restatement, and refuting it on the current text closes it. That only holds if
    the key really identifies a clause. When it does not, findings that share it
    are NOT the same defect, and treating them as one lets a refutation of A
    silently close a live B.

    Demonstrated on 2026-07-28: two distinct `unstated` defects, one reproduced
    against superseded text and never retested, the other refuted against the
    current text -- SETTLED, with the first never looked at again. So anything
    non-identifying is keyed per finding instead, which reads as novel every time
    and errs toward blocking. An unclassifiable finding should stop the queue and
    get a human's eye rather than slip through as somebody else's duplicate.
    """
    clause = (finding.get("clause") or "").strip().lower()
    doc = (finding.get("document") or document or "").strip().lower()
    if clause in NON_IDENTIFYING:
        # Reviewer identity is part of the key. Two families both numbering a
        # finding `F1` and both driving it with the same boilerplate produced one
        # key for two unrelated properties (Codex F5).
        return (f"unidentified:{family}:{finding.get('id', '?')}:"
                f"{finding.get('repro_sha256', '')[:12]}")
    # `D.3` names nothing without the document that numbers it. Refuting D.3 of
    # one text silently closed D.3 of another (Codex F4).
    return f"clause:{doc}:{clause}"


SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def claim_severity(severities):
    """Most severe label across a claim, plus whether any label was unrecognised.

    This was a P0 in this file's first revision, found on its own gate: severity
    was `max()` over raw strings, and in ASCII '?' > '1' > '0', so the LEAST
    severe label won and an unparsed `P?` beat everything. Since `P?` is not in
    `blocking_severities`, a reproduced P0 sharing a clause with one unlabelled
    finding stopped blocking entirely and the item reported SETTLED -- the exact
    false settlement this tool exists to prevent, produced by a sort order.

    Two rules follow, both fail-closed. Severity is ranked explicitly, never
    lexically. An unrecognised label is not harmless: it means the harness could
    not read how bad a thing that DID reproduce is, so it blocks and a human
    looks. The report says `P?` rather than silently promoting it, because
    inventing a severity would be its own false claim.
    """
    severities = list(severities)
    known = [s for s in severities if s in SEVERITY_RANK]
    unknown = len(known) != len(severities)
    label = min(known, key=lambda s: SEVERITY_RANK[s]) if known else "P?"
    return label, unknown


def subject_for_target(name):
    """Recompute the reviewed subject's hash from the LIVE files.

    Shares one definition with the gate rather than copying the slice rule: two
    copies would drift, and a settlement decided against a stale notion of "the
    subject" is the defect this function exists to close.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import adversarial_gate as ag                       # noqa: PLC0415

    t = ag.TARGETS[name]
    return ag.subject_hash(t), t["subject"]


def check_preimages(led):
    """Recompute each finding's hashes from the preimages carried beside them.

    Catches corruption and drift -- a ledger hand-edited, truncated, merged
    badly, or written by a harness whose hashing changed. It does NOT catch
    forgery: whoever can write a ledger can write a consistent one, and that
    trust boundary (documented in the policy) is not closed here and must not be
    described as if it were.

    Findings that carry no preimage are left alone rather than rejected: older
    ledgers predate the field, and refusing to read real recorded evidence
    because of its age would discard exactly what this tool is for.
    """
    bad = []
    for f in led.get("findings", []):
        if "repro" in f and sha256_hex(f["repro"]) != f["repro_sha256"]:
            bad.append(f"{f.get('id')}: repro hash mismatch")
        t = f.get("transcript")
        if t is not None:
            recomputed = sha256_hex(t["stdout"] + t["stderr"] + str(t["exit"]))
            if recomputed != f["transcript_sha256"]:
                bad.append(f"{f.get('id')}: transcript hash mismatch")
    return bad


def load_policy(path):
    if not path.exists():
        sys.exit(f"no gate policy at {path} -- settlement has no rules to apply")
    pol = json.loads(path.read_text())
    for problem in policy_problems(pol):
        sys.exit(f"invalid gate policy {path}: {problem}")
    return pol


def policy_problems(pol):
    """Reject a policy that cannot gate anything.

    Validation checked the version string and nothing else, so a policy with an
    empty `blocking_severities` -- or `min_families: 0` -- was accepted and
    settled a live reproduced P0 (Codex F7). A rule set that forbids nothing is
    not a lenient policy, it is the absence of one, and it must not be reachable
    by editing a file that still says `gate_policy: 0.1`.
    """
    if pol.get("gate_policy") != "0.1":
        return [f"unsupported gate_policy {pol.get('gate_policy')!r}"]
    bad = []
    sev = pol.get("blocking_severities")
    if not isinstance(sev, list) or not sev:
        bad.append("blocking_severities must be a non-empty list")
    elif not set(sev) <= set(SEVERITY_RANK):
        bad.append(f"unknown severities {sorted(set(sev) - set(SEVERITY_RANK))}")
    elif "P0" not in sev:
        bad.append("P0 must be blocking; a policy that settles over a reproduced "
                   "P0 is not a gate")
    n = pol.get("min_families")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        bad.append("min_families must be an integer >= 1")
    fams = pol.get("recognized_families")
    if not isinstance(fams, list) or not fams:
        bad.append("recognized_families must be a non-empty list; without a "
                   "roster, aliases of one reviewer satisfy the diversity rule")
    elif len({f.lower() for f in fams}) != len(fams):
        bad.append("recognized_families contains case-duplicate entries")
    if pol.get("novelty") != "clause":
        bad.append(f"unsupported novelty rule {pol.get('novelty')!r}")
    return bad


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


def settle(item, policy, ledger_dir=None, current=None):
    ledgers = load_ledgers(item, ledger_dir)
    if not current:
        # Fail closed. Guessing which revision is current is exactly the P0 this
        # parameter replaced; refusing to guess is the whole fix.
        return {"item": item, "state": "NO-SUBJECT",
                "reason": "no current subject given -- pass --subject or --target",
                "current_subject": "", "subject_label": "", "families_on_current": [],
                "gates_total": len(ledgers), "blocking": [], "unresolved": [],
                "restatements": [], "claims_total": 0, "policy_sha256": None}
    corrupt = []
    for led in ledgers:
        corrupt += [f"{led['_path']} {m}" for m in check_preimages(led)]
    if corrupt:
        # Fail closed and loudly. A ledger whose evidence does not hash to its
        # own digests is not weak evidence, it is unreadable evidence, and
        # settling under it would be the false claim this tool exists to stop.
        return {"item": item, "state": "CORRUPT",
                "reason": "; ".join(corrupt[:5]),
                "current_subject": current or "", "subject_label": "",
                "families_on_current": [], "gates_total": len(ledgers),
                "blocking": [], "unresolved": [], "restatements": [],
                "claims_total": 0, "policy_sha256": None}
    if not ledgers:
        # Same shape as every other outcome. A report that drops fields when it
        # has nothing to say invites a consumer to read "absent" as "clean".
        return {"item": item, "state": "NO-GATES",
                "reason": f"no ledgers for {item!r} in reviews/ledgers/",
                "current_subject": "", "subject_label": "", "families_on_current": [],
                "gates_total": 0, "blocking": [], "unresolved": [],
                "restatements": [], "claims_total": 0, "policy_sha256": None}

    # The current subject is supplied by the CALLER, from the live reviewed bytes.
    # It was once inferred as max(produced_at) across ledgers, and that was a P0
    # (found by Codex, 2026-07-28): `produced_at` is a string the harness writes,
    # so re-gating an OLDER revision later made the old text "current". A claim
    # reproduced against the real current text then sat outside the current
    # subject, its non-reproduction on the old text counted as the live result,
    # and the item reported SETTLED with the defect still open.
    #
    # The rule this violated is the project's own: trust the hash, not the host.
    # Metadata about an artifact never decides what the artifact is.
    subjects = {}
    for led in ledgers:
        subjects.setdefault(led["subject_sha256"], led.get("subject_label", "?"))

    # A finding with no clause has no inferable identity: not from the clause
    # (there is none) and not from the code (a re-test is new code, so new bytes).
    # Keying it per finding kept two distinct `unstated` defects apart -- and made
    # every one of them immortal, since no re-test could ever land on the same
    # key. Safety without liveness is still a defect; three families refuting a
    # thing must be able to close it.
    #
    # So closure is EXPLICIT: a finding may name the claim it re-tests, and that
    # citation is itself evidence -- the closing reproduction ran, is stored with
    # its transcript, and anyone can re-run it. Nothing closes by accident, and
    # nothing is closed by a sentence.
    claims = {}          # claim_key -> best-known state
    restatements = []
    cited, defined = set(), set()
    for led in ledgers:
        for f in led.get("findings", []):
            closes = (f.get("closes") or "").strip()
            key = closes if closes else claim_key(
                f, led.get("document", ""), led["family"])
            if closes:
                cited.add(closes)
            else:
                defined.add(key)
            rec = claims.setdefault(key, {"key": key, "seen": [], "fingerprints": set()})
            fp = outcome_fingerprint(led["subject_sha256"], f)
            # A repeated outcome is not novel, but it is still a record. Skipping
            # it entirely discarded its SEVERITY too, so a later P0 that happened
            # to share a fingerprint with an earlier unlabelled entry vanished and
            # the claim settled (Codex F2). Novelty and existence are different
            # questions; only the first is what a fingerprint answers.
            if rec["seen"] and f["reproduced"] and fp not in rec["fingerprints"]:
                restatements.append({"claim": key, "family": led["family"],
                                     "id": f.get("id"), "fingerprint": fp[:12]})
            rec["fingerprints"].add(fp)
            rec["seen"].append({
                "family": led["family"], "id": f.get("id"),
                "severity": (f.get("severity") or "P?").upper(),
                "title": f.get("title", ""), "reproduced": bool(f["reproduced"]),
                "subject": led["subject_sha256"], "ledger": led["_path"],
                "repro": f.get("repro_sha256", ""), "closes": closes,
            })

    # A citation that names nothing is a no-op that LOOKS like a closure, which
    # is the most dangerous shape a mistake can take here: it reads as work done.
    dangling = sorted(cited - defined)

    blocking, unresolved = [], []
    for key, rec in sorted(claims.items()):
        on_current = [s for s in rec["seen"] if s["subject"] == current]
        blocked_ever = [s for s in rec["seen"] if s["reproduced"]]
        if not blocked_ever:
            continue
        sev, sev_unknown = claim_severity(s["severity"] for s in blocked_ever)
        if not (sev_unknown or sev in policy["blocking_severities"]):
            continue
        # A claim is retested only by evidence that addresses THE SAME attack:
        # the identical reproduction re-run, or an explicit `closes=` citation.
        # Accepting any non-reproducing finding that shared the clause meant a
        # different probe -- one that never triggered the defect in the first
        # place -- closed an exploit nobody had re-run (Codex F1). "Probe B did
        # not fire" says nothing whatever about probe A.
        live_repros = {s["repro"] for s in blocked_ever}
        retested = [s for s in on_current
                    if not s["reproduced"] and (s["closes"] or s["repro"] in live_repros)]
        if any(s["reproduced"] for s in on_current):
            blocking.append({"claim": key, "severity": sev,
                             "title": blocked_ever[-1]["title"],
                             "family": blocked_ever[-1]["family"]})
        elif not retested:
            # Reproduced once, never re-run against the text now on the branch.
            # Not a pass. Not a failure. A gap, and it is named as one.
            unresolved.append({"claim": key, "severity": sev,
                               "title": blocked_ever[-1]["title"],
                               "last_seen_subject": blocked_ever[-1]["subject"][:12]})

    # Diversity is the whole reason the threshold exists, and it was counted by
    # taking distinct values of a command-line flag. `codex@openai`,
    # `codex@oai` and `Codex@OpenAI` counted as three independent families and
    # settled an item (Codex F6). Only families the policy recognises count;
    # anything else is reported rather than silently believed or silently
    # dropped.
    roster = {f.lower() for f in policy["recognized_families"]}
    seen_fams = {l["family"].strip().lower() for l in ledgers
                 if l["subject_sha256"] == current}
    families = sorted(seen_fams & roster)
    unrecognised = sorted(seen_fams - roster)
    enough_families = len(families) >= policy["min_families"]

    if blocking:
        state, reason = "BLOCKED", f"{len(blocking)} reproduced claim(s) on current subject"
    elif unresolved:
        state, reason = "UNRESOLVED", (
            f"{len(unresolved)} claim(s) reproduced on earlier text and never re-run "
            f"against the current subject -- re-gate before settling")
    elif not enough_families:
        state, reason = "OPEN", (
            f"only {len(families)} recognised family/families gated the current "
            f"subject; policy requires {policy['min_families']}"
            + (f" (ignored, not on roster: {', '.join(unrecognised)})"
               if unrecognised else ""))
    else:
        state, reason = "SETTLED", (
            f"{len(families)} families gated the current subject; no reproduced claim "
            f"remains")

    if dangling:
        state = "BLOCKED" if state == "SETTLED" else state
        reason += f" | closes= names no known claim: {', '.join(dangling[:3])}"

    return {
        "item": item, "state": state, "reason": reason,
        "dangling_closes": dangling,
        "current_subject": current, "subject_label": subjects.get(current, "?"),
        "families_on_current": families,
        "unrecognised_families": unrecognised,
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
    ap.add_argument("--subject", help="sha256 of the reviewed bytes now on the branch")
    ap.add_argument("--target", help="recompute --subject from this gate target's live files")
    ap.add_argument("--ledger-dir", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    policy = load_policy(args.policy)
    if args.subject and args.target:
        sys.exit("give --subject or --target, not both")
    if not (args.subject or args.target):
        sys.exit("settlement needs the current subject: pass --subject <sha256> "
                 "or --target <name>. It is never inferred -- inferring it from "
                 "ledger timestamps was a P0 (false SETTLED with the defect open).")
    current = args.subject
    if args.target:
        current, _ = subject_for_target(args.target)
    report = settle(args.item, policy, args.ledger_dir, current)
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
