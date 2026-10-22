#!/usr/bin/env python3
"""Remembered verdicts (F44): what a store read remembers changes its cost, never its answer.

Snapshot.authentic remembers each verdict of _authenticate in this process, and with an
index (Verdicts.at: Store(root, verdicts=DIR), assess(verdicts=DIR)) also in its owner's
directory, keyed by the trust digest, the record id and the sha256 of the file's bytes,
every index line MACed under the owner's random secret there. Every case compares against the cold path: _authenticate on
every file, nothing remembered (the code before F44). A fixture holds forged, unbound,
misnamed, non-canonical, unanchored, forked, back-dated and unchained records, and
non-ASCII text. Equality is asserted on whole values (the {id: record} and {id: reason}
maps, the head, the report's canonical bytes), never on a message.

    python3 tests/store_index_test.py
"""
import contextlib
import hashlib
import json
import os
import sys
from pathlib import Path

from world import CODEX, HOLDER, OWNER, STRANGER, E, R, W, World, check, finish
from warrant import jcs as C
from warrant import keys as K
from warrant import store as S

DUTY = R.duty(HOLDER, "do the thing", [OWNER], {"attest": {}}, accept_by=[OWNER])
TRANSITION = R.transition("ATTESTED", ["a1" * 32])


def body(text):
    return dict(DUTY, statement=text)


@contextlib.contextmanager
def cold():
    """The path before F44: every file authenticated, nothing remembered or indexed."""
    saved = S._verdict
    S._verdict = lambda rid, data, trust, index=None: S._authenticate(rid, data, trust)
    try:
        yield
    finally:
        S._verdict = saved


@contextlib.contextmanager
def counted():
    """Count the calls of _authenticate made by the remembered path."""
    saved, n = S._authenticate, [0]

    def counting(rid, data, trust):
        n[0] += 1
        return saved(rid, data, trust)
    S._authenticate = counting
    try:
        yield n
    finally:
        S._authenticate = saved


def forget():
    S._MEMO.clear()


def plant(w, r, key, name=None, data=None):
    """A signed envelope for `r` written by hand under `name` (default: its id); its file name."""
    rid = C.doc_id(r)
    env = {"record": r, "sig": {"key": key.id, "ed25519": key.sign(K.sig_message(rid))}}
    name = name or rid
    (w.store.root / "records" / f"{name}.json").write_bytes(C.canon(env) if data is None else data(env))
    return name


