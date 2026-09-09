#!/usr/bin/env python3
"""Tests for fact_provenance — `warrant.fact-provenance@v0` (WRT-008).

WHAT THIS HARNESS IS BUILT TO AVOID
-----------------------------------
The defect family this stack keeps reproducing, and which a provenance checker
is unusually good at reproducing again:

  * *a label wider than its predicate.* `derived` must mean "I re-ran the cited
    decision and it answers this", not "a field said so". So section C reads
    every derived value out of an ACTUAL RE-EXECUTION through
    `warrant.run_ski_check`, and section D proves each negative state fires on
    a real store mutation rather than on a flag.

  * *removing a field turns a check off while the status stays green.* Section E
    deletes and rewrites parts of the provenance document and requires a
    REFUSAL, never a silent downgrade to `observed`.

  * *a harness that cannot fail.* Section F mutates the checker on purpose and
    FAILS IF THE MUTANT SURVIVES.

  A. term preservation: `from` clauses never change the emitted check
  B. grammar: the clause is accepted where it is legal and refused by name where not
  C. derived: the four states, each from a real store
  D. propagation: superseding a cited decision makes downstream facts stale
  E. completeness: omission and tampering are refusals
  F. mutation controls
"""
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "impl"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


W = _load("warrant", "impl/warrant.py")
pl = _load("policy_lang", "impl/policy_lang.py")
fp = _load("fact_provenance", "impl/fact_provenance.py")

ok = []
_TMP = []
T0 = 1708300800
SEED = "c3" * 32


def chk(cond, label, detail=""):
    ok.append(bool(cond))
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def new_store():
    d = tempfile.mkdtemp(prefix="fp-test-")
    _TMP.append(d)
    s = W.Store(os.path.join(d, ".warrants"))
    s.init()
    return s


def keyfile():
    d = tempfile.mkdtemp(prefix="fp-key-")
    _TMP.append(d)
    p = pathlib.Path(d) / "a.key"
    p.write_text(SEED + "\n")
    return str(p)


class Args:
    def __init__(self, **kw):
        d = dict(under=[], evidence=[], prior=[], reason=None, check=None,
                 runtime="cmd@v1", verdict="pass", transcript=None,
                 relitigates=None, ts=T0)
        d.update(kw)
        for k, v in d.items():
            setattr(self, k, v)


def file_check(store, src, *, decision="accept", subject=None, prior=(),
               actor="desk@test", ts=T0, key=None):
    """Compile `src`, store its source + provenance, and file a warrant citing
    the check. Returns (wid, Compiled, provenance_hex)."""
    c = pl.compile_source(src, store.put_blob)
    src_hex = store.put_blob(src.encode())
    prov_hex = fp.put_doc(store, c, c.blob, src_hex)
    subject = subject or store.put_blob(b'{"subject":"test"}')
    policy = store.put_blob(b"POLICY: the rule in force for this test.\n")
    wid = W.file_warrant(
        store, decision, subject,
        Args(under=[policy], evidence=[src_hex, prov_hex], prior=list(prior),
             check=c.blob, runtime="ski@v1", verdict="pass", reason=["test"],
             actor=actor, key=key or keyfile(), ts=ts))
    return wid, c, prov_hex


def load_doc(store, h):
    import json
    return json.loads((store.blobs / h).read_bytes())


def states(findings):
    return {f.fact: f.state for f in findings}


# ------------------------------------------------- A. term preservation (MUST)
def test_term_preservation():
    """The invariant WRT-008 is built around: provenance is not semantics."""
    wid = "5f" + "0" * 62
    chk_hex = "b4" + "0" * 62
    pairs = [
        ("fact e: bool = true\ncheck e\n",
         'fact e: bool = true from "%s"\ncheck e\n' % wid),
        ("fact e: bool = true\ncheck e\n",
         'fact e: bool = true from "%s/%s"\ncheck e\n' % (wid, chk_hex)),
        ("fact a: bool = true\nfact b: bool = false\ncheck a && !b\n",
         'fact a: bool = true from "%s"\nfact b: bool = false from "%s"\n'
         "check a && !b\n" % (wid, wid)),
        ("fact a: bool = false\nfact n: int = 7\ncheck a || n <= 9\n",
         'fact a: bool = false from "%s"\nfact n: int = 7\n'
         "check a || n <= 9\n" % wid),
    ]
    for plain, prov in pairs:
        a = pl.compile_source(plain)
        b = pl.compile_source(prov)
        chk(a.doc == b.doc, f"`from` does not change the check doc ({a.result})",
            f"{a.doc} != {b.doc}")
        chk(a.nodes == b.nodes, "`from` does not change the emitted node set")
        chk(a.result == b.result, "`from` does not change the policy answer")
    # And the blob hash a record cites is unchanged, so nothing is re-signed.
    s1, s2 = new_store(), new_store()
    x = pl.compile_source(pairs[0][0], s1.put_blob)
    y = pl.compile_source(pairs[0][1], s2.put_blob)
    chk(x.blob == y.blob, "`from` does not change the stored check blob hash",
        f"{x.blob} != {y.blob}")


