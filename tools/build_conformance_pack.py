#!/usr/bin/env python3
"""Build `conformance/` — the pack a stranger runs against THEIR implementation.

WHY THIS EXISTS
---------------
`examples/` holds the normative vectors and `impl/warrant.py conformance` checks
them, but only from inside this checkout, and only against our Python. A third
party writing a Go or Rust or TypeScript verifier had no way to ask "does mine
agree?" without cloning this repository and running our code — while the
trademark policy already conditions the name on passing conformance. The policy
pointed at something that could not be exercised from outside.

So the vectors are compiled into a self-contained pack with expectations pinned
next to each input, plus a runner that drives ANY implementation through a
documented CLI contract (`conformance/CONTRACT.md`).

DERIVED, NOT AUTHORED
---------------------
Every expectation here is copied from `examples/` (SPEC §8, §8.2–§8.5) or from
the SPEC tables — never recomputed by running an implementation. If the pack
disagreed with `examples/`, the pack would be a second source of truth, and this
repository has watched two sources of truth drift silently more than once. The
only expectations authored here are the `parse` battery (SPEC §8.3 names those
behaviours normatively but vectors them nowhere) and the store fixtures, and
both are marked as such in the vector files.

    python3 tools/build_conformance_pack.py            # regenerate the pack
    python3 tools/build_conformance_pack.py --check     # fail if the tree drifted

`--check` is the anti-drift gate: it regenerates into a temporary directory and
compares byte-for-byte, so an edit to `examples/` that is not reflected in the
pack is a red suite rather than a stale pack a stranger downloads.
"""
import argparse
import base64
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PACK = ROOT / "conformance"
VECTORS = PACK / "vectors"

PACK_TAG = "warrant.conformance-pack@v1"
VECTOR_TAG = "warrant.conformance-vectors@v1"
# Bumped 1.0.0 -> 1.1.0 on 2026-08-01 for the integer-domain vectors, then
# 1.1.0 -> 1.2.0 for the UTF-16 member-ordering vector. A conformance pack whose
# CONTENTS change under a fixed version string is the defect this pack exists to
# detect: published older assets stay exactly as they are and keep their names.
PACK_VERSION = "1.2.0"

# Store verification is SPEC §6 — BASE grade. What settlement grade adds is
# §7/§5.1/§12: ski@v1 re-execution and a trust configuration that must fail
# closed. impl-rs verifies stores and does not settle, and the grades have to
# render that honestly rather than demote a §6 verifier for not settling.
BASE_CLASSES = ["canon", "validate", "blob-hash", "sig-message", "verify-sig",
                "parse", "verify-store"]
SETTLEMENT_CLASSES = BASE_CLASSES + ["ski-run"]

# The order a newcomer should implement the classes in, cheapest first, with one
# line on what each actually costs. This is ADVISORY and it is DATA: the runner
# reads it out of the pack when it has to tell a partial implementation what to
# do next, rather than carrying an opinion of its own that nobody can review. A
# stranger who disagrees can read it here and argue with it.
#
# The ranking is not vector count -- `verify-sig` has 28 vectors and is one
# library call plus a key test, while `validate` has 16 and CONTRACT.md says
# outright that it is not implementable without SPEC §2 and §3. It is the order
# of dependency and of unavoidable work: canon underlies everything, the two
# hash/concatenate classes cost an afternoon between them, and `verify-store`
# cannot be attempted until four other classes answer.
# The notes are one short line each, because they are printed inside a report
# that wraps at 80 columns; the full account of every class is CONTRACT.md §5,
# and duplicating it here would be a second description to keep in step.
IMPLEMENTATION_ORDER = [
    ("canon", "canonical JSON bytes + SHA-256; the foundation"),
    ("blob-hash", "SHA-256 over the raw bytes; no JSON, no crypto"),
    ("sig-message", "15 ASCII bytes + the hex-decoded WarrantID"),
    ("verify-sig", "one Ed25519 verify + the small-order key test"),
    ("parse", "is this I-JSON? your reader + RFC 7493's rules"),
    ("validate", "the SPEC §2/§3 schema; 12 MUST-REJECTs list it"),
    ("verify-store", "walk a store (§6); needs the four above first"),
    ("ski-run", "settlement: a metered ski@v1 evaluator (§3.1)"),
]

