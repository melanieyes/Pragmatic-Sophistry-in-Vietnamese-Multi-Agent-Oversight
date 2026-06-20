# Report outline — Lost in Translation, Lost in Control

1. **Main claim / headline**
   - AI safety monitors that reliably catch risky banking-agent behaviour in English degrade
     when the same behaviour is expressed in Vietnamese (VI) or Vietnamese-English code-switch (CS).
   - Headline numbers: FNR(VI) − FNR(EN) and FNR(CS) − FNR(EN) per monitor.

2. **Why it matters**
   - Vietnam is e-wallet / QR-first; banking is the highest-stakes AI-safety surface.
   - A monitor blind spot in the local language = real fraud exposure for Global-South deployments.

3. **Dataset setup**
   - 30 base scenarios (third-person agent-behaviour statements) × {EN, VI, CS} = 90 language-rows.
   - 10 benign / 20 suspicious; ≥14 attack vectors; 4 banking sub-domains.
   - Built deterministically (labels + diversity) and expanded with Adaption (enhanced analysis +
     localization). 3 hand-authored gold rows + 27 generated.
   - Diversity gate: semantic dedup (cosine ≤ 0.85) + coverage asserts.

4. **Monitor setup**
   - baseline (EN-only), locale_aware (glossary + warning), translate_then (translate → judge).
   - 90 rows × 3 monitors = 270 verdicts.

5. **Results**
   - metrics_summary: accuracy / FNR / FPR / uncertainty per monitor × language.
   - VI−EN and CS−EN gaps (the headline).
   - Per-domain and per-attack-vector failure: which attack types evade monitors most under VI/CS.
   - Does locale_aware / translate_then close the gap?

6. **Qualitative failures**
   - worst_fnr.csv: caught in EN, missed in VI/CS — walk through 2–3 illustrative cases.

7. **Limitations**
   - 30 base scenarios; single judge model; synthetic (not real-traffic) prompts; CS is modelled.

8. **Conclusion**
   - Implication for deploying banking AI + monitors in non-English / Global-South markets.
