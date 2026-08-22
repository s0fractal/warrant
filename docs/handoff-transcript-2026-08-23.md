# Transcript — 2026-08-23

Produced by executing the shell blocks of
[`try-this-in-fifteen-minutes.md`](try-this-in-fifteen-minutes.md) **as they are
written in that file**: the blocks were extracted from the page and run
unmodified, in a fresh `mktemp -d` directory, with an empty virtualenv, an empty
pip cache, and no checkout of this repository. Nothing was quieted, expanded,
reordered, or rewritten.

Three commands are supposed to fail, and do: the `verify` after Part A's tamper,
and the `check` and `verify` on Part B's tampered pack. Their `[exit 1]` lines
are the point of the exercise.

## What the capture harness contributes, exactly

The harness adds three things and nothing else: a `DEBUG` trap that echoes each
command and stamps the previous one's exit status, an empty `PIP_CACHE_DIR`, and
the elapsed line. It rewrites no command from the page. Reading the result
faithfully means knowing what that mechanism does to the display:

- bash reports `$BASH_COMMAND`, so a command the page wraps across lines with `\`
  appears here on one line, with the continuation collapsed to spaces;
- each component of a pipeline is stamped separately, so `python -m pip show
  warrant-verify | head -2` appears as two entries;
- a heredoc is echoed as its first line (`python3 -  <<'PY'`) without its body;
  the bodies are in the page and were executed from it verbatim;
- trailing spaces in `warrant why` output are stripped so `git diff --check`
  stays clean;
- the block below is indented rather than fenced, because
  `tools/check_release_surface.py` reads every fenced line as a documented
  invocation and this file holds command *output*.

## About the timing and the network

Five seconds, with a pip cache created empty for this run, so it is a cold
install rather than a warm one. The install is one command but not one download:
here it fetched four wheels — `warrant-verify`, and its dependencies
`cryptography`, `cffi` and `pycparser` — which is why the page says the network
is needed in two stages rather than exactly twice.

A transcript of one run goes stale. Re-run it rather than trusting the paste.


    $ cd "$(mktemp -d)"
    [exit 0]

    $ pwd
    /var/folders/3j/t95dsnsj7wlc35dpwlwpdy8r0000gn/T/tmp.N2f4cJpS5J
    [exit 0]

    $ python3 -m venv .venv
    [exit 0]

    $ . .venv/bin/activate
    [exit 0]

    $ python -m pip install warrant-verify==0.9.0
    Collecting warrant-verify==0.9.0
      Downloading warrant_verify-0.9.0-py3-none-any.whl.metadata (20 kB)
    Collecting cryptography>=41 (from warrant-verify==0.9.0)
      Downloading cryptography-50.0.0-cp311-abi3-macosx_11_0_arm64.whl.metadata (4.3 kB)
    Collecting cffi>=2.0.0 (from cryptography>=41->warrant-verify==0.9.0)
      Downloading cffi-2.1.1-cp314-cp314-macosx_11_0_arm64.whl.metadata (2.5 kB)
    Collecting pycparser (from cffi>=2.0.0->cryptography>=41->warrant-verify==0.9.0)
      Downloading pycparser-3.0-py3-none-any.whl.metadata (8.2 kB)
    Downloading warrant_verify-0.9.0-py3-none-any.whl (90 kB)
    Downloading cryptography-50.0.0-cp311-abi3-macosx_11_0_arm64.whl (4.0 MB)
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.0/4.0 MB 18.5 MB/s  0:00:00
    Downloading cffi-2.1.1-cp314-cp314-macosx_11_0_arm64.whl (184 kB)
    Downloading pycparser-3.0-py3-none-any.whl (48 kB)
    Installing collected packages: pycparser, cffi, cryptography, warrant-verify

    Successfully installed cffi-2.1.1 cryptography-50.0.0 pycparser-3.0 warrant-verify-0.9.0
    [exit 0]

    $ python -m pip show warrant-verify
    [exit 0]

    $ head -2
    Name: warrant-verify
    Version: 0.9.0
    ERROR: Pipe to stdout was broken
    [exit 0]

    $ ls "$(dirname "$(command -v warrant)")"
    [exit 0]

    $ grep '^warrant'
    warrant
    warrant-anchor
    warrant-mcp
    warrant-mcp-server
    [exit 0]

    $ git init -q .
    [exit 0]

    $ warrant init
    initialized .warrants
    [exit 0]

    $ warrant keygen --out me.key
    pubkey ca0c5835adae2316c1ee8a8ffbf54c72f840b0d0487b51d8a9daa709f6b2d9e4
    [exit 0]

    $ printf 'demo diff\n' > diff.patch
    [exit 0]

    $ printf 'clause 1: no coverage drop\n' > policy.txt
    [exit 0]

    $ printf '#!/bin/sh\nexit 1\n' > check.sh
    [exit 0]

    $ chmod +x check.sh
    [exit 0]

    $ POL=$(warrant policy add policy.txt)
    [exit 0]

    $ P=$(warrant propose --subject diff.patch --under $POL       --reason "utility fns needed" --actor me@host --key me.key)
    [exit 0]

    $ R=$(warrant reject $P --check check.sh --verdict fail       --reason "clause 1: coverage drop" --actor me@host --key me.key)
    [exit 0]

    $ printf '#!/bin/sh\nexit 0\n' > check.sh
    [exit 0]

    $ A=$(warrant accept $R --check check.sh --verdict pass       --actor me@host --key me.key)
    [exit 0]

    $ warrant why $A
    ACCEPT 14070b33eb97bf9c by me@host  subject=5798d9022c8a
      - check 306c6ca74075 [cmd@v1] -> pass
      under policy be1907d09e8d
      REJECT 4ab1b6d0ea856ff3 by me@host  subject=5798d9022c8a
        - prose: clause 1: coverage drop
        - check 275239824e00 [cmd@v1] -> fail
        under policy be1907d09e8d
        PROPOSE 574887d70416a5c0 by me@host  subject=5798d9022c8a
          - prose: utility fns needed
          under policy be1907d09e8d
    [exit 0]

    $ warrant verify
    WARN 14070b33eb97  binding unverified (no keyring): key ca0c5835adae claims actor me@host
    WARN 4ab1b6d0ea85  binding unverified (no keyring): key ca0c5835adae claims actor me@host
    WARN 574887d70416  binding unverified (no keyring): key ca0c5835adae claims actor me@host

    verify: 3 records, 0 errors, 3 warnings
    [exit 0]

    $ python3 -  <<'PY'
    import json, pathlib
    p = sorted(pathlib.Path(".warrants/records").glob("*.json"))[0]
    d = json.loads(p.read_text())
    d["body"]["actor"]["id"] = "someone-else@host"
    p.write_text(json.dumps(d))
    print("rewrote the deciding actor in", p.name[:12])
    PY

    rewrote the deciding actor in 14070b33eb97
    [exit 0]

    $ warrant verify
    ERR  14070b33eb97  WarrantID mismatch: recomputed f1cdac234e04
    WARN 4ab1b6d0ea85  binding unverified (no keyring): key ca0c5835adae claims actor me@host
    WARN 574887d70416  binding unverified (no keyring): key ca0c5835adae claims actor me@host

    verify: 3 records, 1 errors, 2 warnings
    [exit 1]

    $ curl -LO https://github.com/s0fractal/warrant/releases/download/v0.8.0/air-canada-pack.zip
      % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                     Dload  Upload   Total   Spent    Left  Speed

      0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0
      0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0

    100  8664  100  8664    0     0  38658      0 --:--:-- --:--:-- --:--:-- 38658
    [exit 0]

    $ shasum -a 256 air-canada-pack.zip
    74b36f1d5c7777ea9a3ee240e32f992483a3cd2c0dda0c7d065229c49f1a8249  air-canada-pack.zip
    [exit 0]

    $ unzip -q air-canada-pack.zip
    [exit 0]

    $ warrant --store air-canada-pack/.warrants verify
    WARN 7d8f2e7db315  binding unverified (no keyring): key bc7cbcb56363 claims actor chatbot@aircanada
    WARN 9084cd23f205  binding unverified (no keyring): key 55154f42065e claims actor policy-guard@aircanada

    verify: 2 records, 0 errors, 2 warnings
    [exit 0]

    $ warrant --store air-canada-pack/.warrants verify --settlement --trust-config air-canada-pack/trust.json
    INFO 7d8f2e7db315  signature bound: key bc7cbcb56363 claims actor chatbot@aircanada
    INFO 9084cd23f205  signature bound: key 55154f42065e claims actor policy-guard@aircanada

    verify: 2 records, 0 errors, 0 warnings
    [exit 0]

    $ warrant --store air-canada-pack/.warrants why 9084cd23f205cdd6e013deb6c6e2a84e4a5f4f469fb8f77ba443dfed44716f5a
    REJECT 9084cd23f205cdd6 by policy-guard@aircanada  subject=494ad3316bfa retroactive bereavement refund request
      - prose: policy clause 2: bereavement discount cannot be claimed retroactively
      - check b423b6a82c34 [ski@v1] -> pass
      under policy c8d453b05c7d
      PROPOSE 7d8f2e7db31500ba by chatbot@aircanada  subject=494ad3316bfa retroactive bereavement refund request
        - prose: passenger requested a refund
        under policy c8d453b05c7d
    [exit 0]

    $ warrant --store air-canada-pack/.warrants check b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
    pass  result=65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  atp_spent=17
    [exit 0]

    $ cp -r air-canada-pack tampered
    [exit 0]

    $ python3 -  <<'PY'
    import json, pathlib
    p = pathlib.Path("tampered/.warrants/blobs/"
                     "b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f")
    d = json.loads(p.read_bytes()); d["expect"] = "f" * 64
    p.write_bytes(json.dumps(d, sort_keys=True, separators=(",", ":")).encode())
    print("rewrote what the check expects")
    PY

    rewrote what the check expects
    [exit 0]

    $ warrant --store tampered/.warrants check b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
    fail  result=65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  atp_spent=17
    [exit 1]

    $ warrant --store tampered/.warrants verify
    WARN 7d8f2e7db315  binding unverified (no keyring): key bc7cbcb56363 claims actor chatbot@aircanada
    WARN 9084cd23f205  binding unverified (no keyring): key 55154f42065e claims actor policy-guard@aircanada
    ERR  9084cd23f205  blob b423b6a82c34 content does not match its address (store claims these bytes are SHA-256 b423b6a82c34…)
    WARN 9084cd23f205  ski@v1 verdict mismatch: claimed pass, re-run gives fail (65cd957fee7e)

    verify: 2 records, 1 errors, 3 warnings
    [exit 1]
    [exit 0]

    [elapsed 5 seconds, with an empty pip cache]
