"""The gate's receipt: a merge the merge gate made, stated by the gate's own key.

    WARRANT_GATE_SEED=... python -m warrant.receipt file --merge M.json --pull P.json --commit C.json --repository O/N --store DIR
    WARRANT_GATE_SEED=... python -m warrant.receipt public

Exit status of `file`: 0 filed (or already filed for this merge), 3 refused (the inputs do not agree, or the merge is
not one this receipt describes: nothing filed), 2 the receipt itself cannot be filed (no seed, a store not its own).

Until now a `merged` record was filed afterwards by an agent with its own key (`python -m warrant.review merged`), for
some merges and not others. This files one for every merge the gate makes, signed by the key of the actor
`merge-gate`, in a store of its own on the branch `receipts` (.github/workflows/merge-on-acceptance.yml, job
`receipt`). The body has the shape of an agent's `merged` attest (`target`, `verdict: "merged"`, `merge`, `tip`, `how`)
and adds the base and the pull request's address.

What a receipt says, and all it says: **the gate's key states that GitHub reports pull request #N merged as commit M,
with parents (base, head), from the head version V the gate assessed, the merge's message saying how.** Three inputs
must agree before anything is filed: the gate's own account of the merge (`merge_one`'s result), the pull request as
GitHub reports it (merged, at that merge commit, from that head) and the merge commit as GitHub reports it (its two
parents, its message). `how` is read from that message (`review.merged_how`); a merge whose message is not the gate's
is refused, so the key never states a hand merge.

The store trusts one name, `merge-gate`, bound to the gate's key, and gives nobody a role: a receipt counts for nothing
in any store. Read beside this repository's own store, it is a signed observation on the head version it targets, as
an agent's `merged` attest is. A key that leaked states merges that did not happen; anyone can compare each receipt with
the merge commit it names.

A receipt already filed stops a second only when it is signed under the store's key and says the same; any other line
makes the store not the gate's (Broken), so a forged line can neither stand in for a receipt nor hide a merge.

Limits: one receipt per merge commit; a revert of a vetoed merge gets none (it targets a commit, not a record: the
revert's own message names the merge it reverts)."""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from . import keys as K
from . import records as R
from . import shapes as S
from .engine import _authentic, head
from .review import merged_how
from .store import Refused as StoreRefused
from .store import Store

ACTOR = "merge-gate"
SEED_ENV = "WARRANT_GATE_SEED"
NAME = "receipts/merge-gate"
V3 = "v3.json"
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")


class Refused(Exception):
    """The inputs do not describe one merge the gate made; nothing is filed."""


class Broken(Exception):
    """The receipt cannot be filed (its seed, its store): an error of the run."""


