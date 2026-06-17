#!/usr/bin/env bash
#
# run_pipeline.sh — rebuild the dashboard from raw data, end to end.
#
#   ./run_pipeline.sh             # rebuild only (merge -> classify -> analyze -> build)
#   ./run_pipeline.sh --publish   # also copy artifacts into the repo, commit, and push
#
# Append new data first: drop new crawl exports into  Data Raw/  named
#   <Stem>_reviews_<label>.csv   (e.g. Bank_Jago_reviews_Jul26.csv), then run this.
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "[1/5] merge + de-dup raw   ->  data final/"
python3 merge_data.py | tail -1

echo "[2/5] classify 1-3 star    ->  Data Classified/"
python3 classifier.py | tail -1

echo "[3/5] aggregate classified ->  bad_reviews_classified.csv"
python3 aggregate_classified.py | tail -1

echo "[4/5] analyst metrics      ->  report/competitive-analysis-<date>.md"
python3 compute_analysis.py | tail -1

echo "[5/5] build dashboard      ->  index.html + dashboard.html"
python3 build_dashboard.py | tail -1

echo "Deterministic pipeline complete."
echo "Next (agent step): run the Reporter agent on the analysis file to produce"
echo "  report/intel-report-<date>.md  (see Pipeline_Workflow.md)."

if [[ "${1:-}" == "--publish" ]]; then
  REPO="$ROOT/id-digital-bank-playstore"
  if [[ ! -d "$REPO/.git" ]]; then
    echo "No git repo at $REPO — skipping publish."; exit 0
  fi
  echo "[publish] syncing artifacts into repo and pushing"
  cp index.html dashboard.html build_dashboard.py classifier.py aggregate_classified.py \
     compute_analysis.py merge_data.py run_pipeline.sh Pipeline_Workflow.md "$REPO/" 2>/dev/null || true
  cp Classifier_Agent_Instruction.md Analyst_Agent_Instruction.md \
     Reporter_Agent_Instruction.md "$REPO/agents/" 2>/dev/null || true
  cd "$REPO"
  git add -A
  if git diff --cached --quiet; then
    echo "[publish] nothing changed."
  else
    git commit -q -m "Update dashboard $(date +%F)"
    git push
    echo "[publish] pushed — GitHub Pages will redeploy in ~1 min."
  fi
fi
