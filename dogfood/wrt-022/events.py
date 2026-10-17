#!/usr/bin/env python3
"""The WRT-022 dogfood store: shared helpers for filing and assessing real events.

Each agent signs only its own events, with its own key. The key file is named by
the environment variable WRT022_KEY and is never read from, or written to, the
repository. See POLICY.md for what these records are, and are not.

    python3 dogfood/wrt-022/events.py assess           # anyone: the current view
    WRT022_KEY=... python3 dogfood/wrt-022/events.py accept --actor codex@warrant-wrt022
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import loops as L     # noqa: E402
import warrant as W   # noqa: E402

STORE = HERE / "store"
TRUST = HERE / "trust.json"
PROFILE = json.loads((HERE / "profile.json").read_text())
CLAUDE, CODEX = "claude@warrant-wrt022", "codex@warrant-wrt022"


def store():
    s = W.Store(str(STORE))
    s.init()
    return s


def policy(s):
    return s.put_blob((HERE / "POLICY.md").read_bytes())


def key_path():
    k = os.environ.get("WRT022_KEY")
    if not k:
        sys.exit("set WRT022_KEY to your own private key file (never one inside the repository)")
    return k


def file(s, decision, subject, actor, prior=(), note="wrt-022 dogfood"):
    body = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject, "note": note},
            "under": [policy(s)], "because": [{"kind": "prose", "text": note}], "evidence": [],
            "actor": {"id": actor}, "prior": sorted(prior), "ts": int(time.time())}
    return s.put_record({"body": body, "sigs": [W.sign_envelope(body, actor, key_path())]})


def head():
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def assess(rev=None):
    return L.assess(STORE, TRUST, int(time.time()), workspace=(ROOT, rev or head()), profile=PROFILE)


def cmd_assess(_args):
    rep = assess()
    print(f"assessment {rep['view']['assessment_id'][:16]}  workspace {rep['view']['workspace']['commit']}")
    print(f"invalid records: {len(rep['invalid_records'])}  refused events: {len(rep['refused_events'])}")
    for did, r in sorted(rep["duties"].items(), key=lambda kv: kv[1]["scope"]):
        det = L.reliance_detail(rep, did, "merge-wrt022-slice")
        statement = json.loads((STORE / "blobs" / _subject(did)).read_text())["statement"]
        print(f"- {did[:12]} {r['disposition']!s:<11} reliance {det['state']:<10} {statement}")
        for c in det["causes"]:
            print(f"      cause: {c}")
    for actor in (CLAUDE, CODEX):
        print(f"frontier({actor}): {len(L.frontier(rep, actor))} item(s)")
    return 0


def cmd_check(_args):
    """CI: every record verifies at settlement grade under trust.json, and no event is
    refused by the profile. Says nothing about whether any duty is closed."""
    rep = assess()
    bad = rep["invalid_records"] + sorted(rep["refused_events"])
    print(f"WRT-022 STORE: {len(list((STORE / 'records').glob('*.json')))} records, "
          f"{len(rep['invalid_records'])} invalid, {len(rep['refused_events'])} refused, "
          f"{len(rep['duties'])} duties assessed")
    return 1 if bad or rep["view"]["store_integrity"] != "VERIFIED" else 0


def _subject(wid):
    return json.loads((STORE / "records" / f"{wid}.json").read_text())["body"]["subject"]["hash"]


def cmd_accept(args):
    """File the acceptances owed by `--actor`: every PENDING candidate whose duty names
    that actor in its acceptance list, bound to the exact transition, mapping and
    evidence. The actor signs with its own key; nothing is filed for anyone else."""
    s = store()
    rep = assess()
    filed = 0
    for did, r in sorted(rep["duties"].items()):
        if args.actor not in r["acceptance"]:
            continue
        for c in r["candidates"]:
            if c["verdict"] != "PENDING" or args.actor not in c["why"]:
                continue
            t = json.loads((STORE / "blobs" / _subject(c["transition"])).read_text())
            evidence = t["closes"][c["mapping"]]["evidence"]
            a = s.put_blob(L.canon(L.acceptance(did, c["transition"], c["mapping"], evidence)))
            file(s, "accept", a, args.actor, prior=[c["transition"]], note="acceptance")
            filed += 1
    print(f"filed {filed} acceptance(s) as {args.actor}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("assess")
    sub.add_parser("check")
    acc = sub.add_parser("accept")
    acc.add_argument("--actor", required=True, choices=[CLAUDE, CODEX])
    args = ap.parse_args()
    return {"assess": cmd_assess, "check": cmd_check, "accept": cmd_accept}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
