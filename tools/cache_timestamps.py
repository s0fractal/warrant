#!/usr/bin/env python3
"""Read the build timestamps a committed Go cache left behind, by accident.

WHY BOTHER WITH JUNK
--------------------
`impl-go/.gocache/` was committed by mistake and removed in 2de1d17. It is
worthless as code: 56 MB of compiled objects keyed to one machine's toolchain,
meaningless anywhere else.

But every `-a` entry is one line written by the Go build system:

    v1 <action-hash> <output-hash> <size> <unix-nanoseconds>

That last field is a clock reading git never saw. Git dates are writable --
`git commit --date=…` takes anything, and the commit hash covers the forgery, so
it is internally consistent. These are not covered by that: forging a commit
date while leaving hundreds of nanosecond build stamps consistent with it, with
a plausible compile spread, is a different and much easier thing to get wrong.

So the cache is not evidence of a date. It is evidence *against having faked
one*, which is a weaker and more useful claim than it sounds, and it costs
nothing because the bytes are already in the history and already archived.

WHAT THIS IS NOT
----------------
Corroboration, never proof. These files are as writable as any other; a careful
forger fixes them too. The value is only that a careless one does not, and that
the check is free. Treat agreement as one weak independent signal among the
attestations in PRIOR-ART.md -- never as a substitute for them.

USAGE
    python3 tools/cache_timestamps.py 9421f02
    python3 tools/cache_timestamps.py 9421f02 --limit 2000
"""
import argparse
import datetime as dt
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = "impl-go/.gocache"


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def stamps(ref, limit):
    paths = [p for p in git("ls-tree", "-r", "--name-only", ref, "--", CACHE)
             .splitlines() if p.endswith("-a")][:limit]
    out = []
    for p in paths:
        try:
            last = git("show", f"{ref}:{p}").split()[-1]
        except (subprocess.CalledProcessError, IndexError):
            continue
        # 19 digits is unix nanoseconds; anything else is not this field.
        if len(last) == 19 and last.isdigit():
            out.append(int(last) / 1e9)
    return sorted(out)


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.UTC).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()

    ts = stamps(args.ref, args.limit)
    if not ts:
        print(f"no build stamps under {CACHE} at {args.ref}")
        return 1

    commit_iso = git("show", "-s", "--format=%cI", args.ref).strip()
    commit_t = dt.datetime.fromisoformat(commit_iso).timestamp()

    print(f"ref            {args.ref}")
    print(f"stamps read    {len(ts)}")
    print(f"build earliest {iso(ts[0])}")
    print(f"build median   {iso(statistics.median(ts))}")
    print(f"build latest   {iso(ts[-1])}")
    print(f"build spread   {(ts[-1] - ts[0]) / 60:.1f} min")
    print(f"git claims     {iso(commit_t)}  (self-asserted, writable)")

    gap = (commit_t - ts[-1]) / 60
    # A commit BEFORE its own build outputs is the interesting direction: it
    # means one of the two clocks is lying, and only one of them is cheap to lie
    # with. Report it; do not adjudicate it.
    if gap < 0:
        print(f"\nINCONSISTENT: commit is {abs(gap):.1f} min EARLIER than the "
              f"build it contains. One of these clocks is wrong.")
        return 2
    print(f"\nconsistent: commit follows the build by {gap:.1f} min")
    print("corroboration only -- these files are writable too; see PRIOR-ART.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
