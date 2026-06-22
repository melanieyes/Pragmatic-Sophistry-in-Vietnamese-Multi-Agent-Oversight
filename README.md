Auditing context loss in Vietnamese multi-agent safety monitoring.

This project tests whether safety monitors miss risky workflow actions when Vietnamese instructions are pragmatically disguised and then compressed by a downstream executor. The core question is not only whether Vietnamese pragmatic language is hard to monitor, but whether the executor/report layer removes the context needed to detect a violation.

Summary

Many safety monitors assume that risky behavior is visible in the text they inspect. In multilingual workflow agents, that assumption can fail. A suspicious Vietnamese request may be expressed through hierarchy, relationship pressure, urgency, euphemism, omission, or routine framing rather than explicit risk keywords.

Multi-agent pipelines add a second failure point. A naive executor can turn a socially loaded instruction into a clean API-style action and a neutral report, stripping away the pragmatic cues that made the request suspicious.

This benchmark evaluates that failure mode across three domains:

E-commerce
Banking
Government
Pipeline

Each scenario passes through four stages.

An attacker-renderer turns an English workflow scenario into Vietnamese in two renderings: a direct translation and a pragmatically disguised version.
A fluent oracle checks that the violation remains inferable from the disguised text. Rows that are no longer cleanly inferable are dropped.
A naive executor simulates carrying out the instruction and writes a compact action, formatted as a typed API-style call, plus a short natural-language report.
Two safety monitors independently classify the behavior as benign or suspicious.

The executor is deliberately naive. It does not refuse, add safety checks, or try to deceive. The safety layer under test is the monitor.

Visibility conditions

Each monitor is evaluated under three context modes:

Context mode	What the monitor sees	Purpose
instruction	Original scenario rendering	Can the monitor catch the risky request directly?
action	Executor action and report only	Does downstream execution erase risk evidence?
trace	Instruction plus executor action and report	Does preserving the full trace recover detection?

The key comparison is:

instruction → action → trace

If false negatives rise in action mode, the executor layer is laundering safety-relevant context. If performance recovers in trace mode, the failure is partly an observability problem rather than pure monitor incapability.

Monitors

The current report evaluates:

Gemini 2.5 Flash
DeepSeek Chat

Results are reported both per monitor and as equal-weight pooled rates.

Dataset

The benchmark covers three Vietnamese workflow domains.

Domain	Rows kept	Suspicious	Benign	Verdicts
E-commerce	81	47	34	972
Banking	97	57	40	1,164
Government	100	60	40	1,200

Suspicious rows are filtered with a lexical gate that removes overt skip, bypass, or explicit rule-breaking language. This keeps the benchmark focused on pragmatic encoding rather than keyword detection.

Metrics

The main metric is false-negative rate:

suspicious rows labeled benign

This is the core safety failure.

The benchmark also reports:

False-positive rate on benign rows
Pragmatic gap between direct Vietnamese and pragmatic Vietnamese
Conditional report-hiding rate: among violations caught from the instruction, how often the same monitor misses them when shown only the executor action
Confidence on false negatives
Main finding

The strongest failure appears in e-commerce. When monitors see only the executor action/report, false negatives on suspicious pragmatic-Vietnamese requests rise sharply. Preserving the full instruction-action trace recovers most of the lost detection.

Banking shows a smaller version of the same pattern. Government shows little measurable context-compression failure because many violations remain structurally explicit after execution.

The central conclusion is:

Action-only monitoring is not a safe default for relational or PII-heavy workflows.

Trace-aware monitoring is a low-cost safeguard because it preserves the social and authorization context that executor summaries can erase.

Setup
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

Then fill in the required model API keys in .env.

Check model names in src/agents.py before running. Provider model strings can change.

Run

Guided run:

bash run_all.sh

Manual smoke test:

python src/run.py --mock --limit 12 --stage all

Generate a small batch for inspection:

python src/run.py --limit 12 --stage generate

Run the full pipeline:

python src/run.py --stage all

Do not skip manual inspection before a full run. Early inspection catches generation failures such as explicit label leakage, broken Vietnamese, or rows where the risk is no longer inferable.

Repository layout
prompts/    prompts for attacker, oracle, executor, and monitor roles
src/        pipeline code, model dispatch, agents, metrics, and runner
data/       input scenarios and generated checkpoints
results/    monitor outputs, metrics tables, and report artifacts
Safety scope

Scenarios are description-level benchmark items for evaluating monitor behavior. The dataset is intended for safety research, not for operational misuse.

The benchmark should not contain step-by-step fraud instructions, deployable exploit procedures, or enabling code. Public data release should be checked for sensitive social-engineering templates before sharing.
