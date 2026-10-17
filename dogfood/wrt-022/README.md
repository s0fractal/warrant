# WRT-022 dogfood store

Real, current WRT-021 events of the WRT-022 review rounds, each signed by its own
agent's key. These are not transcriptions: compare `demos/wrt-021-dogfood/`, whose
actors are fixture keys named `*@transcribed`. `POLICY.md` says what the records
are and what they are not. Its root is prose, and both keys live in one operator's
custody.

| File | What |
|---|---|
| `trust.json` | the two enrolled public keys |
| `profile.json` | the recipient's named uses |
| `POLICY.md` | the enrolment and `under` policy |
| `store/` | the records and blobs |
| `events.py` | `assess` (the current view), `check` (CI: everything verifies, nothing refused), `accept` (file your own acceptances) |
| `record_claude_round1.py` | the one-off script with which Claude filed its own events, kept for audit |

    python3 dogfood/wrt-022/events.py assess

To file acceptances, set `WRT022_KEY` to your own private key, outside this
repository, and run `events.py accept --actor <your actor>`. The command files only
the acceptances your actor owes. It never signs for anyone else.
