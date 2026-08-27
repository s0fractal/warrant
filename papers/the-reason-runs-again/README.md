# The Reason Runs Again

The flagship write-up of this repository: the Warrant record format —
content-addressed identity, domain-separated signatures, re-executable
reasons, settlement, and the conformance apparatus — together with what
building it broke and what it still does not provide.

**Not deposited.** No DOI, no archived commit, no peer review. Until a Zenodo
deposit exists, this directory is a draft beside the thing it describes, and
nothing here should be cited as though it carried more.

| | |
| --- | --- |
| source | [`paper.md`](paper.md), bibliography in [`references.bib`](references.bib) |
| build | [`build.sh`](build.sh) — pandoc 3.10.2 with `--citeproc`, tectonic 0.17.0 |
| claims | [`check_claims.py`](check_claims.py) — recounts every countable number in the paper from the repository; `build.sh` runs it first and refuses to build on a mismatch |
| intended licence | CC BY 4.0 on deposit |

## The numbers are enforced, with a boundary

`check_claims.py` reads each countable claim **out of the paper** (a checker
holding its own copy of the answer only proves its two copies agree) and
recomputes it: conformance-pack vector totals, the canonicalization and
negative batteries, signature-vector counts, the review-ledger census and its
vendor mapping, the default re-execution budget. It also prints what it does
*not* check and why — harness-run measurements belong to `tools/test-all.sh`,
and prose is not countable. The vendor mapping (which reviewer label belongs
to which model vendor) is a judgment; it lives in the checker where it can be
disputed, not in the paper as a bare assertion.

## Depositing (when the author decides to)

1. Pick a commit; verify `tools/check.py` and `python3 check_claims.py` are
   green on it.
2. `./build.sh`; attach `paper.pdf` plus a repository snapshot at that commit.
3. Deposit on Zenodo (CC BY 4.0), record concept DOI + version DOI and the
   archived commit here and in `CITATION.cff`.
4. After that, `paper.pdf` as committed **is** the deposited artifact; a
   post-deposit edit to `paper.md` makes rebuild-and-commit-the-PDF the one
   forbidden move (see the sibling repository's deposited paper for the
   precedent and the reasoning).

## Standing

Written by a language model working as maintainer on this stack
(`MODEL-ACTORS.md`). Every number is measured from committed refs; the
limitations section (§8) restates the threat model's scoped assumptions
rather than softening them. What none of that supplies is independent
review — §8 says so about the format, and it applies to this paper in full.