# SPEC §8: the five pinned hashes. Copied from the SPEC table, not recomputed.
SPEC8 = {
    "policy.txt": "cb3a0afe6ee6219867b9c3f9b860080918fe1042f315fe02ff62300f780beb73",
    "check.sh": "05d234bec21803c6fa007d848c1773b9fd05cfdf852d6d09542ed3b127c02b6c",
    "propose.warrant.json": "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1",
    "reject.warrant.json": "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8",
    "accept.warrant.json": "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78",
}
SKI_WARRANT_ID = "8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0"
SKI_CHECK_BLOB = "0c30960435e9c9302a6a1538682e5864f2a754475369979bd3d635543976b2ad"
SKI_RESULT_NODE = "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6"
SKI_ATP_SPENT = 20

DEMO_SEED = b"warrant-demo-seed-000000000000000"[:32]


def b64(data):
    return base64.b64encode(data).decode("ascii")


def vec(vid, polarity, spec, why, inp, expect):
    return {"id": vid, "polarity": polarity, "spec": spec, "why": why,
            "input": inp, "expect": expect}


def doc(cls, grade, source, note, vectors):
    return {"tag": VECTOR_TAG, "class": cls, "grade": grade,
            "source": source, "note": note, "vectors": vectors}


# ---------- class: canon (SPEC §4, §8, §8.4) ----------
def build_canon():
    cases = json.loads((EXAMPLES / "canon-vectors.json").read_text())["cases"]
    out = [vec(f"canon/{c['name']}", "positive", "§8.4",
               f"canonicalization battery case {c['name']}",
               {"body": c["body"]},
               {"canon_hex": c["canon_hex"], "warrant_id": c["warrant_id"]})
           for c in cases]
    # The five §8 identities. These pin WarrantIDs a canon battery never reaches:
    # they are the records the SPEC table names, and an implementation that
    # reproduces every escaping case can still get these wrong.
    for name in ("propose.warrant.json", "reject.warrant.json", "accept.warrant.json"):
        body = json.loads((EXAMPLES / name).read_text())["body"]
        out.append(vec(f"canon/spec8-{name.split('.')[0]}", "positive", "§8",
                       f"WarrantID of examples/{name}, pinned in the SPEC §8 table",
                       {"body": body}, {"warrant_id": SPEC8[name]}))
    ski = json.loads((EXAMPLES / "ski" / "accept-ski.warrant.json").read_text())["body"]
    out.append(vec("canon/spec8.2-ski-accept", "positive", "§8.2",
                   "WarrantID of the 0.2 ski@v1 accept warrant",
                   {"body": ski}, {"warrant_id": SKI_WARRANT_ID}))
    return doc("canon", "base",
               "examples/canon-vectors.json (SPEC §8.4) + the SPEC §8/§8.2 tables",
               "Every expectation is copied from the vector file or the SPEC table; "
               "none is recomputed here.", out)


# ---------- class: blob-hash (SPEC §1, §8) ----------
def build_blob_hash():
    out = []
    for name, path in (("policy.txt", EXAMPLES / "policy.txt"),
                       ("check.sh", EXAMPLES / "check.sh")):
        out.append(vec(f"blob-hash/{name}", "positive", "§8",
                       f"SHA-256 of examples/{name}, pinned in the SPEC §8 table",
                       {"bytes_base64": b64(path.read_bytes())},
                       {"hash": SPEC8[name]}))
    out.append(vec("blob-hash/ski-check.json", "positive", "§8.2",
                   "SHA-256 of the ski@v1 check blob (JCS bytes)",
                   {"bytes_base64": b64((EXAMPLES / "ski" / "check.json").read_bytes())},
                   {"hash": SKI_CHECK_BLOB}))
    out.append(vec("blob-hash/empty", "positive", "§1",
                   "the empty blob — SHA-256 of zero bytes is a real address",
                   {"bytes_base64": ""},
                   {"hash": hashlib.sha256(b"").hexdigest()}))
    return doc("blob-hash", "base", "examples/ + the SPEC §8/§8.2 tables",
               "Content addressing is SHA-256 over the raw bytes, no framing.", out)


