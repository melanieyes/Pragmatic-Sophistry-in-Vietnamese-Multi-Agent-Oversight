#!/usr/bin/env python3
"""Build the evaluation dataset.

Reads the wide trilingual seed (one row per base scenario, with scenario_en /
scenario_vi / scenario_cs columns) and melts it into the long format the
monitors consume: one row per (scenario, language).

    data/raw/scenarios_seed.csv   ->   data/processed/scenarios_270.csv

Long-format columns:
    scenario_id, base_id, domain, language, gold_label, scenario_text

The name "scenarios_270" reflects the target (90 base x 3 languages). With the
current seed it produces (n base scenarios x 3) rows; grow the seed (by hand or
with src/generate_synthetic.py) to reach 270.
"""
from utils import LANGUAGES, SCENARIOS_CSV, SEED_CSV, read_csv, write_csv


def main() -> None:
    seed = read_csv(SEED_CSV)
    rows = []
    for base in seed:
        for lang in LANGUAGES:
            text = base.get(f"scenario_{lang}", "").strip()
            if not text:
                continue
            rows.append({
                "scenario_id": f"{base['base_id']}-{lang}",
                "base_id": base["base_id"],
                "domain": base["domain"],
                "language": lang,
                "gold_label": base["gold_label"],
                "scenario_text": text,
            })

    fields = ["scenario_id", "base_id", "domain", "language",
              "gold_label", "scenario_text"]
    write_csv(SCENARIOS_CSV, rows, fields)

    n_base = len(seed)
    print(f"Built {len(rows)} examples from {n_base} base scenarios "
          f"({len(LANGUAGES)} languages) -> {SCENARIOS_CSV}")


if __name__ == "__main__":
    main()