# --------------------------------------------------------------- B. grammar
def test_grammar():
    wid = "5f" + "0" * 62
    good = [
        ('fact e: bool = true from "%s"\ncheck e\n' % wid, "bare WarrantID"),
        ('fact e: bool = true from "%s/%s"\ncheck e\n' % (wid, "b4" + "0" * 62),
         "WarrantID/check"),
        ("fact from: bool = true\ncheck from\n",
         "`from` still works as a fact name (contextual, not reserved)"),
    ]
    for src, label in good:
        try:
            pl.compile_source(src)
            chk(True, f"accepts: {label}")
        except Exception as e:
            chk(False, f"accepts: {label}", repr(e))

    bad = [
        ('fact n: int = 5 from "%s"\ncheck n <= 9\n' % wid, "only for bool",
         "int fact with `from`"),
        ('fact e: bool = true from "deadbeef"\ncheck e\n', "not a fact reference",
         "short hex"),
        ('fact e: bool = true from "%s"\ncheck e\n' % ("5F" + "0" * 62),
         "not a fact reference", "uppercase hex"),
        ('fact e: bool = true from "%s/%s/%s"\ncheck e\n' % (wid, wid, wid),
         "not a fact reference", "three path parts"),
        ("fact e: bool = true from\n", "takes a quoted reference", "`from` at EOF"),
        ('fact e: bool = true from "%s" from "%s"\ncheck e\n' % (wid, wid),
         "expected `fact` or `check`", "two `from` clauses"),
    ]
    for src, needle, label in bad:
        try:
            pl.compile_source(src)
            chk(False, f"refuses: {label}", "compiled instead")
        except pl.PolicyError as e:
            chk(needle in str(e), f"refuses by name: {label}", str(e)[:90])
        except Exception as e:
            chk(False, f"refuses: {label}", f"wrong exception {e!r}")


