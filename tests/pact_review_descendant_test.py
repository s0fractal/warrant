"""An escrow freeze reaches the grants delegated from an escrowed one: bob's grant to mid is bound to a pact that
breaches; mid's sub-grant to leaf admits nothing then, and admits leaf's acceptance while the pact holds (control)."""
import sys
from world import check, finish
from delegate_test import _setup_base, _key, _line
from warrant import pact as P, delegate as D, records as R, jcs as C
from warrant.store import Snapshot

w = _setup_base()
kmid, kleaf = _key(), _key()
g1 = D.grant_record("bob", "mid", kmid.public, ["acceptor"], ["attest"], 100, 300, max_depth=2,
                    schemas=["task@1"], lineages=[w["task_root"]], at=100)
g1_id = R.rid(g1)
g2 = D.grant_record("mid", "leaf", kleaf.public, ["acceptor"], ["attest"], 120, 250, max_depth=1,
                    schemas=["task@1"], lineages=[w["task_root"]], parent=g1_id, at=120)
p = P.make_proposal("bob", w["keys"]["bob"], parties=["bob", "carol"],
                    commitments={"bob": {"gives": ["x"]}, "carol": {"gives": ["y"]}},
                    expires_at=180, purpose="escrow over a delegation chain", escrow_grants=[g1_id], at=110)
i = R.rid(p["record"])
a = P.make_accept("bob", w["keys"]["bob"], i, at=120)
b = P.make_accept("carol", w["keys"]["carol"], i, at=130)
att = R.record("attest", "leaf", 170, {"target": w["task_done"], "verdict": "accept"}, refs=[w["task_done"]])
s = Snapshot(w["lines"] + [_line(g1, w["keys"]["bob"]), _line(g2, kmid), _line(att, kleaf)]
             + [C.canon(e) + b"\n" for e in (p, a, b)], {}, sort=True)
held = D.assess_delegated(s, w["trust"], w["profile"], 175)        # the pact ACTIVE: leaf's acceptance counts
broken = D.assess_delegated(s, w["trust"], w["profile"], 200)      # expired unfulfilled: the chain is frozen
check("F6 a breached escrow freezes the grants delegated from the escrowed one, not only that grant",
      R.rid(att) in held["provenance"] and R.rid(att) not in broken["provenance"]
      and broken["grants"][R.rid(g2)]["status"] == "ESCROW_FROZEN",
      {"held": R.rid(att) in held["provenance"], "broken": R.rid(att) in broken["provenance"],
       "g2": broken["grants"].get(R.rid(g2), {}).get("status")})
sys.exit(finish())
