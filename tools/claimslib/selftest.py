"""--selftest: `check` burned on a copy of this repository's claims. Each planted defect is refused
with its own code; a clean copy, a supersession and a retirement pass. The cases run in
parallel, each on its own clone; report_selftest's groups run beside them."""
import argparse
import ast
import concurrent.futures
import copy
import difflib
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import warrant as W
from warrant import jcs as C
from warrant import records as R
from warrant.store import Store, Trust

from .base import (AUTHOR, BACKED_RESIDUAL, CLAIM, COUNTER, git, GIT_NO_GC, id_key, ID_RE, norm, Refused,
                   replace_wrapped, RETIRE, ROOT, sha, statement_for, WITNESSES)
from .bindings import binding_message, binding_proof, local_bindings, LOCAL_TRUST
from .repo import Repo
from .model import Model
from .counters import _replay_counter, challenge_table, LOWERS, STATEMENT_REFUSAL, THESIS
from .document import DOCUMENT, Document, DOCUMENT_RESIDUAL, HEADING, render_spec
from .views import cell, ledger, render, render_witnesses
from .check import check
from .author import Author, cmd_heading
from .audit import _mutant_patch
from .report_selftest import _audit_e2e, _audit_synthetic, why_selftest
from .cli import main


_CASE_RUNNER = None


def _run_registered_case(i):
    return _CASE_RUNNER(i)


