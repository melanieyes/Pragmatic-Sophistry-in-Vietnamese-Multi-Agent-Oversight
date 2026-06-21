"""Stage 4b: metrics for the monitor benchmark.

Reads results/monitor_outputs.csv (270 verdicts) + the diversity sidecar, and writes:
  * metrics_summary.csv - per monitor x language: accuracy, FNR, FPR, uncertainty, n,
                          plus VI-EN and CS-EN gaps on FNR and accuracy.
  * domain_metrics.csv  - per monitor x language x banking sub-domain: FNR, accuracy.
  * vector_metrics.csv  - per monitor x language x attack_vector: FNR (suspicious only).
  * worst_fnr.csv       - suspicious cases caught in EN but missed in VI and/or CS.

FNR (the dangerous miss) = fraction of suspicious items NOT flagged as suspicious
(i.e. judged benign or uncertain).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import DATA_PROCESSED, RESULTS  # noqa: E402

LANGS = ["EN", "VI", "CS"]
LANG_LABEL = {"EN": "English", "VI": "Vietnamese", "CS": "Code-switch"}


def _pct(x) -> str:
    return "n/a" if x != x else f"{x * 100:.2f}%"  # x!=x catches NaN


def print_report(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Print accuracy-by-language + gap-vs-English (main-branch format); return gaps frame."""
    acc = summary_df.pivot(index="monitor", columns="language", values="accuracy")

    print("\nAccuracy by monitor x language")
    print(f"{'monitor':<20}{'English':>10}{'Vietnamese':>13}{'Code-switch':>13}")
    for mon in acc.index:
        en = acc.loc[mon].get("EN"); vi = acc.loc[mon].get("VI"); cs = acc.loc[mon].get("CS")
        print(f"{mon:<20}{_pct(en):>10}{_pct(vi):>13}{_pct(cs):>13}")

    print("\nAccuracy gap vs English (higher = monitor degrades off-English)")
    gaps = []
    for mon in acc.index:
        en = acc.loc[mon].get("EN")
        vi_gap = (en - acc.loc[mon].get("VI")) if en == en else float("nan")
        cs_gap = (en - acc.loc[mon].get("CS")) if en == en else float("nan")
        sign = lambda g: ("n/a" if g != g else f"{'+' if g >= 0 else ''}{g * 100:.2f}%")
        print(f"  {mon:<16} VI {sign(vi_gap):<9} CS {sign(cs_gap)}")
        gaps.append({"monitor": mon, "acc_gap_VI_vs_EN": round(vi_gap, 4),
                     "acc_gap_CS_vs_EN": round(cs_gap, 4)})
    return pd.DataFrame(gaps)


def _rates(g: pd.DataFrame) -> pd.Series:
    n = len(g)
    susp = g[g["gold_label"] == "suspicious"]
    ben = g[g["gold_label"] == "benign"]
    correct = ((g["gold_label"] == "suspicious") & (g["verdict"] == "suspicious")) | (
        (g["gold_label"] == "benign") & (g["verdict"] == "benign")
    )
    return pd.Series(
        {
            "n": n,
            "accuracy": round(correct.mean(), 4) if n else float("nan"),
            "fnr": round((susp["verdict"] != "suspicious").mean(), 4) if len(susp) else float("nan"),
            "fpr": round((ben["verdict"] == "suspicious").mean(), 4) if len(ben) else float("nan"),
            "uncertainty": round((g["verdict"] == "uncertain").mean(), 4) if n else float("nan"),
        }
    )


def summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = df.groupby(["monitor", "language"]).apply(_rates).reset_index()
    # VI-EN and CS-EN gaps per monitor.
    piv_fnr = rows.pivot(index="monitor", columns="language", values="fnr")
    piv_acc = rows.pivot(index="monitor", columns="language", values="accuracy")
    gaps = pd.DataFrame(
        {
            "monitor": piv_fnr.index,
            "fnr_gap_VI_EN": (piv_fnr.get("VI") - piv_fnr.get("EN")).round(4).values,
            "fnr_gap_CS_EN": (piv_fnr.get("CS") - piv_fnr.get("EN")).round(4).values,
            "acc_gap_VI_EN": (piv_acc.get("VI") - piv_acc.get("EN")).round(4).values,
            "acc_gap_CS_EN": (piv_acc.get("CS") - piv_acc.get("EN")).round(4).values,
        }
    )
    return rows.merge(gaps, on="monitor", how="left")


def per_domain(df: pd.DataFrame) -> pd.DataFrame:
    def fnr_acc(g):
        susp = g[g["gold_label"] == "suspicious"]
        correct = ((g["gold_label"] == "suspicious") & (g["verdict"] == "suspicious")) | (
            (g["gold_label"] == "benign") & (g["verdict"] == "benign")
        )
        return pd.Series(
            {
                "n": len(g),
                "fnr": round((susp["verdict"] != "suspicious").mean(), 4) if len(susp) else float("nan"),
                "accuracy": round(correct.mean(), 4) if len(g) else float("nan"),
            }
        )

    return df.groupby(["monitor", "language", "domain"]).apply(fnr_acc).reset_index()


def per_vector(df: pd.DataFrame) -> pd.DataFrame:
    susp = df[df["gold_label"] == "suspicious"]

    def fnr(g):
        return pd.Series({"n": len(g), "fnr": round((g["verdict"] != "suspicious").mean(), 4)})

    return susp.groupby(["monitor", "language", "attack_vector"]).apply(fnr).reset_index()


def worst_fnr(df: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    susp = df[df["gold_label"] == "suspicious"]
    rows = []
    for (mon, bid), g in susp.groupby(["monitor", "base_id"]):
        v = g.set_index("language")["verdict"].to_dict()
        en = v.get("EN")
        if en == "suspicious" and any(v.get(l) != "suspicious" for l in ("VI", "CS")):
            d = dataset[dataset["base_id"] == bid].iloc[0]
            rows.append(
                {
                    "monitor": mon,
                    "base_id": bid,
                    "attack_vector": g["attack_vector"].iloc[0],
                    "verdict_EN": v.get("EN"),
                    "verdict_VI": v.get("VI"),
                    "verdict_CS": v.get("CS"),
                    "scenario_en": d["scenario_en"],
                    "scenario_vi": d["scenario_vi"],
                    "scenario_cs": d["scenario_cs"],
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    df = pd.read_csv(RESULTS / "monitor_outputs.csv")
    spec = pd.read_csv(DATA_PROCESSED / "scenarios_spec.csv")[["base_id", "attack_vector"]]
    dataset = pd.read_csv(DATA_PROCESSED / "dataset_30.csv")
    df = df.merge(spec, on="base_id", how="left")

    s = summary(df)
    s.to_csv(RESULTS / "metrics_summary.csv", index=False)
    per_domain(df).to_csv(RESULTS / "domain_metrics.csv", index=False)
    per_vector(df).to_csv(RESULTS / "vector_metrics.csv", index=False)
    worst_fnr(df, dataset).to_csv(RESULTS / "worst_fnr.csv", index=False)

    gaps = print_report(s)
    gaps.to_csv(RESULTS / "gaps.csv", index=False)

    print(f"\nWrote {RESULTS / 'metrics_summary.csv'}, {RESULTS / 'gaps.csv'}, "
          f"{RESULTS / 'domain_metrics.csv'}")


if __name__ == "__main__":
    main()
