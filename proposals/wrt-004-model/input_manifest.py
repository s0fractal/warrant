#!/usr/bin/env python3
"""`warrant.verify-report@v1` input manifest — Python reference (WRT-004 §3).

Design only. Emits no `@v1` report and registers no tag; this computes the
one part of the design whose central claim is decidable today: that two
independent implementations produce **byte-identical** bytes for the same
store.

`input_root = sha256("warrant.verify-report.input@v1:" || JCS(entries))`

Usage:
    input_manifest.py <store-dir> [--trust-config PATH]   # JCS bytes to stdout
    input_manifest.py <store-dir> --root                  # the root only
"""

import hashlib
import json
import os
import sys

DOMAIN = b"warrant.verify-report.input@v1:"


def role_of(rel):
    """Store layout -> role. Unknown layout is `other`, never a guess: a file
    the verifier read but cannot classify still has to be named."""
    parts = rel.split("/")
    if parts[0] == "records" and len(parts) == 2 and rel.endswith(".json"):
        return "record"
    if parts[0] == "blobs" and len(parts) == 2:
        return "blob"
    if rel == "genesis.json":
        return "genesis"
    return "other"


def entries(store_dir, trust_config=None):
    """Every file read or attempted, ordered by the UTF-8 bytes of `path`.

    Sorting on the encoded bytes is stated, not incidental. UTF-8 preserves
    code-point order, so Go sorting native `string` (bytes) and Python
    sorting `str` (code points) already agree — the ordering is chosen
    because it needs no special handling in either language, unlike the
    UTF-16 code-unit order JCS imposes on object *keys*.
    """
    out = []
    base = os.path.abspath(store_dir)
    for root, _dirs, names in os.walk(base):
        for name in names:
            full = os.path.join(root, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            with open(full, "rb") as fh:
                raw = fh.read()
            out.append({"path": rel, "role": role_of(rel),
                        "sha256": hashlib.sha256(raw).hexdigest()})
    if trust_config:
        with open(trust_config, "rb") as fh:
            raw = fh.read()
        # named by basename: the trust config lives outside the store, and a
        # local absolute path would make the manifest machine-specific
        out.append({"path": os.path.basename(trust_config),
                    "role": "trust-config",
                    "sha256": hashlib.sha256(raw).hexdigest()})
    out.sort(key=lambda e: e["path"].encode("utf-8"))
    paths = [e["path"] for e in out]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate path in manifest: not permitted (§3.1)")
    return out


def jcs(value):
    """The JCS subset SPEC §4 uses: UTF-8, compact separators, sorted keys.

    `ensure_ascii=False` matters and is the first place a second
    implementation can diverge — Go's `encoding/json` escapes `<`, `>` and
    `&` unless told not to, so a path containing any of them yields
    different bytes for the same manifest. The corpus tests exactly that.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def input_root(entry_list):
    return hashlib.sha256(DOMAIN + jcs(entry_list)).hexdigest()


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-3])
        return 2
    trust = argv[argv.index("--trust-config") + 1] \
        if "--trust-config" in argv else None
    ents = entries(argv[1], trust)
    if "--root" in argv:
        sys.stdout.write(input_root(ents) + "\n")
    else:
        sys.stdout.buffer.write(jcs(ents))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
