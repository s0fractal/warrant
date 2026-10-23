"""The command line of tools/claims.py."""
import argparse
import os
import re
import sys

from .base import AUTHOR, Refused, ROOT
from .repo import Repo
from .check import cmd_check
from .author import (cmd_accept, cmd_add, cmd_bind, cmd_challenge, cmd_heading, cmd_keygen, cmd_migrate, cmd_pin,
                     cmd_project, cmd_rehome, cmd_replay, cmd_retire, cmd_supersede, cmd_trust)
from .audit import cmd_audit
from .why import cmd_why


def _jobs(v):
    """A worker count: a decimal integer >= 1 ("+2", "-1", "0" and "two" are refused)."""
    if not re.fullmatch(r"[1-9][0-9]*", v):
        raise argparse.ArgumentTypeError(f"--jobs must be an integer >= 1, got {v!r}")
    return int(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description=sys.modules[__package__].__doc__.split("\n\n")[0])
    ap.add_argument("--selftest", action="store_true", help="burn the checker on a copy and exit")
    ap.add_argument("--jobs", type=_jobs, default=min(os.cpu_count() or 1, 8), metavar="N",
                    help="--selftest: cases run N at a time, each on its own clone (default: CPUs, at most 8)")
    ap.add_argument("--root", default=str(ROOT), help="the repository (default: this checkout)")
    sub = ap.add_subparsers(dest="cmd")

    def authoring(p):
        p.add_argument("--key", help="seed file of the signing key (or WARRANT_CLAIMS_KEY)")
        p.add_argument("--actor", default=AUTHOR)
        p.add_argument("--residual", action="append", default=[], help="what this claim does not establish")
        return p

    p = authoring(sub.add_parser("add", help="author claims from a stanza"))
    p.add_argument("--stanza", help="JSON stanza or list: {id, text, witnesses, mutants, informative, unbacked_because, "
                   "counter, residual, because, after, paragraph, item}")
    p.add_argument("--id")
    p.add_argument("--text")
    p.add_argument("--witness", action="append", default=[], help="<test file>:<case>, repeatable or comma-separated")
    p.add_argument("--mutant", action="append", default=[])
    p.add_argument("--informative", help="the reason this sentence is not normative")
    p.add_argument("--unbacked-because", help="why this normative sentence is open (no witness or no mutant)")
    p.add_argument("--because")
    p.add_argument("--after", help="a new sentence's position: the claim it follows, in its own section, or that "
                   "section's number (first under its heading)")
    p.add_argument("--paragraph", action="store_true", help="start a new paragraph after --after")
    p.add_argument("--item", action="store_true", help="start a list item after --after (with --paragraph: a new list)")
    p = authoring(sub.add_parser("supersede", help="replace a claim's statement"))
    p.add_argument("--id", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--because", required=True)
    p.add_argument("--witness", action="append", default=[])
    p.add_argument("--mutant", action="append", default=[])
    p.add_argument("--informative")
    p.add_argument("--unbacked-because", help="why the sentence is open now; the claim keeps no witnesses or mutants")
    p.add_argument("--counter", action="append", default=[],
                   help="challenge record or counter blob id already in the store (a BACKED claim losing its backing)")
    p.add_argument("--counter-file", help="a counter blob (warrant-claims/counter@1 JSON) to store and cite")
    p.add_argument("--challenge", action="store_true",
                   help="also file a challenge against the claim being replaced, its evidence the counter-evidence")
    p = authoring(sub.add_parser("retire", help="retire a claim with counter-evidence"))
    p.add_argument("--id", required=True)
    p.add_argument("--because", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--counter", help="record or blob id of the counter-evidence, already in the store")
    g.add_argument("--counter-file", help="a file to store as the counter-evidence blob")
    sub.add_parser("project", help="regenerate SPEC.md and SPEC-CLAIMS.md")
    p = authoring(sub.add_parser("migrate", help="W5, once: the first document version, from SPEC.md"))
    p.add_argument("--because", required=True)
    p = authoring(sub.add_parser("heading", help="file the heading .warrant/claims.json now pins for a section "
                                 "(a renamed one in place, a newly pinned one before the next section)"))
    p.add_argument("--section", required=True, help="the section number, or 0 for the document's title")
    p.add_argument("--because", required=True)
    p = sub.add_parser("check", help="CI: refuse any disagreement")
    p.add_argument("--base", help="the revision whose claims must survive (default: origin/master)")
    p.add_argument("--no-base", action="store_true")
    p = sub.add_parser("audit", help="report claims whose witnesses miss a mutant of their own code (blind spots)")
    p.add_argument("--matrix", action="append", required=True, metavar="FILE",
                   help="a matrix from tests/mutants.py --matrix or tests/agent_mutants.py --matrix (repeatable)")
    p.add_argument("--counters", metavar="DIR", help="write each candidate's would-be counter blob there")
    p.add_argument("--refuse", action="store_true", help="exit 1 when any candidate is found")
    p.add_argument("--json", metavar="FILE", help="also write the pairs as data (warrant-claims/audit@1), a file in $TMPDIR")
    p = sub.add_parser("why", help="the claims, obligations and goals a source statement serves, or the statements none does")
    p.add_argument("target", nargs="?", metavar="FILE:LINE")
    p.add_argument("--uncovered", nargs="?", const="", metavar="FILE",
                   help="list the statements of warrant/ and warrant_agent/ (or FILE) that no cited mutant changes")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("keygen", help="make a key: seed outside the repository, its binding and proof in the trust")
    p.add_argument("--out", required=True)
    p.add_argument("--actor", default=AUTHOR)
    p.add_argument("--no-bind", action="store_true", help="only write the seed and print the public key (to pin it first)")
    p = sub.add_parser("pin", help="pin a role's key in .warrant/roles.json (a reviewed change of who the role is)")
    p.add_argument("--key", help="seed file whose public key is pinned (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    p = sub.add_parser("bind", help="bind your key to your actor id, with the key's proof of possession")
    p.add_argument("--key", help="seed file of the key to bind (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    sub.add_parser("trust", help="print the trust/2 document of the admitted bindings")
    p = sub.add_parser("accept", help="accept claims' pending closures, signed by an acceptor their duties name")
    p.add_argument("--key", help="seed file of the acceptor's key (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    p.add_argument("--claim", action="append", default=[], help="a claim id (repeatable)")
    p.add_argument("--all", action="store_true", help="every BACKED claim whose closure awaits --actor, none countered")
    p = sub.add_parser("challenge", help="challenge a claim, with a counter blob that must replay (any bound key)")
    p.add_argument("--key", help="seed file of the challenger's key (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--because", required=True)
    p.add_argument("--counter-file", help="a counter blob (warrant-claims/counter@1 JSON) against the claim")
    p = authoring(sub.add_parser("rehome", help="G4: supersede each BACKED claim onto a duty the adopted checker accepts"))
    p.add_argument("--because", required=True)
    p = sub.add_parser("replay", help="the replay checker: accept BACKED claims by replaying their witnesses and mutants")
    p.add_argument("--key", help="seed file of the checker's key (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--claim", action="append", default=[], help="a claim id (repeatable); default: every one awaiting it")
    p.add_argument("--jobs", dest="rjobs", type=_jobs, default=min(os.cpu_count() or 1, 8), metavar="N",
                   help="test files and mutants run N at a time")
    p.add_argument("--verify", action="store_true", help="re-execute the checker acceptances new since --base instead")
    p.add_argument("--base", help="--verify: the revision before them (default: origin/master)")
    a = ap.parse_args(argv)
    if a.selftest:
        from .selftest import selftest      # it imports this module's main
        return selftest(a.jobs)
    repo = Repo(a.root)
    if a.cmd is None:
        ap.print_help()
        return 2
    try:
        if a.cmd == "project":
            cmd_project(repo)
            return 0
        if a.cmd == "check":
            return cmd_check(repo, a)
        if a.cmd == "audit":
            return cmd_audit(repo, a)
        if a.cmd == "why":
            return cmd_why(repo, a)
        if a.cmd == "replay":
            return cmd_replay(repo, a)
        {"add": cmd_add, "supersede": cmd_supersede, "retire": cmd_retire, "keygen": cmd_keygen,
         "migrate": cmd_migrate, "heading": cmd_heading, "bind": cmd_bind, "trust": cmd_trust,
         "accept": cmd_accept, "challenge": cmd_challenge, "pin": cmd_pin, "rehome": cmd_rehome}[a.cmd](repo, a)
        return 0
    except Refused as e:
        print(f"REFUSED {e.code + ' ' if e.code else ''}{e}", file=sys.stderr)
        return 2
