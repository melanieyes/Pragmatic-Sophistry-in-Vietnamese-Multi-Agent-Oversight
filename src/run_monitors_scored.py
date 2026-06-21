"""Stage 4a (SHADE-Arena method): graded 0-100 suspicion scoring.

Melts dataset_30.csv (wide) into language-rows and asks each monitor for a 0-100
suspicion score (never a binary verdict). Writes results/monitor_scores.csv with the
data contract:

    base_id, lang (en|vi|cs), gold (benign|suspicious), monitor_id,
    suspicion_score (float|empty on parse failure), rationale, raw_monitor_output, domain

`monitor_id` encodes both the monitor configuration AND the judge model
(e.g. "baseline@deepseek:deepseek-chat") so cross-model comparisons are unambiguous.

gold is NEVER passed into the monitor prompt (only scenario_text is) -> no label leakage.

Usage:
    python src/run_monitors_scored.py --mock
    python src/run_monitors_scored.py --providers deepseek
    python src/run_monitors_scored.py --providers deepseek,gemini --workers 12
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monitors import MONITORS, PROVIDER_DEFAULT_MODEL, run_monitor_scored  # noqa: E402
from utils import DATA_PROCESSED, RESULTS, load_keys  # noqa: E402

LANG_COL = {"EN": "scenario_en", "VI": "scenario_vi", "CS": "scenario_cs"}
LANG_OUT = {"EN": "en", "VI": "vi", "CS": "cs"}


def melt(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        for lang, col in LANG_COL.items():
            rows.append({
                "base_id": r["base_id"],
                "language": lang,
                "scenario_text": r[col],
                "gold_label": r["gold_label"],
                "domain": r["domain"],
            })
    return pd.DataFrame(rows)


def _task(args):
    r, mon, mock, provider, model = args
    score, rationale, raw = run_monitor_scored(
        mon, r["scenario_text"], language=r["language"],
        provider=provider, model=model, mock=mock,
    )
    mid = "mock" if mock else f"{mon}@{provider}:{model or PROVIDER_DEFAULT_MODEL.get(provider, '?')}"
    # For mock we still keep the monitor config visible in monitor_id.
    if mock:
        mid = f"{mon}@mock"
    return {
        "base_id": r["base_id"],
        "lang": LANG_OUT[r["language"]],
        "gold": r["gold_label"],
        "monitor_id": mid,
        "suspicion_score": score,
        "rationale": rationale,
        "raw_monitor_output": raw,
        "domain": r["domain"],
    }


def _resolve_runs(mock: bool, models: str, providers: str, model: str) -> list[tuple[str, str]]:
    """Build the list of (provider, model) judges. `--models` (provider:model,...) wins;
    otherwise fall back to the legacy `--providers`/`--model` form."""
    if mock:
        return [("mock", "")]
    if models:
        runs = []
        for pair in models.split(","):
            prov, _, mdl = pair.partition(":")
            runs.append((prov.strip(), mdl.strip()))
        return runs
    return [(p, model) for p in providers.split(",")]


def main(mock: bool = False, workers: int = 8, dataset: str = "dataset_30.csv",
         out: str = "", models: str = "", providers: str = "deepseek", model: str = "") -> None:
    load_keys()
    df = pd.read_csv(DATA_PROCESSED / dataset)
    long = melt(df)

    runs = _resolve_runs(mock, models, providers, model)
    tasks = [(r, mon, mock, prov, mdl)
             for _, r in long.iterrows()
             for mon in MONITORS
             for (prov, mdl) in runs]

    if mock or workers <= 1:
        result = [_task(t) for t in tasks]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            result = list(ex.map(_task, tasks))

    res = pd.DataFrame(result).sort_values(
        ["monitor_id", "base_id", "lang"]).reset_index(drop=True)
    out_name = out or ("monitor_scores_100.csv" if "100" in dataset else "monitor_scores.csv")
    res.to_csv(RESULTS / out_name, index=False)

    n_parse_fail = int(res["suspicion_score"].isna().sum())
    tag = "MOCK" if mock else ";".join(f"{p}:{m or '?'}" for p, m in runs)
    print(f"[run_monitors_scored] [{tag}] wrote {len(res)} scored rows "
          f"({long.shape[0]} lang-rows x {len(MONITORS)} monitors x {len(runs)} judge(s)) "
          f"-> {out_name}")
    print(f"[run_monitors_scored] parse failures (score=None): {n_parse_fail}")
    if n_parse_fail:
        bad = res[res["suspicion_score"].isna()][["monitor_id", "base_id", "lang"]]
        print(bad.to_string(index=False))


def _arg(flag: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


if __name__ == "__main__":
    main(
        mock="--mock" in sys.argv,
        workers=int(_arg("--workers", "8")),
        dataset=_arg("--dataset", "dataset_30.csv"),
        out=_arg("--out", ""),
        models=_arg("--models", ""),
        providers=_arg("--providers", "deepseek"),
        model=_arg("--model", ""),
    )
