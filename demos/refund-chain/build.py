#!/usr/bin/env python3
"""Build the refund-chain demo — deterministically, through the real libraries,
so every hash, signature and ATP figure is produced by the code a verifier will
re-run. Nothing here is hand-computed and nothing is narrated that the store
does not contain.

WHAT THIS DEMO IS FOR
---------------------
`demos/air-canada` shows one decision with one re-runnable reason. That proves
a check re-runs. It does not show the thing this format is actually for.

This one shows a settled question REOPENING, mechanically, on a consequence
nobody had drawn — and the reopening propagating to every decision that was
built on top of it, with no registry, no notification service, and nobody
remembering the dependency existed.

    ACT I    three decisions chain: eligibility -> timeliness -> grant.
             Link 3's facts are not observations. Each is the ANSWER of a prior
             decision, cited by WarrantID and recovered by re-running it
             (WRT-010, warrant.fact-provenance@v0).

    ACT II   an objector files a re-litigation carrying only prose.
             REFUSED by §7: "cites nothing new". Rhetoric is legal; it is not
             proof. This is a real refusal from settlement_admissibility(),
             printed as it happens, not a story about one.

    ACT III  someone compiles policy clause 4 — which has been in `under` since
             the first decision — against `days_between_death_and_travel`, which
             has been in the evidence blob since the first decision. No new
             evidence. A new demonstrable consequence of evidence already
             present: §7(b). The settlement REOPENS, eligibility is superseded,
             and link 3's derived fact goes `stale` on its own.

HONEST SCOPE
------------
The story is modelled on Moffatt v. Air Canada, 2024 BCCRT 149, but clause 4
and the 45-day interval are INVENTED for this demo. They are not that case's
facts. What is real is the machinery: every verdict below is read out of an
actual reduction, and every refusal is the library's, not the narrator's.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "impl"))

import fact_provenance as fp      # noqa: E402  (WRT-010 profile)
import policy_lang as pl          # noqa: E402  (WPL v1 -> ski@v1 compiler)
import warrant as w               # noqa: E402  (reference implementation)

PACK = HERE / "pack"
STORE = PACK / ".warrants"
POL = HERE / "policies"

SKI = "ski@v1"
DESK = "desk@airline"
AUDITOR = "auditor@airline"

DESK_SEED = "d1" * 32
AUDIT_SEED = "e2" * 32
CLAIMANT_SEED = "f3" * 32

T0 = 1708300800                   # 2024-02-19
DAY = 86400

POLICY_TEXT = """AIRLINE — BEREAVEMENT TRAVEL POLICY (excerpt, pinned by hash)

1. Bereavement fares are a discount on published fares for travel due to the
   death of an immediate family member.
2. A bereavement discount MUST be requested BEFORE travel. It CANNOT be
   claimed retroactively for tickets already flown.
3. The claimant MUST file a death certificate and MUST be an immediate family
   member of the deceased.
4. Travel MUST commence within 10 days of the date of death. Travel beyond
   that interval is outside the bereavement programme regardless of any other
   clause.

NOTE FOR THE READER OF THIS DEMO: clause 4 is present from the very first
decision and is cited in `under` by every record in this pack. No decision in
ACT I compiles it. That is the point.
"""

# Every number ACT III needs is already here, in the blob the first decision
# cited. The reopening adds no evidence: it draws a consequence.
CLAIM_JSON = json.dumps({
    "action": "grant_refund",
    "basis": "bereavement_discount",
    "amount_cad": 650.88,
    "relationship": "grandmother",
    "certificate_filed": True,
    "requested_before_travel": True,
    "retroactive": False,
    "date_of_death": "2024-01-02",
    "travel_commenced": "2024-02-16",
    "days_between_death_and_travel": 45,
}, indent=2, sort_keys=True) + "\n"


class Args:
    """Minimal shim matching warrant.file_warrant's expected attributes."""

    def __init__(self, **kw):
        d = dict(under=[], evidence=[], prior=[], reason=None, check=None,
                 runtime="cmd@v1", verdict="pass", transcript=None,
                 relitigates=None, ts=None)
        d.update(kw)
        for k, v in d.items():
            setattr(self, k, v)


