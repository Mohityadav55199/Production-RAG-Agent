#!/usr/bin/env bash
# Runs the live retrieval benchmark for each pipeline stage and saves one JSON per run in eval/results/.
# Needs GOOGLE_API_KEY (and GROQ_API_KEY for --condense/--rerank) in backend/.env. Costs a few embedding calls.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
COMMON="--live --min-score 0.63 --max-gap 0.05"
$PY eval/evaluate.py $COMMON --rebuild --json-out eval/results/1_vector.json
$PY eval/evaluate.py $COMMON --hybrid --json-out eval/results/2_hybrid.json
$PY eval/evaluate.py $COMMON --hybrid --rerank --json-out eval/results/3_hybrid_rerank.json
$PY eval/evaluate.py $COMMON --hybrid --rerank --condense --json-out eval/results/4_full_pipeline.json
