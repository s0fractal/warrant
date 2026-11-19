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

prior = R.record("schema", "alice", 1, {"name": "prior@1", "fields": {"state": "str"},
    "states": {"open": None}, "closed": [], "successors": {}})
p = P.make_proposal("alice", KEYS["alice"], parties=["alice", "bob"], commitments=comms,
    expires_at=100, purpose="root entity after a prior actor record", at=10)
rec = dict(p["record"], prev=R.rid(prior))
env = P._sign_env(rec, KEYS["alice"])
s = snap([P._sign_env(prior, KEYS["alice"]), env])
i = pid(env)
r = P.resolve_pacts(s, trust, 20)[i]
check("F5 a lineage-root proposal may follow an earlier record in its actor's chain",
      rec["lineage"] is None and r["status"] == "PROPOSED", (r["status"], r["reason"]))
sys.exit(finish())
