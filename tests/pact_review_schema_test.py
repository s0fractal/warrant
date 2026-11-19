import sys
from world import KEYS, check, finish
from pact_review_world import snap, trust
from warrant import pact as P, records as R


from warrant import engine as E
schema = P._sign_env(R.record("schema", "alice", 1, P.SCHEMA), KEYS["alice"])
profile = {"warrant": "profile/3", "roles": {"schema/author": ["alice"]}}
v = E.View(snap([schema]), trust, profile, 10)
check("F4 the exported pact schema must be admitted by the unchanged V3 engine",
      P.SCHEMA_NAME in v.schemas, v.problems)
sys.exit(finish())
