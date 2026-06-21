# Docs index — `banking` branch

Read in this order to understand the project logic:

1. **[PROJECT_UNDERSTANDING.md](PROJECT_UNDERSTANDING.md)** — what the project is, the
   research question, the core idea, and the design decisions (start here).
2. **[PIPELINE.md](PIPELINE.md)** — the code logic, stage by stage (Stage 0 author →
   Stage 1 Adaption → Stage 2 assemble → Stage 3 gates → Stage 4 monitor audit), with
   the exact files and functions for each step.
3. **[DATASET.md](DATASET.md)** — the deliverable dataset: column schema, sub-domains,
   diversity guarantees, gold rows, how to regenerate, limitations.
4. **[RESULTS.md](RESULTS.md)** — the monitor-audit numbers (Gemini), how to read them,
   and what actually went wrong.

See also the top-level [`README.md`](../README.md) for setup/run commands, and
[`report/final_report.md`](../report/final_report.md) for the narrative write-up.

## 30-second mental model

```
taxonomy + code  →  30 labelled scenarios (EN)        [Stage 0, deterministic]
   + Adaption     →  + analysis, + VI, + CS            [Stage 1, LLM text only]
   = dataset_30.csv (wide, 8 cols)                     [Stage 2]
   → validate + diversity_gate                         [Stage 3, fail loud]
   → 3 monitors × 90 language-rows via Gemini          [Stage 4]
   → accuracy per language + gap vs English            [evaluate]
```

Integrity rule throughout: **code owns labels & diversity; the LLM only writes prose.**