class Fixture:
    """HOLDER: g <- x1 <- x2, and f <- x1 (a fork; f, at 130, is the head); d names f but is
    dated before it and u names a record not in the view (both unanchored); an unchained
    record; a record for HOLDER signed by STRANGER's key, one by a key bound to nobody, a copy
    of x2's bytes under another name, x1's record in non-canonical bytes under its id.
    OWNER: o1 <- o2 with non-ASCII text. CODEX: one unchained record.
    Trusts: T binds every key to its actor; OWN binds HOLDER's key only; BAD binds STRANGER's
    key to HOLDER (and HOLDER's to nobody), so the forged record is authentic under BAD."""

    def __init__(self):
        w = self.w = World(actors=(HOLDER, OWNER, CODEX, STRANGER))
        k = self.k = w.keys[HOLDER]
        st = self.st = w.store
        self.vdir = w.dir / "verdicts"
        self.ws = S.Store(st.root, verdicts=self.vdir)          # the same store, written with an index
        self.T = w.trust
        self.OWN = S.Trust(S.Trust.document([(HOLDER, k.public)]))
        self.BAD = S.Trust(S.Trust.document([(HOLDER, w.keys[STRANGER].public), (OWNER, w.keys[OWNER].public)]))
        self.g = st.put_record(R.record("duty", HOLDER, 100, body("genesis"), prev=None), k)
        self.x1 = st.put_record(R.record("transition", HOLDER, 110, TRANSITION, prev=self.g), k)
        self.x2 = st.put_record(R.record("duty", HOLDER, 120, body("x2"), prev=self.x1), k)
        self.f = st.put_record(R.record("duty", HOLDER, 130, body("fork"), prev=self.x1), k)
        self.d = st.put_record(R.record("duty", HOLDER, 125, body("back-dated"), prev=self.f), k)
        self.u = st.put_record(R.record("duty", HOLDER, 500, body("loose"), prev="e" * 64), k)
        st.put_record(R.record("duty", HOLDER, 950, body("unchained")), k)
        o1 = st.put_record(R.record("duty", OWNER, 105, R.duty(OWNER, "ключ é   \"q\" \\ \U0001f600", [HOLDER],
                                                               {"attest": {}}, accept_by=[HOLDER]), prev=None), w.keys[OWNER])
        st.put_record(R.record("duty", OWNER, 115, R.duty(OWNER, "ναι", [HOLDER], {"attest": {}}, accept_by=[HOLDER]),
                               prev=o1), w.keys[OWNER])
        st.put_record(R.record("duty", CODEX, 140, R.duty(CODEX, "unchained", [HOLDER], {"attest": {}},
                                                          accept_by=[HOLDER])), w.keys[CODEX])
        self.forged = plant(w, R.record("duty", HOLDER, 900, body("forged"), prev=self.f), w.keys[STRANGER])
        plant(w, R.record("duty", HOLDER, 901, body("unbound"), prev=self.f), W.Key.generate())
        rec = self.records_dir() / f"{self.x2}.json"
        (self.records_dir() / f"{'0' * 64}.json").write_bytes(rec.read_bytes())         # misnamed, sorts first
        (self.records_dir() / f"{'f' * 64}.json").write_bytes(rec.read_bytes())         # misnamed, sorts last
        self.noncanon = plant(w, R.record("duty", HOLDER, 111, body("spaced"), prev=self.g), k,
                              data=lambda env: json.dumps(env, indent=1).encode())

    def records_dir(self):
        return self.st.root / "records"

    def snap(self):
        return S.Snapshot.read(self.st.root)

    def index(self):
        return S.Verdicts.at(self.vdir)

    def index_file(self, trust=None):
        return self.index().path((trust or self.T).digest)

    def answers(self, trust):
        """(authentic maps, every actor's head) on the remembered path: memory and the index."""
        idx = self.index()
        auth = self.snap().authentic(trust, idx)
        return auth, {a: self.ws.head(a, trust) for a in (HOLDER, OWNER, CODEX)}

    def cold_answers(self, trust):
        with cold():
            return self.snap().authentic(trust), {a: self.st.head(a, trust) for a in (HOLDER, OWNER, CODEX)}


def equivalence_cases():
    # V1 (F44): authentic() under each trust gives the cold maps, whole, on every path: first
    # read (nothing remembered), from this process's memory, from the writer's index alone
    # (memory emptied), and again from the index as written by that read.
    fx = Fixture()
    rows = []
    for name, trust in (("T", fx.T), ("OWN", fx.OWN), ("BAD", fx.BAD)):
        want = fx.cold_answers(trust)[0]
        forget()
        first = fx.snap().authentic(trust)
        memo = fx.snap().authentic(trust)
        forget()
        index = fx.index()
        idx = fx.snap().authentic(trust, index)
        index.flush(fx.snap())
        forget()
        loaded = fx.snap().authentic(trust, fx.index())
        rows.append((name, [x == want for x in (first, memo, idx, loaded)], len(want[0]), len(want[1])))
    ok = all(all(r[1]) for r in rows) and rows[0][2:] == (10, 5)
    check("V1", ok, "authentic() remembered gives the cold {id: record} and {id: reason} maps under every trust", rows)

    # V2: every actor's head, under each trust, with and without the writer's index, equals the
    # cold head; the fixture's head is the later fork tip f, not a forged, unbound, misnamed,
    # unanchored, back-dated or unchained record.
    rows = []
    for name, trust in (("T", fx.T), ("OWN", fx.OWN), ("BAD", fx.BAD)):
        want = fx.cold_answers(trust)[1]
        forget()
        got = fx.answers(trust)[1]
        forget()
        bare = {a: fx.st.head(a, trust) for a in (HOLDER, OWNER, CODEX)}
        rows.append((name, got == want, bare == want, want[HOLDER]))
    ok = all(r[1] and r[2] for r in rows) and rows[0][3] == (fx.f, 130) and rows[2][3] is None
    check("V2", ok, "every head, remembered or indexed, is the cold head under every trust", rows)

    # V3: an assessment's report is the same bytes cold, on a first read and from memory.
    def report():
        return C.canon(E.assess(fx.snap(), fx.T, 10 ** 6, E.profile()))
    with cold():
        want = report()
    forget()
    got = (report() == want, report() == want)
    check("V3", got == (True, True), "a report's canonical bytes are the same cold and remembered", got)


