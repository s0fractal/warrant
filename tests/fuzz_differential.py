#!/usr/bin/env python3
"""Randomized differential fuzzer: Python vs Go MUST agree (SPEC line 5).

Where tests/differential.py and tests/negative.py pin a *curated* battery, this
generates thousands of adversarial inputs and asserts the two implementations
never diverge. Three loops, each with a crisp invariant:

  A. canon  — random integer-only bodies with adversarial strings (control
     bytes, <>&, astral, combining marks, quotes, 200-codepoint boundaries) and
     shuffled key order: `canon` MUST return byte-identical {warrant_id,
     canon_hex} on both. (Catches JCS escaping / sort / width splits.)
  B. verify — a valid store, one record mutated in an integer-safe, valid-JSON
     way (signatures, unknown fields, bad hashes, notes, decisions, integer ts
     edges, dangling refs, runtimes): both MUST report the EXACT same
     (errors, warnings). (Catches validation / verification splits.)
  C. reject — the nasty non-integer/dup-key/trailing-content space (float ts,
     string ts, duplicate member names): a body one node accepts and another
     rejects is the P0 consensus split, so both MUST reject (errors > 0).

Deterministic: seed the RNG (default 1337) so a divergence is reproducible.

Usage:  python3 tests/fuzz_differential.py [--iters N] [--seed S]
Env:    WARRANT_GO=path/to/warrant-go  (default: ./impl-go/warrant-go)
Exit nonzero on any divergence, printing the seed+iteration to reproduce.
"""
import argparse
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, os.path.join(ROOT, "impl", "warrant.py")]
GO = os.environ.get("WARRANT_GO", os.path.join(ROOT, "impl-go", "warrant-go"))

spec = importlib.util.spec_from_file_location("W", os.path.join(ROOT, "impl", "warrant.py"))
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

ADV = [chr(0), chr(8), chr(9), chr(10), chr(12), chr(13), chr(27), chr(0x7F), chr(0x9F),
       "<", ">", "&", '"', "\\", "/", " ", " ", "б", "\U0001F680",
       "\U0001F525", "́", "é", "ï", " ", "-", ":"]
HEXCH = "0123456789abcdef"


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def counts(out):
    m = re.search(r"(\d+) records, (\d+) errors, (\d+) warnings", out)
    return (int(m.group(2)), int(m.group(3))) if m else None


def rand_hex(rng):
    return "".join(rng.choice(HEXCH) for _ in range(64))


def adv_string(rng, maxlen):
    n = rng.randint(0, maxlen)
    return "".join(rng.choice(ADV + [chr(rng.randint(32, 126))]) for _ in range(n))


def shuffled_json(obj, rng):
    """Serialize with object keys emitted in RANDOM order, so `canon`'s sort is
    actually exercised (json.dumps default would already be insertion order)."""
    if isinstance(obj, dict):
        items = list(obj.items())
        rng.shuffle(items)
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + shuffled_json(v, rng)
                              for k, v in items) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(shuffled_json(v, rng) for v in obj) + "]"
    return json.dumps(obj, ensure_ascii=False)


def rand_body(rng):
    reasons = []
    for _ in range(rng.randint(0, 3)):
        if rng.random() < 0.5:
            reasons.append({"kind": "prose", "text": adv_string(rng, 40)})
        else:
            r = {"kind": "check", "check": rand_hex(rng),
                 "runtime": rng.choice(["cmd@v1", "ski@v1"]),
                 "verdict": rng.choice(["pass", "fail"])}
            if rng.random() < 0.5:
                r["transcript"] = rand_hex(rng)
            reasons.append(r)
    subj = {"hash": rand_hex(rng)}
    if rng.random() < 0.8:
        subj["note"] = adv_string(rng, rng.choice([5, 30, 199, 200, 201]))
    return {
        "warrant": rng.choice(["0.1", "0.2"]),
        "decision": rng.choice(["propose", "accept", "reject", "supersede"]),
        "subject": subj,
        "under": [rand_hex(rng) for _ in range(rng.randint(1, 3))],
        "because": reasons,
        "evidence": [rand_hex(rng) for _ in range(rng.randint(0, 2))],
        "actor": {"id": adv_string(rng, 20)},
        "prior": [rand_hex(rng) for _ in range(rng.randint(0, 2))],
        "ts": rng.randint(0, 2**63 - 1),
    }