SOURCE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def _positive(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 < v < 2 ** 53


def body_of(merge, pull, commit, repository):
    """The receipt's body, or Refused naming the first input that does not agree. `merge` is the gate's result for the
    merge (`merge_one`), `pull` GitHub's pull request, `commit` GitHub's merge commit (REST shapes)."""
    if not (isinstance(repository, str) and REPOSITORY.fullmatch(repository)):
        raise Refused("the repository is not OWNER/NAME")
    if not (isinstance(merge, dict) and merge.get("merged") is True and _positive(merge.get("pr"))):
        raise Refused("the gate's result is not a merge")
    m, tip, base, v = merge.get("merge"), merge.get("head"), merge.get("base"), merge.get("version")
    if not all(S.hex_of(x, 40) for x in (m, tip, base)):
        raise Refused("the gate's result names no merge, head and base commits")
    if not S.hex64(v):
        raise Refused("the gate's result names no head version (a revert targets a commit: it gets no receipt)")
    if not (isinstance(pull, dict) and pull.get("number") == merge["pr"] and pull.get("merged") is True
            and pull.get("merge_commit_sha") == m and isinstance(pull.get("head"), dict) and pull["head"].get("sha") == tip):
        raise Refused("GitHub's pull request is not that one merged as that commit from that head")
    if not isinstance(commit, dict):
        raise Refused("GitHub's merge commit is not that commit with the parents (base, head)")
    parents = commit.get("parents")
    if not (commit.get("sha") == m and isinstance(parents, list) and all(isinstance(p, dict) for p in parents)
            and [p.get("sha") for p in parents] == [base, tip]):
        raise Refused("GitHub's merge commit is not that commit with the parents (base, head)")
    message = commit["commit"].get("message") if isinstance(commit.get("commit"), dict) else None
    if not isinstance(message, str):
        raise Refused("GitHub's merge commit carries no message")
    how = merged_how(message)
    if how == "hand":
        raise Refused("the merge commit's message is not the gate's: the gate's key states only the gate's merges")
    if how == "revert":
        raise Refused("a revert of a vetoed merge targets a commit: it gets no receipt")
    src = merge.get("sources", {})
    if not (isinstance(src, dict) and all(isinstance(k, str) and SOURCE_NAME.fullmatch(k) and (x is None or S.hex_of(x, 40))
                                          for k, x in src.items())):
        raise Refused("the gate's result names its sources' tips in no form a receipt states")
    body = {"target": v, "verdict": "merged", "merge": m, "tip": tip, "base": base, "how": how,
            "github": {"repository": repository, "pr": merge["pr"], "url": f"https://github.com/{repository}/pull/{merge['pr']}"}}
    if src:                       # the commit each declared source's ref named at the merge (Codex 7f09815d); null: none
        body["sources"] = dict(sorted(src.items()))
    return body


def doc_for(public):
    """The configuration of the receipts' store: one name bound to one key, no roles."""
    return {"warrant": "repository/3", "repository": NAME,
            "trust": {"warrant": "trust/3", "keys": {ACTOR: [public]}}, "profile": {"warrant": "profile/3", "roles": {}}}


def is_receipt_store(doc, public):
    """Whether a store's configuration is the gate's: it trusts the one name, bound to this key among its keys, and
    gives nobody a role."""
    if not (isinstance(doc, dict) and doc.get("warrant") == "repository/3" and isinstance(doc.get("trust"), dict)
            and isinstance(doc.get("profile"), dict) and doc["profile"].get("roles") == {}):
        return False
    keys = doc["trust"].get("keys")
    return isinstance(keys, dict) and set(keys) == {ACTOR} and isinstance(keys[ACTOR], list) and public in keys[ACTOR]


def init(store, key):
    """The receipts' store at `store` (a directory holding `.warrant/`), made when absent; an existing one is used only
    when it is the gate's."""
    dot = Path(store).resolve() / ".warrant"   # NOSONAR S8707: the workflow names its own checkout of the receipts branch; any other store is refused below
    if (dot / V3).exists():
        try:
            doc = json.loads((dot / V3).read_text())
        except ValueError:
            doc = None
        if not is_receipt_store(doc, key.public):
            raise Broken("the store is not the gate's: its trust is not the one name merge-gate bound to this key, or it gives a role")
        return dot, doc
    dot.mkdir(parents=True, exist_ok=True)
    doc = doc_for(key.public)
    (dot / V3).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    Store(dot).init()
    return dot, doc


def filed_for(dot, trust, body):
    """The id of the receipt the store already holds for this body's merge commit, or None. Only a record signed under
    the key the store binds to merge-gate stands for a receipt: a line that is not one (unsigned, signed by another key,
    another actor's) makes the store not the gate's, and so does a signed receipt for the same merge that says
    something else; either is Broken, never a reason to skip signing."""
    snap = Store(dot).snapshot()
    recs, basis, _, _ = _authentic(snap, trust, None)
    if set(snap.lines) - {i for i in recs if basis[i] == "SIGNED" and recs[i]["actor"] == ACTOR}:
        raise Broken("the store holds a line that is not signed under merge-gate's key: it is not the gate's")
    for rid, r in recs.items():
        if isinstance(r["body"], dict) and r["body"].get("merge") == body["merge"]:
            if (r["kind"], r["refs"], r["body"]) != ("attest", [body["target"]], body):
                raise Broken("the store holds a signed receipt for this merge that says something else")
            return rid
    return None


def file(store, merge, pull, commit, repository, key, at=None):
    """File the receipt of one merge: {"filed": id, "target", "merge", "how", "already"}. A second call for the same
    merge commit files nothing and answers with the first receipt."""
    body = body_of(merge, pull, commit, repository)
    dot, doc = init(store, key)
    out = {"target": body["target"], "merge": body["merge"], "how": body["how"]}
    had = filed_for(dot, doc["trust"], body)
    if had is not None:
        return dict(out, filed=had, already=True)
    if at is None:                  # a runner's clock behind the chain's last record must not stop the next receipt
        at = max(int(time.time()), head(Store(dot).snapshot(), doc["trust"], ACTOR)["at"] or 0)
    record = R.record("attest", ACTOR, at, body, refs=[body["target"]])
    try:
        return dict(out, filed=Store(dot).extend([record], key, doc["trust"])[0], already=False)
    except StoreRefused as e:
        raise Broken(f"the store did not take the receipt: {e}") from None


def _key():
    seed = os.environ.get(SEED_ENV, "").strip()
    if not seed:
        raise Broken(f"no {SEED_ENV} in the environment")
    return K.Key.from_seed_hex(seed)


def _json(path, what):
    try:
        return json.loads(Path(path).read_text())   # NOSONAR S8707: the runner's own files
    except (OSError, ValueError):
        raise Broken(f"the {what} file is not readable JSON") from None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m warrant.receipt", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("file", help="file the receipt of one merge the gate made")
    f.add_argument("--merge", required=True, help="the gate's result for the merge (warrant.gate gate --receipt)")
    f.add_argument("--pull", required=True, help="GitHub's pull request (GET /repos/O/N/pulls/PR)")
    f.add_argument("--commit", required=True, help="GitHub's merge commit (GET /repos/O/N/commits/MERGE)")
    f.add_argument("--repository", required=True, help="OWNER/NAME")
    f.add_argument("--store", required=True, help="the directory holding the receipts' store (.warrant/)")
    sub.add_parser("public", help="the gate's public key")
    a = ap.parse_args(argv)
    try:
        key = _key()
        if a.cmd == "public":
            print(key.public)
            return 0
        out = file(a.store, _json(a.merge, "merge"), _json(a.pull, "pull request"), _json(a.commit, "commit"), a.repository, key)
    except Refused as e:
        print(json.dumps({"refused": str(e)}, sort_keys=True))
        return 3
    except Broken as e:
        print(json.dumps({"error": str(e)}, sort_keys=True))
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