def banner(text):
    print("\n" + "=" * 70)
    print("  " + text)
    print("=" * 70)


def file_policy(store, src_text, *, decision, subject, policy_hex, prior,
                actor, key, ts, note, extra_evidence=()):
    """Compile a WPL source, pin it and its provenance document, and file a
    warrant citing the check. Returns (wid, Compiled, source_hex, prov_hex).

    The provenance document is what makes a derived fact checkable: it names
    every fact of the check, says whether each is `observed` or `derived`, and
    for a derived one names the decision it came from. Its completeness rule
    means a fact cannot be quietly left undescribed."""
    compiled = pl.compile_source(src_text, store.put_blob)
    src_hex = store.put_blob(src_text.encode())
    prov_hex = fp.put_doc(store, compiled, compiled.blob, src_hex)
    wid = w.file_warrant(
        store, decision, subject,
        Args(under=[policy_hex], prior=list(prior),
             evidence=[src_hex, prov_hex, *extra_evidence],
             check=compiled.blob, runtime=SKI, verdict="pass",
             reason=[note], actor=actor, key=str(key), ts=ts),
        note=note)
    return wid, compiled, src_hex, prov_hex


def show_provenance(store, wid, label):
    r = fp.check_record(store, wid)
    print(f"    {label}  [{r.status}]")
    for e in r.refusals:
        print(f"      REFUSED  {e}")
    for f in r.findings:
        mark = "  " if f.ok else "!!"
        print(f"      {mark} {f.fact:<10} {f.state:<13} {f.detail}")
    return r.findings


