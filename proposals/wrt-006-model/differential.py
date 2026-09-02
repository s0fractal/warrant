#!/usr/bin/env python3
"""WRT-006 reproducer: are two Book I engines observationally equal under `ski@v1`?

Compares E0 (the evaluator bundled before W1, pinned by commit) with E1 (the
evaluator bundled now) on every `kind=eval` vector of two Σ-GLYPH conformance
suites, plus a store-identity control. It writes nothing; it prints a receipt
(JSON, one object) and exits non-zero on any disagreement inside the admitted
domain.

What a green run establishes: equality of (result_hash, atp_spent) on the
CORPUS named in the receipt, under the engines named by sha256 in the receipt.
What it does not establish: equality on the closed admitted domain of ski@v1
(infinite); that is WRT-006 §3's remaining obligation, not this script's claim.

Usage (from the warrant checkout root):
  python3 proposals/wrt-006-model/differential.py \
      [--old <path-or-git:<commit>:impl/sigma_glyph.py>] [--new impl/sigma_glyph.py] \
      [--sigma-repo ../sigma-glyph] [--old-suite v0.6.7] [--new-suite HEAD]
"""
import argparse, hashlib, importlib.util, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
E0_DEFAULT = "git:98169375b3690151ca30891e2bda5046bd80a870:impl/sigma_glyph.py"  # warrant master pre-W1


def read_src(spec, repo):
    if spec.startswith("git:"):
        _, rev, path = spec.split(":", 2)
        return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, "show", f"{rev}:{path}"])
    with open(spec, "rb") as f:
        return f.read()


def load_module(src, name):
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"wrt006_{name}_{hashlib.sha256(src).hexdigest()[:12]}.py")
    with open(tmp, "wb") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location(name, tmp)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def suite(repo, rev):
    path = "tests/spec_conformance/vectors.json"
    if rev == "HEAD" or rev is None:
        with open(os.path.join(repo, path), "rb") as f:
            raw = f.read()
    else:
        raw = subprocess.check_output(["git", "--no-optional-locks", "-C", repo, "show", f"{rev}:{path}"])
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def run(m, v, objs):
    st = m.Store()
    for k in (v.get("store_subset") or list(objs.keys())):
        st.put(bytes.fromhex(objs[k]))
    r = m.eval_hash(bytes.fromhex(v["term"]), v["atp"], st)
    h = r[0].hex() if isinstance(r[0], (bytes, bytearray)) else str(r[0])
    return h, int(r[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default=E0_DEFAULT)
    ap.add_argument("--new", default=os.path.join(ROOT, "impl", "sigma_glyph.py"))
    ap.add_argument("--sigma-repo", default=os.environ.get("SIGMA_GLYPH_REPO", os.path.join(ROOT, "..", "sigma-glyph")))
    ap.add_argument("--old-suite", default="v0.6.7")
    ap.add_argument("--new-suite", default="HEAD")
    a = ap.parse_args()

    src0, src1 = read_src(a.old, ROOT), read_src(a.new, ROOT)
    E0, E1 = load_module(src0, "e0"), load_module(src1, "e1")
    receipt = {
        "kind": "wrt-006-differential-receipt/0",
        "engines": {"E0": {"source": a.old, "sha256": hashlib.sha256(src0).hexdigest()},
                    "E1": {"source": a.new, "sha256": hashlib.sha256(src1).hexdigest()}},
        "corpora": {}, "compared": 0, "agree": 0, "disagree": [], "errors": [],
        "domain_boundary_control": None,
    }
    for label, rev in (("old-suite", a.old_suite), ("new-suite", a.new_suite)):
        d, dig = suite(a.sigma_repo, rev)
        receipt["corpora"][label] = {"rev": rev, "sha256": dig, "eval_vectors": 0}
        objs = d["objects"]
        for v in d["vectors"]:
            if v.get("kind") != "eval":
                continue
            receipt["corpora"][label]["eval_vectors"] += 1
            try:
                r0, r1 = run(E0, v, objs), run(E1, v, objs)
            except Exception as e:  # an engine that cannot run a vector is a disagreement, not a skip
                receipt["errors"].append({"suite": label, "id": v.get("id"), "error": repr(e)[:160]})
                continue
            receipt["compared"] += 1
            if r0 == r1:
                receipt["agree"] += 1
            else:
                receipt["disagree"].append({"suite": label, "id": v.get("id"), "E0": r0, "E1": r1})

    # Domain-boundary control: bytes stored under a key they do not hash to.
    # Measured 2026-09-02: the MODULES differ here. E0 evaluates the foreign
    # bytes and returns a canonical DISSONANCE (spent 3); E1 raises
    # ResourceFault('CAS key mismatch') — a local fault, not a canonical outcome
    # (Book I 0.6.0 §3.5). warrant.run_ski_check additionally refuses such a
    # fetch after W1 (tests/sigma_cas_identity.py). The control records both
    # levels so the boundary is located exactly, not assumed.
    try:
        I_bytes = None
        for m in (E0,):
            g = getattr(m, "GENESIS", None) or getattr(m, "genesis", None)
        # derive genesis I bytes via the engine's own serializer if exposed
        for cand in ("serialize_genesis", "genesis_bytes", "GENESIS_I"):
            if hasattr(E0, cand):
                obj = getattr(E0, cand)
                I_bytes = obj("I") if callable(obj) else obj
                break
        if I_bytes is None:
            # fall back: first object of the new suite is a valid node; use it as "foreign bytes"
            d, _ = suite(a.sigma_repo, a.new_suite)
            I_bytes = bytes.fromhex(next(iter(d["objects"].values())))
        foreign = hashlib.sha256(b"WRT-006 foreign key").digest()
        out = {}
        for name, m in (("E0", E0), ("E1", E1)):
            st = m.Store(); st.m[foreign] = I_bytes
            try:
                r = m.eval_hash(foreign, 8, st)
                out[name] = {"executed": True, "result": (r[0].hex() if isinstance(r[0], (bytes, bytearray)) else str(r[0])), "spent": int(r[1])}
            except Exception as e:
                out[name] = {"executed": False, "error": repr(e)[:120]}
        receipt["domain_boundary_control"] = {"input": "bytes stored under a key they do not hash to", "module_level": out,
                                              "expected": "E0 executes to a canonical DISSONANCE; E1 refuses with a local fault (Book I 0.6.0 §3.5)",
                                              "fetch_layer": "warrant.run_ski_check refuses this after W1 (tests/sigma_cas_identity.py); before W1 it executed"}
    except Exception as e:
        receipt["domain_boundary_control"] = {"error": repr(e)[:160]}

    ok = receipt["compared"] > 0 and not receipt["disagree"] and not receipt["errors"]
    receipt["verdict"] = "EQUAL_ON_CORPUS" if ok else "NOT_EQUAL_OR_INCOMPLETE"
    print(json.dumps(receipt, indent=1, sort_keys=True))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
