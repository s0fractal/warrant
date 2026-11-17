"""Sources: stores a repository reads beside its own, each the store of an actor that files there instead of here.

A repository's `.warrant/sources.json` may name sources:

    {"warrant": "sources/1",
     "sources": [{"name": "claims-checker", "ref": "refs/heads/stores/claims-checker", "actors": ["claims-checker"]}]}

Each is a Git ref of this repository whose tree holds a store (`.warrant/records.jsonl`, `.warrant/blobs/`). Reading
the repository's store reads, beside it, the records each source holds BY ITS ACTORS ONLY, at the ref's commit as
this clone has it, and assesses the union under this repository's own trust and profile, as one overlay
(warrant_agent/overlay.py) does for a reader: a source decides nothing by being read, its records count only as the
repository's receiver counts their signers. A record a source holds by any other actor is left out and named, so a
source cannot speak for another; a ref this clone does not hold is named unavailable, never read as empty.

Why: an actor that files many machine verdicts (the claims checker's acceptances, a reviewer's verdicts) files them
in its own store, with no pull request per verdict and no growth of the repository's store; the repository reads them
where they are (owner, 2026-11-17: models as stores of their own judgments, read through one multi-store graph). The
declaration is its own file, not the rules (v3.json): a source changes no trust and no role."""
import json
import re
import subprocess
from pathlib import Path

from . import shapes as S
from .store import Snapshot, _line_id, read_inside

NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
REF = re.compile(r"refs/(heads|warrant)/[A-Za-z0-9._/-]{1,200}\Z")
RECORDS, BLOBS = ".warrant/records.jsonl", ".warrant/blobs/"
FORMAT = "sources/1"


def declared(doc):
    """The sources a sources/1 document names, checked; [] when it names none. A malformed declaration is refused.
    A source adds only records by keys this repository's trust already binds: who counts stays the rules' (v3.json)."""
    if doc and not (isinstance(doc, dict) and doc.get("warrant") == FORMAT and set(doc) <= {"warrant", "sources"}):
        raise ValueError(f".warrant/sources.json is a {FORMAT} document {{warrant, sources}}")
    xs = doc.get("sources", []) if isinstance(doc, dict) else []
    if not isinstance(xs, list):
        raise ValueError("sources is a list")
    out, seen = [], set()
    for x in xs:
        ok = (isinstance(x, dict) and set(x) == {"name", "ref", "actors"} and isinstance(x["name"], str) and NAME.match(x["name"])
              and isinstance(x["ref"], str) and REF.match(x["ref"]) and ".." not in x["ref"]
              and isinstance(x["actors"], list) and x["actors"] and all(S.is_actor(a) for a in x["actors"]))
        if not ok or x["name"] in seen:
            raise ValueError(f"a source is {{name, ref, actors}} with a unique name, a refs/heads or refs/warrant ref and actor ids: {str(x)[:120]}")
        seen.add(x["name"])
        out.append(x)
    return out


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=True).stdout


def _commit(root, ref):
    """The commit `ref` names in this clone, or None. A branch a plain clone holds only as origin's remote-tracking
    ref (refs/remotes/origin/...) is read there, so `git clone` alone reads every source the origin has. `ref` was
    checked by declared (refs/heads or refs/warrant, no ..), and --end-of-options keeps it an argument even so."""
    if not (isinstance(ref, str) and REF.match(ref) and ".." not in ref):
        return None
    for r in (ref, *(["refs/remotes/origin/" + ref[len("refs/heads/"):]] if ref.startswith("refs/heads/") else [])):
        try:
            commit = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{r}^{{commit}}").decode().strip()
        except subprocess.CalledProcessError:
            continue
        if S.hex_of(commit, 40):
            return commit
    return None


def _actor(line):
    try:
        return json.loads(line)["record"]["actor"]
    except (ValueError, KeyError, TypeError):
        return None


def _blobs(root, commit):
    try:
        rows = _git(root, "ls-tree", "-z", f"{commit}:{BLOBS.rstrip('/')}").decode().split("\0")
    except subprocess.CalledProcessError:
        return {}
    out = {}
    for meta, _, name in (row.partition("\t") for row in rows if "\t" in row):
        kind, obj = meta.split()[1:3]
        if S.hex64(name) and kind == "blob":
            out[name] = _git(root, "cat-file", "blob", obj)
    return out


def read(root, source):
    """(commit, [raw lines by its actors], {blob: bytes}, left out) of one source at its ref in the clone at `root`;
    commit None when the ref is not here."""
    commit = _commit(root, source["ref"])
    if commit is None:
        return None, [], {}, 0
    try:
        raw = _git(root, "cat-file", "blob", f"{commit}:{RECORDS}")
    except subprocess.CalledProcessError:
        raw = b""
    lines = [ln for ln in raw.split(b"\n") if ln]
    mine = [ln + b"\n" for ln in lines if _actor(ln) in source["actors"]]
    return commit, mine, _blobs(root, commit), len(lines) - len(mine)


def with_sources(root, snap, doc):
    """(snapshot, sources read) of the repository at `root`: `snap` (its own store) with each declared source's
    records by its actors and its blobs, one snapshot in canonical order; and per source {name, ref, commit, records,
    left_out} (commit None: the ref is not in this clone). With no source declared, `snap` itself."""
    srcs = declared(doc)
    if not srcs:
        return snap, []
    lines, blobs, info = set(snap.raw), dict(snap.blobs), []
    for s in srcs:
        commit, got, b, left = read(root, s)
        lines |= set(got)
        blobs.update(b)
        info.append({"name": s["name"], "ref": s["ref"], "commit": commit, "records": len(got), "left_out": left})
    return Snapshot(sorted(lines, key=_line_id), blobs), info


def config_doc(root):
    """The repository's .warrant/sources.json as a document, or {} when it has none (a malformed one is refused when
    read, by declared)."""
    dot = Path(root) / ".warrant"
    if not (dot / "sources.json").exists():
        return {}
    try:
        return json.loads(read_inside(dot / "sources.json", dot))      # never through a link out of the store
    except ValueError as e:
        raise ValueError(f".warrant/sources.json is not JSON: {e}") from None
