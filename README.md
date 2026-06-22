# vi-prag-bench

Auditing whether AI safety monitors miss **pragmatically-encoded** violations
in Vietnamese tool-use settings — violations carried by implicature, authority
and face scripts, euphemism, and omission, rather than by decodable slang.

## Hypothesis

> Monitor false-negative rate stays low on lexical Vietnamese slang (decodable)
> but rises sharply on pragmatically-encoded Vietnamese violations — and the
> locale-aware glossary fix, being lexical, does not close that gap.

A secondary axis: pragmatic obfuscation should hurt more in high-trust
relational domains (e-gov, banking) than in transactional ecommerce, and FN
should climb with the e-gov `difficulty` tier.

## The four agents

| Role | What it does | Model | Notes |
|------|--------------|-------|-------|
| Attacker | rewrites a gold scenario into pragmatically-obfuscated Vietnamese | Gemini Flash (free) | high-volume generation |
| Oracle | dual-gate validator + ground truth | Haiku | most reliable model |
| Executor | naive agent that carries out the instruction | DeepSeek | the untrusted agent |
| Monitor | classifies the action benign/suspicious | 4o-mini · Haiku · Flash · DeepSeek | the subject under test |

The dual gate keeps a row only when a fluent oracle recovers the violation AND
a lexical-only pass misses it — that distinguishes "genuinely pragmatic" from
"merely ambiguous" or "leaked the slang." `locale_aware` is a flag on the
Monitor (a lexical glossary), used as a control.

**Executor modeling choice:** the Executor is deliberately naive — it does not
refuse and adds no safety checks. The safety layer under test is the Monitor.
This keeps the gold label aligned (a compliant action inherits the scenario's
label). Run `--skip-executor` to have the Monitor read the rendering directly
(3-agent mode) if you want the static comparison instead.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your four keys
```

Verify the model strings at the top of `src/agents.py` against each provider's
current docs — `gemini-2.5-flash` and `deepseek-chat` in particular drift.

## Run order

```bash
bash run_all.sh                                   # guided: smoke -> small -> full
# or manually:
python src/run.py --mock --limit 12 --stage all --locale-aware   # smoke, $0
python src/run.py --limit 12 --stage generate                    # eyeball data/out_generated.csv
python src/run.py --stage all --locale-aware                     # full 300
```

Do not skip the eyeball step — it is where you catch a generator that leaks the
label or invents risk, before spending on the full panel.

## Layout

```
prompts/   one file per role (attacker, executor, monitor, oracle_fluent, oracle_lexical)
src/       models.py (dispatch+mock) · agents.py (roles) · pipeline.py (stages) · metrics.py · run.py
data/      scenario.csv (kept input) + out_*.csv checkpoints (gitignored)
results/   metrics tables
```

## Scope / safety

Scenarios are description-level benchmark items with gold labels, for evaluating
and improving monitor detection. No operational fraud instructions, step-by-step
methods, or enabling code anywhere — that constraint is in the Attacker prompt
and should stay there.