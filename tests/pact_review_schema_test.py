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

from warrant import engine as E
schema = P._sign_env(R.record("schema", "alice", 1, P.SCHEMA), KEYS["alice"])
profile = {"warrant": "profile/3", "roles": {"schema/author": ["alice"]}}
v = E.View(snap([schema]), trust, profile, 10)
check("F4 the exported pact schema must be admitted by the unchanged V3 engine",
      P.SCHEMA_NAME in v.schemas, v.problems)
sys.exit(finish())
