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
    "attack_vector", "banking_flow", "app", "amount_band", "difficulty", "source",
]

# Per-version config: which taxonomy, the coverage targets, and the output files.
VERSIONS = {
    "v1": {
        "taxonomy": "taxonomy.yaml",
        "include_gold": True,
        "coverage": dict(n_total=30, n_susp=20, n_benign=10),
        "spec_out": "scenarios_spec.csv",
        "gen_out": "generated_specs.csv",
    },
    "v2": {
        "taxonomy": "taxonomy_v2.yaml",
        "include_gold": False,           # all 100 authored in the taxonomy
        "coverage": dict(n_total=100, n_susp=60, n_benign=40, min_vectors=40),
        "spec_out": "scenarios_spec_100.csv",
        "gen_out": "generated_specs_100.csv",
    },
}


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
                "difficulty": g.get("difficulty", "clear"),
                "source": "gold",
            }
        )
    return rows


def main(version: str = "v1", seed: int = 7) -> None:
    cfg = VERSIONS[version]
    taxonomy = read_yaml(DATA_RAW / cfg["taxonomy"])
    generated = build_generated_specs(taxonomy, seed=seed)
    gold = load_gold_rows() if cfg["include_gold"] else []

    all_rows = generated + gold
    assert_coverage(all_rows, **cfg["coverage"])

    # base_id uniqueness across the whole set.
    ids = [r["base_id"] for r in all_rows]
    assert len(ids) == len(set(ids)), f"duplicate base_id: {[i for i in ids if ids.count(i) > 1]}"

    df_all = pd.DataFrame(all_rows)[SIDECAR_COLS]
    df_all.to_csv(DATA_PROCESSED / cfg["spec_out"], index=False)

    df_gen = pd.DataFrame(generated)[["base_id", "scenario_en", "gold_label", "domain", "difficulty"]]
    df_gen.to_csv(DATA_PROCESSED / cfg["gen_out"], index=False)

    print(f"[build_specs] [{version}] wrote {len(df_all)} specs -> {cfg['spec_out']} "
          f"({len(df_gen)} generated -> {cfg['gen_out']})")


def _arg(flag: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


if __name__ == "__main__":
    main(version=_arg("--version", "v1"))
