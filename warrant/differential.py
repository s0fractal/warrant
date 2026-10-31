"""Differential assessment (roadmap G12): the published release n and this package assess one store under its
receiver (`.warrant/v3.json`), and their reports must be the same bytes but for the engine's identity.

    python -m warrant.differential --python N_PYTHON [--root DIR] [--declared FILE] [--release VERSION]

N_PYTHON is a Python whose site-packages hold the published warrant-graph n (installed from PyPI); it runs isolated
(-I: no script directory, no PYTHONPATH, no user site), from outside the checkout, so it imports n and never this
tree. Each report is canonical JSON. `code` (the digest of the engine's files) and `assessment` (the digest of the
operands, `code` among them) name the engine and differ whenever the engine does; every other member is compared
as bytes, after checking that each report's `assessment` is the digest of its own operands. A difference is admitted
only when FILE declares it: {"warrant": "differential/1", "differs": [MEMBER, ...], "because": TEXT}, naming exactly
the members that differ (an undeclared difference is refused, and so is a declared one that did not occur).

With --release VERSION, release n must also admit n+1 (roadmap G12, release.yml): n's own engine assesses the store and
finds an obligation@1 lineage whose effective version is closed (`done`, its guard met: an acceptor accepted it), relied
on (ELIGIBLE), and lists `warrant-graph==VERSION` among its refs (`roadmap close --ref`). None: REFUSED. And n's
history must still be here: every record line and every blob of the store at n's tag (`v` + the version N_PYTHON's
warrant-graph names) is in this checkout's store. Release n+1 may challenge a record of n's history (a challenge, a new
version: the receiver's reliance answers it), never rewrite it; a missing line or blob is REFUSED, a missing tag UNMADE.

Prints the verdict as JSON; exit 0 SAME or DECLARED, 1 REFUSED, 2 when a report could not be made."""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import engine as E
from . import jcs as C
from .store import Store, dot_of, read_inside

FORMAT = "differential/1"
IDENTITY = ("assessment", "code")            # what names the engine, not what it found
OPERANDS = ("snapshot", "trust", "profile", "as_of", "code")
# run by N_PYTHON: the store and its receiver from argv, the report on stdout
SCRIPT = """import json, sys
from warrant import engine as E
from warrant.store import Store
dot, receiver = sys.argv[1], json.loads(sys.argv[2])
rep = E.assess(Store(dot).snapshot(), receiver["trust"], receiver["profile"], None)
sys.stdout.write(json.dumps(rep, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
"""

# run by N_PYTHON: the release duties n itself finds closed, accepted and relied on for one version
RELEASE_SCRIPT = """import json, sys
from warrant import engine as E, records as R
from warrant.store import Store
dot, receiver, want = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]
rep = E.assess(Store(dot).snapshot(), receiver["trust"], receiver["profile"], None)
recs = {}
with open(dot + "/records.jsonl", "rb") as f:
    for line in f:
        if line.strip():
            r = json.loads(line)["record"]
            recs[R.rid(r)] = r
found = sorted(lin["effective"] for lin in rep["lineages"].values()
               if lin["schema"] == "obligation@1" and lin["effective"] and lin["state"] == "done"
               and lin["reliance"] == "ELIGIBLE" and want in (recs.get(lin["effective"], {}).get("body", {}).get("refs") or []))
sys.stdout.write(json.dumps({"release": want, "accepted": found}))
"""
RELEASE_REF = "warrant-graph=={}"
# run by N_PYTHON: the version of the warrant-graph it imports, whose tag holds n's history
VERSION_SCRIPT = """import importlib.metadata, json, sys
sys.stdout.write(json.dumps(importlib.metadata.version("warrant-graph")))
"""
TAG = "v{}"
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?\Z")   # PEP 440, public


class Unmade(Exception):
    pass


def receiver(root):
    dot = dot_of(root)
    return dot, json.loads(read_inside(dot / "v3.json", dot))


def head_report(root):
    dot, doc = receiver(root)
    return E.assess(Store(dot).snapshot(), doc["trust"], doc["profile"], None)


def published(python, root, script, *args, run=subprocess.run):
    """What `script` prints as JSON, run by the warrant-graph N_PYTHON imports on this store and its receiver."""
    dot, doc = receiver(root)
    if os.sep in str(python):                                   # a path names it from here, not from where it runs
        python = os.path.abspath(python)                        # (Codex finding 30154b8b64e1); a bare name: PATH
    with tempfile.TemporaryDirectory() as away:                 # its directory: nothing of the checkout to import
        r = run([str(python), "-I", "-c", script, str(dot), json.dumps({"trust": doc["trust"], "profile": doc["profile"]}),
                 *args], capture_output=True, cwd=away, check=False, timeout=3600)
    if r.returncode:
        raise Unmade(f"{python} exited {r.returncode}: {r.stderr.decode(errors='replace').strip()[-400:]}")
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        raise Unmade(f"{python} printed no report: {e}") from None


def published_report(python, root, run=subprocess.run):
    """The report of the warrant-graph N_PYTHON imports, on the same store and receiver."""
    return published(python, root, SCRIPT, run=run)


def release_duties(python, root, version, run=subprocess.run):
    """[closure id]: the release duties of `version` that n's own engine finds closed, accepted and relied on."""
    got = published(python, root, RELEASE_SCRIPT, RELEASE_REF.format(version), run=run)
    if not (isinstance(got, dict) and isinstance(got.get("accepted"), list)):
        raise Unmade(f"{python} printed no release duties")
    return got["accepted"]


