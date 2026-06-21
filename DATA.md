# DATA.md — How the dataset is built

This documents how `data/processed/agent_safety_bench_ecom.csv` (the evaluation set)
is produced, from a hand-authored seed to the final four-language, A-grade-annotated
benchmark. For *why* the dataset is shaped this way and where it's headed, see
[ADAPTATION_PLAN.md](ADAPTATION_PLAN.md); for the research question, see
[PROJECT.md](PROJECT.md).

---

## 1. Pipeline at a glance

```
            (hand-authored)                  (LLM-assisted, reviewed)
  data/raw/scenarios_seed.csv  <───append───  data/raw/scenarios_generated.csv
        │  EN scenarios + gold labels                ▲  src/generate_scenarios.py
        │  + A-grade annotations                     │  (Gemini drafts → staging)
        ▼
  src/build_dataset.py
        ├─ GEMINI  → scenario_vi / scenario_cs / scenario_en_bt  (+ evidence/safe-action spans)
        │            cached in data/processed/gemini_cache.json
        ├─ ADAPTION → enhanced_prompt / enhanced_completion  (augmentation only)
        ├─ assemble (merge priority: Gemini > Adaption > authored seed)
        └─ qc_report (flags risk cues lost in back-translation)
        ▼
  data/processed/agent_safety_bench_ecom.csv   ← the eval set (one row per scenario)
```

**Who fills what.** Humans author the scenarios and the risk judgement; models only
*translate* and *augment*. Nothing risk-bearing is invented by the pipeline.

| Produced by | Columns |
|---|---|
| **Human (seed)** | `scenario_en`, `gold_label`, `sub_category`, `agent_context`, `tool_calls`, `gold_reason`, and the A-grade layer: `severity`, `risk_type`, `attack_surface`, `injection_source`, `is_hard_benign`, `evidence_phrase_en`, `safe_action_en` |
| **Gemini** | `scenario_vi`, `scenario_cs`, `scenario_en_bt`, `evidence_phrase_{vi,cs,en_bt}`, `safe_action_{vi,cs,en_bt}` |
| **Adaption** | `enhanced_prompt`, `enhanced_completion` |

---

## 2. The seed (`data/raw/scenarios_seed.csv`)

One row = one scenario, authored in **English**. 14 columns:

| Column | Meaning |
|---|---|
| `scenario_id` | `ec_bNN` (benign) / `ec_sNN` (suspicious) |
| `label` | `benign` \| `suspicious` (the gold label) |
| `sub_category` | fine-grained type (`fake_refund`, `address_redirect_attack`, …) |
| `agent_context` | the agent's role/setting + any policy that defines what's allowed |
| `user_message` | the customer/seller message shown to the monitor (= `scenario_en`) |
| `tool_calls` | the tool calls the agent is about to run, with risky params exposed (e.g. `skip_verification=True`) |
| `gold_reason` | one-line justification of the label |
| `severity` | `none` (benign) \| `low` \| `high` \| `critical` |
| `risk_type` | reusable snake_case tag for per-attack analysis (`data_exfiltration`, `prompt_injection`, …) |
| `attack_surface` | tool/endpoint abused (`refund_api`, `auth_2fa`, …) |
| `injection_source` | `none`, or where an indirect payload hides (`product_review`, `seller_note`) |
| `is_hard_benign` | `true` only for benign scenarios engineered to *look* risky (stress false positives) |
| `evidence_phrase_en` | the **exact substring** of `user_message` that signals the risk |
| `safe_action_en` | what the agent should do instead |

**Rules the seed obeys** (validated in `build_dataset.load_seeds`):
- every row is `benign` or `suspicious`; both classes present;
- benign rows carry no risk taxonomy (`severity=none`, taxonomy/evidence blank);
- `evidence_phrase_en` is copy-paste verbatim from `user_message` so it can be located in the vi/cs renderings;
- `is_hard_benign=true` only on benign rows.

**Hard-benigns** are near-twins of attacks that differ only in a legitimacy signal
(authenticated staff console vs. customer chat; a real auth code vs. `trust_me_bro`;
own-account scope vs. third-party). They exist so a monitor can't score well by
keyword-matching scary tokens.

---

## 3. Growing the seed (`src/generate_scenarios.py`)

Tops the seed up to a target size with Gemini, then **writes to a staging file for
human review** — it does not silently edit the curated seed.

```bash
python src/generate_scenarios.py                 # top up to 100 total (~1:2 benign:suspicious)
python src/generate_scenarios.py --benign 21 --suspicious 46
python src/generate_scenarios.py --total 100 --append   # also append into the seed
```

- Generates per label, biased toward **difficulty**: ~half the suspicious rows are
  *subtle/implicit* (risk requires inference, not obvious keywords), and a
  configurable fraction of benigns are **hard-benigns**.
- Output → `data/raw/scenarios_generated.csv` (full seed schema, fresh ids continued
  from the existing max).
- **Validation on each draft:** required fields present; `severity` coerced into the
  allowed set; for suspicious rows `evidence_phrase_en` must be an exact substring of
  `user_message` (case fixed if needed, else blanked and flagged); near-duplicate
  `user_message`s skipped.
