"""The repository the claims live in: its paths, pins, roles, bindings and trust, its store, and
the mutants of tests/mutants.py and tests/agent_mutants.py with the scopes and statements each
one changes. `witness_problems` says which cited case or mutant does not exist or does not burn
a cited case."""
import importlib.util
import json
import os
import re
from pathlib import Path

from warrant import jcs as C
from warrant.store import Snapshot

from .base import HARNESS_PACKAGE, HARNESSES, id_key, TEST_RE, WITNESSES
from .bindings import admit_bindings, local_bindings, read_roles, trust_of
from .statements import changed_scopes, changed_statements


class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.spec = self.root / "SPEC.md"
        self.store_dir = self.root / ".warrant" / "store"
        self.trust_path = self.root / ".warrant" / "trust.json"
        self.pins_path = self.root / ".warrant" / "claims.json"
        self.roles_path = self.root / ".warrant" / "roles.json"
        self.projection = self.root / "SPEC-CLAIMS.md"
        self.witnesses = self.root / WITNESSES
        self.tests = self.root / "tests"
        self._mutants = None

    def pins(self):
        return json.loads(self.pins_path.read_text())

    def write_pins(self, pins):
        pins["sentences"] = dict(sorted(pins["sentences"].items(), key=lambda kv: id_key(kv[0])))
        self.pins_path.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n")

    def roles(self):
        """(roles, problems) of .warrant/roles.json (read_roles); none given, no name has a role."""
        if not self.roles_path.is_file():
            return {}, []
        try:
            doc = json.loads(self.roles_path.read_text())
        except ValueError as e:
            return {}, [("ROLES_SHAPE", f".warrant/roles.json: {e}")]
        return read_roles(doc)

    def bindings(self):
        """(admitted [(actor, public)], problems) of .warrant/trust.json (admit_bindings), under
        the roles of .warrant/roles.json."""
        if not self.trust_path.is_file():
            return [], [("BINDINGS_SHAPE", ".warrant/trust.json does not exist (tools/claims.py bind writes it)")]
        try:
            doc = C.loads(self.trust_path.read_bytes())
        except Exception as e:      # noqa: BLE001 -- an unreadable file admits nothing, and says why
            return [], [("BINDINGS_SHAPE", f".warrant/trust.json: {type(e).__name__}: {e}")]
        return admit_bindings(doc, roles=self.roles()[0])

    def trust(self):
        """The trust this checker uses: the admitted bindings, then the receiver's own (local_bindings)."""
        return trust_of(self.bindings()[0] + local_bindings())

    def snapshot(self):
        return Snapshot.read(self.store_dir)

    def mutants(self):
        """{id: (harness file, test file, [target cases])} from every harness of HARNESSES.
        Also sets `twice` (an id defined twice in one harness), `collide` (an id defined in
        more than one harness) and `misprefixed` ({id: harness} for an id without its
        harness's prefix)."""
        if self._mutants is None:
            out, twice, seen, misprefixed, edits = {}, set(), {}, {}, {}
            for name, prefix in HARNESSES:
                path = self.tests / name
                if not path.is_file():
                    continue
                spec = importlib.util.spec_from_file_location(f"claims_{path.stem}", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                ids = [m[0] for m in mod.MUTANTS]
                twice |= {i for i in ids if ids.count(i) > 1}
                for m in mod.MUTANTS:
                    seen.setdefault(m[0], set()).add(name)
                    if not m[0].startswith(prefix):
                        misprefixed[m[0]] = name
                    out.setdefault(m[0], (name, m[4], list(m[5])))
                    edits.setdefault(m[0], (os.path.normpath(f"{HARNESS_PACKAGE[name]}/{m[1]}"), list(m[3])))
            self.twice, self.misprefixed = twice, misprefixed
            self.collide = {i for i, names in seen.items() if len(names) > 1}
            self._mutants, self.mutant_edits = out, edits
        return self._mutants

    def harness_problems(self):
        """(code, detail) for ids that do not resolve in exactly one harness."""
        try:
            self.mutants()
        except Exception as e:      # noqa: BLE001
            return [("MUTANTS_UNREADABLE", f"{type(e).__name__}: {e}")]
        prefixes = dict(HARNESSES)
        return ([("MUTANT_ID_COLLISION", f"{i} is defined in more than one of tests/mutants.py, tests/agent_mutants.py")
                 for i in sorted(self.collide)]
                + [("MUTANT_ID_PREFIX", f"{i} is in tests/{h}, whose ids start with {prefixes[h]}")
                   for i, h in sorted(self.misprefixed.items())])

    def mutant_scopes(self, mid):
        """The scopes (file, function) mutant `mid` changes, from its own (old, new) edits
        applied to the file as it is now; empty when its edits no longer apply."""
        self.mutants()
        path, edits = self.mutant_edits.get(mid, (None, ()))
        f = self.root / path if path else None
        if f is None or not f.is_file():
            return set()
        old = new = f.read_text()
        for o, n in edits:
            if new.count(o) != 1:
                return set()
            new = new.replace(o, n)
        try:
            return changed_scopes(path, old, new)
        except SyntaxError:
            return set()

    def mutant_statements(self, mid):
        """The statements (changed_statements) mutant `mid` changes in the file as it is now;
        empty when its edits no longer apply."""
        self.mutants()
        path, edits = self.mutant_edits.get(mid, (None, ()))
        f = self.root / path if path else None
        if f is None or not f.is_file():
            return set()
        old = new = f.read_text()
        for o, n in edits:
            if new.count(o) != 1:
                return set()
            new = new.replace(o, n)
        try:
            return changed_statements(path, old, new)
        except SyntaxError:
            return set()

    def has_case(self, test, case):
        p = self.tests / f"{test}.py"
        return p.is_file() and re.search(r"[\"']" + re.escape(case) + r"[\"']", p.read_text()) is not None


def witness_problems(repo, witnesses, mutants):
    """(code, detail) for each cited case or mutant that does not exist or does not burn a cited case."""
    out, cited = [], set()
    for w in witnesses:
        test, _, case = w.partition(":")
        if not (TEST_RE.match(test) and case):
            out.append(("BAD_WITNESS", f"{w!r} is not <test file>:<case id>"))
        elif not (repo.tests / f"{test}.py").is_file():
            out.append(("UNKNOWN_TEST_FILE", f"tests/{test}.py does not exist ({w})"))
        elif not repo.has_case(test, case):
            out.append(("UNKNOWN_CASE", f"tests/{test}.py has no case {case}"))
        else:
            cited.add((test, case))
    try:
        known = repo.mutants()
    except Exception as e:      # noqa: BLE001
        return out + [("MUTANTS_UNREADABLE", f"{type(e).__name__}: {e}")]
    for mid in mutants:
        if mid not in known:
            out.append(("UNKNOWN_MUTANT", f"neither tests/mutants.py nor tests/agent_mutants.py has a mutant {mid}"))
            continue
        harness, test, targets = known[mid]
        if mid in repo.twice:
            out.append(("DUPLICATE_MUTANT_ID", f"tests/{harness} defines {mid} more than once"))
            continue
        if mid in repo.collide:
            out.append(("MUTANT_ID_COLLISION", f"{mid} is defined in more than one harness; it names no one mutant"))
            continue
        if mid in repo.misprefixed:
            out.append(("MUTANT_ID_PREFIX", f"{mid} is in tests/{harness}, whose ids start with {dict(HARNESSES)[harness]}"))
            continue
        missing = [t for t in targets if not (TEST_RE.match(test) and repo.has_case(test, t))]
        if missing or not targets:
            out.append(("MUTANT_TARGET_UNKNOWN", f"{mid} targets {test} {','.join(missing) or '(nothing)'}, "
                        "which is not a case of an existing test file"))
            continue
        if not {(test, t) for t in targets} & cited:
            out.append(("MUTANT_OFF_WITNESS", f"{mid} targets {test} {','.join(targets)}, none of them cited"))
    return out
