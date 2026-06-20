# Lost in Translation, Lost in Control

A static interactive audit of whether AI safety monitors miss risky tool-use behavior in Vietnamese, Vietnamese-English code-switching, and local institutional contexts.

## Project

Most AI safety monitor and prompt-injection evaluations are English-heavy. This project asks whether monitor reliability changes when the same risky tool-use behavior is expressed in Vietnamese, code-switched Vietnamese-English, or Vietnam-specific institutional language.

We test three monitor setups:

1. Baseline monitor
2. Locale-aware monitor
3. Translate-then-monitor

The target dataset contains 90 base scenarios. Each scenario appears in English, Vietnamese, and Vietnamese-English code-switching, giving 270 evaluated examples.

## Repo Structure

- `demo/` contains the static HTML demo.
- `data/` contains raw and processed datasets.
- `prompts/` contains monitor prompts.
- `src/` contains the dataset, evaluation, and export scripts.
- `results/` contains monitor outputs and metrics.
- `report/` contains the final writeup.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
