#!/usr/bin/env python3
"""Bind the bundled Sigma evaluator to the candidate wheel it came from.

This checks ONE dependency boundary — the vendored module named by the manifest
(`vendored_path`, today `impl/sigma_glyph_v06.py`, the ski@v2 evaluator) — against
`trust/sigma-evaluator-provenance.json` and the authoritative Sigma build
receipt it names. It is not a general vendoring framework.

Layers, weakest to strongest:

  schema         the manifest has EXACTLY the known fields (unknown or missing
                 is a refusal, so a pin cannot be quietly added or dropped);
  module digest  the vendored module hashes to the recorded module_sha256
                 (always runnable, no toolchain, no Sigma checkout);
  receipt        the committed Sigma receipt hashes to candidate_receipt_sha256
                 and every field the manifest copies agrees with it;
  source module  Sigma's impl/sigma_glyph.py AT source_commit equals the
                 vendored bytes (the wheel copies it verbatim);
  wheel rebuild  Sigma's own tools/candidate_freeze_check.py rebuilds the wheel
                 at source_commit under the pinned toolchain and reproduces
                 wheel_sha256, and the module extracted from that wheel equals
                 the vendored bytes.

The wheel rebuild needs the official CI Python and a Sigma checkout. Absent
those it is UNRUN — never PASS. In required CI (`--require-rebuild`) an UNRUN
rebuild fails the job; the module/source/receipt bindings are hard checks that
hold regardless. Wheel digest does not replace source/module binding.
"""
import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "trust/sigma-evaluator-provenance.json"
MAP = ROOT / "trust/ski-runtime-evaluators.json"
DEFAULT_VENDORED_PATH = "impl/sigma_glyph_v06.py"

REQUIRED = {
    "kind", "source_repository", "source_commit", "candidate_receipt_commit",
    "candidate_receipt_path", "candidate_receipt_sha256", "wheel_filename",
    "wheel_sha256", "module_path_in_wheel", "module_sha256", "software_version",
    "api_version", "adopted_bundle", "adopted_anchor_set_sha256", "build_pins",
    "source_date_epoch", "official_ci_python", "vendored_path", "runtime_tag",
}
OPTIONAL = {"note"}
# Which manifest fields must appear, and match, in the Sigma receipt.
RECEIPT_MAP = {
    "wheel_sha256": "artifact_sha256",
    "source_commit": "source_commit",
    "software_version": "software_version",
    "adopted_bundle": "adopted_bundle",
    "adopted_anchor_set_sha256": "adopted_anchor_set_sha256",
    "build_pins": "build_pins",
    "source_date_epoch": "source_date_epoch",
}
# api_version is a CLAIM about the evaluator's callable surface. Bind it to what
# the vendored module actually exposes, so the field is not free text: an unknown
# value, or a value whose promised surface the module does not provide, is a
# refusal. Book I's hash-thunk evaluator IS this set of names.
API_SURFACES = {
    "book1-eval-hash/1": ("eval_hash", "node_hash", "term_hash",
                          "ser", "deser", "force", "GENESIS", "ResourceFault"),
}
# EXIT_UNRUN: the check ran but could not COMPLETE (a binding was UNRUN and this
# is not required CI). Distinct from PASS(0) and FAIL(1) so tools/check.py can
# render it as UNRUN, honouring its own UNRUN≠PASS contract.
EXIT_UNRUN = 3


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sigma_repo():
    """Locate a Sigma git repo (env override, then the conventional sibling)."""
    import os
    env = os.environ.get("WARRANT_SIGMA_REPO")
    for cand in ([Path(env)] if env else []) + [ROOT.parent / "sigma-glyph"]:
        if cand and (cand / ".git").exists():
            return cand.resolve()
    return None


def git_show(repo, rev, path):
    r = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"],
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def has_commit(repo, commit):
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e",
                           f"{commit}^{{commit}}"], capture_output=True
                          ).returncode == 0


# ---- hard checks ----------------------------------------------------------

