# HANDOFF: SPEC v0.3 implementation gate

## Commands

Run from the repository root:

```sh
python3 impl/warrant.py selftest && python3 impl/warrant.py conformance
./impl-go/warrant-go selftest && ./impl-go/warrant-go conformance
python3 tests/differential.py && python3 tests/negative.py
python3 tests/settlement.py
```

## Output

```text
7e89c9d33bb361ce3efa0f95a7da0ce7f24550c6b6c86d81cc3f7eda7523d32e
9faed510b164a774a6c2d950acb81926cbefacb4908535c5dbde5df8f494d806
SELFTEST: ALL PASS
OK   blob policy.txt 
OK   blob check.sh 
OK   schema propose.warrant.json 
OK   WarrantID propose.warrant.json 
OK   sig propose.warrant.json by agent-a@vendor1 
OK   schema reject.warrant.json 
OK   WarrantID reject.warrant.json 
OK   sig reject.warrant.json by agent-b@vendor2 
OK   schema accept.warrant.json 
OK   WarrantID accept.warrant.json 
OK   sig accept.warrant.json by agent-b@vendor2 
OK   chain reject.prior -> propose 
OK   chain accept.prior -> reject 
OK   ts non-decreasing 
OK   ski: warrant id 
OK   ski: schema (0.2 body) 
OK   ski: sig by agent-a@vendor1 
OK   ski: check blob hash 
OK   ski: 0.1 body MUST reject ski@v1 
OK   ski: re-run -> pass, H(S), 20 ATP 

CONFORMANCE: ALL PASS (20/20)
OK   unknown body field -> invalid
OK   ski@v1 runtime -> invalid
OK   reject with zero reasons -> invalid
OK   prose-only reject -> schema-valid
OK   prose-only reject -> unverifiable
OK   examples verify with unresolved blobs as warnings
OK   missing prior -> error

SELFTEST: ALL PASS (7/7)
OK   blob policy.txt
OK   blob check.sh
OK   schema propose.warrant.json
OK   WarrantID propose.warrant.json
OK   sig propose.warrant.json by agent-a@vendor1
OK   schema reject.warrant.json
OK   WarrantID reject.warrant.json
OK   sig reject.warrant.json by agent-b@vendor2
OK   schema accept.warrant.json
OK   WarrantID accept.warrant.json
OK   sig accept.warrant.json by agent-b@vendor2
OK   chain reject.prior -> propose
OK   chain accept.prior -> reject
OK   ts non-decreasing
OK   ski: warrant id
OK   ski: schema (0.2 body)
OK   ski: sig by agent-a@vendor1
OK   ski: 0.1 body MUST reject ski@v1
OK   ski: check blob hash
OK   ski: re-run -> pass, H(S), 20 ATP

CONFORMANCE: ALL PASS (20/20)
OK    ctrl-U+0000  10c52de408e7d41e…
OK    ctrl-U+0001  392b1261992547ff…
OK    ctrl-U+0002  121e2d2ad67c8d1c…
OK    ctrl-U+0003  449deac1ea9f7a72…
OK    ctrl-U+0004  88edf288f84fb598…
OK    ctrl-U+0005  a09fef385eef599a…
OK    ctrl-U+0006  0b4049b207ae324e…
OK    ctrl-U+0007  378fcc2146cd3af6…
OK    ctrl-U+0008  cb77c8ca4342e8f2…
OK    ctrl-U+0009  f5511fe377064a24…
OK    ctrl-U+000A  87593df9401492fc…
OK    ctrl-U+000B  7a031829272d42ba…
OK    ctrl-U+000C  865598c74b2299ec…
OK    ctrl-U+000D  ed8c787c2674045d…
OK    ctrl-U+000E  1e0e977f5599eddc…
OK    ctrl-U+000F  363c968b79ea79af…
OK    ctrl-U+0010  e8804b79fcf1d929…
OK    ctrl-U+0011  39311122dab7341b…
OK    ctrl-U+0012  e86620f367a2e696…
OK    ctrl-U+0013  777722a8a84bd3b4…
OK    ctrl-U+0014  ec2b31783ab76bb9…
OK    ctrl-U+0015  ce998b987a9a882b…
OK    ctrl-U+0016  0effb19c249393a8…
OK    ctrl-U+0017  b2e26d9f9cc6f2eb…
OK    ctrl-U+0018  56dca174964b2eb3…
OK    ctrl-U+0019  6cf694393b931d16…
OK    ctrl-U+001A  8b64e8e11c66813a…
OK    ctrl-U+001B  49c02b2cbbcb42c6…
OK    ctrl-U+001C  25b6c1546b55f8f7…
OK    ctrl-U+001D  af5da861bd76fc30…
OK    ctrl-U+001E  63dd4fca28ec7213…
OK    ctrl-U+001F  bc890bf8ed6e8230…
OK    backspace+formfeed  4cf3799dde8485b7…
OK    cyrillic-note  ac672fa21c027de6…
OK    emoji-astral  e0385864a2616a1b…
OK    quote-backslash  48cc70e9a981bf5e…
OK    del+c1  cb7f7b02776ce5c7…
OK    ctrl-in-actor  205c940292b43e83…
OK    ctrl-in-prose  d518c34a563bf66c…
OK    large-ts  668cb9f2360f8324…
OK    note-200-multibyte  5bd9517d1ba80085…
OK    note-201-multibyte  7f523c4368375b7b…
OK    shuffled-keys  0f55d094f083db45…

DIFFERENTIAL: ALL AGREE (43/43)
OK    baseline valid store py=(0, 2) go=(0, 2)
OK    tampered signature py=(2, 1) go=(2, 1)
OK    signer actor != body.actor.id py=(1, 2) go=(1, 2)
OK    signatures stripped py=(1, 1) go=(1, 1)
OK    body tampered (id mismatch) py=(1, 1) go=(1, 1)
OK    dangling prior + supersede subject (SPEC s7 MUST) py=(2, 2) go=(2, 2)
OK    ski@v1 verdict lie (hand-crafted) -> re-run disagrees py=(0, 4) go=(0, 4)

NEGATIVE: ALL AGREE
OK    two roots: one genesis, one unadopted py=(0, 1) go=(0, 1)
OK    threshold adoption activates second root py=(0, 0) go=(0, 0)
OK    pinned genesis.json roots are used py=(0, 0) go=(0, 0)
OK    tampered genesis.json is unused py=(0, 3) go=(0, 3)
OK    invalid threshold policy is an error py=(1, 0) go=(1, 0)
OK    re-litigation: new evidence admissible: (a) new evidence admissible: (a) new evidence
OK    re-litigation: new fingerprint admissible: (b) new outcome fingerprint admissible: (b) new outcome fingerprint
OK    re-litigation: restatement inadmissible: cites nothing new inadmissible: cites nothing new
OK    restatement warns in settlement verify py=(0, 1) go=(0, 1)
OK    key rotation binds incoming key py=(0, 1) go=(0, 1)
OK    genuine forked rotation conflicts py=(0, 10) go=(0, 10)

SETTLEMENT: ALL AGREE
```

## Deviations

No body schema changes and no intentional deviations from the brief.

Implementation convention: key-rotation subject blobs used by the tests are JCS-canonical JSON `{"actor":"...","key":"<hex64>"}`. SPEC v0.3 defines key-state semantics but does not mandate an interchangeable key-state blob format, so this is verifier-local and does not change warrant bodies.