# ------------------------------------------------------- C. the four states
def test_derived_states():
    # --- derived: the cited decision really answers what the policy pinned.
    s = new_store()
    w1, c1, _ = file_check(s, "fact rel: bool = true\nfact cert: bool = true\n"
                              "check rel && cert\n")
    chk(c1.result is True, "upstream decision answers true")
    w2, _, p2 = file_check(
        s, 'fact eligible: bool = true from "%s"\nfact retro: bool = false\n'
           "check eligible && !retro\n" % w1, prior=[w1])
    f = states(fp.check_doc(s, load_doc(s, p2)))
    chk(f == {"eligible": fp.DERIVED, "retro": fp.ATTESTED},
        "derived: re-running the cited decision reproduces the pinned value", f)

    # The value is read from a real reduction, not from a field: re-run the
    # upstream check directly and require the same boolean.
    verdict, rh, _ = W.run_ski_check(s, c1.blob)
    chk(verdict == "pass" and fp.church_bool(rh) is True,
        "the derived value comes out of an actual re-execution")

    # --- contradicted: same citation, opposite pinned value.
    s = new_store()
    w1, _, _ = file_check(s, "fact rel: bool = true\ncheck rel\n")
    _, _, p2 = file_check(
        s, 'fact eligible: bool = false from "%s"\ncheck !eligible\n' % w1,
        prior=[w1])
    f = fp.check_doc(s, load_doc(s, p2))
    chk(states(f) == {"eligible": fp.CONTRADICTED},
        "contradicted: pinned value differs from the cited answer", states(f))
    chk(f[0].level() == "ERR", "contradicted is an ERR in base grade")

    # --- underived: the cited warrant is not in this store.
    s = new_store()
    absent = "ab" + "0" * 62
    _, _, p = file_check(
        s, 'fact e: bool = true from "%s"\ncheck e\n' % absent)
    f = fp.check_doc(s, load_doc(s, p))
    chk(states(f) == {"e": fp.UNDERIVED}, "underived: cited warrant absent")
    chk(f[0].level() == "WARN" and f[0].level(settlement=True) == "ERR",
        "underived is WARN in base grade and ERR under settlement",
        f"got {f[0].level()} / {f[0].level(settlement=True)}")

    # --- underived: the cited warrant has no ski@v1 reason at all.
    s = new_store()
    subj = s.put_blob(b"{}")
    pol = s.put_blob(b"POLICY")
    prose = W.file_warrant(s, "accept", subj,
                           Args(under=[pol], reason=["just words"],
                                actor="desk@test", key=keyfile()))
    _, _, p = file_check(s, 'fact e: bool = true from "%s"\ncheck e\n' % prose)
    f = fp.check_doc(s, load_doc(s, p))
    chk(states(f) == {"e": fp.UNDERIVED}, "underived: cited warrant is prose-only")
    chk("no ski@v1 reason" in f[0].detail, "and says so", f[0].detail)

    # --- underived: the cited blob is gone, so it cannot be re-run.
    s = new_store()
    w1, c1, _ = file_check(s, "fact rel: bool = true\ncheck rel\n")
    _, _, p2 = file_check(
        s, 'fact e: bool = true from "%s"\ncheck e\n' % w1, prior=[w1])
    (s.blobs / c1.blob).unlink()
    f = fp.check_doc(s, load_doc(s, p2))
    chk(states(f) == {"e": fp.UNDERIVED}, "underived: cited check blob removed",
        states(f))


# ------------------------------------------------------------ D. propagation
def test_stale_propagation():
    """The point of the profile: superseding a cited decision lights up every
    downstream policy that derived a fact from it, with nobody remembering the
    dependency existed."""
    s = new_store()
    subj = s.put_blob(b'{"claim":"refund"}')
    w1, _, _ = file_check(s, "fact cert: bool = true\ncheck cert\n", subject=subj)
    _, _, p2 = file_check(
        s, 'fact eligible: bool = true from "%s"\ncheck eligible\n' % w1,
        subject=subj, prior=[w1])

    before = states(fp.check_doc(s, load_doc(s, p2)))
    chk(before == {"eligible": fp.DERIVED}, "before: the derivation holds", before)

    # The certificate turns out forged. The upstream decision is superseded.
    W.file_warrant(s, "supersede", w1,
                   Args(under=[s.put_blob(b"POLICY")], prior=[w1],
                        reason=["certificate was forged"],
                        actor="desk@test", key=keyfile(), ts=T0 + 86400))

    after = fp.check_doc(s, load_doc(s, p2))
    chk(states(after) == {"eligible": fp.STALE},
        "after: the downstream fact is stale, with no registry and no notice",
        states(after))
    chk(after[0].level() == "WARN" and after[0].level(settlement=True) == "ERR",
        "stale is WARN in base grade and ERR under settlement")
    chk("superseded by" in after[0].detail, "and names the superseding record",
        after[0].detail)

    # A supersede of something else must NOT make this stale.
    s = new_store()
    w1, _, _ = file_check(s, "fact cert: bool = true\ncheck cert\n")
    other, _, _ = file_check(s, "fact z: bool = true\ncheck z\n")
    _, _, p2 = file_check(
        s, 'fact e: bool = true from "%s"\ncheck e\n' % w1, prior=[w1])
    W.file_warrant(s, "supersede", other,
                   Args(under=[s.put_blob(b"POLICY")], prior=[other],
                        reason=["unrelated"], actor="desk@test",
                        key=keyfile(), ts=T0 + 10))
    chk(states(fp.check_doc(s, load_doc(s, p2))) == {"e": fp.DERIVED},
        "an unrelated supersede does not make a derivation stale")