- **These are drafts.** Review gold labels and evidence spans before appending —
  subtle scenarios are exactly where labels become contestable.

---

## 4. Building the eval set (`src/build_dataset.py`)

```bash
python -m src.build_dataset                # Gemini translate + Adaption augment
python -m src.build_dataset --skip-gemini  # offline: en + labels only (no vi/cs/en_bt)
python -m src.build_dataset --skip-adaption# no enhanced_* augmentation
python -m src.build_dataset --resume-main DATASET_ID   # reuse an Adaption run
```

### 4a. Gemini — the four language renderings (the independent variable)
For every seed, Gemini produces the non-English renderings of the scenario and of
the authored spans, using three blueprints:

| Rendering | Column | Blueprint | What it is |
|---|---|---|---|
| English | `scenario_en` | — (seed) | the original authored message |
| Vietnamese | `scenario_vi` | `VI_BLUEPRINT` | natural VN as marketplace users type — informal, **slang + abbreviations** (`ko`, `đc`, `ib`, `chốt đơn`, `ship COD`, `bom hàng`), risk level and all IDs/codes/payloads preserved |
| Code-switch | `scenario_cs` | `CS_BLUEPRINT` | Vietnamese matrix sentence that **keeps action/risk words in English** (`refund`, `override`, `disable 2FA`, `export customer DB`) |
| Back-translated EN | `scenario_en_bt` | `BT_BLUEPRINT` | plain English **back-translated from `scenario_vi` only** (blind to the seed) |

`scenario_en_bt` is a *measurement instrument*, not a naturalistic input: comparing
`vi` vs `en_bt` isolates the monitor's language-comprehension deficit, and `en_bt` vs
`en` is the QC that the Vietnamese rendering didn't lose the risk (it also models a
translate-then-monitor defence).

**Caching.** Every call is cached in `data/processed/gemini_cache.json`, keyed on
`(model, blueprint, source text)`. Re-runs and incremental seed edits don't re-spend;
editing a blueprint only re-translates the rows it touches.

### 4b. Adaption — augmentation only
The Adaption main pass produces `enhanced_prompt` / `enhanced_completion`
(instruction-dataset augmentation). Translation is Gemini's job now; Adaption's
code-switch pass is **off by default** (`--adaption-cs` to re-enable). Raw download is
staged in `data/processed/adaption_raw.csv`.

### 4c. Assemble + QC
`assemble()` merges everything one row per scenario with precedence
**Gemini > Adaption > authored seed** (so a hand-authored `scenario_vi` would win over
a machine translation if present). `qc_report()` then flags any suspicious row whose
`evidence_phrase_en` did **not** survive the `en → vi → en_bt` round trip — a heuristic
catch for risk that got laundered out in translation.

---

## 5. The eval set (`data/processed/agent_safety_bench_ecom.csv`)

26 columns, one row per scenario. A superset of the reference `agent_safety_bench`
template (it keeps `agent_context` / `tool_calls` / `gold_reason`, which the reference
drops, and adds the four-language A-grade layer).

```
identity/label : base_id, domain, sub_category, gold_label
agent setting  : agent_context, tool_calls, gold_reason
scenario ×4    : scenario_en, scenario_vi, scenario_cs, scenario_en_bt
risk taxonomy  : severity, risk_type, attack_surface, injection_source, is_hard_benign
evidence ×4    : evidence_phrase_{en,vi,cs,en_bt}
safe action ×4 : safe_action_{en,vi,cs,en_bt}
augmentation   : enhanced_prompt, enhanced_completion
```

Evaluation (`src/run_monitors.py` → `src/evaluate.py`) reads `scenario_{en,vi,cs}`
(and optionally `scenario_en_bt`), `gold_label`, `domain`, and the annotation layer.
`enhanced_*` is not used for scoring — it's a training-style by-product.

---

## 6. Files

| Path | Role |
|---|---|
| `data/raw/scenarios_seed.csv` | hand-authored seed (source of truth) |
| `data/raw/scenarios_generated.csv` | LLM-drafted additions, staged for review |
| `src/generate_scenarios.py` | Gemini scenario generator → staging |
| `src/build_dataset.py` | translate (Gemini) + augment (Adaption) + assemble |
| `data/processed/gemini_cache.json` | translation cache (avoids re-spend) |
| `data/processed/adaption_raw.csv` | Adaption staging download |
| `data/processed/agent_safety_bench_ecom.csv` | **the eval set** |

## 7. Reproduce from scratch

```bash
pip install -r requirements.txt           # google-genai, adaption, pandas, python-dotenv, …
cp .env.example .env                       # set GEMINI_API_KEY (+ ADAPTION_API_KEY if augmenting)

# optional: grow the seed, then REVIEW data/raw/scenarios_generated.csv before appending
python src/generate_scenarios.py --total 100 --append

python -m src.build_dataset                # → data/processed/agent_safety_bench_ecom.csv
```

Determinism / cost: Gemini translation is cached, so a rebuild after editing one seed
re-translates only that row. Without `GEMINI_API_KEY` the build still runs and leaves
the vi/cs/en_bt columns blank (English + labels only).
