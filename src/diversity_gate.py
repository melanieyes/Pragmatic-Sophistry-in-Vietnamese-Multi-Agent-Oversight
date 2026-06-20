"""Stage 3b: semantic-diversity gate over dataset_30.csv.

1. Per-language near-duplicate detection: embed each language column, flag any pair with
   cosine similarity > THRESHOLD (default 0.85), and emit a regenerate-list.
2. Coverage asserts on the diversity sidecar (>=14 attack vectors, >=8 suspicious flows,
   >=8 benign flows, no app > 40%).

Exit code is non-zero if near-duplicates or coverage gaps remain, so an orchestrator can
trigger regeneration (re-run gen_adaption for the flagged base_ids with a "make this
clearly different" instruction) and re-gate until clean.
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import DATA_PROCESSED, RESULTS, cosine_sim_matrix, embed  # noqa: E402

THRESHOLD = 0.85
LANG_COLS = ["scenario_en", "scenario_vi", "scenario_cs"]


def near_duplicates(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    flagged = []
    for col in LANG_COLS:
        texts = df[col].astype(str).tolist()
        sim = cosine_sim_matrix(embed(texts))
        for i, j in combinations(range(len(df)), 2):
            s = float(sim[i][j])
            if s > threshold:
                flagged.append(
                    {
                        "language": col,
                        "base_id_a": df.iloc[i]["base_id"],
                        "base_id_b": df.iloc[j]["base_id"],
                        "similarity": round(s, 3),
                    }
                )
    return pd.DataFrame(flagged)


def coverage_asserts(spec: pd.DataFrame) -> list[str]:
    errs = []
    susp = spec[spec["gold_label"] == "suspicious"]
    benign = spec[spec["gold_label"] == "benign"]
    if susp["attack_vector"].nunique() < 14:
        errs.append(f"attack vectors < 14 ({susp['attack_vector'].nunique()})")
    if susp["banking_flow"].nunique() < 8:
        errs.append(f"suspicious flows < 8 ({susp['banking_flow'].nunique()})")
    if benign["banking_flow"].nunique() < 8:
        errs.append(f"benign flows < 8 ({benign['banking_flow'].nunique()})")
    shares = spec["app"].value_counts(normalize=True)
    if (shares > 0.40).any():
        errs.append(f"app over 40%: {shares[shares > 0.40].to_dict()}")
    return errs


def main(threshold: float = THRESHOLD) -> int:
    df = pd.read_csv(DATA_PROCESSED / "dataset_30.csv")
    spec = pd.read_csv(DATA_PROCESSED / "scenarios_spec.csv")

    flagged = near_duplicates(df, threshold)
    regen = sorted(set(flagged["base_id_a"]).union(flagged["base_id_b"])) if not flagged.empty else []
    pd.DataFrame({"base_id": regen}).to_csv(RESULTS / "regenerate_list.csv", index=False)
    flagged.to_csv(RESULTS / "near_duplicates.csv", index=False)

    errs = coverage_asserts(spec)

    print(f"[diversity_gate] threshold={threshold} near-dup pairs={len(flagged)} "
          f"to-regenerate={len(regen)} coverage_errors={len(errs)}")
    if not flagged.empty:
        print(flagged.to_string(index=False))
    for e in errs:
        print("  COVERAGE:", e)

    return 0 if (flagged.empty and not errs) else 1


if __name__ == "__main__":
    thr = float(sys.argv[1]) if len(sys.argv) > 1 else THRESHOLD
    raise SystemExit(main(thr))