# ---------- class: validate (SPEC §2, §3, §8.3) ----------
def build_validate():
    out = []
    for name in ("propose.warrant.json", "reject.warrant.json", "accept.warrant.json"):
        body = json.loads((EXAMPLES / name).read_text())["body"]
        out.append(vec(f"validate/spec8-{name.split('.')[0]}", "positive", "§2",
                       f"examples/{name} is schema-valid", {"body": body},
                       {"valid": True}))
    ski = json.loads((EXAMPLES / "ski" / "accept-ski.warrant.json").read_text())["body"]
    out.append(vec("validate/spec8.2-ski-accept", "positive", "§3.1",
                   "the 0.2 ski@v1 body is schema-valid", {"body": ski},
                   {"valid": True}))
    neg = json.loads((EXAMPLES / "conformance-negatives.json").read_text())
    for i, case in enumerate(neg["schema_invalid"]):
        slug = case["why"].split("(")[0].strip().replace(" ", "-").replace(",", "")
        out.append(vec(f"validate/reject-{i:02d}-{slug}", "negative", "§8.3",
                       f"MUST reject: {case['why']}", {"body": case["body"]},
                       {"valid": False}))
    out.append(vec("validate/reject-non-object", "negative", "§2",
                   "MUST reject: a body that is not a JSON object",
                   {"body": ["not", "an", "object"]}, {"valid": False}))
    # The upper boundary of §2's integer domain, as a positive. The four
    # negatives above it come from examples/conformance-negatives.json; without
    # this one they are satisfied by an implementation that rejects every large
    # integer, including the largest legal one -- a boundary tested from one side
    # is a boundary nobody has located.
    boundary = json.loads((EXAMPLES / "propose.warrant.json").read_text())["body"]
    boundary["ts"] = 9007199254740991
    out.append(vec("validate/int-domain-2^53-1-is-inside", "positive", "§2",
                   "ts = 2^53-1 is the largest integer RFC 8785 round-trips, and "
                   "is therefore valid, not the first invalid one",
                   {"body": boundary}, {"valid": True}))
    return doc("validate", "base",
               "examples/*.warrant.json + examples/conformance-negatives.json (SPEC §8.3)",
               "The negatives carry the weight: an implementation whose validate() "
               "returns true unconditionally passes every positive here.", out)


# ---------- class: sig-message (SPEC §5, §8.5) ----------
def build_sig_message():
    sv = json.loads((EXAMPLES / "signature-vectors.json").read_text())
    out = [vec(f"sig-message/{m['warrant_id'][:12]}", "positive", "§8.5",
               f"the 47 bytes a key signs for {m['why']}",
               {"warrant_id": m["warrant_id"]}, {"message_hex": m["message_hex"]})
           for m in sv["message"]]
    return doc("sig-message", "base", "examples/signature-vectors.json (SPEC §8.5)",
               "Every way of building this message wrong still reproduces all five "
               "§8 WarrantIDs correctly, so nothing else in the pack catches it.", out)


# ---------- class: verify-sig (SPEC §5, §8.3, §8.5) ----------
def build_verify_sig():
    sv = json.loads((EXAMPLES / "signature-vectors.json").read_text())
    neg = json.loads((EXAMPLES / "conformance-negatives.json").read_text())
    out = []
    for i, a in enumerate(sv["accept"]):
        out.append(vec(f"verify-sig/accept-{i:02d}", "positive", "§8.5",
                       a["why"],
                       {"warrant_id": a["warrant_id"], "key": a["key"], "sig": a["sig"]},
                       {"valid": True}))
    for i, r in enumerate(sv["reject"]):
        out.append(vec(f"verify-sig/reject-{i:02d}", "negative", "§8.5",
                       f"MUST NOT verify: {r['why']}",
                       {"warrant_id": r["warrant_id"], "key": r["key"], "sig": r["sig"]},
                       {"valid": False}))
    for i, k in enumerate(neg["weak_ed25519_pubkeys"]):
        out.append(vec(f"verify-sig/weak-key-{i:02d}", "negative", "§8.3",
                       f"MUST NOT verify under small-order / non-canonical key {k[:16]}…",
                       {"warrant_id": SPEC8["propose.warrant.json"], "key": k,
                        "sig": "00" * 64},
                       {"valid": False}))
    return doc("verify-sig", "base",
               "examples/signature-vectors.json + examples/conformance-negatives.json",
               "24 of the 28 vectors here are MUST-NOT-VERIFY. A verifier that "
               "returns true unconditionally passes the other four.", out)


