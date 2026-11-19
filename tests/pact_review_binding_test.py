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

from warrant import delegate as D
profile = {"warrant": "profile/3", "roles": {"acceptor": ["alice"]}}
g = P._sign_env(D.grant_record("alice", "worker", KEYS["dave"].public,
    ["acceptor"], ["attest"], 0, 200, at=1), KEYS["alice"])
gid = pid(g)
legit = P.make_proposal("alice", KEYS["alice"], parties=["alice", "bob"], commitments=comms,
    expires_at=100, purpose="authorized binding", escrow_grants=[gid], at=10)
i = pid(legit)
a = P.make_accept("alice", KEYS["alice"], i, at=11)
b = P.make_accept("bob", KEYS["bob"], i, at=12)
base = [g, legit, a, b]
before = P.resolve_escrow(snap(base), trust, profile, 20)["escrow"][gid]
# Carol has no grant authority and neither Carol nor Dave is the grant's issuer/delegate.
evil = P.make_proposal("carol", KEYS["carol"], parties=["carol", "dave"],
    commitments={"carol": {"gives": ["x"]}, "dave": {"gives": ["y"]}},
    expires_at=100, purpose="unsolicited binding", escrow_grants=[gid], at=15)
after = P.resolve_escrow(snap(base+[evil]), trust, profile, 20)["escrow"][gid]
check("F3 an unrelated proposal cannot freeze another issuer's active grant",
      before["escrow_allowed"] and after["escrow_allowed"], (before, after))
sys.exit(finish())
