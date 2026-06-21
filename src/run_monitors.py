"""Stage 4a: run the three monitors over the 90 language-rows -> 270 verdicts.

Melts dataset_30.csv (wide) into (base_id, language, scenario_text, gold_label, domain),
then evaluates each row with each monitor. Writes results/monitor_outputs.csv.

Calls run concurrently (I/O-bound) via a thread pool. Each translate_then verdict is
2 LLM calls, so a full run is 90 x (1+1+2) = 360 calls; concurrency cuts wall-clock ~8x.

Usage:
    python src/run_monitors.py                 # real Gemini calls (needs GEMINI_API_KEY)
    python src/run_monitors.py --mock          # deterministic synthetic verdicts (no key)
    python src/run_monitors.py --workers 12    # tune concurrency (default 8)
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
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


def _task(args):
    r, mon, mock, provider, model = args
    kw = {"language": r["language"], "mock": mock, "provider": provider}
    if model:
        kw["model"] = model
    verdict, reason = run_monitor(mon, r["scenario_text"], **kw)
    return {
        "base_id": r["base_id"], "language": r["language"], "gold_label": r["gold_label"],
        "domain": r["domain"], "monitor": mon, "verdict": verdict, "reason": reason,
    }


def main(mock: bool = False, workers: int = 8, provider: str = "gemini", model: str = "") -> None:
    load_keys()
    df = pd.read_csv(DATA_PROCESSED / "dataset_30.csv")
    long = melt(df)

    tasks = [(r, mon, mock, provider, model) for _, r in long.iterrows() for mon in MONITORS]
    if mock or workers <= 1:
        out = [_task(t) for t in tasks]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            out = list(ex.map(_task, tasks))

    res = pd.DataFrame(out).sort_values(["base_id", "language", "monitor"]).reset_index(drop=True)
    res.to_csv(RESULTS / "monitor_outputs.csv", index=False)
    tag = "MOCK" if mock else f"{provider}:{model or 'default'}"
    print(f"[run_monitors] [{tag}] wrote {len(res)} verdicts "
          f"({long.shape[0]} rows x {len(MONITORS)} monitors, workers={1 if mock else workers}) "
          f"-> monitor_outputs.csv")


def _arg(flag: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


if __name__ == "__main__":
    main(
        mock="--mock" in sys.argv,
        workers=int(_arg("--workers", "8")),
        provider=_arg("--provider", "gemini"),
        model=_arg("--model", ""),
    )
