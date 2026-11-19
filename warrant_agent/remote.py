"""Another agent's store, read by its address: the first contact between agents that share no checkout.

    remote {url, op: status | find | context, under?, ...}

`url` is where a store is served over HTTPS as a repository serves it: `<url>.warrant/v3.json` (the publisher's
receiver) and `<url>.warrant/records.jsonl` (e.g. https://raw.githubusercontent.com/OWNER/NAME/BRANCH/). The records
are read once per call, bounded by the operator's `store_bytes`, and assessed in process, never executed:
  - under the publisher's own rules (`under` omitted): what that store counts, as it would answer itself;
  - under one of this agent's workspaces (`under: NAME`): that workspace's trust and profile, so a record counts here
    only when this agent's own rules say so (a name means what its trust binds it to, not what the publisher says).
Each source its .warrant/sources.json declares is read at the commit its ref names now (GitHub's commits API, for a
root on raw.githubusercontent.com), by its declared actors only, as warrant/sources.py reads one; a source this read
cannot resolve is named under `sources_not_read`, never read as empty. `status` gives its identity (the root of its
rules@1 lineage), the lineages by schema and state, the challenges standing and each source with its commit; `find` and `context` answer as warrant_find and warrant_context do for a local workspace. No checkout is
read beside it, so a pinned lineage reads PINS_NOT_CHECKED, never ELIGIBLE (docs/V3.md section 10), and blobs are not
fetched: a cited blob reads unavailable, never absent.

The address is the request's; where it may lead is the operator's: HTTPS only, no redirect to another host, and no
host that resolves to a loopback, private, link-local or reserved address unless the operator's configuration names it
(`remote.allow_hosts`), so an agent cannot point this server at the network it runs in. Nothing is written."""
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from warrant import graph as G
from warrant import shapes as S
from warrant.records import MIGRATION
from warrant import sources as SRC
from warrant.store import Snapshot, _line_id

from .errors import AgentError, need

OPS = ("status", "find", "context")
TIMEOUT = 20
FILES = (".warrant/v3.json", ".warrant/records.jsonl")


def _maps(lines):
    """The blobs the migration attests of `lines` target: what a store's migrated records are counted by."""
    out = set()
    for ln in lines:
        try:
            r = json.loads(ln)["record"]
        except (ValueError, KeyError, TypeError):
            continue
        t = (r.get("body") or {}).get("target") if isinstance(r, dict) else None
        if r.get("kind") == "attest" and r.get("schema") == MIGRATION and S.hex64(t):
            out.add(t)
    return sorted(out)


def _actor(line):
    try:
        return json.loads(line)["record"]["actor"]
    except (ValueError, KeyError, TypeError):
        return None


RAW = re.compile(r"https://raw\.githubusercontent\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})/")


def source_commit(url, ref):
    """The commit `ref` names now in the repository a raw.githubusercontent.com root serves, by GitHub's commits API;
    None elsewhere or when GitHub names none (the source is then named as not read, never read as empty)."""
    m = RAW.match(url)
    if not m:
        return None
    try:
        sha = json.loads(_get(f"https://api.github.com/repos/{m[1]}/{m[2]}/commits/{ref}", 1 << 20)).get("sha")
    except (AgentError, ValueError, AttributeError):
        return None
    return sha if S.hex_of(sha, 40) else None


def source_base(url, commit):
    """Where a source is served at `commit` beside the root `url`: the same repository at that commit."""
    m = RAW.match(url)
    return f"https://raw.githubusercontent.com/{m[1]}/{m[2]}/{commit}/" if m else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):          # a store is read where it was named, never where it points
        return None


