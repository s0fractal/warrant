import sys
from world import check, finish
from delegate_test import _setup_base, _key, _line
from warrant import pact as P, delegate as D, records as R, jcs as C
from warrant.store import Snapshot

w = _setup_base()
k = _key()
g = D.grant_record("bob", "worker", k.public, ["acceptor"], ["attest"], 100, 300,
                   schemas=["task@1"], lineages=[w["task_root"]], at=100)
gid = R.rid(g)
p = P.make_proposal("bob", w["keys"]["bob"], parties=["bob", "carol"],
    commitments={"bob": {"gives": ["x"]}, "carol": {"gives": ["y"]}},
    expires_at=180, purpose="escrow expires before the grant", escrow_grants=[gid], at=110)
i = R.rid(p["record"])
a = P.make_accept("bob", w["keys"]["bob"], i, at=120)
b = P.make_accept("carol", w["keys"]["carol"], i, at=130)
att = R.record("attest", "worker", 200, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
s = Snapshot(w["lines"] + [_line(g, w["keys"]["bob"]), _line(att, k)]
             + [C.canon(e)+b"\n" for e in (p,a,b)], {}, sort=True)
es = P.resolve_escrow(s, w["trust"], w["profile"], 200)
res = D.assess_delegated(s, w["trust"], w["profile"], 200)
check("F2 breached escrow must prevent delegated acceptance",
      es["pacts"][i]["status"] == "BREACHED" and not es["escrow"][gid]["escrow_allowed"]
      and R.rid(att) not in res["provenance"]
      and res["delegated_report"]["lineages"][w["task_root"]]["state"] == "open",
      {"escrow_allowed": es["escrow"][gid]["escrow_allowed"],
       "delegated_admitted": R.rid(att) in res["provenance"],
       "task_state": res["delegated_report"]["lineages"][w["task_root"]]["state"]})
sys.exit(finish())
