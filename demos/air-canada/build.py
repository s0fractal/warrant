#!/usr/bin/env python3
"""Build the Air-Canada demo evidence pack — deterministically, through the real
libraries, so every hash, signature and ATP figure is produced by the code a
verifier will re-run (nothing is hand-computed).

Story (Moffatt v. Air Canada, 2024 BCCRT 149): an airline chatbot told a
passenger a bereavement fare COULD be claimed retroactively. It could not. The
tribunal held the airline liable. Air Canada had no record proving what policy
was in force or that the action was authorized against it.

This pack is the record they would have had under a sealed deployment:
  propose  chatbot@aircanada    — "grant a retroactive bereavement refund"
  reject   policy-guard@aircanada — refused, BECAUSE a ski@v1 check proves the
           pinned policy predicate `retroactive_bereavement_refund_permitted`
           evaluates to Church-FALSE ("not permitted").

Honest scope (per the stack's own caveat): the ski@v1 check does NOT reproduce
the LLM's reasoning. It reproduces a DETERMINISTIC POLICY PREDICATE around the
decision — pinned by hash, budget-bounded, and re-executable by anyone offline.
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPL = HERE.parent.parent / "impl"
sys.path.insert(0, str(IMPL))

import policy_lang as pl          # noqa: E402  (WPL v1 -> ski@v1 compiler)
import sigma_glyph as sg          # noqa: E402  (bundled Book I oracle)
import ski_policy as sp           # noqa: E402  (the hand-built predecessor)
import warrant as w               # noqa: E402  (reference implementation)

PACK = HERE / "pack"
STORE = PACK / ".warrants"

# Deterministic demo identities (fixed 32-byte Ed25519 seeds -> stable hashes).
CHATBOT_SEED = "a1" * 32
GUARD_SEED = "b2" * 32
T0 = 1708300800   # 2024-02-19, the week of the BCCRT decision
T1 = T0 + 3600

POLICY_TEXT = (
    "AIR CANADA — BEREAVEMENT TRAVEL POLICY (excerpt, pinned by hash)\n"
    "\n"
    "1. Bereavement fares are a discount on published fares for travel due to\n"
    "   the death or imminent death of an immediate family member.\n"
    "2. A bereavement discount MUST be requested BEFORE travel. It CANNOT be\n"
    "   claimed retroactively for tickets already purchased or flown.\n"
    "3. Any refund request that relies on retroactive application of the\n"
    "   bereavement discount is OUTSIDE policy and MUST be refused.\n"
)

SUBJECT_JSON = (
    '{"action":"grant_refund",'
    '"basis":"bereavement_discount",'
    '"retroactive":true,'
    '"passenger_claim":"chatbot said I could apply within 90 days of travel",'
    '"amount_cad":650.88}'
)


POLICY_SOURCE = HERE / "policy.wpl"


def build_ski_check(store):
    """Pin the policy predicate as a re-executable Σ-GLYPH Book I term.

    The rule is written in WPL (`policy.wpl`, readable by anyone who has never
    heard of a combinator) and compiled to a closed Book I term:

        check within_window && !retroactive

    over the facts of this request { within_window: true, retroactive: true } —
    the passenger asked to apply the discount retroactively. It reduces to
    Church-FALSE, "not permitted". Anyone re-runs the term and gets the same
    verdict; anyone can also re-run the COMPILER over `policy.wpl` and get the
    same term, which is why the source is filed as evidence below.

    This used to be a hand-built `ski_policy` expression. The compiler emits a
    byte-identical check — same term, same expect, same 17 ATP — and the
    assertion below keeps it that way, so no record in the shipped pack had to
    be re-signed and the README's figures still hold.

    Returns (check_hex, term_hex, expect_hex, atp, source_hex)."""
    check = pl.compile_file(POLICY_SOURCE, store.put_blob)
    assert check.result is False, "policy must deny a retroactive request"

    legacy = sp.compile_check(
        sp.And(sp.Fact("within_window", True),
               sp.Not(sp.Fact("retroactive", True))),
        store.put_blob)
    assert check.doc == legacy.doc, (
        f"WPL compilation drifted from the pinned hand-built check: "
        f"{check.doc} != {legacy.doc}")

    source_hex = store.put_blob(POLICY_SOURCE.read_bytes())
    d = check.doc
    return check.blob, d["term"], d["expect"], d["atp"], source_hex


class Args:
    """Minimal shim matching warrant.file_warrant's expected attributes."""
    def __init__(self, **kw):
        defaults = dict(under=[], evidence=[], prior=[], reason=None, check=None,
                        runtime="cmd@v1", verdict="pass", transcript=None,
                        relitigates=None, ts=None)
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def main():
    if PACK.exists():
        shutil.rmtree(PACK)
    store = w.Store(str(STORE))
    store.init()

    # Fixed demo keys, written to a throwaway temp dir OUTSIDE the pack: a
    # verifier never needs private keys (only trust.json's public keys), and the
    # seeds are hard-coded here so the pack is fully reproducible from source.
    keydir = Path(tempfile.mkdtemp(prefix="warrant-demo-keys-"))
    chatbot_key = keydir / "chatbot.key"
    guard_key = keydir / "guard.key"
    chatbot_key.write_text(CHATBOT_SEED + "\n")
    guard_key.write_text(GUARD_SEED + "\n")

    # Pin the policy and the requested action as content-addressed blobs.
    policy_hex = store.put_blob(POLICY_TEXT.encode())
    subject_hex = store.put_blob(SUBJECT_JSON.encode())

    # Pin the policy predicate as a re-executable ski@v1 check.
    check_hex, term_hex, expect_hex, atp, source_hex = build_ski_check(store)

    # 1) chatbot proposes the (out-of-policy) refund.
    propose_args = Args(under=[policy_hex], reason=["passenger requested a refund"],
                        actor="chatbot@aircanada", key=str(chatbot_key), ts=T0)
    w_propose = w.file_warrant(store, "propose", subject_hex, propose_args,
                               note="retroactive bereavement refund request")

    # 2) policy-guard rejects it, proving the policy value with a ski@v1 check.
    reject_args = Args(under=[policy_hex], prior=[w_propose],
                       reason=["policy clause 2: bereavement discount cannot be "
                               "claimed retroactively"],
                       check=check_hex, runtime="ski@v1", verdict="pass",
                       actor="policy-guard@aircanada", key=str(guard_key), ts=T1)
    w_reject = w.file_warrant(store, "reject", subject_hex, reject_args,
                              note="retroactive bereavement refund request")

    # Human-readable mirrors (labelled by blob hash) for the curious reader.
    (PACK / "policies").mkdir()
    (PACK / "subjects").mkdir()
    (PACK / "policies" / f"bereavement-policy.{policy_hex[:12]}.txt").write_text(POLICY_TEXT)
    (PACK / "policies" / f"check-source.{source_hex[:12]}.wpl").write_text(
        POLICY_SOURCE.read_text())
    (PACK / "subjects" / f"refund-request.{subject_hex[:12]}.json").write_text(SUBJECT_JSON + "\n")

    # trust.json: bind actor <-> key so `verify --settlement` reports bound
    # signatures instead of "binding unverified". Genesis root = the propose.
    chatbot_pub = w.pubkey_hex(w.load_key(str(chatbot_key)))
    guard_pub = w.pubkey_hex(w.load_key(str(guard_key)))
    trust = {
        "genesis_roots": [w_propose],
        "actors": {
            "chatbot@aircanada": [chatbot_pub],
            "policy-guard@aircanada": [guard_pub],
        },
    }
    import json
    (PACK / "trust.json").write_text(json.dumps(trust, indent=2, sort_keys=True) + "\n")

    manifest = {
        "evidence_pack": "0",
        "title": "Air Canada — retroactive bereavement refund, refused",
        "story": "Moffatt v. Air Canada, 2024 BCCRT 149",
        "produced_by": "warrant demos/air-canada/build.py",
        "root": w_propose,
        "decision": w_reject,
        "records": [w_propose, w_reject],
        "ski_checks": [
            {"check": check_hex, "term": term_hex, "expect": expect_hex,
             "atp": atp, "means": "policy predicate (within_window AND NOT "
             "retroactive) = FALSE for this request (retroactive=true) -> not permitted",
             "source": source_hex, "source_language": pl.LANG_VERSION,
             "recompile": "python3 impl/policy_lang.py compile demos/air-canada/policy.wpl"}
        ],
        "expected_verification": {"errors": 0},
        "how_to_verify": "warrant --store .warrants verify",
    }
    (PACK / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    shutil.rmtree(keydir)   # private seeds are not shipped; regenerated on rebuild

    print("\n--- pack built ---")
    print("policy   blob :", policy_hex)
    print("subject  blob :", subject_hex)
    print("ski check    :", check_hex, f"(term {term_hex[:12]} -> FALSE, {atp} ATP)")
    print("propose  wid  :", w_propose)
    print("reject   wid  :", w_reject)


if __name__ == "__main__":
    main()
