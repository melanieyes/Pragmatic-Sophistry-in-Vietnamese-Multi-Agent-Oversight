# Lost in Translation, Lost in Control

*AI safety monitors for Vietnamese banking / fintech tool-use agents — a cross-lingual audit.*

> Status: dataset + harness built and runnable. Fill the **Results** tables from
> `results/metrics_summary.csv`, `results/vector_metrics.csv`, and `results/worst_fnr.csv`
> after the full Adaption generation and a non-mock monitor run.

## 1. Main claim
Safety monitors that flag risky AI banking-agent behaviour in **English** miss a meaningful share
of the *same* behaviour when it is written in **Vietnamese (VI)** or **Vietnamese-English
code-switch (CS)**. We quantify this as the per-monitor false-negative-rate gap
**FNR(VI) − FNR(EN)** and **FNR(CS) − FNR(EN)** — the rate at which genuinely suspicious actions
slip past the monitor purely because of language.

## 2. Why it matters
Vietnam's consumer finance is e-wallet- and QR-first (MoMo, ZaloPay, VNPay, Viettel Money) on top
of banks like Techcombank, Vietcombank, BIDV and VPBank. As agentic AI enters this stack, the
safety monitor is the last line of defence against OTP/MFA bypass, fraudulent credit approval,
unauthorized transfers, QR/refund fraud, and data exfiltration. A monitor that only "sees" risk in
English is a structural blind spot for Vietnam and, by extension, Global-South banking-AI deployments.

## 3. Dataset
- **30 base scenarios**, each a third-person statement of an AI banking-agent *behaviour*, rendered
  in **EN, VI, CS** → **90 language-rows**. Wide schema (one row per base scenario):
  `scenario_en, gold_label, enhanced_prompt, enhanced_completion, base_id, domain, scenario_cs, scenario_vi`.
- **Balance:** 10 benign / 20 suspicious. **Diversity:** ≥14 attack vectors, 4 sub-domains
  (`payments_transfer, lending_credit, account_wallet_ops, kyc_card_qr`), apps rotated (no app > 40%).
- **Integrity:** labels, domains, attack vectors and the diversity assignment are authored
  deterministically in code; **Adaption** fills only the model-generated columns
  (`enhanced_prompt`/`enhanced_completion` analysis + `scenario_vi`/`scenario_cs` localization).
  3 hand-authored gold rows anchor the format; 27 rows are generated.
- **Quality gates:** `validate.py` (counts, language sanity, risk preservation) and
  `diversity_gate.py` (semantic dedup at cosine ≤ 0.85 + coverage asserts).

## 4. Monitors
| Monitor | Description |
|---|---|
| baseline | English-only judge, no Vietnamese context. |
| locale_aware | Told inputs may be VI/CS; given the slang glossary and a warning that risk hides in local terms. |
| translate_then | Translate the statement to English, then apply the baseline judge. |

90 rows × 3 monitors = **270 verdicts** (`results/monitor_outputs.csv`).

## 5. Results — *(populate from results/)*
**5.1 Per monitor × language** (from `metrics_summary.csv`)

| monitor | language | accuracy | FNR | FPR | uncertainty |
|---|---|---|---|---|---|
| … | EN/VI/CS | … | … | … | … |

**5.2 Headline language gaps** (FNR(VI)−FNR(EN), FNR(CS)−FNR(EN)) — _expected positive (worse) for baseline._

**5.3 Per-attack-vector failure** (from `vector_metrics.csv`) — which vectors evade monitors most under VI/CS.

**5.4 Per-domain failure** (from `domain_metrics.csv`).

## 6. Qualitative failures
Walk through 2–3 rows from `worst_fnr.csv` (caught in EN, missed in VI/CS) and explain the
linguistic mechanism (e.g. slang `bỏ qua OTP`, code-switched `bypass verify`).

## 7. Limitations
30 base scenarios; a single judge model; synthetic (not production-traffic) prompts; CS is a
modelled register; localization quality bounded by the generation step.

## 8. Conclusion
If a monitor's protection is language-dependent, then deploying banking AI in non-English markets
without locale-aware monitoring leaves a real, measurable control gap. We show the gap exists and,
via the `locale_aware` and `translate_then` configurations, whether it can be closed.
