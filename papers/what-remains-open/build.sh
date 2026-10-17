#!/bin/sh
# Build paper.pdf from paper.md, with citations resolved from references.bib.
#   pandoc 3.12.1, tectonic 0.17.0 (the same pins as the-reason-runs-again 1.1.0)
# Working draft 0.1: not deposited, no claims checker yet (the paper says so).
set -e
cd "$(dirname "$0")"
pandoc --version | head -1 | grep -qx "pandoc 3.12.1" \
  || { echo "build.sh: need pandoc 3.12.1, have: $(pandoc --version | head -1)" >&2; exit 1; }
tectonic --version | grep -qx "Tectonic 0.17.0" \
  || { echo "build.sh: need Tectonic 0.17.0, have: $(tectonic --version)" >&2; exit 1; }
# 2026-10-17 00:00 UTC, the date in paper.md: byte-reproducible from the same source.
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1792195200}"
pandoc paper.md -o paper.pdf \
  --citeproc --pdf-engine=tectonic \
  -V geometry:margin=1in -V colorlinks=true -V linkcolor=blue -V urlcolor=blue \
  -M reference-section-title=References --toc
