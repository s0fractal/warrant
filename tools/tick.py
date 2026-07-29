#!/usr/bin/env python3
"""Bind a record to the state of a public consensus, in both directions.

WHAT THIS BUYS, PRECISELY
-------------------------
Two separate proofs, doing two different jobs. Conflating them is the usual way
this idea is oversold.

  NOT-BEFORE (entanglement).  A recent Bitcoin block hash embedded in a record
  could not have been guessed in advance, so the record was fixed AFTER that
  block was published. This does not make a record older. It makes it unable to
  *claim* to be older -- and that is its whole value: git author dates are
  writable (`git commit --date=...`), so an unentangled record's earliness is
  self-asserted. Entanglement converts "trust my clock" into a checkable floor.

  NOT-AFTER (OpenTimestamps).  A hash submitted to OTS is aggregated into a
  Merkle tree whose root lands in a later Bitcoin block, proving the record
  existed BEFORE that block. This is the half that carries a prior-art claim,
  because prior art needs "existed by date X", not "was not backdated".

Together they bound the record inside a block interval. Neither half is
optional if you want the interval; either half alone answers a different
question, and saying which one you are answering is most of the honesty here.

WHAT IT DOES NOT BUY
--------------------
  * Not wall-clock time. Bitcoin block timestamps are asserted by miners, are
    only required to exceed the median of the previous eleven, and may run up to
    two hours ahead of a node's own clock. The ORDER of blocks is solid; the
    mapping from a block to a UTC instant carries hours of slack, not minutes.
    Quote intervals in blocks and state the drift; do not quote a UTC minute.
  * Not eIDAS qualified-timestamp status. The Article 41 presumption of accuracy
    attaches to timestamps from a qualified trust service provider. Bitcoin is
    not a QTSP, and a hash chain has weaker standing in continental proceedings
    than a QTSP token -- which is exactly why the QTSP bridge is a separate item
    and not something this file quietly satisfies.
  * Not public availability. A timestamp proves a document existed, never that
    anyone could read it. Prior art needs the second, and that comes from public
    archives (see PRIOR-ART.md), not from this.

WHY THIS IS NOT A NEW WARRANT FIELD
-----------------------------------
SPEC.md §6(1) requires a body to be schema-valid with NO unknown fields,
recursively. A `clock` member added to the body would change every WarrantID and
invalidate every stored record and test vector -- a v0.4 spec change, not a
feature. It is unnecessary: a tick is a blob, cited by hash in `evidence`, which
is the mechanism the format already has for "this record stands on that bytes".

And it stays out of `eval` entirely. Book I is deterministic, integer-only,
total, with no clock and no network. Pricing ATP in block ticks would inject a
network-dependent input into the identity core and destroy the one property the
system exists to provide: two independent machines agreeing bit-exact. A tick is
an annotation over identity, never part of it -- the same rule the wave layer
already obeys.

USAGE
    python3 tools/tick.py fetch                    # current tip, cross-checked
    python3 tools/tick.py stamp FILE               # tick + OTS submit for FILE
    python3 tools/tick.py verify FILE.ots          # what the proof says so far
"""
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Independent operators, queried separately and required to agree. A single API
# cannot forge a block hash -- proof of work stops that -- but it can serve a
# STALE one, which silently weakens the not-before floor to an earlier block.
# Agreement between unrelated operators is the cheap defence.
SOURCES = {
    "mempool.space": ("https://mempool.space/api/blocks/tip/hash",
                      "https://mempool.space/api/blocks/tip/height"),
    "blockchain.info": ("https://blockchain.info/q/latesthash",
                        "https://blockchain.info/q/getblockcount"),
}


def get(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode().strip()


def fetch_tip(tolerance=2):
    """Current chain tip, agreed by independent sources.

    Heights are allowed to differ by a block or two: the sources are genuinely
    independent and a block may land between two HTTP requests. Hashes must
    agree exactly at the LOWER height -- disagreement there is either a chain
    split or a lying endpoint, and both are reasons to stop rather than guess.
    """
    seen = {}
    for name, (hash_url, height_url) in SOURCES.items():
        try:
            seen[name] = {"hash": get(hash_url), "height": int(get(height_url))}
        except Exception as e:                          # noqa: BLE001
            seen[name] = {"error": str(e)}

    ok = {k: v for k, v in seen.items() if "hash" in v}
    if len(ok) < 2:
        raise SystemExit(f"need two agreeing sources, got {len(ok)}: "
                         f"{json.dumps(seen, indent=2)}")

    heights = [v["height"] for v in ok.values()]
    if max(heights) - min(heights) > tolerance:
        raise SystemExit(f"sources disagree on height by more than {tolerance} "
                         f"blocks: {heights} -- refusing to record a tick")

    lowest = min(ok.values(), key=lambda v: v["height"])
    agreeing = [k for k, v in ok.items() if v["height"] == lowest["height"]]
    if len(agreeing) > 1:
        hashes = {ok[k]["hash"] for k in agreeing}
        if len(hashes) > 1:
            raise SystemExit(f"sources disagree on the hash at height "
                             f"{lowest['height']}: {hashes} -- chain split or a "
                             f"lying endpoint; not recording a tick")
    return {
        "tick_version": "1",
        "chain": "bitcoin-mainnet",
        "block_height": lowest["height"],
        "block_hash": lowest["hash"],
        "sources": {k: {kk: vv for kk, vv in v.items()} for k, v in seen.items()},
        "proves": "not-before: this record was fixed after this block was published",
        "does_not_prove": ("wall-clock time (miner-asserted, up to 2h drift); "
                           "eIDAS qualified status; public availability"),
    }


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n"


def cmd_fetch(args):
    tick = fetch_tip()
    body = canonical(tick)
    print(body, end="")
    print(f"# tick_sha256 {hashlib.sha256(body.encode()).hexdigest()}",
          file=sys.stderr)
    return 0


def cmd_stamp(args):
    target = Path(args.file)
    if not target.exists():
        raise SystemExit(f"no such file: {target}")

    tick = fetch_tip()
    tick["subject_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    tick["subject_path"] = str(target.relative_to(ROOT)
                               if target.is_absolute() else target)
    body = canonical(tick)
    out = target.with_suffix(target.suffix + ".tick.json")
    out.write_text(body)
    print(f"not-before  block {tick['block_height']} {tick['block_hash'][:24]}…")
    print(f"tick        {out}")

    # OTS stamps the TICK, not the bare file: the tick already commits to the
    # file's hash, so one proof covers both halves and they cannot drift apart.
    if not args.no_ots:
        r = subprocess.run(["ots", "stamp", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"OTS submit failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        print(f"not-after   submitted to OTS calendars -> {out}.ots")
        print("            (the Bitcoin attestation upgrades in a few hours: "
              "`ots upgrade`)")
    return 0


def cmd_verify(args):
    r = subprocess.run(["ots", "verify", args.file],
                       capture_output=True, text=True)
    print((r.stdout + r.stderr).strip())
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    s = sub.add_parser("stamp")
    s.add_argument("file")
    s.add_argument("--no-ots", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("file")
    args = ap.parse_args()
    return {"fetch": cmd_fetch, "stamp": cmd_stamp, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
