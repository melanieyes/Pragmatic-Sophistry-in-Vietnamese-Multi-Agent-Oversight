"""Stage 0: author the 30 scenario specs (deterministic, no LLM).

Outputs:
  * ``data/processed/scenarios_spec.csv`` - all 30 rows with the diversity sidecar
    (base_id, scenario_en, gold_label, domain, attack_vector, banking_flow, app,
    amount_band, source). This is the ground-truth + diversity record.
  * ``data/processed/generated_specs.csv`` - the 27 generated rows only; consumed by
    gen_adaption.py to build the Adaption upload files.

Fails loudly via diversity_matrix.assert_coverage if any target is missed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from diversity_matrix import assert_coverage, build_generated_specs  # noqa: E402
from utils import DATA_PROCESSED, DATA_RAW, read_yaml  # noqa: E402

SIDECAR_COLS = [
    "base_id", "scenario_en", "gold_label", "domain",
    "attack_vector", "banking_flow", "app", "amount_band", "source",
]


def load_gold_rows() -> list[dict]:
    gold = read_yaml(DATA_RAW / "gold_scenarios.yaml")
    rows = []
    for g in gold:
        rows.append(
            {
                "base_id": g["base_id"],
                "scenario_en": " ".join(g["scenario_en"].split()),
                "gold_label": g["gold_label"],
                "domain": g["domain"],
                "attack_vector": g.get("attack_vector", "none"),
                "banking_flow": g["banking_flow"],
                "app": g["app"],
                "amount_band": g["amount_band"],
                "source": "gold",
            }
        )
    return rows


def main(seed: int = 7) -> None:
    taxonomy = read_yaml(DATA_RAW / "taxonomy.yaml")
    generated = build_generated_specs(taxonomy, seed=seed)
    gold = load_gold_rows()

    all_rows = generated + gold
    assert_coverage(all_rows)

    # base_id uniqueness across the whole set.
    ids = [r["base_id"] for r in all_rows]
    assert len(ids) == len(set(ids)), f"duplicate base_id: {[i for i in ids if ids.count(i) > 1]}"

    df_all = pd.DataFrame(all_rows)[SIDECAR_COLS]
    df_all.to_csv(DATA_PROCESSED / "scenarios_spec.csv", index=False)

    df_gen = pd.DataFrame(generated)[["base_id", "scenario_en", "gold_label", "domain"]]
    df_gen.to_csv(DATA_PROCESSED / "generated_specs.csv", index=False)

    print(f"[build_specs] wrote {len(df_all)} specs -> scenarios_spec.csv "
          f"({len(df_gen)} generated -> generated_specs.csv)")


if __name__ == "__main__":
    main()
