import sys
from world import KEYS, check, finish
from warrant import pact as P, records as R, jcs as C
from warrant.store import Snapshot

def snap(envs):
    return Snapshot([C.canon(e) + b"\n" for e in envs], {}, sort=True)

def pid(env):
    return R.rid(env["record"])

trust = {"warrant": "trust/3", "keys": {a: [k.public] for a, k in KEYS.items()}}
comms = {"alice": {"gives": ["signed"]}, "bob": {"gives": ["published"]}}

p = P.make_proposal("alice", KEYS["alice"], parties=["alice", "bob"], commitments=comms,
                    expires_at=100, purpose="future activation", at=10)
i = pid(p)
a = P.make_accept("alice", KEYS["alice"], i, at=40)
b = P.make_accept("bob", KEYS["bob"], i, at=50)
s = snap([p, a, b])
before = P.resolve_pacts(s, trust, as_of=20)[i]
after = P.resolve_pacts(s, trust, as_of=60)[i]
check("F1 future signatures cannot activate a pact before their timestamps",
      before["status"] == "PROPOSED" and before["accepted"] == {}
      and after["status"] == "ACTIVE", (before["status"], before["activation_at"], after["status"]))
sys.exit(finish())
