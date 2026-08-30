#!/bin/sh
# Build paper.pdf from paper.md, with citations resolved from references.bib.
# Recorded so the artifact deposited at a DOI can be rebuilt from the same source.
#   pandoc 3.10.2, tectonic 0.17.0
set -e
cd "$(dirname "$0")"
# The versions in the comment above are ENFORCED, not decorative (review
# finding, 2026-08-27): a PDF built by other versions is a different artifact.
pandoc --version | head -1 | grep -qx "pandoc 3.10.2" \
  || { echo "build.sh: need pandoc 3.10.2, have: $(pandoc --version | head -1)" >&2; exit 1; }
tectonic --version | grep -qx "Tectonic 0.17.0" \
  || { echo "build.sh: need Tectonic 0.17.0, have: $(tectonic --version)" >&2; exit 1; }
python3 check_claims.py
# Byte-reproducible builds: tectonic embeds the build time (PDF /ID and dates)
# unless SOURCE_DATE_EPOCH is pinned. Fixing it to the paper's date (2026-08-30,
# 00:00:00Z) makes the deposited artifact reproducible from the same source and
# toolchain. Override in the environment only for a deliberately different date.
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1788048000}"
pandoc paper.md -o paper.pdf \
  --citeproc --pdf-engine=tectonic \
  -V geometry:margin=1in -V colorlinks=true -V linkcolor=blue -V urlcolor=blue \
  -M reference-section-title=References --toc
