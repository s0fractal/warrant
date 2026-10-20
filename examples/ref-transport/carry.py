#!/usr/bin/env python3
"""Carry Warrant handoff packets between hosts over git refs, gated by owner-signed pins.

The operator in round 1 of examples/dependency-audit copied the packet by hand and
relayed its digest by message. Here the bytes travel on their own: a party pushes a
packet to `refs/warrant/out/<from>/<to>/<sha256>` of a shared git remote, and the
receiving party fetches it. What does NOT travel on its own is the pin: a packet is
delivered to a receiver only when `refs/warrant/pins/<to>/<sha256>` holds a pin
signed with an ssh key the receiver lists in its allowed-signers file (the owner's
key, as in sokol-core ADR-0023: agents move bytes, the owner pins, the gate refuses
what is not pinned). The remote is untrusted transport: a substituted, damaged or
unpinned packet is refused by digest or by signature, never delivered.

    carry.py send  --repo DIR --remote URL --from A --to B --file PACKET
    carry.py pin   --repo DIR --remote URL --signer KEY --to B --sha256 HEX [--from A]
    carry.py fetch --repo DIR --remote URL --me B --allowed-signers FILE --out DIR
    carry.py selftest

`--repo` is a private working clone for one party (created if absent). Pins are
`ssh-keygen -Y sign` signatures in the namespace `warrant-pin`; the receiver
verifies them with `ssh-keygen -Y verify` against principals it configured. The
carrier knows nothing about Warrant records: packets are opaque bytes, and the
receiving Warrant workspace still applies its own expectation, trust and profile.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

NAMESPACE = "warrant-pin"
PIN_SCHEMA = "warrant-ref-pin/1"
MAX_PACKET = 16 * 1024 * 1024


class Refused(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def need(ok, code, detail=""):
    if not ok:
        raise Refused(code, detail)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def actor_ok(a):
    return isinstance(a, str) and 0 < len(a) <= 64 and all(c.isalnum() or c in "-_." for c in a) and a[0] != "."


def hex_ok(h):
    return isinstance(h, str) and len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def canon(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


# ----------------------------------------------------------------- git plumbing

class Repo:
    def __init__(self, path, remote):
        self.path = Path(path).resolve()
        self.remote = remote
        if not (self.path / ".git").is_dir():
            self.path.mkdir(parents=True, exist_ok=True)
            self.git("init", "-q")
            self.git("remote", "add", "carrier", remote)
        else:
            need(self.git("remote", "get-url", "carrier").strip() == remote, "REMOTE",
                 "this repository carries for another remote")

    def git(self, *args, inp=None):
        p = subprocess.run(["git", "-C", str(self.path), *args], input=inp, capture_output=True, text=False,
                           timeout=600, check=False)
        need(p.returncode == 0, "GIT", f"git {' '.join(args[:3])}: {p.stderr.decode(errors='replace')[-300:]}")
        return p.stdout.decode()

    def put_tree(self, files):
        """{name: bytes} -> tree id; names are fixed by the caller, never by content."""
        lines = []
        for name, data in sorted(files.items()):
            blob = self.git("hash-object", "-w", "--stdin", inp=data).strip()
            lines.append(f"100644 blob {blob}\t{name}")
        return self.git("mktree", inp=("\n".join(lines) + "\n").encode()).strip()

    def publish(self, ref, files, message):
        # A ref is published once. (A plain push would not enforce this: a fresh
        # clone cannot see non-fast-forwards, and identical bytes in the same
        # second even produce the same commit.)
        need(not self.git("ls-remote", "carrier", ref).strip(), "EXISTS", f"{ref} is already published")
        tree = self.put_tree(files)
        env = {**os.environ, "GIT_AUTHOR_NAME": "warrant-carrier", "GIT_AUTHOR_EMAIL": "carrier@invalid",
               "GIT_COMMITTER_NAME": "warrant-carrier", "GIT_COMMITTER_EMAIL": "carrier@invalid"}
        p = subprocess.run(["git", "-C", str(self.path), "commit-tree", tree, "-m", message], env=env,
                           capture_output=True, text=True, check=False)
        need(p.returncode == 0, "GIT", p.stderr[-300:])
        commit = p.stdout.strip()
        self.git("update-ref", ref, commit)
        self.git("push", "-q", "carrier", f"{ref}:{ref}")
        return commit

    def fetch(self, *specs):
        self.git("fetch", "-q", "--prune", "carrier", *[f"+{s}:{s}" for s in specs])

    def refs(self, prefix):
        out = self.git("for-each-ref", "--format=%(refname)", prefix)
        return [line for line in out.splitlines() if line]

    def read(self, ref, name, limit):
        p = subprocess.run(["git", "-C", str(self.path), "cat-file", "-p", f"{ref}:{name}"], capture_output=True,
                           check=False)
        need(p.returncode == 0, "GIT", f"{ref} has no {name}")
        need(len(p.stdout) <= limit, "LIMIT", f"{name} exceeds {limit} bytes")
        return p.stdout


# ----------------------------------------------------------------- pins

def sign_pin(signer_key, doc):
    """ssh-keygen -Y sign over the canonical pin bytes; returns (bytes, signature)."""
    data = canon(doc)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "pin.json"
        f.write_bytes(data)
        p = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(signer_key), "-n", NAMESPACE, str(f)],
                           capture_output=True, text=True, check=False)
        need(p.returncode == 0, "SIGN", p.stderr[-300:])
        return data, (Path(d) / "pin.json.sig").read_bytes()


def verify_pin(allowed_signers, data, sig):
    """The principal in `allowed_signers` whose key signed `data` in our namespace, or None."""
    principals = []
    for line in Path(allowed_signers).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("#"):
            principals.append(parts[0])
    with tempfile.TemporaryDirectory() as d:
        s = Path(d) / "pin.sig"
        s.write_bytes(sig)
        for principal in principals:
            p = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed_signers), "-I", principal,
                                "-n", NAMESPACE, "-s", str(s)], input=data, capture_output=True, check=False)
            if p.returncode == 0:
                return principal
    return None


def pin_doc(kind, digest, to, from_):
    return {"warrant_ref_pin": PIN_SCHEMA, "kind": kind, "sha256": digest, "to": to, "from": from_,
            "at": int(time.time())}


# ----------------------------------------------------------------- commands

def send(a):
    need(actor_ok(a.from_) and actor_ok(a.to), "ACTOR", "actor names are short and plain")
    data = Path(a.file).read_bytes()
    need(0 < len(data) <= MAX_PACKET, "LIMIT", "packet size")
    digest = sha256(data)
    repo = Repo(a.repo, a.remote)
    ref = f"refs/warrant/out/{a.from_}/{a.to}/{digest}"
    commit = repo.publish(ref, {"packet.json": data, "meta.json": canon(
        {"from": a.from_, "to": a.to, "sha256": digest, "size": len(data), "sent": int(time.time())})},
        f"warrant packet {digest[:16]} from {a.from_} to {a.to}")
    print(json.dumps({"ref": ref, "commit": commit, "sha256": digest, "size": len(data),
                      "pin_needed": f"refs/warrant/pins/{a.to}/{digest}.<signer fingerprint>"}, indent=2))


def signer_fingerprint(key):
    """16 hex of SHA-256 over the signer's public key line: pins by different signers
    live under different refs, so nobody can occupy the owner's."""
    p = subprocess.run(["ssh-keygen", "-y", "-f", str(key)], capture_output=True, text=True, check=False)
    need(p.returncode == 0, "SIGN", p.stderr[-200:])
    return sha256(" ".join(p.stdout.split()[:2]).encode())[:16]


