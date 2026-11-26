"""`warrant-agent anchor witness|check --of ADDRESS`: anchor a store read by its address, with no clone (docs/V3.md §16).

    warrant-agent anchor witness --of github.com/OWNER/NAME[/tree/BRANCH] [--commit C] --actor W --key K [--root DIR]
    warrant-agent anchor check   --of ADDRESS [--commit C] [--json] [--root DIR] [--allow-host H ...]

warrant.anchor does the rest (the core reads no network); this reads the store. A GitHub address is read at one commit,
`--commit` or the one its branch names now (GitHub's commits API), at raw.githubusercontent.com/OWNER/NAME/COMMIT/, so
an anchor by address names the bytes an anchor by clone of that commit would; another HTTPS root has no commit (`""`)
and takes none. Reading is warrant_agent.remote's: its host rules (no private host unless `--allow-host` names it) and
its budget. Only the store's own records.jsonl is anchored, never a source it declares."""
import argparse
import sys

from warrant import anchor as AN
from warrant.repo import Failed, Repo, dump, env_root, load_key, main
from warrant import shapes as S
from warrant.store import Snapshot, _line_id

from . import remote as RM
from .config import DEFAULT_LIMITS
from .errors import AgentError
from .rely import address


def reader(allow=frozenset()):
    """A `read` for warrant.anchor's witness and check: (commit, snapshot, identity, repository, trust) by address."""
    def read(of, commit=None):
        try:
            url = RM._checked(address(of), set(allow))
            m = RM.RAW.match(url)
            if m:
                ref = url[len(m[0]):].rstrip("/")
                commit = commit or RM.source_commit(url, ref)
                if not commit:
                    raise Failed("ANCHOR_COMMIT", f"GitHub names no commit for {ref!r} of {url}")
                url = RM.source_base(url, commit)
            elif commit:
                raise Failed("BAD_REQUEST", "--commit names a commit of a GitHub address; this root serves no commits")
            ws = RM.Remote(url, dict(DEFAULT_LIMITS))
        except AgentError as e:
            raise Failed("ANCHOR_READ", f"{of}: {e.code}: {e}") from None
        snap = Snapshot([ln for ln in ws.snap.raw if _line_id(ln)[0] in ws.own], {})
        return (commit or "", snap, *AN.identity_of(snap, ws.doc), ws.doc["trust"])
    return read


def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(prog="warrant-agent anchor", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("witness", "check"):
        p = sub.add_parser(n)
        p.add_argument("--of", required=True, help="github.com/OWNER/NAME[/tree/BRANCH], or an HTTPS root serving .warrant/")
        p.add_argument("--commit")
        p.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                       help="a host of your own network to read from (otherwise refused, as remote's are)")
    sub.choices["witness"].add_argument("--actor", required=True)
    sub.choices["witness"].add_argument("--key", required=True)
    sub.choices["check"].add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.commit is not None and not S.hex_of(a.commit, 40):
        raise Failed("BAD_REQUEST", "--commit is a full commit id")
    repo, read = Repo(root), reader(a.allow_host)
    if a.cmd == "witness":
        dump({"anchor": AN.witness(repo, a.of, a.actor, load_key(a.key, root), a.commit, read)})
        return 0
    out = AN.check(repo, a.of, a.commit, read)
    AN.show(out, a.of, a.json)
    return 0 if out["holds"] else 1


if __name__ == "__main__":
    sys.exit(main(run))
