"""Optional: export dataset + metrics into demo/data.js for the static demo.

Writes a single ``window.DATA = {...}`` object the demo page can read without a server.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import DATA_PROCESSED, RESULTS, ROOT  # noqa: E402


def _read(path: Path) -> list[dict]:
    return pd.read_csv(path).to_dict(orient="records") if path.exists() else []


def main() -> None:
    payload = {
        "dataset": _read(DATA_PROCESSED / "dataset_30.csv"),
        "metrics_summary": _read(RESULTS / "metrics_summary.csv"),
        "domain_metrics": _read(RESULTS / "domain_metrics.csv"),
        "vector_metrics": _read(RESULTS / "vector_metrics.csv"),
        "worst_fnr": _read(RESULTS / "worst_fnr.csv"),
    }
    out = ROOT / "demo" / "data.js"
    out.write_text(
        "window.DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"[export_demo_data] wrote {out} "
          f"({len(payload['dataset'])} rows, {len(payload['metrics_summary'])} metric rows)")


if __name__ == "__main__":
    main()
