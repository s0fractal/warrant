#!/usr/bin/env python3
"""The negative control: a transparent proxy that breaks a candidate on purpose.

    python3 stub/mutate.py --mutation accept-all -- ./my-verifier probe

It speaks the candidate side of CONTRACT.md, forwards each request to the real
candidate, and corrupts the answer in one specific, named way. `run.py
--self-check` drives it through every mutation and asserts the runner noticed.

WHY IT WRAPS *YOUR* IMPLEMENTATION RATHER THAN SHIPPING A FAKE ONE
------------------------------------------------------------------
A hand-written broken implementation would only prove that this runner can catch
*that* fake. Wrapping the candidate you are about to test proves something you
actually care about: "if MY verifier were permissive, this runner would say so."
The green run you get afterwards means something because you have just watched
the same runner, on the same machine, over the same vectors, go red.

This project has shipped gates that could not fail — a release check that asked
whether a subcommand appeared in `--help` rather than whether it worked; a
verifier that reported a store clean after its policy blob was replaced. A
conformance runner nobody has seen fail is in that family until it has been seen
to fail.

THE MUTATIONS
-------------
  accept-all         every validity answer becomes "yes": bodies validate, bytes
                     parse, signatures verify, stores report zero errors. Passes
                     every positive vector in the pack. This is the shape of the
                     implementation the MUST-REJECT half exists to catch.
  legacy-sig         builds the SPEC §5 signed message the pre-0.6.0 way (the
                     bare 32-byte WarrantID, no domain separator). Every §8
                     WarrantID still reproduces; only §8.5 notices.
  false-unsupported  answers `unsupported` for two classes while still claiming
                     its grade. Nothing fails — the vectors simply never run,
                     which is the failure mode a pass/fail runner cannot express.
  crash              exits nonzero instead of answering. A contract violation:
                     not a pass, and not a legitimate skip either.
  none               forwards unchanged (the known-good control).

A MUTATION THAT CANNOT APPLY IS NOT A MUTATION
----------------------------------------------
Every mutation here corrupts an ANSWER. A candidate that answers almost nothing —
which is every implementation on its first afternoon — has almost nothing to
corrupt, and the proxy then forwards a response it did not touch. That is not the
runner failing to notice a defect; there was no defect to notice.

So this proxy reports what it did. `--applied-log FILE` appends one line per
request whose response this proxy actually CHANGED, and `--describe` prints, as
JSON, which classes each mutation can reach. `run.py --self-check` reads both,
and uses them to separate three states that used to be one: the mutation applied
and was caught, the mutation applied and slipped through (loud failure), and the
mutation could not apply at all. "Applied" means the bytes the runner receives
differ from the bytes the real candidate produced — not that this program took a
code path.
"""
import argparse
import json
import subprocess
import sys

MUTATIONS = ("none", "accept-all", "legacy-sig", "false-unsupported", "crash")

# Chosen because they are cheap for a candidate to implement, so "I did not get
# round to it" is not a plausible excuse for them being missing — which is what
# makes their absence worth reporting loudly.
UNSUPPORTED_CLASSES = ("verify-sig", "parse")

# Which classes each mutation can reach, published rather than duplicated: the
# runner needs this to tell "your candidate does not implement the class this
# mutation targets" from "this proxy is broken", and a second copy of the list
# inside run.py would be one more place to drift. `crash` reaches everything,
# including `capabilities`, so it lists nothing in particular.
TARGETS = {
    "none": [],
    # Every class whose answer contains a validity verdict the proxy can flip.
    "accept-all": ["validate", "parse", "verify-sig", "verify-store"],
    "legacy-sig": ["sig-message"],
    "false-unsupported": list(UNSUPPORTED_CLASSES),
    "crash": [],
}


def accept_all(cls, output):
    """Say yes to everything a verifier could say no to."""
    if "valid" in output:
        output["valid"] = True
        output["errors"] = []
    if "ok" in output:
        output["ok"] = True
    if isinstance(output.get("errors"), int):
        output["errors"] = 0
    return output


def legacy_sig(cls, request, output):
    if cls == "sig-message":
        # The pre-0.6.0 construction: sign the bare WarrantID with no separator.
        wid = (request.get("input") or {}).get("warrant_id", "")
        return {"message_hex": wid}
    return output


def record(path, mutation, cls, vid):
    """Append one line for a request whose answer this proxy actually changed."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{mutation}\t{cls}\t{vid}\n")


def main():
    ap = argparse.ArgumentParser(allow_abbrev=False, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mutation", choices=MUTATIONS)
    ap.add_argument("--applied-log", metavar="FILE",
                    help="append one line per response this proxy actually "
                         "changed (the runner counts them)")
    ap.add_argument("--describe", action="store_true",
                    help="print which classes each mutation can reach, as JSON, "
                         "and stop")
    ap.add_argument("candidate", nargs=argparse.REMAINDER,
                    help="-- followed by the real candidate's argv")
    args = ap.parse_args()
    if args.describe:
        print(json.dumps({"tag": "warrant.conformance-mutations@v1",
                          "targets": TARGETS}, sort_keys=True))
        return 0
    if not args.mutation:
        ap.error("--mutation is required")
    argv = [a for a in args.candidate if a != "--"]
    if not argv:
        ap.error("give the real candidate after `--`")

    raw = sys.stdin.buffer.read()
    try:
        request = json.loads(raw.decode("utf-8"))
    except ValueError:
        request = {}
    cls = request.get("class")
    vid = request.get("id")

    if args.mutation == "crash":
        # Always applies: whatever the candidate would have said — an answer or
        # an honest `unsupported` — the runner now gets no response at all.
        record(args.applied_log, "crash", cls, vid)
        sys.stderr.write("mutate: deliberate failure (mutation=crash)\n")
        return 1

    proc = subprocess.run(argv, input=raw, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return proc.returncode
    try:
        resp = json.loads(proc.stdout.decode("utf-8"))
    except ValueError:
        sys.stdout.buffer.write(proc.stdout)
        return 0

    output = resp.get("output")
    if args.mutation == "false-unsupported" and cls in UNSUPPORTED_CLASSES:
        # The real candidate is asked FIRST, and the answer is withheld only if
        # there was an answer to withhold. Against a candidate that already
        # declines this class the proxy changes nothing, and must not claim to:
        # "it declined what it was already declining" is not a defect the runner
        # failed to see.
        #
        # What is still NOT done here: the capabilities answer keeps claiming the
        # class and the grade. The lie is only visible if the runner treats a
        # skipped vector as its own outcome.
        if isinstance(output, dict):
            record(args.applied_log, "false-unsupported", cls, vid)
            print(json.dumps({"warrant_conformance": "1", "id": vid,
                              "unsupported": f"mutation=false-unsupported: "
                                             f"{cls} deliberately withheld"}))
            return 0
        print(json.dumps(resp, ensure_ascii=True))
        return 0

    if isinstance(output, dict) and cls != "capabilities":
        before = json.dumps(output, sort_keys=True, ensure_ascii=True)
        if args.mutation == "accept-all":
            resp["output"] = accept_all(cls, dict(output))
        elif args.mutation == "legacy-sig":
            resp["output"] = legacy_sig(cls, request, dict(output))
        after = json.dumps(resp["output"], sort_keys=True, ensure_ascii=True)
        if after != before:
            record(args.applied_log, args.mutation, cls, vid)
    print(json.dumps(resp, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
