# Dataset — `data/processed/dataset_30.csv`

The deliverable: **30 base scenarios × {EN, VI, CS}**, stored **wide** (one row per
base scenario, the three languages as columns). 20 suspicious / 10 benign.

## Columns (exact order)

| # | Column | Source | Meaning |
|---|---|---|---|
| 1 | `scenario_en` | authored in code | Third-person English statement of an agent behaviour (the thing being judged). |
| 2 | `gold_label` | authored | `benign` or `suspicious` — ground truth. |
| 3 | `enhanced_prompt` | authored template | "Analyze the following statement… 1/2/3" wrapping `scenario_en`. |
| 4 | `enhanced_completion` | **Adaption LLM** | Expert security analysis answering the prompt. |
| 5 | `base_id` | authored | `<domain-prefix>-NNN`, e.g. `pay-001`, `kyc-003`. Gold rows use `-900`. |
| 6 | `domain` | authored | Banking sub-domain (see below). |
| 7 | `scenario_cs` | **Adaption LLM** | Vietnamese-English code-switch rendering of `scenario_en`. |
| 8 | `scenario_vi` | **Adaption LLM** | Natural Vietnamese rendering of `scenario_en`. |

Only columns 4, 7, 8 are model-written; everything else is fixed in code (integrity rule).

A long, melted view (90 rows: one per language) is produced in-memory by
`run_monitors.melt()` for evaluation — the file on disk stays wide.

## Sub-domains (`domain`) and `base_id` prefixes

| domain | prefix | example vectors |
|---|---|---|
| `payments_transfer` | `pay` | unauthorized_transfer, beneficiary_swap, transfer_limit_override |
| `lending_credit` | `lend` | fraudulent_credit_approval, fee_interest_waiver, insider_collusion |
| `account_wallet_ops` | `acct` | account_takeover_recovery, dormant_account_drain, data_exfiltration |
| `kyc_card_qr` | `kyc` | mfa_otp_bypass, qr_payment_fraud, identity_impersonation, card_issuance_fraud |

## Diversity guarantees (enforced by `assert_coverage`)

- 20 suspicious / 10 benign.
- **≥14 distinct attack vectors** among the suspicious rows (actual: 18).
- **≥8 distinct banking flows** on each side.
- Every `(attack_vector, banking_flow)` pair is **unique**.
- No single app is more than **40%** of rows (actual max ≈ 17%).

The internal sidecar `data/processed/scenarios_spec.csv` records `attack_vector,
banking_flow, app, amount_band` per `base_id` — used for per-vector metrics but **not**
part of the 8-column deliverable.

## Gold rows (`*-900`)

Three rows are hand-authored end-to-end (`data/raw/gold_scenarios.yaml`) as a format
reference: `kyc-900` (OTP bypass), `lend-900` (VIP-friend loan), `acct-900` (benign
history lookup). Their `(vector, flow)` tuples are reserved so the generated pool never
duplicates them.

## How to regenerate

```bash
python src/build_specs.py          # rebuild specs (deterministic)
python src/gen_adaption.py enhance full
python src/gen_adaption.py localize full
python src/build_dataset.py        # → dataset_30.csv (+ .jsonl)
python src/validate.py && python src/diversity_gate.py
```

## Known limitations

- 30 base scenarios (small, by design — diversity over volume).
- Synthetic, not production traffic; CS is a modelled register.
- VI/CS quality is bounded by the generation step; `validate.py` language checks and the
  `diversity_gate` catch gross failures, not subtle mistranslations.
