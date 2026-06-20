# Lost in Translation, Lost in Control

An audit of whether AI safety monitors miss risky banking-agent behaviour when it is expressed in
Vietnamese, Vietnamese-English code-switching, and Vietnam-specific institutional contexts.

## Project

Most AI safety-monitor evaluations are English-heavy. This project asks whether monitor reliability
changes when the *same* risky tool-use behaviour is expressed in Vietnamese (VI) or code-switched
Vietnamese-English (CS), focused on the highest-stakes surface in Vietnam: **digital banking / fintech**
(e-wallet / QR-first — MoMo, ZaloPay, VNPay, Viettel Money — plus Techcombank, Vietcombank, BIDV, VPBank).

We test three monitor setups: **baseline** (English-only), **locale-aware** (glossary + warning), and
**translate-then-monitor** (translate → judge).

## Dataset

- **30 base scenarios** — third-person statements of an AI banking-agent *behaviour* — each rendered in
  **EN, VI, CS** → **90 language-rows**. 10 benign / 20 suspicious; ≥14 attack vectors; 4 sub-domains.
- **Wide schema** (`data/processed/dataset_30.csv`):
  `scenario_en, gold_label, enhanced_prompt, enhanced_completion, base_id, domain, scenario_cs, scenario_vi`.
- **Integrity:** labels, domains, attack vectors and the diversity assignment are authored
  deterministically in code; **Adaption** ([adaptionlabs.ai](https://adaptionlabs.ai)) fills only the
  generated columns (analysis `enhanced_prompt`/`enhanced_completion` + `scenario_vi`/`scenario_cs`).
  3 hand-authored gold rows + 27 generated.

## Pipeline

```
src/build_specs.py      ->  data/processed/scenarios_spec.csv (+ generated_specs.csv)   # deterministic
src/gen_adaption.py     ->  data/processed/enhance_raw.csv, localize_raw.csv            # Adaption
src/build_dataset.py    ->  data/processed/dataset_30.csv (+ .jsonl)                     # assemble
src/validate.py         ->  hard checks + results/validation_warnings.csv
src/diversity_gate.py   ->  results/near_duplicates.csv, regenerate_list.csv
src/run_monitors.py     ->  results/monitor_outputs.csv (270 verdicts)                   # Anthropic
src/evaluate.py         ->  results/{metrics_summary,domain_metrics,vector_metrics,worst_fnr}.csv
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set ADAPTION_API_KEY (generation) and ANTHROPIC_API_KEY (monitors)
```

## Run

Adaption and the monitor harness spend credits/tokens, so generation is gated. Always estimate first:

```bash
python src/build_specs.py
python src/gen_adaption.py enhance estimate     # free cost quote
python src/gen_adaption.py enhance pilot        # 6-row sample to inspect
python src/gen_adaption.py enhance full         # full run
python src/gen_adaption.py localize full
python src/build_dataset.py
python src/validate.py && python src/diversity_gate.py

python src/run_monitors.py        # or --mock to run without an Anthropic key
python src/evaluate.py
```

Or end-to-end: `RUN_FULL=1 ./run_all.sh` (add `MONITOR_MOCK=1` to skip live monitor calls).

## Repo structure

- `data/raw/` — `taxonomy.yaml` (diversity menus + slang glossary), `gold_scenarios.yaml` (3 gold rows).
- `data/processed/` — specs, Adaption downloads, and the final `dataset_30.csv`.
- `prompts/` — Adaption blueprints + the 3 monitor prompts.
- `src/` — pipeline scripts (see above).
- `results/` — monitor outputs and metrics.
- `report/` — `outline.md` and `final_report.md`.
- `demo/` — static HTML demo fed by `src/export_demo_data.py`.
