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
# unless SOURCE_DATE_EPOCH is pinned. Fixing it to the paper's date makes the
# deposited artifact reproducible from the same source and toolchain: 1.0.0 was
# built with 1788048000 (2026-08-30), 1.1.0 with 1792108800 (2026-10-16, the
# date in paper.md). Override only to rebuild an earlier version.
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1792108800}"
pandoc paper.md -o paper.pdf \
  --citeproc --pdf-engine=tectonic \
  -V geometry:margin=1in -V colorlinks=true -V linkcolor=blue -V urlcolor=blue \
  -M reference-section-title=References --toc
