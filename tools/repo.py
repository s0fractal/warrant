"""What the repository's tools share: the repository's store and receiver configuration (.warrant/v3.json),
filing records as a configured actor, and what a checker's attest says about the code that ran (docs/V3.md §6):
`code`, the digest of its whole import closure, and `env`, the interpreter's and signature library's versions.

The domain rules are the schema records'; nothing here decides a verdict. A tool reads the store, assesses
it with the package's engine and shows or files records."""
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from warrant import engine as E          # noqa: E402
from warrant import jcs as C             # noqa: E402
from warrant import keys as K            # noqa: E402
from warrant import records as R         # noqa: E402
from warrant.store import Refused, Store  # noqa: E402

OUTSIDE = ("build", ".venv")      # ignored by Git: an interpreter's environment there is not the repository's code


class Failed(Exception):
    """A refusal of a tool's run: printed as `REFUSED <code> <detail>`, exit 2."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class Repo:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.dot = self.root / ".warrant"
        self.store = Store(self.dot)

    def config(self):
        """(trust, profile, repository name) of .warrant/v3.json."""
        doc = json.loads((self.dot / "v3.json").read_text())
        for why in (E.trust_problem(doc["trust"]), E.profile_problem(doc["profile"])):
            if why:
                raise Failed("CONFIG", f".warrant/v3.json: {why}")
        return doc["trust"], doc["profile"], doc["repository"]

    def view(self, snap=None):
        trust, profile, _ = self.config()
        return E.View(snap if snap is not None else self.store.snapshot(), trust, profile)

    def report(self, snap=None):
        v = self.view(snap)
        rep = v.report()
        rep["_recs"], rep["_basis"] = v.recs, v.basis
        return rep

    def file(self, actor, key, records):
        """Append `records` (dicts as records.record makes them, actor and prev filled here) signed by `key` as
        `actor`, each dated now or at the actor's head; the ids."""
        trust, _, _ = self.config()
        if key.public not in trust["keys"].get(actor, []):
            raise Failed("SIGNER", f"the key {key.id[:12]} is not one .warrant/v3.json binds to {actor!r}")
        if not records:
            return []
        h = E.head(self.store.snapshot(), trust, actor)
        at = max(int(time.time()), h["at"] or 0)
        return self.store.extend([dict(r, actor=actor, at=at, prev=None) for r in records], key, trust, expect_head=h["id"] or "")


def inside(path, root=ROOT):
    """The real path of a file a tool reads or writes on an operator's word, refused unless it lies in the checkout."""
    real, base = os.path.realpath(path), os.path.realpath(root)
    if not real.startswith(base + os.sep):
        raise Failed("PATH", f"{path}: a tool reads and writes files of the checkout only")
    return Path(real)


def load_key(arg):
    """A seed from standard input ("-") or a file outside the repository."""
    if arg == "-":
        text = sys.stdin.readline()
    else:
        p = Path(arg).expanduser().resolve()
        if p.is_relative_to(ROOT):
            raise Failed("SEED", "a seed lives outside the repository")
        text = p.read_text()
    try:
        return K.Key.from_seed_hex(text.strip())
    except ValueError as e:
        raise Failed("SEED", f"not a seed: {e}") from None


def _paths(files, root):
    out = []
    for f in files:
        p = root / f
        out += sorted(p.glob("*.py")) if p.is_dir() else [p] if p.is_file() else []
    return out


def _digest(contents):
    """The code digest of {path relative to the repository: bytes}."""
    return C.doc_id({"files": {p: hashlib.sha256(b).hexdigest() for p, b in sorted(contents.items())}})


