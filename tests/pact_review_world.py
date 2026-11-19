"""What the pact review reproducers share: a snapshot of envelopes, a record's id, the trust of world's keys and two
parties' commitments."""
from world import KEYS
from warrant import records as R, jcs as C
from warrant.store import Snapshot


def snap(envs):
    return Snapshot([C.canon(e) + b"\n" for e in envs], {}, sort=True)


def pid(env):
    return R.rid(env["record"])


trust = {"warrant": "trust/3", "keys": {a: [k.public] for a, k in KEYS.items()}}
comms = {"alice": {"gives": ["signed"]}, "bob": {"gives": ["published"]}}
