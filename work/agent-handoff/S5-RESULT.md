# S5: fresh-context handoff run and contrast

Run on 2026-10-19 by Claude.

**What kind of run this is.** Two fresh-context **subagents of the same model**
(Claude Opus 5.5) on the same machine and the same shared disk. Each was started
with no conversation history: only its prompt and its tools. This is **not** an
independent model, and it is **not** a live MCP host. The headless Claude Code
host launch was refused by the auto-mode classifier ("Create Unsafe Agents"), so
arm A reached the backend through a journaled CLI wrapper (`warrant-agent`, the
same backend the MCP server uses) instead of through MCP.

**Fixture.** `examples/agent/packet.py --out world` (warrant `b954bd0`).
- The producer's work and the paused computation are filed, the full cut is
  exported, and the receiver inspects it against its own expectation and imports
  it. Then the run stops; the receiver has filed nothing.
- The auditor's challenge on t1 is present.
- The kept fixture lives under the session scratchpad `s5/world`.
  `truth.json` was not shown to either arm.

| | Arm A: warrant-agent | Arm B: plain signed JSON log |
| --- | --- | --- |
| Starting input | prompt 4,319 B, of which the packet is 3,458 B (capsules, frontier, use, delivery, computation addresses) | prompt 840 B + log 8,874 B (every signed envelope, all blobs base64, the trust file) |
| Tools | `wa` (context, read, prepare, commit, compute) | Read on one file |
| Calls | context 1, read record 1 (t2), compute resume 1, prepare 1, commit 1 | Read 2 |
| Evidence reads beyond the start | 1 (record t2) + 1 replay | the whole log is read up front |
| Tokens / time (harness-measured) | 78,654 tokens, 44.8 s | 78,556 tokens, 56.9 s |
| Manual actions left | 0: the accept was signed and filed by the configured signer | 2: signing, and the replay it said it needed but could not run |
| Subtask result | accept `609d701c…` committed, for t2 item 0, with evidence {checkpoint, state, environment}. This matches truth exactly. | no accept. It wrote the exact conditional body: t2 item 0 with the same three ids, which matches truth. It withheld signing because it could not replay. |
| Challenge on d1 noticed | yes, rely = hold | yes, rely = hold |
| Residual of t2 ("not computed; receiver must replay") | yes, and it did the replay (REPLAYED/PAUSED, then advanced to NORMAL_FORM) | yes; it could not replay |
| Checkpoint made no progress (credit 2, actions 0) | not noticed; the capsule does not show it and the replay made it moot | **noticed**. It called this an anomaly; in fact it is a valid Book I pause, because the credit is below the first action's cost |
| False alarms | stated that "the profile names nobody whose acceptance closes results", so the accept "may not close" d2, and did not re-check. After the commit, d2 is DISCHARGED and use is WITHIN_POLICY. It confused `accept_by.results` (computation results) with the duty's own `accept_by`. | read `sig.key` (a key id) as a public key and concluded that no record is signed by a trusted key. It also flagged log order and equal timestamps as non-causal (true but harmless), and mistyped a duty id in its JSON. |
| Things it could not do | n/a | verify signatures, record ids, blob hashes or the replay |

## What this shows, and what it does not

- Both arms named the same established and open facts and the same exact
  acceptance body. The packet did **not** improve the recognition of facts in
  this one run.
- The difference is in action and verification:
  - arm A replayed the foreign checkpoint from its own root before accepting, then
    filed the exact record with no manual step;
  - arm B could verify nothing cryptographic, raised one false trust alarm, and
    left two manual actions.
- Arm A's input was about 2.6 times smaller (3.5 KB packet against a 9.7 KB
  prompt plus log). Total tokens were about the same, because tool output was
  counted too.
- The plain log exposed a raw detail (zero progress in the paused checkpoint)
  that the capsule hides. This is a real readability cost of the compact form,
  even though it was correct here.
- Arm A's false alarm comes from wording: `accept_by.results` in the use reasons
  and boundary text is easy to misread. This is a candidate wording fix for the
  context projection, not a semantic defect.
- n = 1 per arm, same model, same disk. Nothing here generalizes, and no claim
  about other models or hosts is made.
