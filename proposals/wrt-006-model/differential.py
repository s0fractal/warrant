#!/usr/bin/env python3
"""WRT-006 reproducer — three typed observations about two Book I engines under `ski@v1`.

  corpus_equivalence   MATCH | MISMATCH | INCOMPLETE
      E0 vs E1 on every unique `kind=eval` input of the Σ-GLYPH conformance suites
      (two suite documents; the inputs are deduplicated and counted once each),
      compared on the canonical NodeHash of the result and on atp_spent.
  ski_specimen         MATCH | MISMATCH | INCOMPLETE
      the one `ski@v1` check this repository ships (examples/ski/check.json),
      re-executed by both engines and compared to its `expect`.
  boundary_observation EXPECTED_DIVERGENCE | CHANGED | INCOMPLETE
      bytes stored under a key they do not hash to: the expectation stated in
      WRT-006 §2 is that E0 executes them as the requested node (a canonical
      outcome) and E1 refuses with a local fault. This axis is checked, not narrated; it never substitutes for
      the corpus axis and the corpus axis never substitutes for it.

Exit 0 only if all three are at their expected value. Writes nothing outside a
TemporaryDirectory. All paths in the receipt are relative to the repository root.

What a green run establishes: agreement on the named finite corpora at named
digests, and one located divergence outside them. It is profile-conformance /
regression evidence. It is NOT a proof of equivalence on the admitted domain.

Usage (any checkout root or worktree):
  python3 proposals/wrt-006-model/differential.py [--old git:<commit>:impl/sigma_glyph.py | <path>]
      [--new impl/sigma_glyph.py] [--sigma-repo <path>] [--old-suite v0.6.7] [--new-suite HEAD]
"""
import argparse, hashlib, importlib.util, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
E0_DEFAULT = "git:98169375b3690151ca30891e2bda5046bd80a870:impl/sigma_glyph.py"  # pre-W1 bundled module


def rel(p):
    try:
        return os.path.relpath(os.path.abspath(p), ROOT)
    except ValueError:
        return os.path.basename(p)


def read_src(spec):
    if spec.startswith("git:"):
        _, rev, path = spec.split(":", 2)
        return subprocess.check_output(["git", "--no-optional-locks", "-C", ROOT, "show", f"{rev}:{path}"])
    with open(spec, "rb") as f:
        return f.read()


def load_module(src, name, tmpdir):
    path = os.path.join(tmpdir, f"{name}.py")
    with open(path, "wb") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def find_sigma(explicit):
    cands = [explicit, os.environ.get("SIGMA_GLYPH_REPO"),
             os.path.join(ROOT, "..", "sigma-glyph"), os.path.join(ROOT, "..", "..", "sigma-glyph"),
             os.path.expanduser("~/Projects/sigma-glyph")]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "tests", "spec_conformance", "vectors.json")):
            return os.path.abspath(c)
    return None