def identity(files, root=ROOT):
    """{code, env} of a checker run from `root`: `code` the digest of `files` (paths relative to the repository; a
    directory names its *.py), refused when a module this process loaded from the repository is not among them (the
    digest names the whole import closure); `env` the versions the digest leaves out."""
    import cryptography
    paths = _paths(files, root)
    hashed = {p.resolve() for p in paths}
    for m in list(sys.modules.values()):
        loc = getattr(m, "__file__", None)
        rel = Path(loc).resolve().relative_to(root.resolve()) if loc and Path(loc).resolve().is_relative_to(root.resolve()) else None
        if rel is not None and rel.parts[0] not in OUTSIDE and Path(loc).resolve() not in hashed:
            raise Failed("IDENTITY", f"{Path(loc).resolve().relative_to(root.resolve())} is imported and not in the identity")
    return {"code": _digest({p.relative_to(root).as_posix(): p.read_bytes() for p in paths}),
            "env": {"python": platform.python_version(), "cryptography": cryptography.__version__}}


def git(root, *a, raw=False):
    out = subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=True).stdout
    return out if raw else out.decode().strip()


def code_at(files, commit, root=ROOT):
    """The code digest of `files` in the tree of `commit`, read from Git objects: what `identity` gives a checkout
    of that commit."""
    contents = {}
    for f in files:
        for row in git(root, "ls-tree", commit, "--", f + "/" if (root / f).is_dir() else f).splitlines():
            meta, path = row.split("\t", 1)
            if meta.split()[1] == "blob" and (path == f or path.endswith(".py")):
                contents[path] = git(root, "cat-file", "blob", meta.split()[2], raw=True)
    return _digest(contents)


def code_tree(root, commit):
    """`commit`'s tree outside .warrant/ (as `git ls-tree -r` rows): the code a test runs against. Records added
    after a result do not change it."""
    rows = git(root, "ls-tree", "-r", commit).splitlines()
    return "\n".join(r for r in rows if not r.split("\t", 1)[1].startswith(".warrant/"))


def checker_problem(body, files, root=ROOT):
    """Why a checker's attest body does not name the code it ran, or None: `commit` must be a commit of this
    repository, `tree` its tree, `code` the digest of `files` there (CODE_DIFFERS) and `env` the versions."""
    x = body.get("commit")
    if not (isinstance(x, str) and len(x) == 40 and all(c in "0123456789abcdef" for c in x)):
        return "names no commit"
    try:
        tree, code = git(root, "rev-parse", f"{x}^{{tree}}"), code_at(files, x, root)
    except subprocess.CalledProcessError:
        return f"names {x[:12]}, not a commit of this repository"
    env = body.get("env")
    if body.get("tree") != tree:
        return f"names the tree {str(body.get('tree'))[:12]}, not {x[:12]}'s"
    if body.get("code") != code:
        return f"CODE_DIFFERS: names the code {str(body.get('code'))[:12]}, {x[:12]} holds {code[:12]}"
    if not (isinstance(env, dict) and set(env) == {"python", "cryptography"} and all(isinstance(v, str) for v in env.values())):
        return "names no env {python, cryptography}"
    return None


def tree_id(root=ROOT):
    """(commit, tree) of a clean checkout, refused when anything tracked or untracked differs from HEAD: a result
    named by a commit holds for that whole tree (the hermetic identity)."""
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise Failed("DIRTY", "the checkout differs from HEAD: a checker runs on a commit's whole tree")
    return git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")


def main(run, argv=None):
    """Run a tool's `run(argv)`: a Failed or a store refusal prints `REFUSED <code> <detail>` and exits 2."""
    try:
        return run(argv)
    except Failed as e:
        print(f"REFUSED {e.code} {e}", file=sys.stderr)
        return 2
    except (Refused, R.Invalid) as e:
        print(f"REFUSED STORE {e}", file=sys.stderr)
        return 2


def dump(obj):
    print(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False))


def env_root(argv):
    """--root DIR before the command (the waker runs a base tree's tool on another tree)."""
    if argv[:1] and argv[0].startswith("--root"):
        if "=" in argv[0]:
            return Path(argv[0].split("=", 1)[1]), argv[1:]
        return Path(argv[1]), argv[2:]
    return Path(os.environ.get("WARRANT_REPO_ROOT", ROOT)), argv