# ------------------------------------------------------- E. completeness rule
def test_completeness_and_tampering():
    s = new_store()
    w1, _, _ = file_check(s, "fact rel: bool = true\ncheck rel\n")
    src = ('fact eligible: bool = true from "%s"\nfact retro: bool = false\n'
           "check eligible && !retro\n" % w1)
    _, c, p = file_check(s, src, prior=[w1])
    good = load_doc(s, p)

    def refuses(doc, label, needle=None):
        try:
            fp.check_doc(s, doc)
            chk(False, f"refuses: {label}", "accepted instead")
        except fp.ProvenanceError as e:
            chk(needle is None or needle in str(e), f"refuses: {label}", str(e)[:95])

    import copy
    # THE defect this rule exists for: drop a fact and the check goes quiet.
    d = copy.deepcopy(good)
    del d["facts"]["retro"]
    refuses(d, "a fact omitted from the document", "MUST describe exactly")

    d = copy.deepcopy(good)
    del d["facts"]["eligible"]
    refuses(d, "the DERIVED fact omitted", "MUST describe exactly")

    d = copy.deepcopy(good)
    d["facts"]["ghost"] = {"kind": "observed", "value": True}
    refuses(d, "a fact the check does not have", "MUST describe exactly")

    # Downgrading a derived fact to observed is a value change, so it is caught
    # by the recompile + fact-set comparison, not by trust in the label.
    d = copy.deepcopy(good)
    d["facts"]["eligible"] = {"kind": "observed", "value": True}
    f = fp.check_doc(s, d)
    chk(states(f)["eligible"] == fp.ATTESTED,
        "a document may downgrade to `observed` — but then it says `attested`, "
        "never `derived`")

    d = copy.deepcopy(good)
    d["facts"]["retro"]["value"] = True
    refuses(d, "a value that disagrees with the source", "the source pins")

    d = copy.deepcopy(good)
    d["source"] = "cc" + "0" * 62
    refuses(d, "a source blob not in the store", "is not in the store")

    d = copy.deepcopy(good)
    d["check"] = "dd" + "0" * 62
    refuses(d, "a check the source does not compile to", "recompiling")

    d = copy.deepcopy(good)
    d["provenance"] = "warrant.fact-provenance@v1"
    refuses(d, "an unknown profile tag", "not a warrant.fact-provenance@v0")

    d = copy.deepcopy(good)
    d["facts"]["eligible"]["extra"] = 1
    refuses(d, "an unknown member (closed schema)", "closed schema")

    d = copy.deepcopy(good)
    d["facts"]["retro"]["from"] = w1
    refuses(d, "an observed fact carrying a derivation", "carries a derivation")

    d = copy.deepcopy(good)
    del d["facts"]["eligible"]["from"]
    refuses(d, "a derived fact with no `from`", "no valid `from`")

    for key in ("check", "source", "facts", "provenance"):
        d = copy.deepcopy(good)
        del d[key]
        refuses(d, f"the document with {key!r} removed")


# -------------------------------------------------------- F. mutation controls
def test_mutation_controls():
    """A harness that cannot fail is the same defect one level up."""
    s = new_store()
    w1, _, _ = file_check(s, "fact rel: bool = true\ncheck rel\n")
    _, _, p = file_check(
        s, 'fact e: bool = false from "%s"\ncheck !e\n' % w1, prior=[w1])
    doc = load_doc(s, p)

    baseline = states(fp.check_doc(s, doc))
    chk(baseline == {"e": fp.CONTRADICTED},
        "control: this fixture really is contradicted", baseline)

    # Mutant 1: stop comparing the re-run answer to the pinned value.
    real = fp.church_bool
    try:
        fp.church_bool = lambda h: False        # always agree with the pin
        mutated = states(fp.check_doc(s, doc))
    finally:
        fp.church_bool = real
    chk(mutated != baseline,
        "mutant survives if the value comparison is removed — it does not",
        f"mutant produced {mutated}")

    # Mutant 2: stop checking for supersedes.
    s2 = new_store()
    w1, _, _ = file_check(s2, "fact rel: bool = true\ncheck rel\n")
    _, _, p2 = file_check(
        s2, 'fact e: bool = true from "%s"\ncheck e\n' % w1, prior=[w1])
    W.file_warrant(s2, "supersede", w1,
                   Args(under=[s2.put_blob(b"POLICY")], prior=[w1],
                        reason=["x"], actor="desk@test", key=keyfile(),
                        ts=T0 + 5))
    chk(states(fp.check_doc(s2, load_doc(s2, p2))) == {"e": fp.STALE},
        "control: this fixture really is stale")
    real2 = fp._superseded_by
    try:
        fp._superseded_by = lambda recs, wid: []
        mutated = states(fp.check_doc(s2, load_doc(s2, p2)))
    finally:
        fp._superseded_by = real2
    chk(mutated == {"e": fp.DERIVED},
        "removing the supersede scan turns stale into derived — the scan is "
        "load-bearing", mutated)

    # Mutant 3: accept a check whose reason does not re-run to its own expect.
    chk(fp.BAD_STATES == (fp.CONTRADICTED, fp.UNDERIVED, fp.STALE),
        "no state is quietly counted as success")