# ---------- class: parse (SPEC §4 / RFC 7493 I-JSON) ----------
def build_parse():
    # AUTHORED HERE, not derived. SPEC §8.3 names these behaviours normatively
    # ("duplicate member names, trailing content after the JSON value ... a third
    # implementation MUST agree there too") but vectors them nowhere — they were
    # only exercised by two in-repo harnesses a stranger cannot run. Each case was
    # executed against all three implementations before being pinned; a case they
    # did not agree on would be a finding, not a vector.
    def case(vid, raw, ok, spec, why):
        return vec(f"parse/{vid}", "positive" if ok else "negative", spec, why,
                   {"bytes_base64": b64(raw)}, {"ok": ok})

    out = [
        case("canonical", b'{"a":1,"b":"x"}', True, "§4",
             "a canonical object parses"),
        case("whitespace", b'{\n  "a" : 1,\n  "b": "x"\n}\n', True, "§4",
             "insignificant whitespace is legal input (canonical FORM is a "
             "separate question from parse acceptance)"),
        case("unicode-escape", b'{"a":"\\u00e9"}', True, "§4",
             "a \\u escape for a BMP code point parses"),
        case("surrogate-pair", b'{"a":"\\ud83d\\ude80"}', True, "§4",
             "a valid surrogate PAIR is one astral code point, not two errors"),
        case("nested", b'{"a":{"b":[1,2,{"c":null}]},"d":true}', True, "§4",
             "nested containers, null and booleans parse"),
        case("dup-keys", b'{"a":1,"a":2}', False, "§4",
             "MUST reject: duplicate member name (RFC 7493). Stock parsers "
             "silently keep the last, which is a canonicalization attack"),
        case("dup-keys-nested", b'{"x":{"a":1,"a":2}}', False, "§4",
             "MUST reject: duplicate member name in a NESTED object"),
        case("trailing-value", b'{"a":1} {"b":2}', False, "§4",
             "MUST reject: a second JSON value after the first"),
        case("trailing-garbage", b'{"a":1}x', False, "§4",
             "MUST reject: trailing content after the JSON value"),
        case("bom", b"\xef\xbb\xbf" + b'{"a":1}', False, "§4",
             "MUST reject: a leading byte order mark. RFC 8259 says a receiver "
             "MAY ignore one — which is exactly the problem for a "
             "content-addressed format"),
        case("lone-high-surrogate", b'{"a":"\\ud800"}', False, "§4",
             "MUST reject: unpaired high surrogate (invalid I-JSON). Python keeps "
             "the surrogate code point, Go substitutes U+FFFD: same bytes, "
             "different strings, different WarrantID"),
        case("lone-low-surrogate", b'{"a":"\\udc00"}', False, "§4",
             "MUST reject: unpaired low surrogate"),
        case("nan", b'{"a":NaN}', False, "§4",
             "MUST reject: NaN is not JSON (Python's stock parser accepts it)"),
        case("infinity", b'{"a":Infinity}', False, "§4",
             "MUST reject: Infinity is not JSON"),
        case("invalid-utf8", b'{"a":"\xff\xfe"}', False, "§4",
             "MUST reject: invalid UTF-8 in a string"),
        case("raw-control", b'{"a":"x\x01y"}', False, "§4",
             "MUST reject: an unescaped control character inside a string"),
        case("unterminated", b'{"a":', False, "§4",
             "MUST reject: truncated input"),
        case("leading-zero", b'{"a":01}', False, "§4",
             "MUST reject: a number with a leading zero"),
        case("single-quotes", b"{'a':1}", False, "§4",
             "MUST reject: single-quoted keys are not JSON"),
        case("trailing-comma", b'{"a":1,}', False, "§4",
             "MUST reject: a trailing comma"),
    ]
    return doc("parse", "base", "authored for this pack (see note)",
               "SPEC §8.3 names these behaviours normatively but vectors them "
               "nowhere; before this pack they were only exercised by in-repo "
               "harnesses a third party cannot run. Each case was executed "
               "against all three reference implementations before being pinned. "
               "DELIBERATELY NOT VECTORED: whether the parse layer itself rejects "
               "a document whose top level is not an object. The three reference "
               "implementations enforce that rule at three different layers (the "
               "decoder, the envelope-shape check, the body validator) and agree "
               "on the observable outcome — one error — so pinning the layer "
               "would test an implementation's internal structure rather than "
               "the format. `validate/reject-non-object` covers the part the "
               "spec does fix.", out)