def cost_cases():
    # V4: what is remembered is used. With the index written and memory emptied, a head reads
    # no signature again; a new file costs one authentication; with the index removed every
    # file is authenticated again. An append reads the head once.
    fx = Fixture()
    fx.ws.head(HOLDER, fx.T)
    n_files = len(list(fx.records_dir().iterdir()))
    forget()
    with counted() as n:
        fx.ws.head(HOLDER, fx.T)
        warm = n[0]
    fx.st.put_record(R.record("duty", HOLDER, 140, body("new"), prev=fx.f), fx.k)
    forget()
    with counted() as n:
        fx.ws.head(HOLDER, fx.T)
        one = n[0]
    os.remove(fx.index_file())
    forget()
    with counted() as n:
        fx.ws.head(HOLDER, fx.T)
        all_ = n[0]
    calls = []
    saved = S.Store.head
    S.Store.head = lambda self, *a, **kw: calls.append(1) or saved(self, *a, **kw)
    try:
        fx.ws.append("duty", HOLDER, 150, body("appended"), fx.k, fx.T)
    finally:
        S.Store.head = saved
    got = (warm, one, all_ == n_files + 1, len(calls))
    check("V4", got == (0, 1, True, 1), "an indexed head authenticates only new files; an append reads the head once", got)

    # V5: the index is its owner's and is never shipped: a head read with it writes nothing into
    # the store, so no Snapshot, digest or handoff sees it; its secret is 32 bytes only the
    # owner reads.
    fx = Fixture()
    before = fx.snap()
    fx.ws.head(HOLDER, fx.T)
    after = fx.snap()
    secret = fx.vdir / "secret"
    got = (sorted(p.name for p in fx.st.root.iterdir()), before.digest == after.digest,
           before.records == after.records and before.blobs == after.blobs and before.misfiled == after.misfiled,
           fx.index_file().is_file(), len(secret.read_bytes()), oct(secret.stat().st_mode & 0o777))
    check("V5", got == (["blobs", "records"], True, True, True, 32, "0o600"),
          "the index is outside the store and every snapshot, its secret the owner's", got)


def corrupt(edit, trust_name="T"):
    """A fixture whose index was written by heads under BAD and then T, then `edit(fx)`, memory
    emptied: (remembered answers == cold answers, HOLDER's head's `at` remembered, detail),
    read twice, the second time from the index the first read left. A raise is a False."""
    try:
        fx = Fixture()
        for t in (fx.BAD, fx.T):
            fx.ws.head(HOLDER, t)
        edit(fx)
        trust = {"T": fx.T, "OWN": fx.OWN}[trust_name]
        want = fx.cold_answers(trust)
        forget()
        got = fx.answers(trust)
        forget()
        again = fx.answers(trust)
        head = got[1][HOLDER]
        return got == want and again == want, head and head[1], (head, want[1][HOLDER])
    except Exception as e:      # noqa: BLE001
        return False, None, f"raised {type(e).__name__}: {e}"


def lines(fx, trust=None):
    return [json.loads(x) for x in fx.index_file(trust).read_bytes().split(b"\n") if x]


def write_lines(fx, rows, keep=True):
    old = fx.index_file().read_bytes() if keep else b""
    fx.index_file().write_bytes(old + b"".join(json.dumps(r).encode() + b"\n" for r in rows))


def line_for(fx, rid, trust):
    return next(x for x in lines(fx, trust) if x[2] == trust.digest and x[3] == rid)


def sha(fx, rid):
    return hashlib.sha256((fx.records_dir() / f"{rid}.json").read_bytes()).hexdigest()


