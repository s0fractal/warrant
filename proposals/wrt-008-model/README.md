# WRT-008 model — design evidence, not a gate

`fact_derivation_check.py` and `harness.py` are the executable part of
WRT-008 (CLOSED — DEFERRED, 2026-09-07). They are kept so the profile, the
extractors and the verdicts stay runnable; nothing in `tools/check.py` runs
them, and `--record` is refused rather than claiming a binding two gates found
unverified.

```sh
python3 proposals/wrt-008-model/fact_derivation_check.py --selftest
python3 proposals/wrt-008-model/harness.py
```