# ---------- class: ski-run (SPEC §3.1, §8.2 — settlement grade) ----------
def build_ski_run():
    ski = EXAMPLES / "ski"
    blobs = {p.name: b64(p.read_bytes()) for p in sorted(ski.glob("*.bin"))}
    out = [vec("ski-run/spec8.2", "positive", "§8.2",
               "TV-10: C1[λxy.x] S K reduces to S within 20 ATP. A verifier that "
               "reports a verdict without executing the term is the defect SPEC "
               "§6(7) forbids",
               {"check_base64": b64((ski / "check.json").read_bytes()),
                "blobs_base64": blobs},
               {"verdict": "pass", "result_node_hash": SKI_RESULT_NODE,
                "atp_spent": SKI_ATP_SPENT})]
    return doc("ski-run", "settlement", "examples/ski/ (SPEC §8.2)",
               "Settlement grade only: SPEC §7 escalates an unexecuted ski@v1 "
               "reason to an ERR, so an implementation that cannot re-execute "
               "cannot settle. Base grade candidates report this UNRUN.", out)


# ---------- class: verify-store (SPEC §6 — settlement grade) ----------
def _demo_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(DEMO_SEED)


def _canon(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _wid(body):
    return hashlib.sha256(_canon(body)).hexdigest()


def _envelope(body, sk):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: F401
    from cryptography.hazmat.primitives import serialization
    wid = _wid(body)
    pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    sig = sk.sign(b"warrant-sig-v1:" + bytes.fromhex(wid)).hex()
    return wid, {"body": body, "sigs": [{"actor": body["actor"]["id"],
                                         "key": pub, "sig": sig}]}


def _write_store(dest, records, blobs):
    (dest / "records").mkdir(parents=True)
    (dest / "blobs").mkdir(parents=True)
    for name, text in records.items():
        (dest / "records" / name).write_text(text)
    for name, data in blobs.items():
        (dest / "blobs" / name).write_bytes(data)


def build_verify_store():
    """Build the store fixtures on disk and return the vector document.

    Deterministic: the demo seed of SPEC §8, fixed timestamps, Ed25519 signatures
    (which are deterministic), and blob contents fixed here. Re-running produces
    byte-identical fixtures, which is what makes `--check` a drift gate.
    """
    sk = _demo_key()
    policy = (EXAMPLES / "policy.txt").read_bytes()
    check = (EXAMPLES / "check.sh").read_bytes()
    subject = b"conformance fixture: the change under decision\n"
    transcript = b"conformance fixture: check transcript\nexit 0\n"

    def h(b):
        return hashlib.sha256(b).hexdigest()

    blobs = {h(policy): policy, h(check): check, h(subject): subject,
             h(transcript): transcript}

    propose = {
        "warrant": "0.1", "decision": "propose",
        "subject": {"hash": h(subject), "note": "conformance fixture"},
        "under": [h(policy)],
        "because": [{"kind": "prose", "text": "a fixture store that verifies clean"}],
        "evidence": [h(subject)], "actor": {"id": "fixture@warrant.example"},
        "prior": [], "ts": 1751673600,
    }
    pid, penv = _envelope(propose, sk)
    accept = {
        "warrant": "0.1", "decision": "accept",
        "subject": {"hash": h(subject), "note": "conformance fixture"},
        "under": [h(policy)],
        "because": [{"kind": "check", "runtime": "cmd@v1", "check": h(check),
                     "verdict": "pass", "transcript": h(transcript)}],
        "evidence": [h(transcript)], "actor": {"id": "fixture@warrant.example"},
        "prior": [pid], "ts": 1751677200,
    }
    aid, aenv = _envelope(accept, sk)
    records = {f"{pid}.json": json.dumps(penv, indent=2, sort_keys=True) + "\n",
               f"{aid}.json": json.dumps(aenv, indent=2, sort_keys=True) + "\n"}

    stores = VECTORS / "stores"
    if stores.exists():
        shutil.rmtree(stores)

    def mutate_none(recs, blb):
        return recs, blb

    def mutate_ts(recs, blb):
        env = json.loads(recs[f"{aid}.json"])
        env["body"]["ts"] += 1                     # WarrantID no longer recomputes
        recs[f"{aid}.json"] = json.dumps(env, indent=2, sort_keys=True) + "\n"
        return recs, blb

    def mutate_sig(recs, blb):
        env = json.loads(recs[f"{pid}.json"])
        s = env["sigs"][0]["sig"]
        env["sigs"][0]["sig"] = ("0" if s[0] != "0" else "1") + s[1:]
        recs[f"{pid}.json"] = json.dumps(env, indent=2, sort_keys=True) + "\n"
        return recs, blb

    def mutate_blob(recs, blb):
        blb[h(policy)] = b"Refunds are ALWAYS granted retroactively.\n"
        return recs, blb

    def mutate_prior(recs, blb):
        del recs[f"{pid}.json"]
        return recs, blb

    def mutate_malformed(recs, blb):
        recs[f"{pid}.json"] = "{not json"
        return recs, blb

    fixtures = [
        ("clean", mutate_none, "positive", 0,
         "a store with nothing wrong: every reference resolves, both signatures "
         "verify, both WarrantIDs recompute"),
        ("tampered-ts", mutate_ts, "negative", 1,
         "MUST report an error: one byte of the body changed, so the record no "
         "longer hashes to the WarrantID it is filed under (§6(2))"),
        ("tampered-sig", mutate_sig, "negative", 1,
         "MUST report an error: the only signature by body.actor.id is invalid "
         "(§6(3))"),
        ("swapped-blob", mutate_blob, "negative", 1,
         "MUST report an error: the POLICY blob cited by `under` was replaced "
         "wholesale and still sits at the original address. Both shipped "
         "implementations once reported this store clean (2026-07-29)"),
        ("missing-prior", mutate_prior, "negative", 1,
         "MUST report an error: a `prior` edge points at a record the store does "
         "not hold (§6(4))"),
        ("malformed-record", mutate_malformed, "negative", 1,
         "MUST report an error: a record file that is not JSON at all"),
    ]
    out = []
    for name, mutate, polarity, min_errors, why in fixtures:
        recs, blb = mutate(dict(records), dict(blobs))
        _write_store(stores / name, recs, blb)
        expect = ({"errors": 0} if polarity == "positive"
                  else {"errors": {"at_least": min_errors}})
        out.append(vec(f"verify-store/{name}", polarity, "§6", why,
                       {"store_dir": f"stores/{name}", "grade": "base"}, expect))
    return doc("verify-store", "base", "fixtures generated for this pack",
               "AUTHORED for this pack, deterministically, from the SPEC §8 demo "
               "seed. Only the ERROR count is pinned: SPEC §6 fixes which "
               "conditions are errors, but not how many warnings an "
               "implementation chooses to emit, and pinning a number the spec "
               "does not fix would test our taste rather than the format. "
               "The mutations are the defects this repository actually shipped.",
               out)


# ---------- class: verify-store, settlement grade (SPEC §12.3) ----------
def build_verify_store_settlement():
    """Settlement grade is where a trust configuration must FAIL CLOSED.

    SPEC §12.3 is unusually crisp — "MUST report exactly one ERR with subject
    `settlement`, MUST NOT continue into a partial base-grade verification, and
    MUST NOT silently fall open" — so this is one of the few settlement surfaces
    where an exact error count is normative rather than a matter of taste.
    """
    trust = VECTORS / "trust"
    if trust.exists():
        shutil.rmtree(trust)
    trust.mkdir(parents=True)
    (trust / "malformed.json").write_text("{not json\n")
    (trust / "empty.json").write_text('{"genesis_roots":[]}\n')
    out = [
        vec("verify-store/settlement-trust-malformed", "negative", "§12.3",
            "MUST report exactly one ERR: a settlement verification was requested "
            "with an unparseable trust configuration. Falling open to 'no trust "
            "configured' would report a verification that did not happen",
            {"store_dir": "stores/clean", "grade": "settlement",
             "trust_config": "trust/malformed.json"},
            {"errors": 1}),
        vec("verify-store/settlement-trust-missing", "negative", "§12.3",
            "MUST report exactly one ERR: the trust configuration file does not "
            "exist. A requested settlement verification that could not construct "
            "its trust did not happen",
            {"store_dir": "stores/clean", "grade": "settlement",
             "trust_config": "trust/does-not-exist.json"},
            {"errors": 1}),
        vec("verify-store/settlement-trust-empty", "positive", "§9",
            "a valid trust configuration naming no genesis root: the store still "
            "verifies with zero errors; the roots are simply not settlement-active",
            {"store_dir": "stores/clean", "grade": "settlement",
             "trust_config": "trust/empty.json"},
            {"errors": 0}),
    ]
    return doc("verify-store", "settlement", "fixtures generated for this pack",
               "Settlement grade adds the fail-closed trust surface of SPEC §12.3. "
               "A base-grade candidate answers these `unsupported`; a candidate "
               "that claims settlement and silently ignores the requested grade "
               "returns zero errors here and fails.", out)


BUILDERS = [
    ("canon.json", build_canon),
    ("blob-hash.json", build_blob_hash),
    ("validate.json", build_validate),
    ("sig-message.json", build_sig_message),
    ("verify-sig.json", build_verify_sig),
    ("parse.json", build_parse),
    ("verify-store.json", build_verify_store),
    ("verify-store-settlement.json", build_verify_store_settlement),
    ("ski-run.json", build_ski_run),
]


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                    encoding="utf-8")


