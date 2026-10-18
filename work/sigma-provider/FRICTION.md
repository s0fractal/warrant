# Friction notes (Warrant 2 used on its own integration work)

Short observations while recording this work with the current CLI. Not a tracker.

1. A duty body has 11 members and every one is required: each `file --type duty`
   repeats `"release_by":[],"schedule":null,"requires":[],"serves":[],"answers":null,"subject":null`.
2. `warrant file` prints JSON; getting the new id into a shell variable needs a
   JSON parser every time.
3. A transition body has 10 members; an attestation that closes one duty still
   repeats `"relied_on":[],"opened":[],"supersedes":[],"triggers":[]` and the
   evidence twice (transition and item).
4. Evidence is easiest as a captured log piped into `warrant blob -`; fine.
5. One assessment has one `--workspace`. D1's grounds live in sigma-glyph and
   D2's in warrant, so D1 could not declare a `subject_changed` trigger that the
   same assessment can evaluate; it relies on `subject` + `--current` instead.
6. For Codex's acceptance to count, Codex must first be in `trust.json`: his
   public key is his to provide, so the reviewer's first step is outside Warrant.
7. A subject revision must be the full 40-hex SHA; short SHAs from `git log` are
   refused by the schema (correctly) and had to be expanded by hand.
8. (handoff) The holder's frontier said `close` for duties whose closures were
   filed and only waited for codex. Now it says `awaiting acceptance by codex`.
9. (handoff) Nothing in a report said that codex had no key in trust.json, so
   no acceptance by codex could count. Reports now list `unbound_actors`.
10. (handoff) `assess` did not show a duty's `requires`; it does now.
11. (handoff) T2's residual "GitHub CI not run" was stale when the new session
    read it. A residual is a snapshot; the packet's refresh step covers records,
    not the outside world.
