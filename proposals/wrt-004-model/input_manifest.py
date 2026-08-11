#!/usr/bin/env python3
"""`warrant.verify-report@v1` sealed observation — Python reference.

Round 2 of WRT-004 §6, rebuilt after round 1 was **refuted**. Round 1 walked
the filesystem and hashed what it found; a live verifier follows a symlinked
record that the walk silently skipped, so `input_root` committed to `[]`
while the report judged one record. A manifest that does not commit the bytes
the judgement used is not a manifest.

**One atomic observation.** `seal()` produces the store's byte view exactly
once. Both `input_manifest` and — in a full implementation — the judgement
are derived from *that view and nothing else*, so they cannot disagree about
what exists. Anything the seal refuses is not judged either.

    input_manifest.py <store-dir> [--trust-config PATH]   # JCS bytes
    input_manifest.py <store-dir> --root                  # input_root only
"""

import hashlib
import json
import os
import sys

DOMAIN = b"warrant.verify-report.input@v1:"

# SPEC §4 short escapes. Everything else below U+0020 is \u00xx LOWERCASE;
# everything else — including < > & / and all non-ASCII, and explicitly
# U+2028/U+2029 — is raw UTF-8. Round 1's Go used encoding/json, which
# escapes U+2028 even with SetEscapeHTML(false), and that is forbidden here.
SHORT = {0x22: '\\"', 0x5C: "\\\\", 0x08: "\\b", 0x09: "\\t",
         0x0A: "\\n", 0x0C: "\\f", 0x0D: "\\r"}


def jcs_string(s):
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if cp in SHORT:
            out.append(SHORT[cp])
        elif cp < 0x20:
            out.append("\\u%04x" % cp)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def jcs(value):
    """The SPEC §4 subset, written out rather than delegated to a library.

    `json.dumps(ensure_ascii=False)` happens to agree with §4 today, but the
    agreement is incidental — a library default is not a specification, and
    the Go side proved that by escaping U+2028 under the same intent.
    """
    if isinstance(value, str):
        return jcs_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return "null"
    if isinstance(value, list):
        return "[" + ",".join(jcs(v) for v in value) + "]"
    if isinstance(value, dict):
        # UTF-16 code-unit order, which is JCS's rule for keys. All keys here
        # are ASCII, where it coincides with code-point order; the sort key is
        # written out anyway so a future non-ASCII key does not silently
        # change meaning.
        items = sorted(value.items(), key=lambda kv: kv[0].encode("utf-16-be"))
        return "{" + ",".join(jcs_string(k) + ":" + jcs(v)
                              for k, v in items) + "}"
    raise TypeError("not representable in the §4 subset: %r" % type(value))


def role_of(rel):
    parts = rel.split("/")
    if parts[0] == "records" and len(parts) == 2 and rel.endswith(".json"):
        return "record"
    if parts[0] == "blobs" and len(parts) == 2:
        return "blob"
    if rel == "genesis.json":
        return "genesis"
    return "other"


def seal(store_dir, trust_config=None):
    """The observation. Every path the verifier can see, with its state.

    `state` is a sum type, because round 1's schema could not represent what
    §3.1 required: it demanded that failed reads appear while making
    `sha256` mandatory, and there are no bytes after a failed read.

      read       — bytes obtained; `sha256` present
      unreadable — attempted, no bytes (permissions, I/O)
      refused    — deliberately not read, with a reason

    A symlink is **refused**, not followed and not skipped. Following it
    leaves the store's byte universe; skipping it silently is what made the
    round-1 manifest disagree with the judgement. Refusing it is visible in
    the manifest, and the judgement — reading only this view — does not see
    the record either. That is a deliberate difference from `@v0`, which
    follows symlinks, and it is why `@v1` is a different tag.
    """
    view = []
    base = os.path.abspath(store_dir)
    for root, dirs, names in os.walk(base):
        dirs.sort()
        for name in sorted(names + [d for d in dirs
                                    if os.path.islink(os.path.join(root, d))]):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            e = {"path": rel, "role": role_of(rel)}
            if os.path.islink(full):
                e["state"], e["reason"] = "refused", "symlink"
            elif not os.path.isfile(full):
                e["state"], e["reason"] = "refused", "not-a-regular-file"
            else:
                try:
                    with open(full, "rb") as fh:
                        raw = fh.read()
                except OSError:
                    e["state"] = "unreadable"
                else:
                    e["state"] = "read"
                    e["sha256"] = hashlib.sha256(raw).hexdigest()
            view.append(e)
    if trust_config:
        rel = os.path.basename(trust_config)
        e = {"path": rel, "role": "trust-config"}
        try:
            with open(trust_config, "rb") as fh:
                raw = fh.read()
        except OSError:
            e["state"] = "unreadable"
        else:
            e["state"] = "read"
            e["sha256"] = hashlib.sha256(raw).hexdigest()
        view.append(e)
    view.sort(key=lambda e: e["path"].encode("utf-8"))
    paths = [e["path"] for e in view]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate path in the observation: refused")
    return view


def input_root(view):
    return hashlib.sha256(DOMAIN + jcs(view).encode("utf-8")).hexdigest()


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-2])
        return 2
    trust = argv[argv.index("--trust-config") + 1] \
        if "--trust-config" in argv else None
    try:
        view = seal(argv[1], trust)
    except ValueError as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 1
    if "--root" in argv:
        sys.stdout.write(input_root(view) + "\n")
    else:
        sys.stdout.buffer.write(jcs(view).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
