"""A small world for tests: a temporary store, one key per actor, explicit times."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(ROOT))

import warrant as W                      # noqa: E402
from warrant import compute as P         # noqa: E402
from warrant import engine as E          # noqa: E402
from warrant import records as R         # noqa: E402
from warrant.store import Store, Trust   # noqa: E402

HOLDER, OWNER, CODEX, OBSERVER, STRANGER = "claude", "owner", "codex", "probe", "stranger"
SHA_OLD, SHA_NEW = "1" * 40, "2" * 40


class World:
    def __init__(self, actors=(HOLDER, OWNER, CODEX, OBSERVER, STRANGER)):
        self.dir = Path(tempfile.mkdtemp(prefix="warrant-test-"))
        self.store = Store(self.dir / "store").init()
        self.keys = {a: W.Key.generate() for a in actors}
        self.trust = Trust(Trust.document([(a, k.public) for a, k in self.keys.items()]))
        self.t = 100
        self.heads = {}         # actor -> its last filed record: each actor's chain (SPEC §3)

    def tick(self, at=None):
        if at is not None:
            self.t = at
        else:
            self.t += 1
        return self.t

    def next_prev(self, actor):
        return self.heads.get(actor)

    def file(self, rtype, actor, body, at=None, prev="head"):
        """File a record that names `actor`'s last record as its `prev` (a test may date it
        earlier: then it is unanchored). prev=R.UNCHAINED files an unchained record; an id or
        None names that predecessor (a fork, a genesis, another actor's record)."""
        prev = self.next_prev(actor) if prev == "head" else prev
        rid = self.store.put_record(R.record(rtype, actor, self.tick(at), body, prev=prev), self.keys[actor])
        self.heads[actor] = rid
        return rid

    def blob(self, doc):
        return self.store.put_json(doc)

    def evidence(self, text="evidence"):
        return self.store.put_blob(text.encode())

    # sugar
    def duty(self, condition=None, holder=HOLDER, owed_to=(OWNER,), accept_by=(OWNER,), at=None, **kw):
        return self.file("duty", holder, R.duty(holder, kw.pop("statement", "do the thing"), owed_to,
                                                condition or {"attest": {}}, accept_by=accept_by, **kw), at)

    def act(self, actor, closes, basis="ATTESTED", evidence=None, at=None, prev="head", **kw):
        ev = evidence if evidence is not None else sorted({h for m in closes for h in m["evidence"]})
        return self.file("transition", actor, R.transition(basis, ev, closes=closes, **kw), at, prev=prev)

    def close(self, did, actor=HOLDER, act="discharge", basis="ATTESTED", evidence=None, at=None, tkw=None, prev="head",
              **mkw):
        ev = [self.evidence()] if evidence is None else evidence
        return self.act(actor, [R.item(did, act, ev, **mkw)], basis=basis, evidence=ev, at=at, prev=prev, **(tkw or {}))

    def accept(self, actor, t_id, index=0, at=None, evidence=None, prev="head"):
        env = W.loads(self.store.snapshot().records[t_id])["record"]["body"]
        ev = evidence if evidence is not None else (env["evidence"] if index is None else env["closes"][index]["evidence"])
        return self.file("accept", actor, R.accept(t_id, index, ev), at, prev=prev)

    def assess(self, as_of=10_000, prof=None, current=(SHA_NEW,), workspace=None, provider=None):
        return E.assess(self.store.snapshot(), self.trust, as_of, prof or E.profile(), current=current,
                        workspace=workspace, provider=provider)


results = {}


def check(cid, ok, what, detail=""):
    results[cid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{cid} {what}" + ("" if ok else f" | {detail}"), flush=True)


def finish(name):
    import json
    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"{name}: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("WARRANT_RESULTS"):
        Path(os.environ["WARRANT_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0


def verdicts(rep, did):
    return [(c["act"], c["verdict"]) for c in rep["duties"][did]["candidates"]]