def pin(a):
    """The owner's act: sign that `sha256` may be delivered to `to`."""
    need(actor_ok(a.to) and hex_ok(a.sha256), "ARGS", "to/sha256")
    repo = Repo(a.repo, a.remote)
    doc = pin_doc(a.kind, a.sha256, a.to, a.from_)
    data, sig = sign_pin(a.signer, doc)
    ref = f"refs/warrant/pins/{a.to}/{a.sha256}.{signer_fingerprint(a.signer)}"
    commit = repo.publish(ref, {"pin.json": data, "pin.json.sig": sig}, f"warrant pin {a.sha256[:16]} for {a.to}")
    print(json.dumps({"ref": ref, "commit": commit, "pin": doc}, indent=2))


def deliveries(repo, me, allowed_signers):
    """Every packet addressed to `me` whose pin verifies: [{sha256, from, principal, bytes}]. Packets
    without a verified pin are reported, never written."""
    # git allows one wildcard per refspec: every outgoing ref is fetched, and addressing is checked here.
    repo.fetch("refs/warrant/out/*", f"refs/warrant/pins/{me}/*")
    pins = {}
    for ref in repo.refs(f"refs/warrant/pins/{me}/"):
        digest = ref.rsplit("/", 1)[1].split(".")[0]
        if not hex_ok(digest) or pins.get(digest, {}).get("state") == "PINNED":
            continue                      # one verified pin per digest is enough; others cannot undo it
        try:
            data, sig = repo.read(ref, "pin.json", 4096), repo.read(ref, "pin.json.sig", 8192)
            doc = json.loads(data)
        except (Refused, ValueError):
            pins[digest] = {"state": "UNREADABLE_PIN"}
            continue
        principal = verify_pin(allowed_signers, data, sig)
        if principal is None:
            pins[digest] = {"state": "PIN_NOT_BY_ALLOWED_SIGNER"}
        elif not (isinstance(doc, dict) and doc.get("warrant_ref_pin") == PIN_SCHEMA and doc.get("sha256") == digest
                  and doc.get("to") == me and doc.get("kind") in ("packet", "reply")):
            pins[digest] = {"state": "PIN_FOR_ANOTHER_DELIVERY"}
        else:
            pins[digest] = {"state": "PINNED", "principal": principal, "kind": doc["kind"], "from": doc.get("from")}
    out, seen = [], set()
    for ref in repo.refs("refs/warrant/out/"):
        parts = ref.split("/")
        if len(parts) != 6 or parts[4] != me or not hex_ok(parts[5]):
            continue
        sender, digest = parts[3], parts[5]
        seen.add(digest)
        status = dict(pins.get(digest, {"state": "UNPINNED"}), sha256=digest, **{"from": sender})
        if status["state"] != "PINNED" or (status.get("from") not in (None, sender)):
            out.append(dict(status, delivered=False))
            continue
        data = repo.read(ref, "packet.json", MAX_PACKET)
        if sha256(data) != digest:
            out.append(dict(status, state="BYTES_DO_NOT_MATCH_DIGEST", delivered=False))
            continue
        out.append(dict(status, delivered=True, bytes=data))
    for digest, st in pins.items():
        if digest not in seen:
            out.append(dict(st, sha256=digest, delivered=False, state="PIN_WITHOUT_PACKET"))
    return out