def published_version(python, root, run=subprocess.run):
    """The version of the warrant-graph N_PYTHON imports, refused unless it is a public PEP 440 version: it names
    the tag whose store is n's history, and a git argument is never anything else."""
    n = published(python, root, VERSION_SCRIPT, run=run)
    if not (isinstance(n, str) and VERSION.match(n)):
        raise Unmade(f"{python} named no warrant-graph version: {n!r}"[:200])
    return n


def git_bytes(root, cmd, *args, options=()):
    r = subprocess.run(["git", "-C", str(root), cmd, *options, "--end-of-options", *args], capture_output=True,
                       check=False)
    if r.returncode:
        raise Unmade(f"git {cmd} {' '.join(args)}: {r.stderr.decode(errors='replace').strip()[-300:]}")
    return r.stdout


def rewritten(root, ref):
    """{records: [line], blobs: [name]}: what the store at `ref` (n's tag) holds that this checkout's store does not.
    Blobs by name: the store refuses one not named by its hash."""
    dot = dot_of(root)
    then = {x for x in git_bytes(root, "show", f"{ref}:.warrant/records.jsonl").split(b"\n") if x.strip()}
    now = {x for x in (dot / "records.jsonl").read_bytes().split(b"\n") if x.strip()}
    named = git_bytes(root, "ls-tree", ref, "--", ".warrant/blobs/", options=("-z", "--name-only")).split(b"\0")
    blobs = {Path(n.decode()).name for n in named if n}
    here = {p.name for p in (dot / "blobs").iterdir()} if (dot / "blobs").is_dir() else set()
    return {"records": sorted(x.decode() for x in then - now), "blobs": sorted(blobs - here)}


def compare(n, head, declared=None):
    """{verdict: SAME|DECLARED|REFUSED, differs: [member], why?}."""
    for name, rep in (("n", n), ("head", head)):
        if not isinstance(rep, dict) or rep.get("assessment") != C.doc_id({k: rep.get(k) for k in OPERANDS}):
            return {"verdict": "REFUSED", "differs": [], "why": f"the {name} report's assessment is not its operands' digest"}
    members = sorted((set(n) | set(head)) - set(IDENTITY))
    differs = [m for m in members if m not in n or m not in head or C.canon(n[m]) != C.canon(head[m])]
    if not differs and not (declared or {}).get("differs"):
        return {"verdict": "SAME", "differs": []}
    named = sorted((declared or {}).get("differs") or [])
    if named == differs:
        return {"verdict": "DECLARED", "differs": differs, "because": declared.get("because")}
    return {"verdict": "REFUSED", "differs": differs,
            "why": f"undeclared: {sorted(set(differs) - set(named))}; declared but the same: {sorted(set(named) - set(differs))}"}


def declaration(path):
    doc = json.loads(Path(path).read_text())
    if not (isinstance(doc, dict) and set(doc) == {"warrant", "differs", "because"} and doc["warrant"] == FORMAT
            and isinstance(doc["differs"], list) and all(isinstance(m, str) for m in doc["differs"]) and doc["differs"]
            and isinstance(doc["because"], str) and doc["because"].strip()):
        raise Unmade(f"{path} is not a {FORMAT} declaration {{warrant, differs: [member, ...], because}}")
    return doc


def admit(python, root, version, out):
    """`out` (compare's verdict) with release n's admission of `version`: a release duty of it accepted, as n assesses
    the store, and n's history (the store at n's tag) kept whole; REFUSED with every reason otherwise."""
    tag = TAG.format(published_version(python, root))
    gone = rewritten(root, tag)
    out = dict(out, release={"version": version, "accepted": release_duties(python, root, version),
                             "history": {"of": tag, **{k: len(v) for k, v in gone.items()}}})
    why = [out["why"]] if out["verdict"] == "REFUSED" else []
    if not out["release"]["accepted"]:
        why.append(f"no release duty of {version} is closed and accepted, as n assesses the store (an "
                   f"obligation@1 closure with the ref {RELEASE_REF.format(version)})")
    if gone["records"] or gone["blobs"]:
        why.append(f"the store at {tag} holds {len(gone['records'])} record line(s) and "
                   f"{len(gone['blobs'])} blob(s) this one does not: n's history is challenged, never rewritten")
    return dict(out, verdict="REFUSED", why="; ".join(why)) if why else out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m warrant.differential", description=__doc__.split("\n\n")[0])
    ap.add_argument("--python", required=True, help="a Python with the published warrant-graph n installed")
    ap.add_argument("--root", default=".", help="the repository whose .warrant/ both releases assess")
    ap.add_argument("--declared", help=f"a {FORMAT} declaration of the members that differ")
    ap.add_argument("--release", help="also require a release duty of this version accepted, as n assesses it")
    a = ap.parse_args(argv)
    try:
        declared = declaration(a.declared) if a.declared else None
        out = compare(published_report(a.python, a.root), head_report(a.root), declared)
        if a.release is not None:
            out = admit(a.python, a.root, a.release, out)
    except (Unmade, OSError, ValueError) as e:
        print(json.dumps({"verdict": "UNMADE", "why": str(e)}))
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0 if out["verdict"] in ("SAME", "DECLARED") else 1


if __name__ == "__main__":
    sys.exit(main())
