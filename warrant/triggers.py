"""Revalidation triggers (SPEC §5): FIRED, NOT_FIRED or UNEVALUABLE, never a guess."""
import hashlib
import re
import subprocess

from . import jcs as C

RESULTS = ("FIRED", "NOT_FIRED", "UNEVALUABLE")
FILE_MODES = ("100644", "100755")
MAX_SELECTOR = 256
KNOWN_NOT_DISCHARGED = ("OPEN", "RELEASED", "IMPOSSIBLE")


class Refusal(Exception):
    """A manifest cannot be built; the message is the stable reason."""


def selector_problem(sel):
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
    if not (isinstance(rev, str) and re.fullmatch(r"[0-9a-f]{7,40}|[0-9a-f]{64}|HEAD", rev)):
        return None
    out = _git(repo, "rev-parse", "--verify", "--quiet", rev + "^{commit}")
    return out.strip() if out else None


def manifest(repo, rev, selector):
    """The manifest of `selector` at commit `rev`, or Refusal(reason)."""
    why = selector_problem(selector)
    if why:
        raise Refusal(why)
    commit = resolve(repo, rev)
    if commit is None:
        raise Refusal("revision unavailable")
    entries = {}
    for path in selector:
        rows = [r for r in (_git(repo, "ls-tree", "-r", "-z", commit, "--", path) or "").split("\0") if r]
        exact = [r for r in rows if r.split("\t", 1)[-1] == path]
        if not rows:
            raise Refusal(f"missing dependency: {path}")
        if len(rows) != 1 or not exact:
            raise Refusal(f"unsupported input (directory): {path}")
        mode, kind, oid = exact[0].split("\t", 1)[0].split(" ")
        if mode not in FILE_MODES or kind != "blob":
            raise Refusal(f"unsupported input (mode {mode}): {path}")
        data = _git(repo, "cat-file", "blob", oid, data=True)
        if data is None:
            raise Refusal(f"missing dependency: {path}")
        entries[path] = {"mode": mode, "sha256": hashlib.sha256(data).hexdigest()}
    return {"selector": list(selector), "entries": entries}


def manifest_problem(doc):
    if not (isinstance(doc, dict) and set(doc) == {"selector", "entries"}):
        return "manifest fields"
    why = selector_problem(doc["selector"])
    if why:
        return why
    ents = doc["entries"]
    if not (isinstance(ents, dict) and sorted(ents) == doc["selector"]):
        return "manifest entries must name exactly the selector"
    for e in ents.values():
        if not (isinstance(e, dict) and set(e) == {"mode", "sha256"} and isinstance(e["mode"], str)
                and e["mode"] in FILE_MODES and isinstance(e["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", e["sha256"])):
            return "manifest entry"
    return None


class Workspace:
    """The recipient's current revision of one repository. Every manifest computed
    is remembered, so the assessment identity names what trigger results used."""

    def __init__(self, repo, rev):
        self.repo, self.rev = repo, rev
        self.commit = resolve(repo, rev) if repo is not None else None
        self.computed = {}

    def current(self, selector):
        key = tuple(selector)
        if self.commit is None:
            self.computed[key] = "REFUSED:revision unavailable"
            raise Refusal("revision unavailable")
        try:
            doc = manifest(self.repo, self.commit, list(selector))
        except Refusal as e:
            self.computed[key] = f"REFUSED:{e}"
            raise
        self.computed[key] = C.doc_id(doc)
        return doc

    def identity(self):
        return {"commit": self.commit, "manifests": {"\n".join(k): v for k, v in sorted(self.computed.items())}}


def evaluate(trigger, json_blob, workspace, dispositions):
    """(result, detail) of one trigger in one view."""
    if trigger["kind"] == "duty_not_discharged":
        d = trigger["duty"]
        if d not in dispositions:
            return "UNEVALUABLE", "duty not in view"
        disp = dispositions[d]
        if disp == "DISCHARGED":
            return "NOT_FIRED", "DISCHARGED"
        if disp in KNOWN_NOT_DISCHARGED:
            return "FIRED", f"duty is {disp}"
        return "UNEVALUABLE", f"duty state not assessable here: {disp}"
    base = json_blob(trigger["baseline"])
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
