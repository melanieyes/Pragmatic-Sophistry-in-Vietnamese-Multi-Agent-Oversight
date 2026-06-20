"""Stage 4a: run the three monitors over the 90 language-rows -> 270 verdicts.

Melts dataset_30.csv (wide) into (base_id, language, scenario_text, gold_label, domain),
then evaluates each row with each monitor. Writes results/monitor_outputs.csv.

Usage:
    python src/run_monitors.py          # real Anthropic calls (needs ANTHROPIC_API_KEY)
    python src/run_monitors.py --mock   # deterministic synthetic verdicts (no API key)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monitors import MONITORS, run_monitor  # noqa: E402
from utils import DATA_PROCESSED, RESULTS, load_keys  # noqa: E402

LANG_COL = {"EN": "scenario_en", "VI": "scenario_vi", "CS": "scenario_cs"}


def melt(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        for lang, col in LANG_COL.items():
            rows.append(
                {
                    "base_id": r["base_id"],
                    "language": lang,
                    "scenario_text": r[col],
                    "gold_label": r["gold_label"],
                    "domain": r["domain"],
                }
            )
    return pd.DataFrame(rows)


def main(mock: bool = False) -> None:
    load_keys()
    df = pd.read_csv(DATA_PROCESSED / "dataset_30.csv")
    long = melt(df)

    out = []
    for _, r in long.iterrows():
        for mon in MONITORS:
            verdict, reason = run_monitor(mon, r["scenario_text"], language=r["language"], mock=mock)
            out.append(
                {
                    "base_id": r["base_id"],
                    "language": r["language"],
                    "gold_label": r["gold_label"],
                    "domain": r["domain"],
                    "monitor": mon,
                    "verdict": verdict,
                    "reason": reason,
                }
            )
    res = pd.DataFrame(out)
    res.to_csv(RESULTS / "monitor_outputs.csv", index=False)
    print(f"[run_monitors] {'MOCK ' if mock else ''}wrote {len(res)} verdicts "
          f"({long.shape[0]} rows x {len(MONITORS)} monitors) -> monitor_outputs.csv")


if __name__ == "__main__":
    main(mock="--mock" in sys.argv)
