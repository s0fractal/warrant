#!/usr/bin/env python3
"""WRT-006 reproducer, rev 3 — independent typed axes over two Book I engines under `ski@v1`.

Axes (each asserted; none substitutes for another; exit 0 only if every required axis holds):

  suite_shape            MATCH | MISMATCH | INCOMPLETE
      the two suite documents carry the SAME closed set of operational inputs, where an input's
      identity is (term, atp, ordered (object-key, sha256(object bytes)) …); duplicates refuse;
      `missing_from_old` / `missing_from_new` are printed; the expected count is pinned (--expect-inputs).
  E0_conformance         PASS | FAIL | INCOMPLETE
  E1_conformance         PASS | FAIL | INCOMPLETE
      each engine against the suites' NORMATIVE expected values (result_hash, atp_spent, outcome, and
      exit where the suite carries it and the engine can report it). A field a suite does not carry, or
      an engine cannot report, is listed as `not_checkable`, never invented.
  differential_agreement MATCH | MISMATCH | INCOMPLETE
      E0 vs E1 on the engine's own canonical NodeHash of the result and atp_spent, per unique input.
  ski_specimen           MATCH | MISMATCH | INCOMPLETE
      examples/ski/check.json re-executed by both engines; both must equal its `expect`.
  boundary_observation   EXPECTED_DIVERGENCE | CHANGED | INCOMPLETE
      two PINNED fixtures (node I, APPLY(I,I)) stored under a foreign key: E0 must return the exact
      pinned (result hash, spent); E1 must raise ResourceFault with the exact message 'CAS key mismatch'.

The receipt names the reproducer's own sha256 and schema id. Writes only to a TemporaryDirectory.
Paths in the receipt are relative to the repository root. What a green run establishes: the named
finite evidence at named digests. It is NOT a proof of equivalence on the admitted domain.
"""
import argparse, hashlib, importlib.util, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELF = os.path.abspath(__file__)
SCHEMA = "wrt-006-differential-receipt/2"
E0_DEFAULT = "git:98169375b3690151ca30891e2bda5046bd80a870:impl/sigma_glyph.py"  # pre-W1 bundled module
FOREIGN_KEY = hashlib.sha256(b"WRT-006 foreign key").digest()
# Pinned boundary expectations, measured 2026-09-02 against E0 sha 0d2b898b… (see WRT-006 §2).
BOUNDARY_EXPECT = {
    "I":          {"E0": ("2f33694d09810641fa5b8c47a7c0dc42e1b99eb8c9784a00aaee9a66330f4162", 1)},
    "APPLY(I,I)": {"E0": ("2f33694d09810641fa5b8c47a7c0dc42e1b99eb8c9784a00aaee9a66330f4162", 4)},
}
E1_REFUSAL = ("ResourceFault", "CAS key mismatch")
FIELDS = ("result_hash", "atp_spent", "outcome", "exit")


def rel(p):
    ap = os.path.abspath(p)
    return os.path.relpath(ap, ROOT) if ap.startswith(ROOT + os.sep) else "<external>/" + os.path.basename(ap)


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
    for c in (explicit, os.environ.get("SIGMA_GLYPH_REPO"), os.path.join(ROOT, "..", "sigma-glyph"),
              os.path.join(ROOT, "..", "..", "sigma-glyph"), os.path.expanduser("~/Projects/sigma-glyph")):
        if c and os.path.isfile(os.path.join(c, "tests", "spec_conformance", "vectors.json")):
            return os.path.abspath(c)
    return None


def suite(repo, rev):
    path = "tests/spec_conformance/vectors.json"
    if rev in ("HEAD", None, ""):
        raw = open(os.path.join(repo, path), "rb").read()
    else:
        raw = subprocess.check_output(["git", "--no-optional-locks", "-C", repo, "show", f"{rev}:{path}"])
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def input_key(v, objs):
    keys = tuple(v.get("store_subset") or sorted(objs.keys()))
    return (v["term"], int(v["atp"]), tuple((k, hashlib.sha256(bytes.fromhex(objs[k])).hexdigest()) for k in keys))