def fetch(a):
    need(actor_ok(a.me), "ACTOR", "me")
    repo = Repo(a.repo, a.remote)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for d in deliveries(repo, a.me, a.allowed_signers):
        row = {k: v for k, v in d.items() if k != "bytes"}
        if d["delivered"]:
            path = out / f"{d['sha256']}.json"
            path.write_bytes(d["bytes"])
            row["file"] = str(path)
        report.append(row)
    print(json.dumps({"me": a.me, "deliveries": report}, indent=2))
    return report


# ----------------------------------------------------------------- local control

def selftest(a):
    base = Path(tempfile.mkdtemp(prefix="warrant-carry-"))
    passed = []

    def check(label, ok):
        need(ok, "SELFTEST", label)
        passed.append(label)
        print("PASS", label, flush=True)

    def keypair(name):
        key = base / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)], check=True)
        return key, (base / f"{name}.pub").read_text().split()[1]

    remote = base / "carrier.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    owner, owner_pub = keypair("owner")
    stranger, stranger_pub = keypair("stranger")
    allowed = base / "allowed_signers"
    allowed.write_text(f"owner ssh-ed25519 {owner_pub}\n")
    packet = base / "packet.json"
    packet.write_bytes(canon({"experiment": "carry-selftest", "payload": "x" * 1000}))
    digest = sha256(packet.read_bytes())
    ns = lambda **kw: argparse.Namespace(**kw)
    send(ns(repo=base / "a", remote=str(remote), from_="alice", to="bob", file=packet))
    rows = fetch(ns(repo=base / "b", remote=str(remote), me="bob", allowed_signers=allowed, out=base / "bob-in"))
    check("an unpinned packet is reported, not delivered",
          rows == [{"state": "UNPINNED", "sha256": digest, "from": "alice", "delivered": False}])
    # a pin by a key the receiver does not list
    pin(ns(repo=base / "s", remote=str(remote), signer=stranger, to="bob", sha256=digest, from_="alice", kind="packet"))
    rows = fetch(ns(repo=base / "b", remote=str(remote), me="bob", allowed_signers=allowed, out=base / "bob-in"))
    check("a pin by a key not in allowed-signers delivers nothing", rows[0]["state"] == "PIN_NOT_BY_ALLOWED_SIGNER"
          and not rows[0]["delivered"] and not (base / "bob-in" / f"{digest}.json").exists())
    # pins live under refs keyed by the signer: the stranger's pin cannot occupy the owner's
    pin(ns(repo=base / "o", remote=str(remote), signer=owner, to="bob", sha256=digest, from_="alice", kind="packet"))
    rows = fetch(ns(repo=base / "b", remote=str(remote), me="bob", allowed_signers=allowed, out=base / "bob-in"))
    check("a stranger's earlier pin does not block the owner's pin", rows[0]["state"] == "PINNED"
          and rows[0]["principal"] == "owner" and rows[0]["delivered"])
    try:
        pin(ns(repo=base / "o-again", remote=str(remote), signer=owner, to="bob", sha256=digest, from_="alice", kind="packet"))
        collided = False
    except Refused as e:
        collided = e.code == "EXISTS"
    check("a pin ref is published once; it cannot be replaced in place", collided)
    # fresh delivery to carol: owner pins, carol receives
    send(ns(repo=base / "a2", remote=str(remote), from_="alice", to="carol", file=packet))
    pin(ns(repo=base / "o2", remote=str(remote), signer=owner, to="carol", sha256=digest, from_="alice", kind="packet"))
    allowed_c = base / "allowed_c"
    allowed_c.write_text(f"owner ssh-ed25519 {owner_pub}\n")
    rows = fetch(ns(repo=base / "c", remote=str(remote), me="carol", allowed_signers=allowed_c, out=base / "carol-in"))
    got = base / "carol-in" / f"{digest}.json"
    check("an owner-pinned packet is delivered byte-exact", rows[0]["state"] == "PINNED" and rows[0]["principal"] == "owner"
          and rows[0]["delivered"] and got.read_bytes() == packet.read_bytes())
    check("a receiver does not see packets addressed to others",
          all(r["sha256"] == digest for r in rows) and len(rows) == 1)
    # a pin for a digest whose packet never arrived
    pin(ns(repo=base / "o3", remote=str(remote), signer=owner, to="carol", sha256="ab" * 32, from_="alice", kind="packet"))
    rows = fetch(ns(repo=base / "c", remote=str(remote), me="carol", allowed_signers=allowed_c, out=base / "carol-in"))
    check("a pin without its packet delivers nothing", any(r["state"] == "PIN_WITHOUT_PACKET" and not r["delivered"] for r in rows))
    # tampered bytes under a pinned ref: rewrite the ref in the bare remote directly
    tampered = canon({"experiment": "carry-selftest", "payload": "y" * 1000})
    r = Repo(base / "evil", str(remote))
    tree = r.put_tree({"packet.json": tampered, "meta.json": b"{}"})
    env = {**os.environ, "GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": "x@invalid", "GIT_COMMITTER_NAME": "x",
           "GIT_COMMITTER_EMAIL": "x@invalid"}
    commit = subprocess.run(["git", "-C", str(r.path), "commit-tree", tree, "-m", "tamper"], env=env,
                            capture_output=True, text=True, check=True).stdout.strip()
    ref = f"refs/warrant/out/alice/carol/{digest}"
    r.git("update-ref", ref, commit)
    r.git("push", "-q", "-f", "carrier", f"{ref}:{ref}")
    rows = fetch(ns(repo=base / "c2", remote=str(remote), me="carol", allowed_signers=allowed_c, out=base / "carol-in2"))
    check("bytes that do not hash to the pinned digest are refused",
          any(r["sha256"] == digest and r["state"] == "BYTES_DO_NOT_MATCH_DIGEST" for r in rows)
          and not (base / "carol-in2" / f"{digest}.json").exists())
    # a pin signed for another receiver or another digest does not transfer
    pin(ns(repo=base / "o4", remote=str(remote), signer=owner, to="dave", sha256=digest, from_="alice", kind="packet"))
    send(ns(repo=base / "a3", remote=str(remote), from_="alice", to="erin", file=packet))
    evil = Repo(base / "evil2", str(remote))
    evil.fetch("refs/warrant/pins/dave/*")
    dave_ref = evil.refs("refs/warrant/pins/dave/")[0]
    erin_ref = dave_ref.replace("/dave/", "/erin/")
    evil.git("update-ref", erin_ref, evil.git("rev-parse", dave_ref).strip())
    evil.git("push", "-q", "carrier", f"{erin_ref}:{erin_ref}")
    rows = fetch(ns(repo=base / "e", remote=str(remote), me="erin", allowed_signers=allowed_c, out=base / "erin-in"))
    check("a pin signed for another receiver is not a pin for this one",
          rows[0]["state"] == "PIN_FOR_ANOTHER_DELIVERY" and not rows[0]["delivered"])
    shutil.rmtree(base, ignore_errors=True)
    frozen = Path(__file__).resolve().parent / "round-2"
    if frozen.is_dir():
        sums = dict(line.split()[::-1] for line in (frozen / "SHA256SUMS").read_text().splitlines())
        check("round-2 frozen files have their recorded digests",
              all(sha256((frozen / name).read_bytes()) == h for name, h in sums.items()))
        for pin_dir in sorted(frozen.glob("pins/*")):
            data, sig = (pin_dir / "pin.json").read_bytes(), (pin_dir / "pin.json.sig").read_bytes()
            doc = json.loads(data)
            packet = frozen / ("reply.json" if doc["kind"] == "reply" else "packet.json")
            check(f"round-2 owner pin verifies offline and names the frozen {doc['kind']}: {doc['sha256'][:12]}",
                  verify_pin(frozen / "allowed_signers", data, sig) == "owner"
                  and sha256(packet.read_bytes()) == doc["sha256"] and pin_dir.name.startswith(f"{doc['to']}--{doc['sha256']}"))
    print(f"REF-TRANSPORT: {len(passed)} controls PASS (local bare remote with ephemeral keys, plus the frozen "
          "round-2 pins verified offline; no Warrant semantics claimed)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["send", "pin", "fetch", "selftest"])
    ap.add_argument("--repo", type=Path, help="private working clone for this party (created if absent)")
    ap.add_argument("--remote", help="the carrier git remote (URL or path)")
    ap.add_argument("--from", dest="from_", help="sending actor")
    ap.add_argument("--to", help="receiving actor")
    ap.add_argument("--me", help="fetch: the receiving actor")
    ap.add_argument("--file", type=Path, help="send: the packet bytes")
    ap.add_argument("--sha256", help="pin: the packet digest the owner pins")
    ap.add_argument("--kind", choices=["packet", "reply"], default="packet")
    ap.add_argument("--signer", type=Path, help="pin: the OWNER's private ssh key")
    ap.add_argument("--allowed-signers", type=Path, help="fetch: principals whose pins this receiver honours")
    ap.add_argument("--out", type=Path, help="fetch: where delivered packets are written, named by digest")
    args = ap.parse_args()
    try:
        if args.mode != "selftest":
            need(args.repo is not None and args.remote, "ARGS", "--repo and --remote are required")
        {"send": send, "pin": pin, "fetch": fetch, "selftest": selftest}[args.mode](args)
    except Refused as exc:
        print(json.dumps({"status": "REFUSED", "code": exc.code, "detail": str(exc)}), file=sys.stderr)
        sys.exit(2)