def main():
    if PACK.exists():
        shutil.rmtree(PACK)
    store = w.Store(str(STORE))
    store.init()

    keydir = Path(tempfile.mkdtemp(prefix="refund-chain-keys-"))
    desk = keydir / "desk.key"
    audit = keydir / "audit.key"
    claimant = keydir / "claimant.key"
    desk.write_text(DESK_SEED + "\n")
    audit.write_text(AUDIT_SEED + "\n")
    claimant.write_text(CLAIMANT_SEED + "\n")

    policy_hex = store.put_blob(POLICY_TEXT.encode())
    claim_hex = store.put_blob(CLAIM_JSON.encode())

    # ------------------------------------------------------------- ACT I
    banner("ACT I — three decisions, chained")

    w1, c1, _, _ = file_policy(
        store, (POL / "1-eligibility.wpl").read_text(),
        decision="accept", subject=claim_hex, policy_hex=policy_hex, prior=[],
        actor=DESK, key=desk, ts=T0,
        note="claimant is inside the bereavement programme",
        extra_evidence=[claim_hex])
    print(f"  [1] eligibility  {w1[:16]}…  answer={str(c1.result).lower()}  "
          f"{c1.atp} ATP")
    show_provenance(store, w1, "facts:")

    w2, c2, _, _ = file_policy(
        store, (POL / "2-timeliness.wpl").read_text(),
        decision="accept", subject=claim_hex, policy_hex=policy_hex, prior=[w1],
        actor=DESK, key=desk, ts=T0 + 3600,
        note="request was made before travel and is not retroactive",
        extra_evidence=[claim_hex])
    print(f"\n  [2] timeliness   {w2[:16]}…  answer={str(c2.result).lower()}  "
          f"{c2.atp} ATP")
    show_provenance(store, w2, "facts:")

    grant_src = ((POL / "3-grant.wpl.tmpl").read_text()
                 .replace("{{eligibility_wid}}", w1)
                 .replace("{{timeliness_wid}}", w2))
    w3, c3, _grant_src_hex, _grant_prov = file_policy(
        store, grant_src, decision="accept", subject=claim_hex,
        policy_hex=policy_hex, prior=[w1, w2], actor=DESK, key=desk,
        ts=T0 + 7200, note="refund granted: eligible and timely")
    print(f"\n  [3] grant        {w3[:16]}…  answer={str(c3.result).lower()}  "
          f"{c3.atp} ATP   <- SETTLES THE QUESTION")
    show_provenance(store, w3, "facts (neither is an observation):")

    # ------------------------------------------------------------ ACT II
    banner("ACT II — an objection made of words")

    objection = {
        "warrant": "0.2", "decision": "reject", "subject": {"hash": claim_hex},
        "under": [policy_hex], "evidence": [], "prior": [w3],
        "because": [{"kind": "prose", "text":
                     "I have reviewed this and I believe the grant is wrong. "
                     "The claim does not sit right with the spirit of the "
                     "policy and should be reconsidered."}],
        "actor": {"id": "objector@airline"}, "ts": T0 + 30 * DAY,
    }
    verdict = w.settlement_admissibility(store, w3, objection)
    print("  candidate: one prose reason, no check, no new evidence")
    print(f"  §7 verdict: {verdict}")
    print("  -> the store does not change. Rhetoric is legal;")
    print("     SPEC §3.1: \"it just doesn't count as proof\".")
    assert verdict.startswith("inadmissible"), verdict

    # ----------------------------------------------------------- ACT III
    banner("ACT III — a consequence nobody had drawn")

    prox_src = (POL / "4-proximity.wpl").read_text()
    prox = pl.compile_source(prox_src, store.put_blob)
    prox_src_hex = store.put_blob(prox_src.encode())
    prox_prov = fp.put_doc(store, prox, prox.blob, prox_src_hex)
    print(f"  clause 4 compiled: answer={str(prox.result).lower()}  "
          f"{prox.atp} ATP")
    print(f"  it reads days_between_death_and_travel = "
          f"{json.loads(CLAIM_JSON)['days_between_death_and_travel']} "
          f"from {claim_hex[:12]}… — the SAME blob the first decision cited.")

    # The candidate cites ONLY evidence already inside the settling tunnel. If
    # it cited the new WPL source blob, §7 would admit it under (a) "new
    # evidence" and this demo's whole claim would be false — admitted for a
    # reason other than the one it is about. The source and provenance blobs
    # are filed with the supersede below, where no novelty test applies.
    candidate = {
        "warrant": "0.2", "decision": "reject", "subject": {"hash": claim_hex},
        "under": [policy_hex],
        "evidence": [claim_hex],
        "prior": [w3],
        "because": [prox.reason("pass")],
        "actor": {"id": AUDITOR}, "ts": T0 + 60 * DAY,
    }
    verdict = w.settlement_admissibility(store, w3, candidate)
    print(f"  evidence cited: only {claim_hex[:12]}…, already in the tunnel")
    print(f"  §7 verdict: {verdict}")
    # Enforced, not narrated: this demo is about (b), so (a) is a failure here.
    assert verdict == "admissible: (b) new outcome fingerprint", verdict

    w4 = w.file_warrant(
        store, "reject", claim_hex,
        Args(under=[policy_hex], prior=[w3],
             evidence=[claim_hex],
             check=prox.blob, runtime=SKI, verdict="pass",
             reason=["policy clause 4: travel began 45 days after the death, "
                     "outside the 10-day interval"],
             actor=AUDITOR, key=str(audit), ts=T0 + 60 * DAY,
             relitigates=w3),
        note="clause 4 was never compiled against the filed interval")
    print(f"  re-litigation filed: {w4[:16]}…")

    w5 = w.file_warrant(
        store, "supersede", w1,
        Args(under=[policy_hex], prior=[w1, w4],
             evidence=[claim_hex, prox_src_hex, prox_prov],
             check=prox.blob, runtime=SKI, verdict="pass",
             reason=["eligibility rested on clauses 1-3 alone; clause 4 "
                     "excludes this claim"],
             actor=AUDITOR, key=str(audit), ts=T0 + 60 * DAY + 60),
        note="eligibility decision replaced")
    print(f"  eligibility superseded by: {w5[:16]}…")

    banner("THE PAYOFF — nobody told link 3 anything")
    print("  Link 3 was filed 60 days earlier. No registry recorded that it")
    print("  depended on link 1. No service notified it. Its own provenance")
    print("  document is enough for a verifier to walk the dependency now:\n")
    findings = show_provenance(store, w3, "grant, re-checked today:")
    stale = [f for f in findings if f.state == fp.STALE]
    assert stale, "the grant's derived fact should be stale"
    print("\n  `stale` is not an opinion about the grant. It is: the cited")
    print("  decision still re-runs to the value this policy pinned, AND that")
    print("  decision has been replaced. Both facts, mechanically, offline.")

    # ------------------------------------------------------------ artifacts
    (PACK / "policies").mkdir(parents=True)
    (PACK / "subjects").mkdir()
    (PACK / "policies" / f"bereavement-policy.{policy_hex[:12]}.txt").write_text(
        POLICY_TEXT)
    for name, src in (("1-eligibility", (POL / "1-eligibility.wpl").read_text()),
                      ("2-timeliness", (POL / "2-timeliness.wpl").read_text()),
                      ("3-grant", grant_src),
                      ("4-proximity", prox_src)):
        h = w.blob_hash(src.encode())
        (PACK / "policies" / f"{name}.{h[:12]}.wpl").write_text(src)
    (PACK / "subjects" / f"claim.{claim_hex[:12]}.json").write_text(CLAIM_JSON)

    trust = {
        "genesis_roots": [w1],
        "actors": {
            DESK: [w.pubkey_hex(w.load_key(str(desk)))],
            AUDITOR: [w.pubkey_hex(w.load_key(str(audit)))],
            "objector@airline": [w.pubkey_hex(w.load_key(str(claimant)))],
        },
    }
    (PACK / "trust.json").write_text(
        json.dumps(trust, indent=2, sort_keys=True) + "\n")

    manifest = {
        "evidence_pack": "0",
        "title": "Bereavement refund — granted on a chain, reopened by a "
                 "consequence nobody had drawn",
        "story": "modelled on Moffatt v. Air Canada, 2024 BCCRT 149; clause 4 "
                 "and the 45-day interval are invented for this demo",
        "produced_by": "warrant demos/refund-chain/build.py",
        "profile": fp.PROFILE,
        "proposal": "proposals/WRT-010-fact-provenance.md",
        "root": w1,
        "chain": {"eligibility": w1, "timeliness": w2, "grant": w3},
        "reopening": {"relitigation": w4, "supersede": w5},
        "records": [w1, w2, w3, w4, w5],
        "ski_checks": [
            {"name": n, "check": c.blob, "term": c.doc["term"],
             "expect": c.doc["expect"], "atp": c.atp, "answer": c.result}
            for n, c in (("eligibility", c1), ("timeliness", c2),
                         ("grant", c3), ("clause-4-proximity", prox))
        ],
        "derived_facts": {
            "grant.eligible": {"from": w1, "state_after_reopening": fp.STALE},
            "grant.timely": {"from": w2, "state_after_reopening": fp.DERIVED},
        },
        "expected_verification": {
            "base": {"records": 5, "errors": 0,
                     "note": "staleness is not a §6 error; the records are "
                             "well-formed, signed and their checks re-run"},
            "profile": {"findings": 1,
                        "note": "one WARN: grant.eligible is stale, because "
                                "the decision it derives from was superseded. "
                                "The profile CLI exits 1 on any finding."},
        },
        "how_to_verify": "\n".join([
            "python3 impl/warrant.py --store demos/refund-chain/pack/.warrants verify",
            "python3 impl/fact_provenance.py --store demos/refund-chain/pack/.warrants",
        ]),
    }
    (PACK / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    shutil.rmtree(keydir)
    print(f"\n  pack written to {PACK.relative_to(ROOT)}")

    # The envelope: the whole pack as ONE file that opens as a document and
    # runs as its own archive. It deliberately does not verify itself.
    sys.path.insert(0, str(ROOT / "tools"))
    import pack_pdf                                            # noqa: E402
    envelope = HERE / "refund-chain.pdf"
    envelope.write_bytes(pack_pdf.compose(
        STORE,
        "Bereavement refund: granted on a chain, reopened by a consequence",
        "warrant evidence pack - " + fp.PROFILE,
        pack_pdf.summarize_pack(PACK)))
    print(f"  envelope written to {envelope.relative_to(ROOT)} "
          f"({envelope.stat().st_size:,} bytes)")
    print(f"    open it as a document, or: python3 "
          f"{envelope.relative_to(ROOT)} --extract DIR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