def run_engine(m, term_hex, atp, objs, keys):
    """Observables of one evaluation, derived exactly as the normative runner derives them.

    `exit` comes from `eval_receipt` where the engine has it (Book I 0.6.0 API); an engine without
    `eval_receipt` cannot report `exit`, and the field is left None (not_checkable), never guessed.
    `outcome` follows tests/spec_conformance/run_reference.py `classify()`: `invalid_object` iff the
    exit is normal_form and the result is the Canonical Invalid Object; otherwise the exit kind."""
    st = m.Store()
    for k in keys:
        st.put(bytes.fromhex(objs[k]))
    r = m.eval_hash(bytes.fromhex(term_hex), atp, st)
    t, spent = r[0], int(r[1])
    result_hash = m.term_hash(t).hex()
    invalid_hash = m.term_hash(("dis", m.R_INVALID)).hex()
    exit_kind = None
    if hasattr(m, "eval_receipt"):
        st2 = m.Store()
        for k in keys:
            st2.put(bytes.fromhex(objs[k]))
        rc = m.eval_receipt(bytes.fromhex(term_hex), atp, st2)
        if rc.result_hash.hex() != result_hash or int(rc.atp_spent) != spent:
            raise RuntimeError("eval_receipt and eval_hash disagree inside one engine")
        exit_kind = rc.exit
    else:
        # two-value engine: the exit KIND is recoverable from a DISSONANCE result's atom only for
        # the two canonical failures; for a normal form it is `normal_form`; it is still reported as
        # not_checkable against `expected.exit` because the engine has no exit observable.
        pass
    if exit_kind is not None:
        outcome = "invalid_object" if (exit_kind == "normal_form" and result_hash == invalid_hash) else exit_kind
    else:
        if isinstance(t, tuple) and t[0] == "dis" and t[1] == m.R_ATP:
            outcome = "atp_exhausted"
        elif isinstance(t, tuple) and t[0] == "dis" and t[1] == m.R_UNRES:
            outcome = "unresolved_reference"
        elif result_hash == invalid_hash:
            outcome = "invalid_object"
        else:
            outcome = "normal_form"
    return {"result_hash": result_hash, "atp_spent": spent, "exit": exit_kind, "outcome": outcome}


