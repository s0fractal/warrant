# What Remains Open (working draft 0.3)

A follow-on to [`the-reason-runs-again`](../the-reason-runs-again/) (1.1.0,
DOI 10.5281/zenodo.23414323). It reports the work on the three links that paper
leaves open, the separation of evidence bases, and the WRT-021 open-loop draft,
and it states the vision those point to.

**Status: working draft, not deposited, no DOI.** It is written to be reviewed
for gaps in the vision; section 9 lists the questions. Every claim is labelled
IMPLEMENTED (artifact and commit named), DRAFT or VISION. Every count was re-run
on the named commit on 2026-10-17. There is no `check_claims.py` yet: unlike the
flagship, nothing re-derives the counts on each build, and the paper says so.

Draft 0.1 received an automated review (DeepReview, PDF only). It is kept
verbatim in `reviews/` with a point-by-point triage against the code; draft 0.2
answers it. The triage also found one error the reviewer missed.

    sh build.sh     # pandoc 3.12.1 + tectonic 0.17.0 -> paper.pdf