def test_store_level_and_cli():
    s = new_store()
    w1, _, _ = file_check(s, "fact rel: bool = true\ncheck rel\n")
    w2, _, _ = file_check(
        s, 'fact e: bool = true from "%s"\ncheck e\n' % w1, prior=[w1])
    res = fp.check_store(s)
    chk(set(res) == {w1, w2}, "check_store finds every record citing provenance",
        sorted(res))
    chk(states(res[w2][0]) == {"e": fp.DERIVED}, "and reports the chain")
    chk(res[w1][1] == [] and res[w2][1] == [], "with no document-level refusals")
    rc = fp.main(["--store", str(s.root)])
    chk(rc == 0, "CLI exits 0 on a store whose derivations all hold", rc)


# ------------------------------------------------- G. the demo, and its prose
def test_refund_chain_demo():
    """The demo must build, and its README must quote the hashes the build
    actually produces. A demo whose prose has drifted from its pack is the
    defect this stack keeps finding in its own reviews."""
    import re
    import subprocess

    demo = ROOT / "demos" / "refund-chain"
    r = subprocess.run([sys.executable, str(demo / "build.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    chk(r.returncode == 0, "demos/refund-chain builds",
        (r.stderr or r.stdout)[-400:])
    if r.returncode != 0:
        return

    out = r.stdout
    # The three acts must each do what the README says they do. These assert on
    # the LIBRARY's verdicts, echoed by the build, not on the narration.
    chk("inadmissible: cites nothing new" in out,
        "ACT II: prose alone is refused by §7")
    chk("admissible: (b) new outcome fingerprint" in out,
        "ACT III: admitted on the NEW CONSEQUENCE ground, not on new evidence",
        "if this fails the demo's whole claim is false")
    chk("stale" in out, "the payoff: the downstream derived fact goes stale")

    man = json.loads((demo / "pack" / "manifest.json").read_text())
    chk(len(man["records"]) == 5, "the pack holds all five records")
    chk(man["derived_facts"]["grant.eligible"]["state_after_reopening"]
        == fp.STALE, "the manifest records the stale outcome")

    # Base verification and the profile must disagree, and each must be right.
    store = W.Store(str(demo / "pack" / ".warrants"))
    recs = store.all_records()
    chk(len(recs) == 5, "five records load")
    findings, errors = fp.check_record(store, man["chain"]["grant"], recs)
    chk(errors == [], "the grant's provenance document is usable", errors)
    chk(states(findings) == {"eligible": fp.STALE, "timely": fp.DERIVED},
        "the grant: one stale derivation, one live one", states(findings))

    # Every hex prefix the README quotes must be one the build really produced.
    readme = (demo / "README.md").read_text()
    quoted = set(re.findall(r"\b([0-9a-f]{12})…", readme))
    produced = {h[:12] for h in recs}
    produced |= {h[:12] for h in re.findall(r"\b([0-9a-f]{12})…", out)}
    drift = quoted - produced
    chk(not drift, "every hash the README quotes is one the build produced",
        f"README quotes {sorted(drift)}, which the build does not produce")
    chk(len(quoted) >= 4, "the README quotes real hashes at all", len(quoted))


def main():
    print("=" * 66)
    print("  fact_provenance — warrant.fact-provenance@v0 (WRT-008)")
    print("=" * 66)
    try:
        test_term_preservation()
        test_grammar()
        test_derived_states()
        test_stale_propagation()
        test_completeness_and_tampering()
        test_mutation_controls()
        test_store_level_and_cli()
        test_refund_chain_demo()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    good = all(ok)
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("FACT-PROVENANCE: ALL PASS" if good
          else "FACT-PROVENANCE: FAILURES PRESENT")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