def _checked(url, allow):
    """`url` refused unless it is an HTTPS address of a public host, or of a host the operator allows."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        u = None
    need(u is not None and u.scheme in ("https", "http") and u.hostname and not u.username and not u.password
         and not u.query and not u.fragment and url.endswith("/"),
         "BAD_REQUEST", "url is the HTTPS address of a store's root, ending in /, with no credentials, query or fragment")
    host = u.hostname
    if host in allow:
        return url
    need(u.scheme == "https", "BAD_REQUEST", "a store is read over HTTPS")
    try:
        addrs = {ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host, u.port or 443, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, ValueError):
        raise AgentError("NOT_FOUND", f"{host}: no address") from None
    need(addrs and all(a.is_global for a in addrs), "NOT_PERMITTED",
         f"{host} resolves to an address that is not public: the operator names such a host in remote.allow_hosts")
    return url


def _get(url, limit):
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "warrant-agent remote reader"})
    try:
        with opener.open(req, timeout=TIMEOUT) as r:  # NOSONAR S5332: plain HTTP only for a host the operator allows
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise AgentError("NOT_FOUND" if e.code == 404 else "REFUSED", f"{url}: HTTP {e.code}") from None
    except (OSError, ValueError) as e:            # urllib.error.URLError is an OSError
        raise AgentError("REFUSED", f"{url}: not fetched ({type(e).__name__})") from None
    need(len(data) <= limit, "RESOURCE_LIMIT", f"{url} is larger than this server reads ({limit} bytes)")
    return data


class Remote:
    """A store read from its address, shaped as a workspace for the API's readers: no repository, no signer."""

    repo, signer = None, None

    def __init__(self, url, limits, under=None):
        self.name, self.limits, self.url = url, limits, url
        self.doc = self._receiver_doc()
        self.budget = limits["store_bytes"]
        lines = [x + b"\n" for x in _get(url + FILES[1], self.budget).split(b"\n") if x]
        blobs = {}
        for h in _maps(lines):                    # a migration's map: its records count only with it (as site/ reads it)
            blobs[h] = self._spend(_get(f"{url}.warrant/blobs/{h}", self.budget), "the migration maps")
        try:
            self.snap = Snapshot(lines, blobs)
        except ValueError as e:                  # store.Refused included
            raise AgentError("RESOURCE_LIMIT" if "limit" in str(e) else "REFUSED", str(e)) from None
        self._receiver = under.receiver() if under is not None else (self.doc["trust"], self.doc["profile"])
        self.sources, self.sources_not_read = [], []
        extra = set()
        for x in self._declared():               # each at the commit its ref names, by its actors only (sources.py)
            extra |= self._source(x)
        if extra:
            self.snap = Snapshot(sorted(set(self.snap.raw) | extra, key=_line_id), self.snap.blobs)

    def _receiver_doc(self):
        try:
            doc = json.loads(_get(self.url + FILES[0], 1 << 20))
        except ValueError:
            doc = None
        if not (isinstance(doc, dict) and isinstance(doc.get("trust"), dict) and isinstance(doc.get("profile"), dict)):
            raise AgentError("BAD_REQUEST", f"{self.url}{FILES[0]} is no repository's receiver")
        return doc

    def _spend(self, data, what):
        self.budget -= len(data)
        need(self.budget > 0, "RESOURCE_LIMIT", f"{self.url}: {what} are larger than this server reads")
        return data

    def _declared(self):
        """The sources its .warrant/sources.json declares; none when it has none; a declaration that cannot be read is
        named under sources_not_read."""
        try:
            return SRC.declared(json.loads(_get(self.url + ".warrant/sources.json", 1 << 16)))
        except AgentError as e:
            if e.code != "NOT_FOUND":
                self.sources_not_read.append("(sources.json not read)")
        except ValueError:
            self.sources_not_read.append("(sources.json malformed)")
        return []

    def _source(self, x):
        """The lines of source `x` by its actors, read at the commit its ref names, or none (and it is named unread)."""
        commit = source_commit(self.url, x["ref"])
        base = source_base(self.url, commit) if commit else None
        if base is None:
            self.sources_not_read.append(x["name"])
            return set()
        got = [ln + b"\n" for ln in self._spend(_get(base + FILES[1], self.budget), "its sources").split(b"\n") if ln]
        mine = [ln for ln in got if _actor(ln) in x["actors"]]
        self.sources.append({"name": x["name"], "ref": x["ref"], "commit": commit, "records": len(mine),
                             "left_out": len(got) - len(mine)})
        return set(mine)

    def receiver(self):
        return self._receiver

    def permit(self, _op):                   # every read is permitted: the operator allowed the address
        return None

    def open(self):
        return self

    def snapshot(self):
        return self.snap


def remote(api, cfg, req):
    api._closed(req, ("url", "op"), ("under", "schema", "kind", "actor", "where", "text", "state", "leaves", "limit",
                                     "targets"))
    need(req["op"] in OPS, "BAD_REQUEST", f"op is one of {list(OPS)}")
    allow = set(getattr(cfg, "remote", {}).get("allow_hosts", []))
    url = _checked(req["url"] if isinstance(req["url"], str) else "", allow)
    under = cfg.workspace(req["under"]) if req.get("under") is not None else None
    limits = (under or next(iter(cfg.workspaces.values()))).limits
    ws = Remote(url, limits, under)
    rest = {k: v for k, v in req.items() if k not in ("url", "op", "under")}
    if req["op"] == "find":
        return dict(api.W.find(api, _Cfg(ws), dict(rest, workspace="remote")), url=url, under=req.get("under"))
    if req["op"] == "context":
        api._closed(rest, (), ("targets",))
        return dict(api.context(_Cfg(ws), dict(rest, workspace="remote")), url=url, under=req.get("under"))
    api._closed(rest, (), ())
    snap, view, _, _ = api._assess(ws)
    rep = api._report(ws, view)
    counts, challenges = {}, sum(1 for x in rep["challenges"].values() if x["counted"] and x.get("stands", True))
    for lin in rep["lineages"].values():
        key = f"{lin['schema']} {lin['state']}"
        counts[key] = counts.get(key, 0) + 1
    reliance = {}
    for lin in rep["lineages"].values():
        reliance[lin["reliance"]] = reliance.get(lin["reliance"], 0) + 1
    return {**api._header(rep), "url": url, "under": req.get("under"), "repository": ws.doc.get("repository"),
            "identity": G.identity(rep, snap), "records": len(snap.lines), "lineages": dict(sorted(counts.items())),
            "reliance": dict(sorted(reliance.items())), "challenges_standing": challenges,
            "trusted": sorted(ws.receiver()[0].get("keys", {})),
            # the sources it declares, each read at the commit its ref names, by its actors only; and those this
            # read could not take in, whose records do not count here
            "sources": ws.sources, "sources_not_read": ws.sources_not_read}


class _Cfg:
    """One workspace, the remote store, under the handle `remote`, for the API's readers."""

    def __init__(self, ws):
        self.workspaces = {"remote": ws}

    def workspace(self, _name):
        return self.workspaces["remote"]