def corruption_cases():
    # V6: a trust change is noticed. The index holds BAD's verdicts (the forged record authentic,
    # HOLDER's own rejected) before T's; read under T it is rejected and the head is f, as cold.
    got = corrupt(lambda fx: None)
    fx = Fixture()                          # and in one process: BAD's verdicts remembered, then T read
    for t in (fx.BAD, fx.T):
        fx.ws.head(HOLDER, t)
    same = fx.answers(fx.T) == fx.cold_answers(fx.T)
    check("V6", got[:2] == (True, 130) and same, "a verdict under another trust never stands in", (got, same))

    # V7: a changed file is noticed. f, the head, is rewritten in place with other bytes under
    # the same name after its verdict was indexed; the head is x2, as cold.
    def rewrite(fx):
        p = fx.records_dir() / f"{fx.f}.json"
        p.write_bytes(p.read_bytes() + b" ")
    got = corrupt(rewrite)
    check("V7", got[:2] == (True, 120), "a verdict for other bytes under the same name never stands in", got)

    # V8: a file's name is part of its verdict: x2's authentic bytes copied under two other names
    # (sorting before and after x2) are rejected, as cold, after x2's verdict is remembered.
    fx = Fixture()
    with cold():
        want = fx.snap().authentic(fx.T)
    forget()
    rows = [fx.snap().authentic(fx.T) == want for _ in range(2)]
    forget()
    rows.append(fx.snap().authentic(fx.T, fx.index()) == want)
    check("V8", all(rows) and "0" * 64 in want[1] and "f" * 64 in want[1],
          "a verdict for the same bytes under another name never stands in", rows)

    # V9: a new file is authenticated. A forged record naming the head, planted after the index
    # was written, is rejected and is no head, as cold.
    def planted(fx):
        plant(fx.w, R.record("duty", HOLDER, 990, body("planted"), prev=fx.f), fx.w.keys[STRANGER])
    got = corrupt(planted)
    check("V9", got[:2] == (True, 130), "a file the index has not seen is authenticated", got)

    # V10: a removed file is noticed. f is deleted after its verdict was indexed: the head is x2.
    got = corrupt(lambda fx: os.remove(fx.records_dir() / f"{fx.f}.json"))
    check("V10", got[:2] == (True, 120), "an indexed verdict of a removed file admits nothing", got)

    # V11: a forged line. Lines declaring the forged and the misnamed records authentic under T,
    # MACed under a secret that is not the writer's, are skipped.
    def forged_line(fx):
        other = S.Verdicts(fx.vdir, b"\0" * 32, fx.index().code)
        write_lines(fx, [json.loads(other._line((fx.T.digest, rid, sha(fx, rid)), None))
                         for rid in (fx.forged, "f" * 64)])
    got = corrupt(forged_line)
    check("V11", got[:2] == (True, 130), "an index line MACed under another secret is skipped", got)

    # V12: a flipped verdict. The writer's own line rejecting the forged record under T, its
    # verdict changed to authentic and its MAC kept, is skipped.
    def flipped(fx):
        x = line_for(fx, fx.forged, fx.T)
        x[5] = None
        write_lines(fx, [x])
    got = corrupt(flipped)
    check("V12", got[:2] == (True, 130), "a line whose verdict was changed after it was MACed is skipped", got)

    # V13: a moved line. The writer's own line admitting f, moved onto the forged record (its
    # record id and bytes digest changed, so its actor and prev would be the forged record's),
    # and the BAD line admitting the forged record moved onto T, are skipped.
    def moved(fx):
        a = line_for(fx, fx.f, fx.T)
        a[3], a[4] = fx.forged, sha(fx, fx.forged)
        b = line_for(fx, fx.forged, fx.BAD)
        b[2] = fx.T.digest
        write_lines(fx, [a, b])
    got = corrupt(moved)
    check("V13", got[:2] == (True, 130), "a line moved onto another record or trust is skipped", got)

    # V14: another code identity. Lines MACed with the writer's own secret but under another
    # package identity (an index an older warrant wrote), admitting the forged record, are skipped.
    def old_code(fx):
        old = S.Verdicts(fx.vdir, fx.index()._secret, "0" * 64)
        write_lines(fx, [json.loads(old._line((fx.T.digest, fx.forged, sha(fx, fx.forged)), None))])
    got = corrupt(old_code)
    check("V14", got[:2] == (True, 130), "a verdict computed by other code never stands in", got)

    # V15: a missing entry, a truncated line and garbage cost an authentication, nothing else.
    def damaged(fx):
        rows = fx.index_file().read_bytes().split(b"\n")
        keep = [r for r in rows if r and json.loads(r)[3] != fx.f]
        fx.index_file().write_bytes(b"\n".join(keep[:-1]) + b"\n" + keep[-1][: len(keep[-1]) // 2] + b"\n\xff{not json\n[1,2]\n")
    got = corrupt(damaged)
    check("V15", got[:2] == (True, 130), "a missing, truncated or garbled index line costs time only", got)

    # V16: under the writer's own trust (the `warrant` CLI default) the corrupted indexes of
    # V11-V13 still give the cold answers.
    got = [corrupt(e, "OWN")[0] for e in (forged_line, flipped, moved)]
    check("V16", all(got), "the corruptions change no answer under the signing key's own trust", got)


def receiver_cases():
    # V17: a receiver's own index (assess(verdicts=DIR), `warrant assess --verdicts`). Its secret
    # is 32 random bytes only the receiver reads; reports are the cold bytes on a first read, from
    # the index alone (no signature checked again), and with lines MACed under another secret
    # (the zero secret) or a flipped verdict appended; the index changes no assessment identity.
    fx = Fixture()
    folder = fx.w.dir / "verdicts"

    def report(**kw):
        return C.canon(E.assess(fx.snap(), fx.T, 10 ** 6, E.profile(), **kw))
    with cold():
        want = report()
    forget()
    first = report(verdicts=folder)
    forget()
    with counted() as n:
        again = report(verdicts=folder)
        warm = n[0]
    secret = folder / "secret"
    idx = S.Verdicts.at(folder)
    other = S.Verdicts(folder, bytes(32), idx.code)
    flip = next(x for x in lines_at(idx.path(fx.T.digest)) if x[3] == fx.forged)
    flip[5] = None
    with open(idx.path(fx.T.digest), "a") as f:
        f.write(other._line((fx.T.digest, fx.forged, sha(fx, fx.forged)), None))
        f.write(json.dumps(flip) + "\n")
    forget()
    forged = report(verdicts=folder)
    got = (first == want, again == want, warm, forged == want, len(secret.read_bytes()), oct(secret.stat().st_mode & 0o777))
    check("V17", got == (True, True, 0, True, 32, "0o600"),
          "a receiver's index gives the cold report bytes, and a forged or flipped line is skipped", got)


def cli_cases():
    # V18: the CLI. `warrant file --verdicts DIR` twice extends the chain (the second record's prev
    # is the first) and writes the index into DIR, nothing into the store beside the records;
    # `warrant assess --verdicts DIR2` prints the same report as without, cold and from DIR2.
    import io
    from warrant import cli
    fx = Fixture()
    keyfile = fx.w.dir / "holder.key"
    keyfile.write_text(fx.k.seed_hex() + "\n")
    trustfile = fx.w.dir / "trust.json"
    trustfile.write_bytes(C.canon(S.Trust.document([(a, k.public) for a, k in fx.w.keys.items()])))

    def run(*argv):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cli.main([str(x) for x in argv])
        except SystemExit as e:            # a refusal is an answer here, not the end of the test run
            return json.dumps({"record": f"refused: {e}"})
        return buf.getvalue()
    filed = [json.loads(run("file", "--store", fx.st.root, "--key", keyfile, "--actor", HOLDER, "--at", at,
                            "--verdicts", fx.w.dir / "signer", "--type", "duty", json.dumps(body(f"cli {at}"))))["record"]
             for at in (700, 701)]
    recs = fx.snap().authentic(fx.T)[0]
    view = ("assess", "--store", fx.st.root, "--trust", trustfile, "--as-of", 10 ** 6)
    forget()
    plain = run(*view)
    forget()
    first = run(*view, "--verdicts", fx.w.dir / "reader")
    forget()
    again = run(*view, "--verdicts", fx.w.dir / "reader")
    got = (recs[filed[0]]["prev"] == fx.f, recs[filed[1]]["prev"] == filed[0],
           sorted(p.name for p in (fx.w.dir / "signer").iterdir()), sorted(p.name for p in fx.st.root.iterdir()),
           first == plain, again == plain, sorted(p.name for p in (fx.w.dir / "reader").iterdir()))
    want = (True, True, sorted(["secret", f"{fx.OWN.digest}.jsonl"]), ["blobs", "records"], True, True,
            sorted(["secret", f"{fx.T.digest}.jsonl"]))
    check("V18", got == want, "warrant file and assess --verdicts DIR: the chain and the report as without it", got)


def lines_at(path):
    return [json.loads(x) for x in Path(path).read_bytes().split(b"\n") if x]


def main():
    for group in (equivalence_cases, cost_cases, corruption_cases, receiver_cases, cli_cases):
        try:
            group()
        except Exception as e:      # noqa: BLE001
            check(f"RAISED-{group.__name__}", False, f"{group.__name__} ran to its end", f"{type(e).__name__}: {e}")
    return finish("STORE-INDEX")


if __name__ == "__main__":
    sys.exit(main())