def selftest(jobs=1):
    """Burns `check`: on a copy of this repository's claims, each defect must be refused
    with its own code, and the clean copy, a supersession and a retirement must pass."""
    work = Path(tempfile.mkdtemp(prefix="claims-selftest-"))
    try:
        fix = work / "base"
        (fix / "tests").mkdir(parents=True)
        for p in [ROOT / "SPEC.md", ROOT / "SPEC-CLAIMS.md", ROOT / WITNESSES]:
            shutil.copy2(p, fix / p.name)
        for p in sorted((ROOT / "tests").glob("*.py")):
            shutil.copy2(p, fix / "tests" / p.name)
        shutil.copytree(ROOT / ".warrant", fix / ".warrant")
        for pkg in ("warrant", "warrant_agent"):     # a counter blob's patch is replayed against them
            if (ROOT / pkg).is_dir():
                shutil.copytree(ROOT / pkg, fix / pkg, ignore=shutil.ignore_patterns("__pycache__"))
        repo = Repo(fix)
        # An ephemeral second key for the claim author. The first binding of an actor wins, so it
        # cannot be one of the repository's bindings: the selftest binds it as a receiver binds
        # keys for itself (WARRANT_CLAIMS_TRUST), outside the repository, for this process only.
        key = W.Key.generate()
        local = work / "local-trust.json"
        local.write_bytes(C.canon(Trust.document([(AUTHOR, key.public)])))
        os.environ[LOCAL_TRUST] = str(local)
        # No automatic gc or maintenance: a detached repack after the commit would move the
        # fixture's objects while a case is made from it (run 39537906378).
        g_cfg = ["-c", "user.name=claims-selftest", "-c", "user.email=selftest@invalid", "-c", "commit.gpgsign=false",
                 *GIT_NO_GC, "-c", "maintenance.auto=false"]
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, *g_cfg, "commit", "-q", "-m", "base")
        base = git(repo, "rev-parse", "HEAD").decode().strip()
        model = Model(repo.snapshot(), repo.trust())
        live = sorted((n for n in model.current.values() if n.backed), key=lambda n: id_key(n.id))
        if len(live) < 2:
            print("FAIL  selftest: the repository's store has fewer than two backed claims to work on")
            return 1
        a, b = live[0], live[-1]
        # `e`: a claim whose witnesses are records_test cases and whose mutants live outside jcs.py, so a
        # counter patch to jcs.py replays for it (some case fails, its witnesses pass) yet is not local.
        e = next((n for n in live if n.doc["witnesses"] and all(w.startswith("records_test:") for w in n.doc["witnesses"])
                  and "records_test:E2" not in n.doc["witnesses"] and n.doc["mutants"]
                  and all(sc[0] != "warrant/jcs.py" for mid in n.doc["mutants"] for sc in repo.mutant_scopes(mid))
                  and all(repo.mutant_scopes(mid) for mid in n.doc["mutants"])), None)
        if e is None:
            print("FAIL  selftest: no claim backed by records_test whose mutants live outside jcs.py")
            return 1
        # `g`: a claim whose mutants all live in one function of engine.py (SPEC-4.1-6, M02 in
        # engine._transfer_effect, when present): the target of Codex's reproduction on 0590956.
        def one_engine_scope(n):
            scs = {sc for mid in n.doc["mutants"] for sc in repo.mutant_scopes(mid)}
            return len(scs) == 1 and next(iter(scs))[0] == "warrant/engine.py" and next(iter(scs))[1] != "<module>"
        g = next((n for n in live if n.id == "SPEC-4.1-6" and one_engine_scope(n)), None) or \
            next((n for n in live if n.doc["mutants"] and one_engine_scope(n)), None)
        if g is None:
            print("FAIL  selftest: no claim whose mutants all alter one engine.py function")
            return 1
        # AMEND 1 of #169: counters are confined to the statements of one of the claim's mutants.
        # `sc`: SPEC-3.2-20, whose mutant M232 changes the statement of records._item that M234 changes
        # too (another rule on it): M234's patch is a counter that replays. `sw`: SPEC-3.6-7, whose
        # mutants change another statement of _counting_challenges than M29: that counter replayed
        # per function and is refused per statement.
        repo.mutants()
        m29_fails = ["conditions_test:K2"]
        live_ids = {n.id: n for n in live}
        sc, sw = live_ids.get("SPEC-3.2-20"), live_ids.get("SPEC-3.6-7")
        if sc is None or sw is None or not {"M234", "M29"} <= set(repo.mutant_edits) or not any(
                repo.mutant_statements("M234") <= repo.mutant_statements(m) for m in sc.doc["mutants"]):
            print("FAIL  selftest: SPEC-3.2-20 x M234 (one statement) or SPEC-3.6-7 x M29 is not in the fixture")
            return 1
        failures, ran = 0, []

        cases = []
        seed = work / "selftest.seed"
        seed.write_text(key.seed_hex() + "\n")

        def case(name, expect, mutate, also=None):
            """Register one case; all of them run later, `jobs` at a time (run_case).
            `mutate` may return a revision to check against instead of `base`; `also(r)`,
            when given, must hold as well (what the rendered files say)."""
            cases.append((name, expect, mutate, also))

        def run_case(i):
            """(ok, report line) of case `i`, on a clone of its own: cases share nothing but
            the read-only fixture, so they may run in parallel processes."""
            name, expect, mutate, also = cases[i]
            prior_local_trust = os.environ.get(LOCAL_TRUST)
            d = work / f"case-{i:03d}"
            # A clone through the pack protocol, never a copy of .git's files: copytree, and a
            # local clone (which copies objects/ too), fail with ENOENT if the fixture is
            # repacked meanwhile; --no-local reads objects through git, consistently.
            try:
                subprocess.run(["git", *GIT_NO_GC, "clone", "-q", "--no-local", str(fix), str(d)],
                               capture_output=True, check=True)
                r = Repo(d)
                against = mutate(r)
                against = against if isinstance(against, str) else base
                got = check(r, against)
                codes = {c for c, _ in got}
                ok = bool(((not got) if expect is None else expect in codes) and (also is None or also(r)))
                detail = f" | got {sorted(codes) or 'nothing'}: {got[:3]}"
            except Exception as ex:      # noqa: BLE001 -- a case that crashes is a failed case, not a crashed selftest
                ok, detail = False, f" | raised {type(ex).__name__}: {ex}"
            finally:
                if prior_local_trust is None:
                    os.environ.pop(LOCAL_TRUST, None)
                else:
                    os.environ[LOCAL_TRUST] = prior_local_trust
                shutil.rmtree(d, ignore_errors=True)
            what = "passes" if expect is None else f"refused {expect}"
            return ok, ("ok    " if ok else "FAIL  ") + f"{name}: {what}" + ("" if ok else detail)

        def author(r):
            return Author(r, key, AUTHOR, validate=False)

        def spec_edit(old, new):
            def f(r):
                r.spec.write_text(replace_wrapped(r.spec.read_text(), old, new))
            return f

        def reproject(r):
            m = Model(r.snapshot(), r.trust())
            doc = Document(m)
            if doc.current is not None:
                r.spec.write_bytes(render_spec(m, doc.current).encode())
            t = challenge_table(r, m)
            r.projection.write_bytes(render(r, m, t).encode())
            r.witnesses.write_bytes(render_witnesses(r, m, t).encode())

        def spec_text(r):
            return norm(r.spec.read_text())

        def doc_version(change, because="selftest"):
            """File a document version whose parts are `change(parts)` of the current ones."""
            def f(r):
                au = author(r)
                parts = copy.deepcopy(Document(Model(r.snapshot(), r.trust())).current["parts"])
                au.file_document(change(parts), because, au.at())
                reproject(r)
            return f

        def part_of(parts, cid):
            return next(i for i, q in enumerate(parts) if isinstance(q, dict) and q.get("claim") == cid)

        def rebacked(witnesses, mutants, unbacked_because=None, counter=None, claim=None):
            def f(r):
                cid = (claim or a).id
                n = Model(r.snapshot(), r.trust()).current[cid]
                ev = counter(r, n) if counter else ()
                author(r).claim(cid, n.doc["text"], witnesses, mutants, because="selftest", previous=n,
                                unbacked_because=unbacked_because, counter=ev)
                reproject(r)
            return f

        def challenge_of(target):
            def f(r, n):
                au = author(r)
                return [au.put("challenge", R.challenge(target(n), "selftest: the witness passes without the rule",
                                                        [Store(r.store_dir).put_blob(b"selftest: failing case")], 0), au.at())]
            return f

        def junk_blob(r, n):
            return [Store(r.store_dir).put_blob(b"lol\n")]

        # A counter blob against claim `a`: a patch that admits floats (records_test E2 fails)
        # while every witness `a` cites still passes. Variants break one requirement each.
        floats_old, floats_new = "    if isinstance(v, int):\n", "    if isinstance(v, float):\n        return repr(v)\n    if isinstance(v, int):\n"

        # A patch to jcs._check_text: lone surrogates reach the encoder (records_test E3 fails), in a
        # function of the same file that no mutant of `a` alters (its mutants alter _scalar, _push_container).
        surrogates_old, surrogates_new = '        raise NotCanonical("lone surrogate")', "        pass"

        def counter_doc(r, n, edit=None, **kv):
            old_text, new_text = edit or (floats_old, floats_new)
            src = (r.root / "warrant" / "jcs.py").read_text()
            patch = "".join(difflib.unified_diff(src.splitlines(True), src.replace(old_text, new_text, 1).splitlines(True),
                                                 "a/warrant/jcs.py", "b/warrant/jcs.py"))
            doc = {"counter": COUNTER, "claim": n.id, "against": n.tid, "patch": patch,
                   "passes": sorted(n.doc["witnesses"]), "fails": ["records_test:E2"],
                   "why": "selftest: floats admitted while the cited witnesses still pass"}
            doc.update(kv)
            return doc

        def counter(**kv):
            def f(r, n):
                return [Store(r.store_dir).put_json(counter_doc(r, n, **kv))]
            return f

        def challenge_carrying(**kv):
            def f(r, n):
                au = author(r)
                h = Store(r.store_dir).put_json(stmt_counter_doc(r, n, **kv))
                return [au.put("challenge", R.challenge(n.tid, "selftest: the witnesses pass without the rule", [h], 0), au.at())]
            return f

        def stmt_counter_doc(r, n, mid="M234", fails=("records_test:I5",), **kv):
            """A counter against `n` whose patch is mutant `mid`'s edit (default: M234 against SPEC-3.2-20)."""
            r.mutants()
            doc = {"counter": COUNTER, "claim": n.id, "against": n.tid, "patch": _mutant_patch(r, mid),
                   "passes": sorted(n.doc["witnesses"]), "fails": list(fails), "why": f"selftest: {mid}'s edit"}
            doc.update(kv)
            return doc

        def stmt_counter(**kv):
            def f(r, n):
                return [Store(r.store_dir).put_json(stmt_counter_doc(r, n, **kv))]
            return f

        def outside_patch(r, n):
            doc = counter_doc(r, n)
            doc["patch"] = doc["patch"].replace("a/warrant/jcs.py", "a/tests/world.py").replace("b/warrant/jcs.py", "b/tests/world.py")
            return [Store(r.store_dir).put_json(doc)]

        def witness_gone_at_base(r):
            """The witness case is renamed away in a commit of its own, which becomes the base;
            the downgrade comes after it."""
            for w in a.doc["witnesses"]:
                test, _, cid = w.partition(":")
                pth = r.tests / f"{test}.py"
                pth.write_text(pth.read_text().replace(f'"{cid}"', f'"{cid}gone"'))
            git(r, "add", "-A")
            git(r, *g_cfg, "commit", "-q", "-m", "the witness leaves first")
            rev = git(r, "rev-parse", "HEAD").decode().strip()
            rebacked([], [], unbacked_because="selftest: its witness case was removed earlier")(r)
            return rev

        def retext(cid, text):
            """Supersede claim `cid` with `text` (no validation), then project."""
            def f(r):
                n = Model(r.snapshot(), r.trust()).current[cid]
                author(r).claim(cid, text, n.doc["witnesses"], n.doc["mutants"], n.doc["reason"] if n.kind == "informative" else None,
                                because="selftest", previous=n,
                                unbacked_because=n.doc["reason"] if n.kind == "normative" and not n.backed else None)
                reproject(r)
            return f

        def head_of(parts, sec):
            return next(k for k, q in enumerate(parts) if isinstance(q, dict) and "heading" in q
                        and HEADING.match(q["heading"]) and HEADING.match(q["heading"]).group(1) == sec)

        def heading_through_pin(r):
            pins = r.pins()
            pins["headings"]["2"] = "## 2. Encoding of values"
            r.write_pins(pins)
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_heading(r, argparse.Namespace(key=str(seed), actor=AUTHOR, section="2", because="selftest: a renamed heading"))
            reproject(r)

        def document_fork(r):
            au = author(r)
            d = Document(Model(r.snapshot(), r.trust()))
            prev = {"transition": d.tid, "sha256": d.nodes[d.tid][1]}
            for k in (1, 2):
                h = au.store.put_json({"schema": DOCUMENT, "source": "SPEC.md", "parts": d.current["parts"],
                                       "because": f"selftest fork {k}", "previous": prev})
                au.put("transition", R.transition("ATTESTED", [h], residual=[DOCUMENT_RESIDUAL],
                                                  supersedes=[d.tid]), au.at() + k)
            reproject(r)

        def document_bad_previous(r):
            au = author(r)
            d = Document(Model(r.snapshot(), r.trust()))
            h = au.store.put_json({"schema": DOCUMENT, "source": "SPEC.md", "parts": d.current["parts"],
                                   "because": "selftest", "previous": {"transition": a.tid, "sha256": d.nodes[d.tid][1]}})
            au.put("transition", R.transition("ATTESTED", [h], residual=[DOCUMENT_RESIDUAL], supersedes=[a.tid]), au.at())
            reproject(r)

        def control_text(r):
            n = Model(r.snapshot(), r.trust()).current[a.id]
            author(r).claim(a.id, n.doc["text"].replace(" ", " \x00", 1), n.doc["witnesses"], n.doc["mutants"],
                            because="selftest", previous=n)
            reproject(r)

        def delete_document(r):
            m = Model(r.snapshot(), r.trust())
            for rid in Document(m).nodes:
                (r.store_dir / "records" / f"{rid}.json").unlink()
            reproject(r)

        def witness_gone(r):
            for w in a.doc["witnesses"]:
                test, _, cid = w.partition(":")
                pth = r.tests / f"{test}.py"
                pth.write_text(pth.read_text().replace(f'"{cid}"', f'"{cid}gone"'))
            rebacked([], [], unbacked_because="selftest: its witness case was removed")(r)

        def own_sentence_blob(r, n):
            return [sha(n.doc["text"])]

        def new_open_question(reason):
            def f(r):
                text = "An open rule is stated here."
                cid = f"SPEC-{b.doc['section']}-{id_key(b.id)[1] + 1000}"
                author(r).claim(cid, text, unbacked_because=reason, after=b.id)
                reproject(r)
            return f

        def edit_harness(name, old, new):
            def f(r):
                pth = r.tests / name
                src = pth.read_text()
                assert src.count(old) == 1, (name, old)
                pth.write_text(src.replace(old, new))
            return f

        def duplicate_mutant(r):
            p = r.tests / "mutants.py"
            src = p.read_text()
            mid = a.doc["mutants"][0]
            other = next(i for i in re.findall(r'\("(M[0-9]+)", ', src) if i != mid)
            p.write_text(src.replace(f'("{other}", ', f'("{mid}", ', 1))

        def rename(r):
            p = sorted((r.store_dir / "records").iterdir())[0]
            p.rename(p.with_name(hashlib.sha256(p.name.encode()).hexdigest() + ".json"))
            reproject(r)

        def noncanonical(r):
            p = r.store_dir / "records" / f"{a.tid}.json"
            p.write_text(json.dumps(json.loads(p.read_text()), indent=1))
            reproject(r)

        def delete_claim(r):
            for rid in {n.tid for n in Model(r.snapshot(), r.trust()).by_id[b.id]} | {b.doc["duty"]}:
                (r.store_dir / "records" / f"{rid}.json").unlink()
            reproject(r)

        def hand_edit(r):
            s = r.projection.read_text()
            r.projection.write_text(s.replace("| BACKED |", "| BACKED (reviewed) |", 1))

        def challenge(r):
            author(r).put("challenge", R.challenge(a.tid, "selftest: a standing counterexample", [], 0), author(r).at())
            reproject(r)

        def unpin(r):
            p = r.pins()
            del p["sentences"][b.id]
            r.write_pins(p)

        def add_sentence(r):
            spec_edit(b.doc["text"], b.doc["text"] + " An unclaimed rule appears here.")(r)

        amended = a.doc["text"] + " (as amended)"

        def supersede(r):
            n = Model(r.snapshot(), r.trust()).current[a.id]
            author(r).claim(a.id, amended, n.doc["witnesses"], n.doc["mutants"], because="selftest amendment", previous=n)
            reproject(r)

        def supersede_rendered(r):
            t = spec_text(r)
            return norm(amended) in t and t.count(norm(a.doc["text"])) == t.count(norm(amended))

        def retire(r):
            ev = Store(r.store_dir).put_blob(b"selftest: the sentence leaves SPEC.md")
            author(r).retire(b.id, "selftest: the sentence leaves SPEC.md", ev)
            reproject(r)

        def retire_rendered(r):
            m = Model(r.snapshot(), r.trust())
            history = [n for n in m.by_id[b.id] if not n.retired]
            return (norm(b.doc["text"]) not in spec_text(r) and m.current[b.id].retired and history
                    and all((r.store_dir / "records" / f"{n.tid}.json").is_file() for n in history)
                    and cell(b.doc["text"]) in r.projection.read_text().split("## Retired", 1)[1])

        inserted = "A new sentence is inserted here."
        new_id = f"SPEC-{a.doc['section']}-{id_key(a.id)[1] + 1000}"

        def insert(r):
            author(r).claim(new_id, inserted, unbacked_because="selftest: placed, not yet backed", after=a.id)
            reproject(r)

        def insert_rendered(r):
            return norm(a.doc["text"] + " " + inserted) in spec_text(r)

        def unretired_removal(r):
            spec_edit(b.doc["text"], "")(r)

        def newline_id(r):
            # AMEND 2 of #164: while ID_RE ended in `$`, an id with a trailing newline passed
            # `.match`; a claim filed under one, with a duty of its own and pinned, was accepted
            au = author(r)
            cid, text = a.id + "\n", a.doc["text"]
            at = au.at()
            au.store.put_blob(text.encode())
            duty = au.put("duty", R.duty(AUTHOR, statement_for(cid, text), au.pins["owed_to"], {"attest": {}},
                                         accept_by=au.pins["accept_by"], subject=sha(text)), at)
            doc = {"schema": CLAIM, "id": cid, "source": "SPEC.md", "section": a.doc["section"], "text": text,
                   "kind": "normative", "duty": duty, "witnesses": a.doc["witnesses"], "mutants": a.doc["mutants"],
                   "reason": None, "because": None, "previous": None}
            h = au.store.put_json(doc)
            au.put("transition", R.transition("ATTESTED", [h], closes=[R.item(duty, "discharge", [h])],
                                              established=[text], residual=[BACKED_RESIDUAL]), at)
            p = r.pins()
            p["sentences"][cid] = "normative"
            r.write_pins(p)
            reproject(r)

        def target_unknown(r):
            pth = r.tests / "agent_mutants.py"
            src = pth.read_text()
            i = src.index('("A28", ')
            j = src.index('"agent_handoff_test", ["V09"]', i)
            pth.write_text(src[:j] + '"agent_handoff_test", ["V09", "Z99"]' + src[j + len('"agent_handoff_test", ["V09"]'):])
            rebacked(["agent_handoff_test:V09"], ["A28"])(r)

        case("clean copy", None, lambda r: None)
        # W5: SPEC.md is the rendering of the records; nothing in it is written by hand
        case("SPEC.md edited by hand: a sentence changed", "SPEC_NOT_PROJECTION", spec_edit(a.doc["text"], "Something else entirely."))
        case("SPEC.md edited by hand: layout only (a line break joined)", "SPEC_NOT_PROJECTION",
             lambda r: r.spec.write_text(r.spec.read_text().replace(".\n", ". ", 1)))
        case("SPEC.md with \\r\\n line ends", "SPEC_NOT_PROJECTION",
             lambda r: r.spec.write_bytes(r.spec.read_bytes().replace(b"\n", b"\r\n")))
        case("SPEC-CLAIMS.md with \\r\\n line ends", "PROJECTION_STALE",
             lambda r: r.projection.write_bytes(r.projection.read_bytes().replace(b"\n", b"\r\n")))
        case("a supersede + project round trip", None, supersede, also=supersede_rendered)
        case("a new sentence inserted at a position renders there", None, insert, also=insert_rendered)
        case("a retired sentence leaves SPEC.md, stays in the store and in SPEC-CLAIMS.md", None, retire, also=retire_rendered)
        case("a cited mutant that does not exist", "UNKNOWN_MUTANT", rebacked(a.doc["witnesses"], ["M999"]))
        case("a cited case that does not exist", "UNKNOWN_CASE", rebacked(["contract_test:Z9"], a.doc["mutants"]))
        case("a mutant that burns none of the cited cases", "MUTANT_OFF_WITNESS", rebacked(["contract_test:A1"], ["M19"]))
        # W4: UNBACKED is an allowed open question, with guards
        case("a new sentence filed UNBACKED with its reason", None, new_open_question("selftest: no case reaches it"))
        case("an UNBACKED claim without a reason", "UNBACKED_WITHOUT_REASON", new_open_question(None))
        case("a BACKED claim superseded UNBACKED without counter-evidence", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked(a.doc["witnesses"], [], unbacked_because="selftest"))
        # AMEND 1: the counter-evidence must be a counter blob that replays, not any blob or challenge
        case("a BACKED claim superseded UNBACKED citing a counter-file of junk bytes", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=junk_blob))
        case("a BACKED claim superseded UNBACKED citing a challenge alone", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=challenge_of(lambda n: n.tid)))
        case("a counter blob that replays (its patch changes only a statement a cited mutant changes)", None,
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(), claim=sc))
        # AMEND 1 of #169: per function, M29 was a counter against SPEC-3.6-7; per statement it is not
        case("a counter confined to the claim's function but to another statement (SPEC-3.6-7 by M29)", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", claim=sw,
                      counter=stmt_counter(mid="M29", fails=m29_fails)))
        case("the floats counter: an inserted statement in a function a cited mutant changes", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=counter()))
        # AMEND 2: the patch must alter code the claim's own mutants alter
        case("a counter patch in a module the claim's mutants do not touch", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=counter(), claim=e))
        case("a counter patch in another function of the same file", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest",
                      counter=counter(edit=(surrogates_old, surrogates_new), fails=["records_test:E3"])))
        # AMEND 4: a scope changes only if its AST does, and every changed scope must be the claim's
        # mutants' (Codex on 0590956: a comment in M02's function let a foreign JCS break through).
        def scope_edit(r, how):
            """A diff that changes `g`'s mutant function in the fixture as `how` says."""
            (path, qual), = {sc for mid in g.doc["mutants"] for sc in r.mutant_scopes(mid)}
            src = (r.root / path).read_text()
            node = next(x for x in ast.walk(ast.parse(src)) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and x.name == qual.split(".")[-1])
            lines = src.splitlines(True)
            at = node.body[0].lineno - 1
            indent = lines[at][:len(lines[at]) - len(lines[at].lstrip())]
            doc = isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str)
            if how == "docstring" and doc:
                lines[at] = lines[at].replace('"""', '"""Selftest. ', 1)
            else:
                lines.insert(at, indent + {"comment": "# selftest marker: no behavioural change", "blank": "   ",
                                           "docstring": '"""Selftest docstring."""', "assign": "_selftest_unused = 1"}[how] + "\n")
            return "".join(difflib.unified_diff(src.splitlines(True), lines, f"a/{path}", f"b/{path}"))

        def foreign_break(r):
            """Codex's foreign hunk: jcs admits floats (records_test E2 fails)."""
            src = (r.root / "warrant" / "jcs.py").read_text()
            new = src.replace(floats_old, floats_new, 1).replace("parse_constant=_constant, parse_float=_float)",
                                                                  "parse_constant=_constant)", 1)
            return "".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), "a/warrant/jcs.py", "b/warrant/jcs.py"))

        def g_counter(how, foreign=True):
            def f(r, n):
                doc = {"counter": COUNTER, "claim": n.id, "against": n.tid,
                       "patch": (foreign_break(r) if foreign else "") + scope_edit(r, how),
                       "passes": sorted(n.doc["witnesses"]), "fails": ["records_test:E2"], "why": "selftest"}
                return [Store(r.store_dir).put_json(doc)]
            return f

        for name, how, foreign in (
                ("Codex's shape: a foreign float break plus a comment inside the mutant's function", "comment", True),
                ("a foreign break plus a whitespace-only line inside the mutant's function", "blank", True),
                ("a foreign break plus a docstring-only change inside the mutant's function", "docstring", True),
                ("a foreign hunk plus a behaviour-neutral AST change inside the mutant's function", "assign", True),
                ("a patch whose only change is AST-equal inside the mutant's function", "comment", False)):
            case(name, "COUNTER_NOT_REPLAYED",
                 rebacked([], [], unbacked_because="selftest", counter=g_counter(how, foreign), claim=g))
        case("a challenge carrying a counter blob that replays", None,
             rebacked([], [], unbacked_because="selftest", counter=challenge_carrying(), claim=sc))
        case("a counter blob whose passes omits a cited witness", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(passes=[]), claim=sc))
        case("a counter blob whose fails case passes under the patch", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(fails=["records_test:E3"]), claim=sc))
        case("a counter blob with an empty patch (nothing fails)", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(patch=""), claim=sc))
        case("a counter blob against another claim", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(against=b.tid), claim=sc))
        case("a counter blob whose patch reaches outside the packages", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=outside_patch))
        case("a challenge carrying a counter blob that does not replay", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=challenge_carrying(fails=["records_test:E3"]), claim=sc))
        # W5: route 1 is admitted only when the witness was already gone at the base
        case("a BACKED claim superseded UNBACKED in the change that removes its witness", "WITNESS_REMOVED_WITH_DOWNGRADE",
             witness_gone)
        case("a BACKED claim superseded UNBACKED whose witness was already absent at the base", None, witness_gone_at_base)
        case("a BACKED claim superseded UNBACKED citing a challenge against another record", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=challenge_of(lambda n: n.doc["duty"])))
        case("a BACKED claim superseded UNBACKED citing only its own sentence", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=own_sentence_blob))
        case("a normative sentence without a mutant and without a reason", "UNBACKED_WITHOUT_REASON",
             rebacked(a.doc["witnesses"], []))
        # W4: mutants of tests/agent_mutants.py are citable, in their own namespace
        case("an agent mutant cited with the case it targets", None, rebacked(["agent_handoff_test:V09"], ["A28"]))
        case("an agent mutant that burns none of the cited cases", "MUTANT_OFF_WITNESS",
             rebacked(["contract_test:A1"], ["A28"]))
        case("a mutant id defined in both harnesses", "MUTANT_ID_COLLISION",
             edit_harness("agent_mutants.py", '("A28", ', f'("{a.doc["mutants"][0]}", '))
        case("an agent harness id without its prefix", "MUTANT_ID_PREFIX",
             edit_harness("agent_mutants.py", '("A28", ', '("M9999", '))
        case("a cited mutant whose target is not a case of an existing test file", "MUTANT_TARGET_UNKNOWN", target_unknown)
        case("a cited mutant id defined twice", "DUPLICATE_MUTANT_ID", duplicate_mutant)
        case("a record file renamed", "RECORD_MISNAMED", rename)
        case("a record rewritten in non-canonical bytes", "NOT_CANONICAL", noncanonical)
        case("a claim deleted without a retiring record", "CLAIM_DELETED", delete_claim)
        case("the projection edited by hand", "PROJECTION_STALE", hand_edit)
        case("a standing challenge against a current claim", "CHALLENGED", challenge)
        case("a pinned sentence unpinned without retirement", "UNPINNED_WITHOUT_RETIREMENT", unpin)
        case("a new sentence in SPEC.md with no claim", "SPEC_NOT_PROJECTION", add_sentence)
        case("a sentence removed from SPEC.md, its claim not retired", "SPEC_NOT_PROJECTION", unretired_removal)
        # W5: the document record's own guards, each with SPEC.md re-rendered so only the guard refuses
        case("prose smuggled into a document literal", "DOCUMENT_LITERAL",
             doc_version(lambda ps: ps[:1] + [" Every actor may sign for every other. "] + ps[1:]))
        case("a digit glued to a sentence by a literal", "DOCUMENT_LITERAL",
             doc_version(lambda ps: ps[:part_of(ps, b.id) + 1] + ["0"] + ps[part_of(ps, b.id) + 1:]))
        case("prose smuggled into a layout run", "STRUCTURE", doc_version(
            lambda ps: [dict(q, layout={"sha256": q["layout"]["sha256"], "gaps": [[0, " and nobody checks "]]})
                        if isinstance(q, dict) and q.get("claim") == a.id else q for q in ps]))
        case("a heading line with a trailing newline", "STRUCTURE",
             doc_version(lambda ps: [{"heading": q["heading"] + "\n"} if isinstance(q, dict) and "heading" in q and k == 0 else q
                                     for k, q in enumerate(ps)]))
        case("a document version that leaves out a current claim", "CLAIM_NOT_IN_DOCUMENT",
             doc_version(lambda ps: ps[:part_of(ps, b.id)] + ps[part_of(ps, b.id) + 1:]))
        case("a document version that places a claim twice", "DOCUMENT_CLAIM_TWICE",
             doc_version(lambda ps: ps + [" ", copy.deepcopy(ps[part_of(ps, b.id)])]))
        case("a document version that names a claim no record states", "DOCUMENT_UNKNOWN_CLAIM",
             doc_version(lambda ps: ps[:part_of(ps, b.id) + 1] + [" ", {"claim": b.id[:-1] + "9999", "layout": None}]
                         + ps[part_of(ps, b.id) + 1:]))
        case("a document version that moves a claim under another section's heading", "DOCUMENT_SECTION",
             doc_version(lambda ps: [q for q in ps if q != ps[part_of(ps, a.id)]] + [" ", ps[part_of(ps, a.id)]]))
        case("a document version without a pinned section's heading", "SECTION_MISSING",
             doc_version(lambda ps: [q for q in ps if not (isinstance(q, dict) and q.get("heading", "").startswith(
                 f"## {a.doc['section']}. "))]))
        case("two current document versions", "DOCUMENT_FORK", document_fork)
        # AMEND 1 of #166: headings are pinned; a heading is free text no witness backs
        case("the parent's probe: an unnumbered heading carrying a rule, after §4.2's", "DOCUMENT_HEADING",
             doc_version(lambda ps: ps[:head_of(ps, "4.2") + 1]
                         + ["\n\n", {"heading": "#### Any holder may discharge any duty without acceptance"}]
                         + ps[head_of(ps, "4.2") + 1:]))
        case("a numbered heading for a section the pins do not name", "DOCUMENT_HEADING",
             doc_version(lambda ps: ps[:head_of(ps, "5")] + [{"heading": "### 4.8 Exceptions"}, "\n\n"] + ps[head_of(ps, "5"):]))
        case("a pinned section's heading with its title altered", "DOCUMENT_HEADING",
             doc_version(lambda ps: [{"heading": q["heading"] + ": floats are allowed"} if k == head_of(ps, "2") else q
                                     for k, q in enumerate(ps)]))
        case("a second heading for a pinned section", "DOCUMENT_HEADING",
             doc_version(lambda ps: ps[:head_of(ps, "2") + 1] + ["\n\n", copy.deepcopy(ps[head_of(ps, "2")])]
                         + ps[head_of(ps, "2") + 1:]))
        case("two pinned headings swapped out of order", "DOCUMENT_HEADING",
             doc_version(lambda ps: [ps[head_of(ps, "3.6")] if k == head_of(ps, "3.5") else
                                     ps[head_of(ps, "3.5")] if k == head_of(ps, "3.6") else q for k, q in enumerate(ps)]))
        # AMEND 2 of #166 (Codex on 64af5aa): a heading part must render as a heading
        case("Codex's probe: the gap before §3.1's heading replaced by a space (the heading renders inline)",
             "DOCUMENT_HEADING", doc_version(lambda ps: [" " if k == head_of(ps, "3.1") - 1 else q for k, q in enumerate(ps)]))
        case("a heading glued to the previous sentence (no gap at all)", "DOCUMENT_HEADING",
             doc_version(lambda ps: [q for k, q in enumerate(ps) if k != head_of(ps, "6") - 1]))
        case("a heading followed by a sentence on the same line", "DOCUMENT_HEADING",
             doc_version(lambda ps: [" " if k == head_of(ps, "5") + 1 else q for k, q in enumerate(ps)]))
        case("a sentence that renders as an ATX heading line", "SPEC_HEADINGS_MISMATCH",
             retext("SPEC-3-4", "## 4.8 Hidden rule: anyone may release"))
        case("a sentence that renders as a setext underline", "SPEC_HEADINGS_MISMATCH", retext("SPEC-3-4", "---"))
        case("a heading changed through its pin, then `heading --section`", None, heading_through_pin,
             also=lambda r: "## 2. Encoding of values\n" in r.spec.read_text())
        case("a document version whose previous is not a document version", "STRUCTURE", document_bad_previous)
        case("a claim text with a control character (U+0000 would vanish from SPEC.md)", "STRUCTURE", control_text)
        case("the document records deleted", "DOCUMENT_MISSING", delete_document)
        case("a claim id with a trailing newline", "STRUCTURE", newline_id)

        # Open circle of witnesses. A: a binding certifies itself; B: acceptance by the named acceptor;
        # C: a counter from anyone lowers backing, never authorship; D: the ledger is a checked view.
        def set_role(r, actor, value):
            doc = json.loads(r.roles_path.read_text())
            doc["actors"][actor] = value
            r.roles_path.write_text(json.dumps(doc, indent=2) + "\n")

        def bind_entry(r, actor, k, proof=None, first=False, pin=False):
            """Append (or put first) `actor`'s binding of key `k`; `pin` also pins its role to `k`."""
            if pin:
                set_role(r, actor, k.public)
            doc = C.loads(r.trust_path.read_bytes())
            e = {"actor": actor, "public": k.public, "proof": binding_proof(k, actor) if proof is None else proof}
            doc["keys"] = [e] + doc["keys"] if first else doc["keys"] + [e]
            r.trust_path.write_bytes(C.canon(doc))

        def binding(actor="stranger", proof=None, first=False, signer=None):
            """A newcomer's binding; `signer` signs the proof instead of the bound key (and is bound itself)."""
            def f(r):
                k = W.Key.generate()
                if signer:
                    s = W.Key.generate()
                    bind_entry(r, signer, s)
                    proof_ = s.sign(binding_message(actor, k.public))
                else:
                    proof_ = proof
                bind_entry(r, actor, k, proof_, first)
                reproject(r)
            return f

        def raw_claim(r, k, actor, n, text, accept_by=None, cid=None):
            """A claim transition filed by `actor` with no tool guard: superseding `n` (or new, as `cid`)."""
            st = Store(r.store_dir)
            at = author(r).at()
            pins = r.pins()
            cid = cid or n.id
            st.put_blob(text.encode())
            duty = st.put_record(R.record("duty", actor, at, R.duty(actor, statement_for(cid, text), pins["owed_to"],
                                                                     {"attest": {}}, accept_by=pins["accept_by"] if accept_by is None
                                                                     else accept_by, subject=sha(text))), k)
            prev = None if n is None else {"transition": n.tid, "duty": n.doc["duty"], "statement_sha256": sha(n.doc["text"])}
            doc = {"schema": CLAIM, "id": cid, "source": "SPEC.md", "section": ID_RE.match(cid).group(1), "text": text,
                   "kind": "normative", "duty": duty, "witnesses": a.doc["witnesses"], "mutants": a.doc["mutants"],
                   "reason": None, "because": None if n is None else "selftest: a stranger rewrites it", "previous": prev}
            h = st.put_json(doc)
            return st.put_record(R.record("transition", actor, at, R.transition(
                "ATTESTED", [h], closes=[R.item(duty, "discharge", [h])], established=[text], residual=[BACKED_RESIDUAL],
                supersedes=[] if n is None else [n.tid])), k)

        def stranger_supersedes(r):
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            n = Model(r.snapshot(), r.trust()).current[a.id]
            raw_claim(r, k, "stranger", n, n.doc["text"] + " (as the stranger has it)")
            reproject(r)

        def stranger_retires(r):
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            n = Model(r.snapshot(), r.trust()).current[b.id]
            st, at = Store(r.store_dir), author(r).at()
            ev = st.put_blob(b"selftest: the stranger wants it gone")
            ch = st.put_record(R.record("challenge", "stranger", at, R.challenge(n.tid, "selftest", [ev], 0)), k)
            doc = {"schema": RETIRE, "id": b.id, "because": "selftest: gone", "counter": ev, "challenge": ch,
                   "previous": {"transition": n.tid, "duty": n.doc["duty"], "statement_sha256": sha(n.doc["text"])}}
            h = st.put_json(doc)
            st.put_record(R.record("transition", "stranger", at, R.transition(
                "ATTESTED", sorted({ev, ch, h}), established=[f"{b.id} is retired"], supersedes=[n.tid])), k)
            reproject(r)

        def stranger_document(r):
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            d = Document(Model(r.snapshot(), r.trust()))
            st = Store(r.store_dir)
            h = st.put_json({"schema": DOCUMENT, "source": "SPEC.md", "parts": d.current["parts"], "because": "selftest",
                             "previous": {"transition": d.tid, "sha256": d.nodes[d.tid][1]}})
            st.put_record(R.record("transition", "stranger", author(r).at(), R.transition(
                "ATTESTED", [h], residual=[DOCUMENT_RESIDUAL], supersedes=[d.tid])), k)
            reproject(r)

        def stranger_claim_without_acceptor(r):
            """The stranger's duty names its own accomplice as acceptor, not the pinned one (records
            refuse an attested duty with no acceptor besides its holder)."""
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            cid = f"SPEC-{b.doc['section']}-{id_key(b.id)[1] + 2000}"
            raw_claim(r, k, "stranger", None, "A rule only my accomplice has to accept.", accept_by=["accomplice"], cid=cid)
            reproject(r)

        def challenge_by(actor, counter_kv=None, claim=None, pin=False):
            """`actor` binds a fresh key in this change and challenges `claim` (default SPEC-3.2-20),
            carrying a counter (stmt_counter_doc with `counter_kv`) when given."""
            def f(r):
                k = W.Key.generate()
                bind_entry(r, actor, k, pin=pin)
                n = Model(r.snapshot(), r.trust()).current[(claim or sc).id]
                ev = [] if counter_kv is None else [Store(r.store_dir).put_json(stmt_counter_doc(r, n, **counter_kv))]
                Store(r.store_dir).put_record(R.record("challenge", actor, author(r).at(), R.challenge(
                    n.tid, "selftest: the witnesses pass without the rule", ev, 0)), k)
                reproject(r)
            return f

        def lowered_by(actor, cid, kind):
            def f(r):
                m = Model(r.snapshot(), r.trust())
                t = challenge_table(r, m)
                rows = ledger(m, t, r.bindings()[0])
                mine = [x for x in t.values() if x["actor"] == actor and x["claim"] == cid]
                line = next(ln for ln in r.projection.read_text().splitlines() if ln.startswith(f"| {cid} |"))
                status = line.split(" | ")[4]
                if kind == LOWERS:
                    return ([x["kind"] for x in mine] == [LOWERS] and status.startswith("COUNTERED")
                            and len(rows[actor]["now"]) == 1 and len(rows[actor]["counters"]) == 1)
                return [x["kind"] for x in mine] == [kind] and status.startswith("BACKED") and not rows[actor]["now"]
            return f

        acceptance_fixture = {}

        def accepted_by_codex(r):
            """Accept with an ephemeral receiver-local key, without rotating an existing codex binding.
            A real codex binding and its signed records may already be in the copied store."""
            k = W.Key.generate()
            local_c = r.root.parent / f"{r.root.name}-codex-trust.json"
            local_c.write_bytes(C.canon(Trust.document(local_bindings() + [("codex", k.public)])))
            os.environ[LOCAL_TRUST] = str(local_c)     # run_case restores it after check and also()
            acceptance_fixture[r.root.name] = {rid for rid, rec in Model(r.snapshot(), r.trust()).recs.items()
                                               if rec["type"] == "accept" and rec["actor"] == "codex"}
            # G4: a BACKED claim's duty names the replay checker. A duty that codex accepts is one filed
            # where the pins adopt no checker; `a` moves to such a duty first (a supersession, same sentence).
            au = author(r)
            au.acceptors = lambda backed: list(au.pins["accept_by"])     # the pins themselves stay as they are
            cur = Model(r.snapshot(), r.trust()).current[a.id]
            au.claim(a.id, cur.doc["text"], cur.doc["witnesses"], cur.doc["mutants"],
                     because="selftest: a duty codex accepts", previous=cur)
            seed_c = r.root / ".." / f"{r.root.name}-codex.seed"
            seed_c.write_text(k.seed_hex() + "\n")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--root", str(r.root), "accept", "--key", str(seed_c), "--actor", "codex", "--claim", a.id])
            seed_c.unlink()
            reproject(r)
            assert rc == 0, rc

        def shows_accepted(r):
            line = next(ln for ln in r.projection.read_text().splitlines() if ln.startswith(f"| {a.id} |"))
            m = Model(r.snapshot(), r.trust())
            rows = ledger(m, {}, r.bindings()[0])
            before, after = acceptance_fixture[r.root.name], set(rows["codex"]["accepts"])
            added = after - before
            return ("| DISCHARGED (accepted by codex) |" in line and before <= after and len(added) == 1
                    and m.recs[next(iter(added))]["body"]["transition"] == m.current[a.id].tid)

        squat = {}
        squat_accepts = {}

        def squatter_takes_codex(r):
            """The parent's reproduction on fad382f: a fresh key binds `codex` through the CLI and
            accepts a claim. The binding is written by hand here (bind refuses it now)."""
            k = W.Key.generate()
            squat_accepts[r.root.name] = {rid for rid, rec in Model(r.snapshot(), r.trust()).recs.items()
                                         if rec["type"] == "accept" and rec["actor"] == "codex"}
            bind_entry(r, "codex", k)
            seed_s = r.root / ".." / f"{r.root.name}-squatter.seed"
            seed_s.write_text(k.seed_hex() + "\n")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                squat[r.root.name] = (main(["--root", str(r.root), "bind", "--key", str(seed_s), "--actor", "codex"]),
                                      main(["--root", str(r.root), "accept", "--key", str(seed_s), "--actor", "codex",
                                            "--claim", a.id]))
            seed_s.unlink()
            reproject(r)

        def squatter_refused(r):
            m = Model(r.snapshot(), r.trust())
            return (squat.get(r.root.name) == (2, 2)
                    and {rid for rid, rec in m.recs.items() if rec["type"] == "accept" and rec["actor"] == "codex"}
                    == squat_accepts[r.root.name])

        def pin_against_claude(r):
            set_role(r, AUTHOR, W.Key.generate().public)

        def drop_role(r):
            doc = json.loads(r.roles_path.read_text())
            del doc["actors"]["codex"]
            r.roles_path.write_text(json.dumps(doc) + "\n")

        def legacy_trust(r):
            doc = C.loads(r.trust_path.read_bytes())
            r.trust_path.write_bytes(C.canon(Trust.document([(x["actor"], x["public"]) for x in doc["keys"]])))

        def unproven(r):
            doc = C.loads(r.trust_path.read_bytes())
            doc["keys"].append({"actor": "stranger", "public": W.Key.generate().public})
            r.trust_path.write_bytes(C.canon(doc))

        def drop_claude_binding(r):
            doc = C.loads(r.trust_path.read_bytes())
            doc["keys"] = [x for x in doc["keys"] if x["actor"] != AUTHOR]
            r.trust_path.write_bytes(C.canon(doc))
            binding("stranger")(r)

        case("A: a newcomer binds a fresh key with its proof", None, binding("stranger"))
        case("A: a binding whose proof is forged", "BINDING_PROOF_FORGED", binding("stranger", proof="00" * 64))
        case("A: a binding whose proof another key signed", "BINDING_PROOF_OTHER_KEY", binding("victim", signer="mallory"))
        case("A: a newcomer binds the actor id claude to its own key (pinned role)", "BINDING_ROLE_KEY", binding(AUTHOR))
        case("A: two newcomers bind one unpinned name, the second with another key", "BINDING_ACTOR_TAKEN",
             lambda r: (binding("newcomer")(r), binding("newcomer")(r)))
        case("A: an actor id failing SPEC-3-21 (a trailing newline)", "BINDING_ACTOR_SHAPE", binding("stranger\n"))
        case("A: an actor id failing SPEC-3-21 (white space at an end)", "BINDING_ACTOR_SHAPE", binding(" stranger"))
        case("A: a binding with no proof", "BINDING_UNPROVEN", unproven)
        case("A: the trust file as trust/2, without proofs", "BINDINGS_SHAPE", legacy_trust)
        case("A: claude's binding removed (a newcomer's added instead)", "BINDING_REMOVED", drop_claude_binding)
        case("A: a newcomer's claude binding put before the one at the base", "BINDING_ROLE_KEY", binding(AUTHOR, first=True))
        # AMEND 1 of #170 (parent's reproduction on fad382f): a name with a role is pinned, not first-come
        case("A1: a squatter binds codex with its own key and accepts: refused, nothing accepted", "BINDING_ROLE_KEY",
             squatter_takes_codex, also=squatter_refused)
        case("A1: a squatter binds s0fractal (reserved)", "BINDING_ROLE_RESERVED", binding("s0fractal"))
        case("A1: anyone binds readers (a collective role)", "BINDING_ROLE_COLLECTIVE", binding("readers"))
        case("A1: a fresh pinned role binds with the key its pin names", None,
             lambda r: (bind_entry(r, "selftest-pinned-role", W.Key.generate(), pin=True), reproject(r)))
        case("A1: a pin change that contradicts claude's admitted binding", "ROLE_PIN_CONFLICT", pin_against_claude)
        case("A1: a role named in .warrant/claims.json and missing from .warrant/roles.json", "ROLE_UNPINNED", drop_role)
        case("A1: a role pinned to something that is not a key, null or collective", "ROLES_SHAPE",
             lambda r: set_role(r, "codex", "anyone"))
        case("B: codex accepts with a receiver-local fixture key; the view names the acceptor", None, accepted_by_codex, also=shows_accepted)
        case("C: a newcomer binds in this change and files a counter that replays: admitted, backing lowered", None,
             challenge_by("stranger", {}), also=lowered_by("stranger", "SPEC-3.2-20", LOWERS))
        case("C: a newcomer files a counter that does not replay", "COUNTER_NOT_REPLAYED",
             challenge_by("stranger", {"fails": ["records_test:E3"]}))
        case("C: a newcomer's challenge without a counter: admitted, lowers and blocks nothing", None,
             challenge_by("stranger"), also=lowered_by("stranger", "SPEC-3.2-20", THESIS))
        # The acceptor its duty names: the replay checker for a BACKED claim since G4 (codex before).
        acceptor = model.recs[sc.doc["duty"]]["body"]["accept_by"][0]
        case("C: the acceptor's challenge without a counter stands", "CHALLENGED", challenge_by(acceptor, pin=True))
        case("C: a newcomer supersedes claude's claim", "LINEAGE_NOT_AUTHOR", stranger_supersedes)
        case("C: a newcomer retires claude's claim", "LINEAGE_NOT_AUTHOR", stranger_retires)
        case("C: a newcomer files the next document version", "LINEAGE_NOT_AUTHOR", stranger_document)
        case("C: a newcomer files a claim whose duty names its own acceptor", "CLAIM_DUTY_TERMS", stranger_claim_without_acceptor)
        case("D: WITNESSES.md edited by hand", "WITNESSES_STALE",
             lambda r: r.witnesses.write_text(r.witnesses.read_text().replace("| claude |", "| claude (trusted) |", 1)))
        case("D: WITNESSES.md with \\r\\n line ends", "WITNESSES_STALE",
             lambda r: r.witnesses.write_bytes(r.witnesses.read_bytes().replace(b"\n", b"\r\n")))
        case("D: WITNESSES.md deleted", "WITNESSES_MISSING", lambda r: r.witnesses.unlink())

        def statement_reasons():
            """Reasons, not only codes: the statement rule (AMEND 1 of #169) is what refuses M29 against
            SPEC-3.6-7 and the floats insertion against SPEC-2-2 (each replays without it), M234 against
            SPEC-3.2-20 replays, and a fails case that passes is refused by the replay, not by locality."""
            why_sw = _replay_counter(repo, stmt_counter_doc(repo, sw, mid="M29", fails=m29_fails), sw)
            why_sw_off = _replay_counter(repo, stmt_counter_doc(repo, sw, mid="M29", fails=m29_fails), sw,
                                         statements=False)
            why_sc = _replay_counter(repo, stmt_counter_doc(repo, sc), sc)
            why_fl = _replay_counter(repo, counter_doc(repo, a), a)
            why_fl_off = _replay_counter(repo, counter_doc(repo, a), a, statements=False)
            why_e3 = _replay_counter(repo, stmt_counter_doc(repo, sc, fails=["records_test:E3"]), sc)
            return [
                ("statement rule: M29 against SPEC-3.6-7 is refused for its statements, and replays per function",
                 bool(why_sw) and STATEMENT_REFUSAL in why_sw and why_sw_off is None, (why_sw, why_sw_off)),
                ("statement rule: the floats insertion against SPEC-2-2 is refused for its statements, and replays per function",
                 bool(why_fl) and STATEMENT_REFUSAL in why_fl and why_fl_off is None, (why_fl, why_fl_off)),
                ("statement rule: M234 against SPEC-3.2-20 (the statement M232 changes) replays", why_sc is None, why_sc),
                ("statement rule: a fails case that passes is refused by the replay, not by locality",
                 bool(why_e3) and "not FAIL" in why_e3, why_e3)]

        # Gemini review, part C: `audit` names a claim whose witnesses all pass under a mutant of its own
        # code that some case kills, and only such a claim (_audit_synthetic, _audit_e2e); `why` maps this
        # repository's statements to claims, obligations and goals (why_selftest). These groups run as
        # more tasks of the pool, beside the registered cases.
        groups = [statement_reasons, lambda: _audit_synthetic(fix, work), lambda: _audit_e2e(fix, work, key),
                  lambda: why_selftest(fix, work, key)]

        def run_any(i):
            return run_case(i) if i < len(cases) else groups[i - len(cases)]()

        # Run the registered cases and the groups: in `jobs` forked processes (each inherits the fixture
        # and the closures above), results reported in registration order.
        global _CASE_RUNNER
        _CASE_RUNNER = run_any           # a forked worker finds it here; a closure does not pickle
        tasks = range(len(cases) + len(groups))
        if jobs > 1 and "fork" in multiprocessing.get_all_start_methods():
            with concurrent.futures.ProcessPoolExecutor(jobs, mp_context=multiprocessing.get_context("fork")) as ex:
                results = list(ex.map(_run_registered_case, reversed(tasks)))[::-1]     # the long groups first
        else:
            results = [run_any(i) for i in tasks]
        results, grouped = results[:len(cases)], [x for group in results[len(cases):] for x in group]
        for (name, *_), (ok, line) in zip(cases, results):
            failures += not ok
            ran.append(name)
            print(line)

        # AMEND 3: a refused command leaves the store byte-identical. Through the command line:
        # `supersede --counter-file` with junk bytes, and with a well-formed counter blob that is
        # not local (and --challenge), each refused; then the store's files, and `check`, as before.
        import contextlib
        import io
        d = work / "refused-counter-file"
        subprocess.run(["git", *GIT_NO_GC, "clone", "-q", "--no-local", str(fix), str(d)], capture_output=True, check=True)
        r = Repo(d)

        def listing():
            return sorted((q.relative_to(r.store_dir).as_posix(), q.read_bytes()) for q in r.store_dir.rglob("*") if q.is_file())
        junk = work / "junk.txt"
        junk.write_bytes(b"lol\n")
        nonlocal_counter = work / "nonlocal.json"
        nonlocal_counter.write_text(json.dumps(counter_doc(r, Model(r.snapshot(), r.trust()).current[e.id])))
        before, rcs = listing(), []
        for cid, f, extra in ((a.id, junk, []), (e.id, nonlocal_counter, ["--challenge"])):
            n = Model(r.snapshot(), r.trust()).current[cid]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rcs.append(main(["--root", str(d), "supersede", "--key", str(seed), "--id", cid, "--text", n.doc["text"],
                                 "--because", "selftest", "--unbacked-because", "selftest", "--counter-file", str(f)] + extra))
        got = check(r, base)
        ok = rcs == [2, 2] and listing() == before and not got
        failures += not ok
        print(("ok    " if ok else "FAIL  ") + "a refused counter-file leaves no blob: refused, store unchanged, check passes"
              + ("" if ok else f" | exit {rcs}, store {'changed' if listing() != before else 'unchanged'}, check {got[:2]}"))
        ran.append("refused counter-file")
        # W5: a new sentence names its position; without one, nothing is written. Through the
        # command line (`add` with no --after) and through Author.claim, on the same clone.
        before = listing()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = main(["--root", str(d), "add", "--key", str(seed), "--id", new_id, "--text", inserted,
                       "--unbacked-because", "selftest: no position given"])
        try:
            Author(r, key, AUTHOR, validate=False).claim(new_id, inserted, unbacked_because="selftest")
            raised = False
        except Refused:
            raised = True
        ok = rc == 2 and raised and listing() == before and not check(r, base)
        failures += not ok
        ran.append("unplaced sentence")
        print(("ok    " if ok else "FAIL  ") + "a new sentence without a position: refused, store unchanged, check passes"
              + ("" if ok else f" | exit {rc}, raised {raised}, store {'changed' if listing() != before else 'unchanged'}"))
        for name, ok, detail in grouped:
            failures += not ok
            ran.append(name)
            print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f" | {detail}"))
        print(f"CLAIMS SELFTEST: {'OK' if not failures else f'{failures} FAIL'} ({len(ran)} cases)")
        return 1 if failures else 0
    finally:
        os.environ.pop(LOCAL_TRUST, None)
        shutil.rmtree(work, ignore_errors=True)