def build(pack_root):
    vectors = pack_root / "vectors"
    vectors.mkdir(parents=True, exist_ok=True)
    global VECTORS
    saved, VECTORS = VECTORS, vectors
    try:
        index_files, counts = [], {}
        for fname, builder in BUILDERS:
            payload = builder()
            write_json(vectors / fname, payload)
            index_files.append({"class": payload["class"], "grade": payload["grade"],
                                "file": fname, "vectors": len(payload["vectors"])})
            counts[fname] = len(payload["vectors"])
        # A class that exists in the pack but not in the order would be silently
        # missing from the "what do I implement next" advice — the shape of
        # defect this repository has shipped most often. Fail the build instead.
        ordered = [c for c, _ in IMPLEMENTATION_ORDER]
        present = {e["class"] for e in index_files}
        if present - set(ordered):
            raise SystemExit(
                "IMPLEMENTATION_ORDER does not cover every class in the pack: "
                f"{sorted(present - set(ordered))}")
        if set(ordered) - present:
            raise SystemExit(
                "IMPLEMENTATION_ORDER names classes the pack does not have: "
                f"{sorted(set(ordered) - present)}")
        index = {
            "tag": PACK_TAG,
            "pack_version": PACK_VERSION,
            "protocol": "warrant-conformance/1",
            "contract": "CONTRACT.md",
            "spec": "SPEC.md — Warrant 0.6.0 (sections §2 §3 §4 §5 §6 §8)",
            "grades": {"base": BASE_CLASSES, "settlement": SETTLEMENT_CLASSES},
            # Advisory, cheapest first. The runner reads this to tell a partial
            # candidate what to write next; it fixes nothing normative.
            "implementation_order": [{"class": c, "needs": n}
                                     for c, n in IMPLEMENTATION_ORDER],
            "files": index_files,
            "total_vectors": sum(counts.values()),
        }
        write_json(vectors / "index.json", index)
        return index
    finally:
        VECTORS = saved


