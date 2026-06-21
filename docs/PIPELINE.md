# Pipeline Logic — how the code actually works

Read this with the source open. Every stage lists its **script**, **what it does**,
**inputs → outputs**, and the **key functions**. Data flows top to bottom.

```
                       data/raw/taxonomy.yaml   data/raw/gold_scenarios.yaml
                                   │                       │
  STAGE 0  build_specs.py  ───────┴───────────────────────┘
   (deterministic)                ▼
                       data/processed/scenarios_spec.csv   (30 rows, ground truth + diversity)
                       data/processed/generated_specs.csv  (27 rows to generate)
                                   │
  STAGE 1  gen_adaption.py  ───────┤   (Adaption LLM service, 2 runs)
                                   ▼
                       data/processed/enhance_raw.csv    (enhanced_completion analysis)
                       data/processed/localize_raw.csv   (JSON {scenario_vi, scenario_cs})
                                   │
  STAGE 2  build_dataset.py  ──────┤   (+ gold rows)
                                   ▼
                       data/processed/dataset_30.csv  +  .jsonl   (FINAL wide dataset, 8 cols)
                                   │
  STAGE 3  validate.py + diversity_gate.py   (quality gates, fail loud)
                                   │
  STAGE 4  run_monitors.py  ───────┤   (Gemini judge, parallel)
                                   ▼
                       results/monitor_outputs.csv   (270 verdicts)
                                   │
           evaluate.py  ───────────┤
                                   ▼
                       results/metrics_summary.csv, gaps.csv, domain_metrics.csv,
                       vector_metrics.csv, worst_fnr.csv
```

`src/utils.py` is shared by everything (paths, `AdaptionRunner`, language helpers,
embeddings, the Gemini/Anthropic call helpers).

---

## Stage 0 — Author the scenarios (no LLM, fully deterministic)

**Files:** [`data/raw/taxonomy.yaml`](../data/raw/taxonomy.yaml),
[`src/diversity_matrix.py`](../src/diversity_matrix.py),
[`src/build_specs.py`](../src/build_specs.py),
[`data/raw/gold_scenarios.yaml`](../data/raw/gold_scenarios.yaml)

**Logic:**
1. `taxonomy.yaml` is the content source: 4 sub-domains, the apps/amount-band menus, a
   slang glossary, and **27 scenario templates** — 18 suspicious (one per attack
   vector) + 9 benign. Each template has `{app}` and `{amount}` placeholders and a
   baked-in banking flow so the sentence stays coherent.
2. `diversity_matrix.build_generated_specs()` fills each template:
   - rotates the 8 apps round-robin (so no app exceeds 40% of rows),
   - renders a concrete VND amount from the template's amount band,
   - assigns a `base_id` like `pay-001` (`<domain-prefix>-NNN`).
3. `diversity_matrix.assert_coverage()` checks the whole 30-row set and **raises** if a
   target is missed: 20 suspicious / 10 benign, ≥14 distinct attack vectors, ≥8 flows
   each side, every `(attack_vector, banking_flow)` tuple unique, no app > 40%.
4. `build_specs.py` loads the 3 hand-written gold rows, merges them with the 27
   generated specs, runs `assert_coverage`, and writes:
   - `scenarios_spec.csv` — all 30 rows, the **ground-truth + diversity record**
     (this is the file `evaluate.py` later joins for per-attack-vector metrics),
   - `generated_specs.csv` — the 27 rows that Stage 1 will send to Adaption.

**Why deterministic:** labels and diversity are the part that must be *correct*, so
they're code, not model output.

---

## Stage 1 — Generate the LLM text columns (Adaption)

**Files:** [`src/gen_adaption.py`](../src/gen_adaption.py),
[`prompts/blueprint_adaption.md`](../prompts/blueprint_adaption.md),
[`prompts/blueprint_localize.md`](../prompts/blueprint_localize.md),
`AdaptionRunner` in [`src/utils.py`](../src/utils.py)

Adaption "Adaptive Data" is a dataset-augmentation service: upload a CSV, it generates
a completion per row. We use it for **two runs**, each gated `estimate → pilot(6) → full`:

- **enhance run** → produces `enhanced_completion` (the expert analysis).
  The upload's prompt column is an authored `analysis_prompt` that wraps `scenario_en`
  in *"Analyze the following statement… 1. risks 2. define terms 3. safe alternatives."*
  The blueprint tells the model to write only the analysis.
- **localize run** → produces `scenario_vi` and `scenario_cs`.
  The prompt asks for a JSON object `{"scenario_vi": ..., "scenario_cs": ...}`; the
  blueprint pins meaning/risk preservation and the code-switch style.

