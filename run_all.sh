#!/usr/bin/env bash
# smoke → small-real → full, one command.
set -euo pipefail

cd "$(dirname "$0")"

echo "== smoke (mock, 5 rows) =="
python src/run.py --mock --limit 5

echo "== small-real (10 rows) =="
python src/run.py --limit 10

echo "== full =="
python src/run.py