MANIFEST_NAME = "MANIFEST.sha256"


def manifest_lines(pack_root):
    lines = []
    for path in sorted(pack_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(pack_root).as_posix()
        if rel == MANIFEST_NAME or "__pycache__" in rel:
            continue
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
    return lines


def write_manifest(pack_root):
    text = "\n".join(manifest_lines(pack_root)) + "\n"
    (pack_root / MANIFEST_NAME).write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pack_digest(pack_root):
    return hashlib.sha256((pack_root / MANIFEST_NAME).read_bytes()).hexdigest()


SPEC_PIN_LABEL = "conformance pack"


def check_spec_pin(digest):
    """The digest published in SPEC §8.6 must be the digest of the built pack.

    A hash written into prose is a number nobody counts. This repository has
    watched that go wrong often enough that any figure in a document is checked
    by a tool or it is not trusted: a stranger comparing the tarball against a
    stale SPEC line would conclude the artifact was tampered with, and a stranger
    comparing it against a SPEC line updated by hand to match a pack nobody
    rebuilt would conclude nothing at all.
    """
    spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    pinned = [line for line in spec.splitlines()
              if SPEC_PIN_LABEL in line and "MANIFEST.sha256" in line]
    if not pinned:
        return [f"SPEC.md has no §8.6 pin line for the {SPEC_PIN_LABEL}"]
    problems = []
    for line in pinned:
        if digest not in line:
            problems.append(
                f"SPEC.md §8.6 pins a different digest than the built pack\n"
                f"    SPEC.md: {line.strip()[:110]}\n"
                f"    built  : {digest}")
    return problems


def main():
    ap = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="regenerate into a temp dir and fail on any difference")
    ap.add_argument("--print-digest", action="store_true",
                    help="print the pack digest (SHA-256 of MANIFEST.sha256)")
    ap.add_argument("--tarball", metavar="DIR",
                    help="also write warrant-conformance-<version>.tar.gz into "
                         "DIR — the distribution artifact for GitHub Releases")
    args = ap.parse_args()

    if args.print_digest:
        print(pack_digest(PACK))
        return 0

    if args.check:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "conformance"
            # Files that are hand-written rather than generated are copied in, so
            # the manifest covers the whole pack in both trees.
            tmp.mkdir()
            for name in ("README.md", "CONTRACT.md", "run.py"):
                if (PACK / name).exists():
                    shutil.copy2(PACK / name, tmp / name)
            if (PACK / "stub").is_dir():
                shutil.copytree(PACK / "stub", tmp / "stub",
                                ignore=shutil.ignore_patterns("__pycache__"))
            build(tmp)
            write_manifest(tmp)
            want = (tmp / MANIFEST_NAME).read_text()
            got = (PACK / MANIFEST_NAME).read_text() if (PACK / MANIFEST_NAME).exists() else ""
            if want != got:
                print("CONFORMANCE PACK: DRIFT — the committed pack is not what "
                      "examples/ would generate today.")
                want_map = dict(reversed(l.split("  ", 1)) for l in want.strip().splitlines())
                got_map = dict(reversed(l.split("  ", 1)) for l in got.strip().splitlines())
                for name in sorted(set(want_map) | set(got_map)):
                    if want_map.get(name) != got_map.get(name):
                        print(f"  {name}: committed={got_map.get(name, 'ABSENT')[:12]} "
                              f"regenerated={want_map.get(name, 'ABSENT')[:12]}")
                print("  fix:  python3 tools/build_conformance_pack.py")
                return 1
        pin_problems = check_spec_pin(pack_digest(PACK))
        if pin_problems:
            print("CONFORMANCE PACK: the SPEC §8.6 pin does not match the pack.")
            for p in pin_problems:
                print(f"  {p}")
            print("  A third party checks the tarball against that line; a stale "
                  "one is worse\n  than no line at all.")
            return 1
        print(f"CONFORMANCE PACK: IN SYNC with examples/, and SPEC §8.6 pins it "
              f"(digest {pack_digest(PACK)[:16]}…)")
        return 0

    index = build(PACK)
    digest = write_manifest(PACK)
    print(f"conformance pack {PACK_VERSION}: {index['total_vectors']} vectors "
          f"in {len(index['files'])} classes")
    print(f"pack digest (SHA-256 of {MANIFEST_NAME}): {digest}")
    if args.tarball:
        print(f"tarball: {build_tarball(Path(args.tarball))}")
    return 0