def conformance(m, docs):
    """Engine vs normative expected values across suite documents."""
    out = {"checked": {f: 0 for f in FIELDS}, "failed": [], "not_checkable": {f: 0 for f in FIELDS}, "errors": []}
    for label, (d, dig) in docs.items():
        objs = d["objects"]
        for v in d["vectors"]:
            if v.get("kind") != "eval":
                continue
            exp = v.get("expected", {})
            keys = tuple(v.get("store_subset") or sorted(objs.keys()))
            try:
                got = run_engine(m, v["term"], v["atp"], objs, keys)
            except Exception as e:
                out["errors"].append({"suite": label, "id": v.get("id"), "error": repr(e)[:160]}); continue
            for f in FIELDS:
                if f not in exp or got.get(f) is None:
                    out["not_checkable"][f] += 1
                    continue
                out["checked"][f] += 1
                if str(got[f]) != str(exp[f]):
                    out["failed"].append({"suite": label, "id": v.get("id"), "field": f, "expected": exp[f], "got": got[f]})
    out["verdict"] = "INCOMPLETE" if out["errors"] or sum(out["checked"].values()) == 0 else ("FAIL" if out["failed"] else "PASS")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default=E0_DEFAULT)
    ap.add_argument("--new", default=os.path.join(ROOT, "impl", "sigma_glyph.py"))
    ap.add_argument("--sigma-repo", default=None)
    ap.add_argument("--old-suite", default="v0.6.7")
    ap.add_argument("--new-suite", default="HEAD")
    ap.add_argument("--expect-inputs", type=int, default=33)
    a = ap.parse_args()

    R = {"schema": SCHEMA, "reproducer_sha256": hashlib.sha256(open(SELF, "rb").read()).hexdigest(),
         "root": "warrant checkout root (paths relative)", "engines": {}, "suites": {}, "axes": {}, "verdicts": {}}
    with tempfile.TemporaryDirectory(prefix="wrt006-") as tmp:
        src0, src1 = read_src(a.old), read_src(a.new)
        E0, E1 = load_module(src0, "e0", tmp), load_module(src1, "e1", tmp)
        R["engines"] = {"E0": {"source": a.old if a.old.startswith("git:") else rel(a.old), "sha256": hashlib.sha256(src0).hexdigest()},
                        "E1": {"source": a.new if a.new.startswith("git:") else rel(a.new), "sha256": hashlib.sha256(src1).hexdigest()}}

        sigma = find_sigma(a.sigma_repo)
        docs = {}
        if sigma is None:
            R["suites"] = {"error": "no sigma-glyph checkout found (--sigma-repo / SIGMA_GLYPH_REPO)"}
            for ax in ("suite_shape", "E0_conformance", "E1_conformance", "differential_agreement"):
                R["verdicts"][ax] = "INCOMPLETE"
        else:
            for label, rev in (("old-suite", a.old_suite), ("new-suite", a.new_suite)):
                docs[label] = suite(sigma, rev)
                R["suites"][label] = {"rev": rev, "sha256": docs[label][1],
                                      "eval_vectors": sum(1 for v in docs[label][0]["vectors"] if v.get("kind") == "eval")}
            R["suites"]["sigma_repo"] = rel(sigma)

            # --- suite_shape
            sets, dups = {}, {}
            for label, (d, _) in docs.items():
                seen = {}
                for v in d["vectors"]:
                    if v.get("kind") != "eval":
                        continue
                    k = input_key(v, d["objects"])
                    if k in seen:
                        dups.setdefault(label, []).append([seen[k], v.get("id")])
                    seen[k] = v.get("id")
                sets[label] = seen
            old_k, new_k = set(sets["old-suite"]), set(sets["new-suite"])
            shape = {"unique_inputs_old": len(old_k), "unique_inputs_new": len(new_k), "unique_inputs_union": len(old_k | new_k),
                     "missing_from_old": sorted(sets["new-suite"][k] for k in new_k - old_k),
                     "missing_from_new": sorted(sets["old-suite"][k] for k in old_k - new_k),
                     "duplicates": dups, "expected_inputs": a.expect_inputs}
            R["axes"]["suite_shape"] = shape
            R["verdicts"]["suite_shape"] = ("INCOMPLETE" if not old_k or not new_k else
                                            "MATCH" if (old_k == new_k and not dups and len(old_k) == a.expect_inputs) else "MISMATCH")

            # --- conformance, per engine
            for name, m in (("E0", E0), ("E1", E1)):
                c = conformance(m, docs)
                R["axes"][f"{name}_conformance"] = c
                R["verdicts"][f"{name}_conformance"] = c["verdict"]

            # --- differential agreement on the union of unique inputs
            disagree, errors, n = [], [], 0
            for label, (d, _) in docs.items():
                for v in d["vectors"]:
                    if v.get("kind") != "eval":
                        continue
                    keys = tuple(v.get("store_subset") or sorted(d["objects"].keys()))
                    try:
                        r0, r1 = run_engine(E0, v["term"], v["atp"], d["objects"], keys), run_engine(E1, v["term"], v["atp"], d["objects"], keys)
                    except Exception as e:
                        errors.append({"suite": label, "id": v.get("id"), "error": repr(e)[:160]}); continue
                    n += 1
                    if (r0["result_hash"], r0["atp_spent"]) != (r1["result_hash"], r1["atp_spent"]):
                        disagree.append({"suite": label, "id": v.get("id"), "E0": r0, "E1": r1})
            R["axes"]["differential_agreement"] = {"replays": n, "unique_inputs": len(old_k | new_k), "disagreements": disagree, "errors": errors}
            R["verdicts"]["differential_agreement"] = "INCOMPLETE" if errors or n == 0 else ("MISMATCH" if disagree else "MATCH")

        # --- ski specimen
        try:
            skidir = os.path.join(ROOT, "examples", "ski")
            chk = json.load(open(os.path.join(skidir, "check.json")))
            objs = {fn[:-4]: open(os.path.join(skidir, fn), "rb").read().hex() for fn in os.listdir(skidir) if fn.endswith(".bin")}
            keys = sorted(objs)
            r0, r1 = run_engine(E0, chk["term"], int(chk["atp"]), objs, keys), run_engine(E1, chk["term"], int(chk["atp"]), objs, keys)
            R["axes"]["ski_specimen"] = {"check": "examples/ski/check.json", "expect": chk["expect"], "blobs": len(objs),
                                         "E0": [r0["result_hash"], r0["atp_spent"]], "E1": [r1["result_hash"], r1["atp_spent"]]}
            R["verdicts"]["ski_specimen"] = "MATCH" if (r0["result_hash"] == r1["result_hash"] == chk["expect"] and r0["atp_spent"] == r1["atp_spent"]) else "MISMATCH"
        except Exception as e:
            R["axes"]["ski_specimen"] = {"error": repr(e)[:160]}; R["verdicts"]["ski_specimen"] = "INCOMPLETE"

        # --- boundary, two pinned fixtures
        try:
            nodeI = E0.ser(E0.LITERAL, E0.F_ATOM, atom=E0.sha(b"I"))
            nodeA = E0.ser(E0.APPLY, E0.F_LEFT | E0.F_RIGHT, left=E0.node_hash(nodeI), right=E0.node_hash(nodeI))
            fixtures = {"I": nodeI, "APPLY(I,I)": nodeA}
            obs, ok = {}, True
            for fx, bts in fixtures.items():
                obs[fx] = {}
                for name, m in (("E0", E0), ("E1", E1)):
                    st = m.Store(); st.m[FOREIGN_KEY] = bts
                    try:
                        r = m.eval_hash(FOREIGN_KEY, 8, st)
                        obs[fx][name] = {"class": "canonical_outcome", "result_hash": m.term_hash(r[0]).hex(), "atp_spent": int(r[1])}
                    except Exception as e:
                        obs[fx][name] = {"class": "exception", "type": type(e).__name__, "message": str(e)}
                e0, e1 = obs[fx]["E0"], obs[fx]["E1"]
                exp0 = BOUNDARY_EXPECT[fx]["E0"]
                ok &= e0.get("class") == "canonical_outcome" and (e0.get("result_hash"), e0.get("atp_spent")) == exp0
                ok &= e1.get("class") == "exception" and (e1.get("type"), e1.get("message")) == E1_REFUSAL
            R["axes"]["boundary_observation"] = {"foreign_key": FOREIGN_KEY.hex(), "expected": {"E0": BOUNDARY_EXPECT, "E1": E1_REFUSAL},
                                                 "observed": obs, "fetch_layer_note": "warrant.run_ski_check additionally refuses such a fetch after W1 (tests/sigma_cas_identity.py)"}
            R["verdicts"]["boundary_observation"] = "EXPECTED_DIVERGENCE" if ok else "CHANGED"
        except Exception as e:
            R["axes"]["boundary_observation"] = {"error": repr(e)[:160]}; R["verdicts"]["boundary_observation"] = "INCOMPLETE"

    good = {"suite_shape": "MATCH", "E0_conformance": "PASS", "E1_conformance": "PASS", "differential_agreement": "MATCH",
            "ski_specimen": "MATCH", "boundary_observation": "EXPECTED_DIVERGENCE"}
    R["exit"] = 0 if all(R["verdicts"].get(k) == v for k, v in good.items()) else 1
    print(json.dumps(R, indent=1, sort_keys=True, default=str))
    sys.exit(R["exit"])


if __name__ == "__main__":
    main()
