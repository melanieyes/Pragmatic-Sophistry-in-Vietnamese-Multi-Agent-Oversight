#!/usr/bin/env bash
# End-to-end pipeline for the VN banking AI-safety dataset.
#
# Generation steps (Adaption) and the monitor harness (Anthropic) spend credits / tokens,
# so they are gated: run estimates first, then pass RUN_FULL=1 to execute full runs.
#
#   ./run_all.sh                 # specs + (estimates) + validate/metrics on existing outputs
#   RUN_FULL=1 ./run_all.sh      # also execute full Adaption runs + monitor harness
#   MONITOR_MOCK=1 ./run_all.sh  # use mock monitor verdicts (no Anthropic key needed)
set -euo pipefail

PY="${PY:-.venv/bin/python}"

echo "== Stage 0: build specs =="
$PY src/build_specs.py

echo "== Stage 1: Adaption estimates =="
$PY src/gen_adaption.py enhance estimate
$PY src/gen_adaption.py localize estimate

if [[ "${RUN_FULL:-0}" == "1" ]]; then
  echo "== Stage 1: Adaption FULL runs =="
  $PY src/gen_adaption.py enhance full
  $PY src/gen_adaption.py localize full

  echo "== Stage 2: assemble =="
  $PY src/build_dataset.py

  echo "== Stage 3: validate + diversity gate =="
  $PY src/validate.py
  $PY src/diversity_gate.py || echo "  (diversity gate flagged items -> results/regenerate_list.csv)"
fi

echo "== Stage 4: monitor harness =="
if [[ "${MONITOR_MOCK:-0}" == "1" ]]; then
  $PY src/run_monitors.py --mock
else
  $PY src/run_monitors.py
fi
$PY src/evaluate.py

echo "== Optional: demo export =="
$PY src/export_demo_data.py

echo "== DONE =="