def build_tarball(dest_dir):
    """The distribution artifact: one file, curl-able, no clone, no install.

    Deterministic — fixed mtimes, uid/gid 0, sorted entries — so the same pack
    produces the same bytes on any machine. A conformance artifact whose hash
    changes with the wall clock cannot be pinned by hash, and pinning it by hash
    is the whole point of publishing the digest in the SPEC.
    """
    import gzip
    import tarfile
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"warrant-conformance-{PACK_VERSION}.tar.gz"
    members = sorted(p for p in PACK.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    raw = dest_dir / f".{out.name}.tar"
    with tarfile.open(raw, "w") as tar:
        for path in members:
            info = tar.gettarinfo(str(path),
                                  arcname=f"warrant-conformance-{PACK_VERSION}/"
                                          f"{path.relative_to(PACK).as_posix()}")
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if path.suffix == ".py" else 0o644
            with open(path, "rb") as fh:
                tar.addfile(info, fh)
    data = raw.read_bytes()
    raw.unlink()
    with open(out, "wb") as fh:
        # mtime=0 in the gzip header too, or the archive differs run to run.
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz:
            gz.write(data)
    return f"{out}  ({out.stat().st_size} bytes, sha256 " \
           f"{hashlib.sha256(out.read_bytes()).hexdigest()[:16]}…)"


if __name__ == "__main__":
    sys.exit(main())