def check_schema(m):
    out = []
    if not isinstance(m, dict):
        return ["manifest is not an object"]
    missing = sorted(REQUIRED - set(m))
    unknown = sorted(set(m) - REQUIRED - OPTIONAL)
    if missing:
        out.append(f"manifest missing fields: {', '.join(missing)}")
    if unknown:
        out.append(f"manifest has unknown fields: {', '.join(unknown)}")
    if m.get("kind") != "warrant/sigma-evaluator-provenance@v0":
        out.append("manifest kind is not warrant/sigma-evaluator-provenance@v0")
    return out


def check_module_digest(m, module_path=None):
    module_path = module_path or (ROOT / m.get("vendored_path", DEFAULT_VENDORED_PATH))
    if not module_path.exists():
        return [f"vendored module absent: {module_path}"]
    got = sha256_bytes(module_path.read_bytes())
    if got != m.get("module_sha256"):
        return [f"vendored module digest {got[:16]}… != manifest "
                f"module_sha256 {str(m.get('module_sha256'))[:16]}…"]
    return []


def check_receipt(m, repo):
    """Returns (problems, ran). ran=False -> UNRUN (no Sigma checkout)."""
    if repo is None or not has_commit(repo, m["candidate_receipt_commit"]):
        return [], False
    raw = git_show(repo, m["candidate_receipt_commit"], m["candidate_receipt_path"])
    if raw is None:
        return [f"receipt {m['candidate_receipt_path']} absent at "
                f"{m['candidate_receipt_commit'][:12]}"], True
    if sha256_bytes(raw) != m["candidate_receipt_sha256"]:
        return [f"receipt digest {sha256_bytes(raw)[:16]}… != manifest "
                f"candidate_receipt_sha256"], True
    receipt = json.loads(raw)
    out = []
    for mf, rf in RECEIPT_MAP.items():
        if receipt.get(rf) != m.get(mf):
            out.append(f"receipt.{rf} != manifest.{mf} "
                       f"({receipt.get(rf)!r} vs {m.get(mf)!r})")
    return out, True


def check_api_version(m, module_path=None):
    module_path = module_path or (ROOT / m.get("vendored_path", DEFAULT_VENDORED_PATH))
    """api_version must name a known Σ-GLYPH API surface, and the vendored module
    must actually expose it. Always runnable (no toolchain, no checkout)."""
    av = m.get("api_version")
    names = API_SURFACES.get(av)
    if names is None:
        return [f"api_version {av!r} is not a recognised Σ-GLYPH API surface "
                f"(known: {', '.join(sorted(API_SURFACES))})"]
    if not module_path.exists():
        return [f"vendored module absent: {module_path}"]
    ns = {}
    try:
        exec(compile(module_path.read_text(), "sigma_glyph", "exec"), ns)  # noqa: S102
    except Exception as ex:                       # pragma: no cover - defensive
        return [f"vendored module did not import: {ex}"]
    missing = [n for n in names if n not in ns]
    if missing:
        return [f"api_version {av} but the vendored module omits {missing}"]
    return []


def _norm_remote(u):
    """Reduce a git remote URL to host/owner/repo for comparison across the
    https / ssh / scp-style forms git accepts for the same repository. The scheme
    (whatever it is) is stripped, so this compares identity, not transport."""
    u = u.strip().removesuffix(".git")
    u = re.sub(r"^[a-z+]+://", "", u)             # drop any scheme://
    u = re.sub(r"^git@([^:/]+):", r"\1/", u)      # scp-style host:owner/repo
    u = re.sub(r"^[^@/]+@", "", u)                # drop any leading user@
    return u.rstrip("/").lower()


def check_source_repository(m, repo):
    """The clone the receipt/source are read FROM must be source_repository.
    Returns (problems, ran); ran=False (UNRUN) when there is no clone with an
    origin to compare against."""
    if repo is None:
        return [], False
    r = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [], False
    got, want = r.stdout.strip(), m.get("source_repository", "")
    if _norm_remote(got) != _norm_remote(want):
        return [f"clone origin {got!r} != manifest.source_repository {want!r}"], True
    return [], True


