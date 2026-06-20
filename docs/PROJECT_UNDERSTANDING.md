# Project Understanding — Lost in Translation, Lost in Control

> A working summary of what this repository is, how it is meant to fit together,
> and what currently exists. Generated from a read-through of the repo on
> 2026-06-20.

## 1. What this project is

An **AI-safety research project** investigating a blind spot in safety monitoring:
most AI safety / prompt-injection evaluations are **English-heavy**.

**Core research question:** Do AI safety monitors get *worse* at catching risky
tool-use behavior when the same behavior is expressed in **Vietnamese**,
**Vietnamese-English code-switching**, or **Vietnam-specific institutional
language**, compared to plain English?

The deliverables are a reproducible evaluation pipeline, a results table, a
static interactive HTML demo, and a written report.

## 2. Experiment design

- **90 base scenarios** of risky tool-use behavior.
- Each scenario is rendered in **3 language variants**:
  1. English
  2. Vietnamese
  3. Code-switched Vietnamese-English
- → **270 evaluated examples** total (90 × 3).
- Each example is run against **3 monitor setups**:
  1. **Baseline monitor** — a plain safety monitor.
  2. **Locale-aware monitor** — monitor given local/institutional context.
  3. **Translate-then-monitor** — translate the input to English first, then
     run the monitor.

The comparison of monitor reliability *across languages* and *across the three
setups* is the heart of the study.

## 3. Intended pipeline

Inferred from `src/` filenames and `run_all.sh`:

```
data/raw/scenarios_seed.csv
        │  build_dataset.py        (seed → expand to 3 language variants)
        ▼
data/processed/scenarios_270.csv
        │  run_monitors.py         (Anthropic API × 3 monitor prompts)
        ▼
results/monitor_outputs.csv
        │  evaluate.py             (compute metrics)
        ▼
results/metrics_summary.csv
results/domain_metrics.csv
        │  export_demo_data.py     (results → demo input)
        ▼
demo/data.js  ──►  static HTML demo (demo/index.html)
report/final_report.md
```

`src/utils.py` is presumably shared helpers (I/O, API client, parsing).

## 4. Repository layout

| Path | Purpose |
|---|---|
| `README.md` | Project overview and setup. |
| `data/raw/scenarios_seed.csv` | Hand-authored seed scenarios. |
| `data/processed/scenarios_270.csv` | Expanded 270-example dataset. |
| `prompts/baseline_monitor.md` | Baseline monitor prompt. |
| `prompts/locale_aware_monitor.md` | Locale-aware monitor prompt. |
| `prompts/translate_then_monitor.md` | Translate-then-monitor prompt. |
| `src/build_dataset.py` | Build the 270-example dataset from the seed. |
| `src/run_monitors.py` | Run the three monitors over the dataset. |
| `src/evaluate.py` | Compute metrics from monitor outputs. |
| `src/export_demo_data.py` | Export results into the demo. |
| `src/utils.py` | Shared utilities. |
| `results/monitor_outputs.csv` | Raw per-example monitor verdicts. |
| `results/metrics_summary.csv` | Aggregate metrics. |
| `results/domain_metrics.csv` | Metrics broken down by domain. |
| `demo/` | Static HTML/JS/CSS interactive demo. |
| `report/outline.md`, `report/final_report.md` | Writeup. |
| `run_all.sh` | End-to-end pipeline runner. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Holds `ANTHROPIC_API_KEY=`. |

## 5. Current state — it is a scaffold

The directory structure and intent are fully defined, but **almost no
implementation exists yet**.

**Files with real content (3):**
- `README.md`
- `.gitignore`
- `.env.example` (just `ANTHROPIC_API_KEY=`)

**Empty 0-byte placeholders (everything else):** all of `src/*.py`,
all `prompts/*.md`, all `results/*.csv`, both data CSVs, the entire `demo/`,
both `report/*.md`, plus `requirements.txt`, `run_all.sh`, and `LICENSE`.

Git history confirms this: the latest commit is just "initialize the project."

## 6. Stack & conventions

- **Language:** Python (venv-based, per README setup).
- **API:** Anthropic (`ANTHROPIC_API_KEY` via `.env`).
- **Demo:** static HTML + vanilla JS/CSS (no build step), fed by `demo/data.js`.
- **Data interchange:** CSV throughout.

## 7. Natural build order

1. `requirements.txt` — pin dependencies.
2. `data/raw/scenarios_seed.csv` — author the seed scenarios (everything
   depends on this).
3. `prompts/*.md` — the three monitor prompts.
4. `src/utils.py` → `build_dataset.py` → `run_monitors.py` → `evaluate.py` →
   `export_demo_data.py`.
5. `demo/` — wire up the static demo.
6. `report/` — outline then final report.
7. `run_all.sh` — glue the pipeline.