def suite(repo, rev):
    path = "tests/spec_conformance/vectors.json"
    if rev in ("HEAD", None, ""):
        with open(os.path.join(repo, path), "rb") as f:
            raw = f.read()
    else:
        raw = subprocess.check_output(["git", "--no-optional-locks", "-C", repo, "show", f"{rev}:{path}"])
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def evaluate(m, term_hex, atp, objs, keys):
    """Return (result_node_hash_hex, atp_spent, exit_or_None) using the engine's own canonical hash."""
    st = m.Store()
    for k in keys:
        st.put(bytes.fromhex(objs[k]))
    r = m.eval_hash(bytes.fromhex(term_hex), atp, st)
    t, spent = r[0], int(r[1])
    exit_kind = r[2] if len(r) > 2 else None
    return m.term_hash(t).hex(), spent, exit_kind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default=E0_DEFAULT)
    ap.add_argument("--new", default=os.path.join(ROOT, "impl", "sigma_glyph.py"))
    ap.add_argument("--sigma-repo", default=None)
    ap.add_argument("--old-suite", default="v0.6.7")
    ap.add_argument("--new-suite", default="HEAD")
    a = ap.parse_args()

    receipt = {"kind": "wrt-006-differential-receipt/1", "root": "warrant checkout root (paths relative)",
               "engines": {}, "corpus": {}, "ski_specimen": {}, "boundary": {},
               "verdicts": {"corpus_equivalence": "INCOMPLETE", "ski_specimen": "INCOMPLETE",
                            "boundary_observation": "INCOMPLETE"}}
    with tempfile.TemporaryDirectory(prefix="wrt006-") as tmp:
        src0, src1 = read_src(a.old), read_src(a.new)
        E0, E1 = load_module(src0, "e0", tmp), load_module(src1, "e1", tmp)
        receipt["engines"] = {
            "E0": {"source": a.old if a.old.startswith("git:") else rel(a.old), "sha256": hashlib.sha256(src0).hexdigest()},
            "E1": {"source": a.new if a.new.startswith("git:") else rel(a.new), "sha256": hashlib.sha256(src1).hexdigest()}}

        # ---- axis 1: corpus equivalence on unique inputs
        sigma = find_sigma(a.sigma_repo)
        if sigma is None:
            receipt["corpus"] = {"error": "no sigma-glyph checkout found (--sigma-repo / SIGMA_GLYPH_REPO)"}
        else:
            docs, unique, disagree, errors, replays = {}, {}, [], [], 0
            for label, rev in (("old-suite", a.old_suite), ("new-suite", a.new_suite)):
                d, dig = suite(sigma, rev)
                n = 0
                for v in d["vectors"]:
                    if v.get("kind") != "eval":
                        continue
                    n += 1
                    keys = tuple(v.get("store_subset") or sorted(d["objects"].keys()))
                    key = (v["term"], int(v["atp"]), keys)
                    unique.setdefault(key, []).append(f"{label}:{v.get('id')}")
                    try:
                        r0 = evaluate(E0, v["term"], v["atp"], d["objects"], keys)
                        r1 = evaluate(E1, v["term"], v["atp"], d["objects"], keys)
                    except Exception as e:
                        errors.append({"suite": label, "id": v.get("id"), "error": repr(e)[:160]})
                        continue
                    replays += 1
                    if (r0[0], r0[1]) != (r1[0], r1[1]):
                        disagree.append({"suite": label, "id": v.get("id"), "E0": r0[:2], "E1": r1[:2]})
                docs[label] = {"rev": rev, "sha256": dig, "eval_vectors": n}
            receipt["corpus"] = {"sigma_repo": rel(sigma) if sigma.startswith(ROOT) else "<external checkout>",
                                 "suite_documents": docs, "unique_inputs": len(unique),
                                 "replays": replays, "disagreements": disagree, "errors": errors}
            receipt["verdicts"]["corpus_equivalence"] = (
                "INCOMPLETE" if errors or replays == 0 else ("MISMATCH" if disagree else "MATCH"))

        # ---- axis 2: the repository's own ski@v1 specimen
        try:
            skidir = os.path.join(ROOT, "examples", "ski")
            chk = json.load(open(os.path.join(skidir, "check.json")))
            objs = {}
            for fn in os.listdir(skidir):
                if fn.endswith(".bin"):
                    objs[fn[:-4]] = open(os.path.join(skidir, fn), "rb").read().hex()
            keys = sorted(objs.keys())
            r0 = evaluate(E0, chk["term"], int(chk["atp"]), objs, keys)
            r1 = evaluate(E1, chk["term"], int(chk["atp"]), objs, keys)
            receipt["ski_specimen"] = {"check": "examples/ski/check.json", "expect": chk["expect"],
                                       "E0": r0[:2], "E1": r1[:2], "blobs": len(objs)}
            ok = r0[0] == r1[0] == chk["expect"] and r0[1] == r1[1]
            receipt["verdicts"]["ski_specimen"] = "MATCH" if ok else "MISMATCH"
        except Exception as e:
            receipt["ski_specimen"] = {"error": repr(e)[:160]}

        # ---- axis 3: domain boundary (bytes under a key they do not hash to)
        try:
            node_I = E0.ser(E0.LITERAL, E0.F_ATOM, atom=E0.sha(b"I"))   # a valid node's bytes
            foreign = hashlib.sha256(b"WRT-006 foreign key").digest()
            obs = {}
            for name, m in (("E0", E0), ("E1", E1)):
                st = m.Store(); st.m[foreign] = node_I
                try:
                    r = m.eval_hash(foreign, 8, st)
                    t = r[0]
                    obs[name] = {"class": "canonical_outcome",
                                 "kind": (t[0] if isinstance(t, tuple) else "?"),
                                 "result_hash": m.term_hash(t).hex(), "atp_spent": int(r[1])}
                except Exception as e:
                    rf = getattr(m, "ResourceFault", ())
                    obs[name] = {"class": "refusal" if isinstance(e, rf) else "other_exception",
                                 "error": repr(e)[:120]}
            # Expected divergence (WRT-006 §2): E0 EXECUTES the foreign bytes as the
            # requested node (a canonical outcome — normal form or DISSONANCE
            # depending on the bytes); E1 REFUSES with a local fault.
            expected = obs["E0"]["class"] == "canonical_outcome" and obs["E1"]["class"] == "refusal"
            receipt["boundary"] = {"input": "valid node bytes stored under a foreign key; eval of that key with atp=8",
                                   "observed": obs,
                                   "expected_per_WRT-006_§2": "E0 executes the foreign bytes (canonical outcome); E1 refuses (local fault)",
                                   "fetch_layer_note": "warrant.run_ski_check additionally refuses such a fetch after W1 (tests/sigma_cas_identity.py)"}
            receipt["verdicts"]["boundary_observation"] = "EXPECTED_DIVERGENCE" if expected else "CHANGED"
        except Exception as e:
            receipt["boundary"] = {"error": repr(e)[:160]}

    v = receipt["verdicts"]
    ok = v["corpus_equivalence"] == "MATCH" and v["ski_specimen"] == "MATCH" and v["boundary_observation"] == "EXPECTED_DIVERGENCE"
    receipt["exit"] = 0 if ok else 1
    print(json.dumps(receipt, indent=1, sort_keys=True, default=str))
    sys.exit(receipt["exit"])


if __name__ == "__main__":
    main()
