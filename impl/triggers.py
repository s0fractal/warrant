#!/usr/bin/env python3
"""WRT-022 S1: revalidation triggers over an explicit dependency manifest.

DRAFT profile code, used by impl/loops.py. Nothing `warrant verify` decides changes.

A closure mapping may declare triggers. Each one evaluates, in one view, to
exactly one of FIRED, NOT_FIRED or UNEVALUABLE(reason). Unknown never reads as
NOT_FIRED: a revision that cannot be read, a dependency that is missing, or an
input this code does not support gives UNEVALUABLE.

  subject_changed      {"kind", "baseline": <manifest blob hash>}
  duty_not_discharged  {"kind", "duty": <WarrantID>}

A manifest names a CLOSED, explicit selector: repository-relative file paths,
no globs. The producer chooses it, so the scope of any claim is bounded to it.
Each entry is the git mode and the SHA-256 of the bytes. Symlinks, submodules
and directories are refused as unsupported inputs instead of being hashed in a
way that would claim more coverage than this code has.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path

import warrant as W

MANIFEST = "warrant.manifest@draft-2"
TRIGGER_KINDS = {"subject_changed", "duty_not_discharged"}
RESULTS = {"FIRED", "NOT_FIRED", "UNEVALUABLE"}
FILE_MODES = {"100644", "100755"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_TRIGGERS = 32
MAX_SELECTOR = 256
EVALUATOR = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class Refusal(Exception):
    """A manifest cannot be built; the message is the stable reason."""


def selector_problem(sel):
    """None if `sel` is a closed, canonical selector, else the reason."""
    if not (isinstance(sel, list) and 0 < len(sel) <= MAX_SELECTOR and all(isinstance(p, str) for p in sel)):
        return "selector must be a non-empty list of paths"
    if sel != sorted(set(sel)):
        return "selector must be sorted and without duplicates"
    for p in sel:
        parts = p.split("/")
        if not p or p.startswith("/") or "\\" in p or any(x in ("", ".", "..") for x in parts):
            return f"not a plain repository-relative path: {p!r}"
    return None


def _git(repo, *args, data=False):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if r.returncode != 0:
        return None
    return r.stdout if data else r.stdout.decode()


def resolve(repo, rev):
    """The full commit id of `rev` in `repo`, or None if it cannot be read."""
    if not (isinstance(rev, str) and re.fullmatch(r"[0-9a-f]{7,40}|[0-9a-f]{64}", rev)):
        return None
    out = _git(repo, "rev-parse", "--verify", "--quiet", rev + "^{commit}")
    return out.strip() if out else None


def build(repo, rev, selector):
    """The manifest of `selector` at commit `rev`, or Refusal(reason)."""
    why = selector_problem(selector)
    if why:
        raise Refusal(why)
    commit = resolve(repo, rev)
    if commit is None:
        raise Refusal("revision unavailable")
    entries = {}
    for path in selector:
        out = _git(repo, "ls-tree", "-r", "-z", commit, "--", path)
        rows = [r for r in (out or "").split("\0") if r]
        exact = [r for r in rows if r.split("\t", 1)[-1] == path]
        if not rows:
            raise Refusal(f"missing dependency: {path}")
        if len(rows) != 1 or not exact:
            raise Refusal(f"unsupported input (directory): {path}")
        meta, _ = exact[0].split("\t", 1)
        mode, kind, oid = meta.split(" ")
        if mode not in FILE_MODES or kind != "blob":
            raise Refusal(f"unsupported input (mode {mode}): {path}")
        data = _git(repo, "cat-file", "blob", oid, data=True)
        if data is None:
            raise Refusal(f"missing dependency: {path}")
        entries[path] = {"mode": mode, "sha256": hashlib.sha256(data).hexdigest()}
    return {"schema": MANIFEST, "selector": list(selector), "entries": entries}


def manifest_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == {"schema", "selector", "entries"} and doc["schema"] == MANIFEST):
        return "manifest fields"
    why = selector_problem(doc["selector"])
    if why:
        return why
    ents = doc["entries"]
    if not (isinstance(ents, dict) and sorted(ents) == doc["selector"]):
        return "manifest entries must name exactly the selector"
    for e in ents.values():
        if not (isinstance(e, dict) and set(e) == {"mode", "sha256"} and e["mode"] in FILE_MODES
                and isinstance(e["sha256"], str) and HEX64.match(e["sha256"])):
            return "manifest entry"
    return None


def trigger_problem(t):
    """None if `t` is a well-formed trigger declaration, else the reason."""
    if not (isinstance(t, dict) and isinstance(t.get("kind"), str) and t["kind"] in TRIGGER_KINDS):
        return "trigger kind"
    operand = {"subject_changed": "baseline", "duty_not_discharged": "duty"}[t["kind"]]
    if set(t) != {"kind", operand} or not (isinstance(t[operand], str) and HEX64.match(t[operand])):
        return f"{t['kind']} takes exactly {operand}"
    return None


def triggers_problem(ts):
    if not (isinstance(ts, list) and len(ts) <= MAX_TRIGGERS):
        return "triggers must be a list"
    for t in ts:
        why = trigger_problem(t)
        if why:
            return why
    if len({json.dumps(t, sort_keys=True) for t in ts}) != len(ts):
        return "duplicate trigger"
    return None


class Workspace:
    """The recipient's current revision of one repository, read once per assessment.
    Every manifest computed here is remembered, so the assessment identity can name
    exactly the operands its trigger results depend on."""

    def __init__(self, repo, rev):
        self.repo, self.rev = repo, rev
        self.commit = resolve(repo, rev) if repo is not None else None
        self.computed = {}            # selector tuple -> manifest hash, or "REFUSED:<reason>"

    def current(self, selector):
        key = tuple(selector)
        if self.commit is None:
            self.computed[key] = "REFUSED:revision unavailable"
            raise Refusal("revision unavailable")
        try:
            doc = build(self.repo, self.commit, list(selector))
        except Refusal as e:
            self.computed[key] = f"REFUSED:{e}"
            raise
        self.computed[key] = hashlib.sha256(W.canon(doc)).hexdigest()
        return doc

    def identity(self):
        return {"commit": self.commit, "manifests": {"\n".join(k): v for k, v in sorted(self.computed.items())}}


def evaluate(trigger, read_blob, workspace, dispositions):
    """One trigger in one view: (result, detail). `read_blob(h)` returns a canonical
    JSON blob or None; `dispositions` maps every duty in the view to its disposition."""
    if trigger["kind"] == "duty_not_discharged":
        d = trigger["duty"]
        if d not in dispositions:
            return "UNEVALUABLE", "duty not in view"
        disp = dispositions[d]
        return ("NOT_FIRED", "DISCHARGED") if disp == "DISCHARGED" else ("FIRED", f"duty is {disp}")
    base = read_blob(trigger["baseline"])
    if base is None:
        return "UNEVALUABLE", "baseline manifest not in view"
    why = manifest_problem(base)
    if why:
        return "UNEVALUABLE", f"baseline manifest: {why}"
    if workspace is None:
        return "UNEVALUABLE", "no current workspace in view"
    try:
        cur = workspace.current(base["selector"])
    except Refusal as e:
        return "UNEVALUABLE", str(e)
    changed = [p for p in base["selector"] if cur["entries"][p] != base["entries"][p]]
    return ("FIRED", "changed: " + ", ".join(changed)) if changed else ("NOT_FIRED", "unchanged")