def check_source_module(m, repo):
    """Returns (problems, ran)."""
    if repo is None or not has_commit(repo, m["source_commit"]):
        return [], False
    b = git_show(repo, m["source_commit"], "impl/sigma_glyph.py")
    if b is None:
        return [f"impl/sigma_glyph.py absent at source_commit "
                f"{m['source_commit'][:12]}"], True
    if sha256_bytes(b) != m["module_sha256"]:
        return ["Sigma source module at source_commit does not match "
                "module_sha256"], True
    if b != (ROOT / m.get("vendored_path", DEFAULT_VENDORED_PATH)).read_bytes():
        return ["vendored module bytes differ from Sigma source at "
                "source_commit"], True
    return [], True


def check_wheel_rebuild(m, repo):
    """Returns (status, detail). status in {'PASS','FAIL','UNRUN'}."""
    pyver = ".".join(platform.python_version_tuple()[:2])
    if pyver != m["official_ci_python"]:
        return "UNRUN", (f"running Python {pyver}; the receipt reproduces only "
                         f"under CPython {m['official_ci_python']}")
    if repo is None or not has_commit(repo, m["candidate_receipt_commit"]) \
            or not has_commit(repo, m["source_commit"]):
        return "UNRUN", "no Sigma checkout with the receipt/source commits"

    work = Path(tempfile.mkdtemp(prefix="warrant-sigma-freeze-"))
    tree = work / "sigma"
    try:
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach",
                        "--quiet", str(tree), m["candidate_receipt_commit"]],
                       check=True, capture_output=True)
        # 1) authoritative digest gate: Sigma rebuilds and requires the frozen digest
        fc = subprocess.run(
            [sys.executable, str(tree / "tools/candidate_freeze_check.py"),
             "--receipt", m["candidate_receipt_path"]],
            cwd=str(tree), capture_output=True, text=True)
        if fc.returncode != 0:
            return "FAIL", "candidate_freeze_check did not reproduce the wheel:\n" \
                           + (fc.stdout + fc.stderr)[-800:]
        # 2) build once more to EXTRACT the module from the produced wheel
        stree = work / "src"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach",
                        "--quiet", str(stree), m["source_commit"]],
                       check=True, capture_output=True)
        import os
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(m["source_date_epoch"]))
        b = subprocess.run(
            [sys.executable, str(stree / "tools/candidate_artifact.py"),
             "build", "--out", str(work / "out")],
            cwd=str(stree), capture_output=True, text=True, env=env)
        if b.returncode != 0:
            return "FAIL", "candidate_artifact build failed:\n" + (b.stdout + b.stderr)[-600:]
        man = json.loads((work / "out/release-manifest.json").read_text())
        if man["artifact_sha256"] != m["wheel_sha256"]:
            return "FAIL", (f"rebuilt wheel {man['artifact_sha256'][:16]}… != "
                            f"wheel_sha256 {m['wheel_sha256'][:16]}…")
        wheel = work / "out" / m["wheel_filename"]
        if not wheel.exists():
            return "FAIL", f"expected wheel {m['wheel_filename']} not produced"
        with zipfile.ZipFile(wheel) as z:
            names = [n for n in z.namelist()
                     if n == m["module_path_in_wheel"] or n.endswith(
                         "/" + m["module_path_in_wheel"])]
            if not names:
                return "FAIL", f"{m['module_path_in_wheel']} not in the wheel"
            extracted = z.read(names[0])
        if sha256_bytes(extracted) != m["module_sha256"]:
            return "FAIL", "module extracted from the wheel != module_sha256"
        if extracted != (ROOT / m.get("vendored_path", DEFAULT_VENDORED_PATH)).read_bytes():
            return "FAIL", "module extracted from the wheel != vendored bytes"
        return "PASS", (f"rebuild reproduces {m['wheel_sha256'][:16]}… and its "
                        f"{m['module_path_in_wheel']} equals the vendored module")
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                        str(tree)], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                        str(work / "src")], capture_output=True)
        shutil.rmtree(work, ignore_errors=True)


# ---- per-tag evaluator map (trust/ski-runtime-evaluators.json) -------------