def build_base_store(tmp):
    store = os.path.join(tmp, "base")
    key = os.path.join(tmp, "k.key")
    sh(PY + ["--store", store, "init"])
    sh(PY + ["--store", store, "keygen", "--out", key])
    pol, sub = os.path.join(tmp, "p"), os.path.join(tmp, "s")
    open(pol, "w").write("policy\n")
    open(sub, "w").write("subject\n")
    _, u, _ = sh(PY + ["--store", store, "blob", "add", pol]).stdout, None, None
    u = sh(PY + ["--store", store, "blob", "add", pol]).stdout.strip()
    subj = sh(PY + ["--store", store, "blob", "add", sub]).stdout.strip()
    w1 = sh(PY + ["--store", store, "accept", "--subject", subj, "--note", "base",
                  "--under", u, "--reason", "ok", "--actor", "a@b", "--key", key]).stdout.strip()
    w2 = sh(PY + ["--store", store, "supersede", w1, "--under", u,
                  "--reason", "sup", "--actor", "a@b", "--key", key]).stdout.strip()
    return store, key, w1, w2


SMALL_ORDER = "0000000000000000000000000000000000000000000000000000000000000000"


def verify_both(store):
    po = sh(PY + ["--store", store, "verify"]).stdout
    go = sh([GO, "verify", store]).stdout
    return counts(po.splitlines()[-1] if po.splitlines() else ""), \
        counts(go.splitlines()[-1] if go.splitlines() else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=150)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    fails = []

    with tempfile.TemporaryDirectory() as tmp:
        # ---- Loop A: canon byte-agreement ----
        bodyfile = os.path.join(tmp, "body.json")
        for i in range(args.iters):
            body = rand_body(rng)
            open(bodyfile, "w").write(shuffled_json(body, rng))
            p = sh(PY + ["canon", bodyfile])
            g = sh([GO, "canon", bodyfile])
            try:
                pj, gj = json.loads(p.stdout), json.loads(g.stdout)
            except Exception:
                fails.append(("A-canon-crash", i, p.stdout[:80], g.stdout[:80]))
                continue
            if pj != gj:
                fails.append(("A-canon", i, pj, gj))

        # ---- Loops B & C: verify-agreement over mutations ----
        base, key, w1, w2 = build_base_store(tmp)
        rec = os.path.join(base, "records", w1 + ".json")

        def fresh():
            d = os.path.join(tmp, "case")
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(base, d)
            return d, os.path.join(d, "records", w1 + ".json")

        def reid(store, path):
            env = json.load(open(path))
            nid = W.warrant_id(env["body"])
            os.rename(path, os.path.join(store, "records", nid + ".json"))

        # integer-safe, valid-JSON mutations -> EXACT (errs,warns) agreement
        def m_junk_sig(env):
            env["sigs"].append({"actor": "z@z", "key": rng.choice(
                [SMALL_ORDER, rand_hex(rng)]), "sig": "00" * 64})
        def m_tamper_sig(env):
            s = env["sigs"][0]["sig"]
            env["sigs"][0]["sig"] = ("1" if s[0] == "0" else "0") + s[1:]
        def m_forge_actor(env):
            env["sigs"][0]["actor"] = "mallory@evil"
        def m_extra_top(env):
            env["body"]["_x"] = rng.randint(0, 9)
        def m_extra_subject(env):
            env["body"]["subject"]["_x"] = 1
        def m_extra_reason(env):
            env["body"]["because"].append({"kind": "prose", "text": "t", "_x": 1})
        def m_badhash(env):
            env["body"]["subject"]["hash"] = rng.choice(["zz", "a" * 63, "A" * 64])
        def m_note(env):
            env["body"]["subject"]["note"] = adv_string(rng, rng.choice([199, 200, 201, 250]))
        def m_decision(env):
            env["body"]["decision"] = rng.choice(["propose", "accept", "reject", "supersede"])
        def m_empty_because(env):
            env["body"]["because"] = []
        def m_ts_int_edge(env):
            env["body"]["ts"] = rng.choice([0, -1, 2**63 - 1, 2**63, 2**64])
        def m_dangling(env):
            env["body"]["evidence"] = [rand_hex(rng)]
        def m_runtime(env):
            env["body"]["because"] = [{"kind": "check", "check": rand_hex(rng),
                                       "runtime": "wasm@v1", "verdict": "pass"}]
        def m_scalar_cosig(env):
            # a non-object co-sig entry alongside the valid actor signature: both
            # impls MUST exclude it and keep the record valid (0 errors), never
            # crash on it (Gemini 3.1 Pro audit — Python .get() on a str sig).
            env["sigs"].append(rng.choice(["x", 7, None, []]))
        int_safe = [m_junk_sig, m_tamper_sig, m_forge_actor, m_extra_top, m_extra_subject,
                    m_extra_reason, m_badhash, m_note, m_decision, m_empty_because,
                    m_ts_int_edge, m_dangling, m_runtime, m_scalar_cosig]

        for i in range(args.iters):
            store, path = fresh()
            env = json.load(open(path))
            mut = rng.choice(int_safe)
            mutated_body = mut in (m_extra_top, m_extra_subject, m_extra_reason, m_badhash,
                                   m_note, m_decision, m_empty_because, m_ts_int_edge,
                                   m_dangling, m_runtime)
            mut(env)
            json.dump(env, open(path, "w"), indent=2, sort_keys=True)
            if mutated_body and rng.random() < 0.5:
                reid(store, path)          # make id match again -> exercise downstream
            cp, cg = verify_both(store)
            if cp is None or cg is None or cp != cg:
                fails.append(("B-verify", i, mut.__name__, cp, cg))

        # ---- Loop C: dirty (non-integer / dup-key / trailing) -> both MUST reject ----
        kinds = ["float_ts", "str_ts", "dup_key", "trailing", "exp_num",
                 "sigs_notlist", "sig_scalar", "deep_nest"]
        for i in range(args.iters):
            store, path = fresh()
            raw = open(path).read()
            env = json.loads(raw)
            kind = rng.choice(kinds)
            if kind == "float_ts":
                env["body"]["ts"] = 1.5
                text = json.dumps(env)
            elif kind == "str_ts":
                env["body"]["ts"] = "123"
                text = json.dumps(env)
            elif kind == "exp_num":   # exponent-notation number (a float, invalid)
                text = re.sub(r'"ts":\s*-?\d+', '"ts": 1e3', json.dumps(env), count=1)
            elif kind == "dup_key":
                text = json.dumps(env)[:-1] + ',"body":{"warrant":"0.2"}}'  # duplicate body key
            elif kind == "sigs_notlist":
                env["sigs"] = "nope"          # sigs is not an array
                text = json.dumps(env)
            elif kind == "sig_scalar":
                env["sigs"] = [rng.choice(["malicious", 123, None])]  # non-object sig entry
                text = json.dumps(env)
            elif kind == "deep_nest":         # deeply-nested body: parser recursion
                text = '{"body":' + "[" * 50000 + "]" * 50000 + ',"sigs":[]}'
            else:  # trailing content after the JSON value
                text = json.dumps(env) + "\n{}"
            open(path, "w").write(text)
            cp, cg = verify_both(store)
            # Both MUST REJECT (errors > 0) — strengthened from the earlier
            # "disagree" check, which silently passed a SHARED accept of a
            # malformed record (Gemini 3.1 Pro audit, 2026-07). Neither impl may
            # crash: a None (no summary line) is itself a failure.
            if cp is None or cg is None or not (cp[0] > 0 and cg[0] > 0):
                fails.append(("C-reject", i, kind, cp, cg))

    total = args.iters * 3
    if fails:
        print(f"FUZZ-DIFFERENTIAL: DIVERGENCE ({len(fails)} of {total}) seed={args.seed}")
        for f in fails[:20]:
            print("  ", f)
        return 1
    print(f"FUZZ-DIFFERENTIAL: ALL AGREE ({total}/{total}) seed={args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