**Two non-obvious things the code handles (learned the hard way):**
1. *Adaption deduplicates identical prompts.* A constant localize instruction collapsed
   27 rows → 1, so the scenario text is **embedded in each prompt** to keep them unique.
2. *Gemini/Adaption can echo the prompt.* `build_dataset` strips any `**enhanced_prompt**`
   preamble defensively.

**Run it:**
```bash
python src/gen_adaption.py enhance estimate   # free quote
python src/gen_adaption.py enhance pilot      # 6 rows to eyeball
python src/gen_adaption.py enhance full       # writes enhance_raw.csv
python src/gen_adaption.py localize full      # writes localize_raw.csv
```

---

## Stage 2 — Assemble the final wide dataset

**File:** [`src/build_dataset.py`](../src/build_dataset.py)

**Logic:** join the 27 generated rows by `base_id`:
- `enhanced_prompt` = the authored analysis prompt (guaranteed to quote `scenario_en`);
- `enhanced_completion` = Adaption's analysis (after `_clean_completion` strips echoes);
- `scenario_vi` / `scenario_cs` = parsed from the localize JSON (`_parse_localize_json`).

Then append the 3 gold rows and write **`dataset_30.csv`** (+ `.jsonl`) in the exact
8-column order: `scenario_en, gold_label, enhanced_prompt, enhanced_completion,
base_id, domain, scenario_cs, scenario_vi`. See [DATASET.md](DATASET.md).

---

## Stage 3 — Quality gates (fail loud before trusting anything)

**Files:** [`src/validate.py`](../src/validate.py),
[`src/diversity_gate.py`](../src/diversity_gate.py)

`validate.py` — **hard** checks raise a non-zero exit:
- 30 rows, unique `base_id`, 20 suspicious / 10 benign, no empty cells,
- `enhanced_prompt` actually quotes its `scenario_en`,
- language sanity: VI is Vietnamese with low English ratio; CS mixes English tech
  tokens + Vietnamese function words; EN looks English.
- **soft** checks (warnings only, written to `results/validation_warnings.csv`):
  does the VI/CS keep a risk word for suspicious rows / avoid violation verbs for benign.

`diversity_gate.py`:
- embeds each language column and flags any pair with cosine similarity > **0.85**
  (near-duplicates → `results/regenerate_list.csv`);
- re-asserts coverage (≥14 vectors, ≥8 flows, no app > 40%).
- Exits non-zero if duplicates or coverage gaps remain, so an orchestrator could
  regenerate the flagged rows and re-gate.

---

## Stage 4 — Audit the monitors (Gemini) and score them

**Files:** [`src/monitors.py`](../src/monitors.py),
[`src/run_monitors.py`](../src/run_monitors.py),
[`src/evaluate.py`](../src/evaluate.py)

**`run_monitors.py` logic:**
1. `melt()` turns the wide 30-row dataset into **90 language-rows**
   `(base_id, language ∈ {EN,VI,CS}, scenario_text, gold_label, domain)`.
2. For each row × each of 3 monitors → a verdict. That's **270 verdicts**.
   - `baseline` — English-only judge (1 LLM call).
   - `locale_aware` — same judge + the slang glossary and a warning (1 call).
   - `translate_then` — translate the text to English, then run baseline (2 calls).
   - ⇒ 90×(1+1+2) = **360 Gemini calls**.
3. Calls run through a **thread pool** (`--workers`, default 8) with retry/backoff in
   `utils.gemini_complete`; verdicts use Gemini **JSON mode** so parsing is clean.
4. Writes `results/monitor_outputs.csv` (one row per verdict).

**`evaluate.py` logic:** join the attack vector from `scenarios_spec.csv`, then compute
per monitor × language:
- **accuracy** (verdict matches gold), **FNR** (suspicious wrongly called benign — the
  dangerous miss), **FPR**, uncertainty;
- the **accuracy gap vs English** (the headline);
- breakdowns by sub-domain and by attack vector;
- `worst_fnr.csv` — suspicious cases caught in EN but missed in VI/CS.

It prints the accuracy table + gap, and writes `metrics_summary.csv`, `gaps.csv`,
`domain_metrics.csv`, `vector_metrics.csv`, `worst_fnr.csv`.

**Run it:**
```bash
python src/run_monitors.py --workers 10     # real Gemini, ~2 min
python src/evaluate.py                       # prints table + writes metrics
# or: python src/run_monitors.py --mock      # no API key, deterministic stand-in
```

---

## One-shot

`./run_all.sh` chains Stage 0 → estimates → (with `RUN_FULL=1`) full generation +
assemble + gates → monitors → evaluate. `MONITOR_MOCK=1` skips live monitor calls.