def _warrant_constant():
    """SKI_EVALUATORS as impl/warrant.py defines it (the code is the enforcer)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("warrant_pc", ROOT / "impl/warrant.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SKI_EVALUATORS


def _check_runtime_entry(tag, ent, const, repo):
    """Validate one closed runtime-map entry."""
    if not isinstance(ent, dict):
        return [f"{tag}: runtime-map entry is not an object"], []
    out, unrun = [], []
    path = ROOT / ent.get("module", "")
    if not path.exists():
        return [f"{tag}: module absent: {ent.get('module')}"], unrun
    got = sha256_bytes(path.read_bytes())
    if got != ent.get("sha256"):
        out.append(f"{tag}: module {path.name} hashes {got[:16]}… != record "
                   f"{str(ent.get('sha256'))[:16]}…")
    if tag in const and (const[tag][0] != path.name or
                         const[tag][1] != ent.get("sha256")):
        out.append(f"{tag}: record ({path.name}, {str(ent.get('sha256'))[:16]}…) "
                   f"!= code constant ({const[tag][0]}, {const[tag][1][:16]}…)")
    src = ent.get("source", {})
    if not isinstance(src, dict) or not (src.get("commit") and src.get("path")):
        return out, unrun
    if repo is None or not has_commit(repo, src["commit"]):
        unrun.append(f"{tag}: source-module equality (no Sigma checkout at "
                     f"{src['commit'][:12]})")
        return out, unrun
    source_bytes = git_show(repo, src["commit"], src["path"])
    if source_bytes is None or sha256_bytes(source_bytes) != ent.get("sha256"):
        out.append(f"{tag}: {src['path']} at {src['commit'][:12]} != module digest")
    return out, unrun


def check_runtime_map(repo, map_path=MAP):
    """Bind each recorded tag to code, bytes, and available source history."""
    if not map_path.exists():
        return [f"runtime map missing: {map_path}"], []
    rec = json.loads(map_path.read_text())
    if rec.get("kind") != "warrant/ski-runtime-evaluators@v0" or not isinstance(rec.get("tags"), dict):
        return ["runtime map: unknown kind or shape"], []
    const, out, unrun = _warrant_constant(), [], []
    if set(const) != set(rec["tags"]):
        out.append(f"runtime map tags {sorted(rec['tags'])} != code tags {sorted(const)}")
    for tag, ent in rec["tags"].items():
        entry_out, entry_unrun = _check_runtime_entry(tag, ent, const, repo)
        out.extend(entry_out)
        unrun.extend(entry_unrun)
    return out, unrun


# ---- mutation controls: each load-bearing pin must reject ------------------

def mutation_controls(m, repo):
    import copy
    out = []

    def want_reject(name, problems):
        out.append((name, bool(problems)))

    bad = copy.deepcopy(m); bad["module_sha256"] = "00" * 32
    want_reject("wrong module_sha256 rejected", check_module_digest(bad))

    bad = copy.deepcopy(m); bad["surprise"] = True
    want_reject("unknown manifest field rejected", check_schema(bad))

    bad = copy.deepcopy(m); del bad["wheel_sha256"]
    want_reject("missing required field rejected", check_schema(bad))

    bad = copy.deepcopy(m); bad["api_version"] = "book1-eval-hash/9"
    want_reject("unknown api_version rejected", check_api_version(bad))

    # the per-tag map: a wrong pin, and a tag the code does not know, must reject
    if MAP.exists():
        import tempfile
        rec = json.loads(MAP.read_text())
        for label, mutate in (("runtime map: wrong module sha256 rejected",
                               lambda r: r["tags"]["ski@v1"].__setitem__("sha256", "00" * 32)),
                              ("runtime map: tag unknown to the code rejected",
                               lambda r: r["tags"].__setitem__("ski@v9", dict(r["tags"]["ski@v1"])))):
            bad = copy.deepcopy(rec); mutate(bad)
            tmp = Path(tempfile.mkdtemp(prefix="skimap-")) / "map.json"
            tmp.write_text(json.dumps(bad))
            probs, _ = check_runtime_map(repo, tmp)
            want_reject(label, probs)
            shutil.rmtree(tmp.parent, ignore_errors=True)

    if repo is not None:
        bad = copy.deepcopy(m)
        bad["source_repository"] = "https://github.com/attacker/not-sigma"
        probs, _ = check_source_repository(bad, repo)
        # Only assert the rejection where an origin exists to compare against;
        # without one the binding is UNRUN, not silently satisfied.
        if check_source_repository(m, repo)[1]:
            want_reject("wrong source_repository rejected", probs)

    if repo is not None and has_commit(repo, m["candidate_receipt_commit"]):
        for field, val in (("wheel_sha256", "ff" * 32),
                           ("source_commit", "0" * 40),
                           ("adopted_anchor_set_sha256", "ab" * 32),
                           ("software_version", "9.9.9")):
            bad = copy.deepcopy(m); bad[field] = val
            probs, _ = check_receipt(bad, repo)
            want_reject(f"receipt rejects wrong {field}", probs)
    return out


def _collect(m, repo):
    """Run every binding + mutation control. Returns (problems, unrun): problems
    are (kind, message) refusals; unrun names a binding that could not execute."""
    problems, unrun = [], []
    problems += [("schema", p) for p in check_schema(m)]
    problems += [("module-digest", p) for p in check_module_digest(m)]
    problems += [("api-version", p) for p in check_api_version(m)]
    rm_probs, rm_unrun = check_runtime_map(repo)
    problems += [("runtime-map", p) for p in rm_probs]
    unrun += rm_unrun
    for kind, label, (probs, ran) in (
            ("receipt", "receipt agreement (no Sigma checkout with the receipt "
             "commit)", check_receipt(m, repo)),
            ("source-repository", "source-repository binding (no clone with an "
             "origin remote)", check_source_repository(m, repo)),
            ("source-module", "source-module equality (no Sigma checkout at "
             "source_commit)", check_source_module(m, repo))):
        problems += [(kind, p) for p in probs]
        if not ran:
            unrun.append(label)

    status, detail = check_wheel_rebuild(m, repo)
    print(f"  wheel rebuild: {status} — {detail}")
    if status == "FAIL":
        problems.append(("wheel-rebuild", detail))
    elif status == "UNRUN":
        unrun.append(f"wheel rebuild ({detail})")

    for name, ok in mutation_controls(m, repo):
        print(f"  control: {'ok ' if ok else 'BAD'} {name}")
        if not ok:
            problems.append(("mutation-control", f"did not reject: {name}"))
    return problems, unrun


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-rebuild", action="store_true",
                    help="required-CI mode: an UNRUN wheel rebuild fails")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"SIGMA-PROVENANCE: manifest missing: {MANIFEST}", file=sys.stderr)
        return 1
    m = json.loads(MANIFEST.read_text())
    repo = sigma_repo()
    problems, unrun = _collect(m, repo)

    for kind, p in problems:
        print(f"  FAIL [{kind}] {p}", file=sys.stderr)
    for u in unrun:
        print(f"  UNRUN: {u}", file=sys.stderr)

    if problems:
        print("SIGMA-PROVENANCE: FAIL", file=sys.stderr)
        return 1
    if unrun and args.require_rebuild:
        print("SIGMA-PROVENANCE: UNRUN under --require-rebuild is a failure "
              "(the frozen artifact must be re-derived in required CI)",
              file=sys.stderr)
        return 1
    if unrun:
        # Every executed binding held, but some could not run. This is NOT a pass:
        # a distinct exit so tools/check.py renders it UNRUN, never `ok`. The
        # mandatory rebuild in required CI (`--require-rebuild`) is where these
        # UNRUN bindings are forced to execute.
        print(f"SIGMA-PROVENANCE: INCOMPLETE — {len(unrun)} check(s) UNRUN "
              f"(executed bindings held; not settlement-grade until re-derived)",
              file=sys.stderr)
        return EXIT_UNRUN
    print(f"SIGMA-PROVENANCE: ALL PASS — vendored evaluator bound to "
          f"{m['module_sha256'][:16]}…; per-tag map bound (every binding executed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
