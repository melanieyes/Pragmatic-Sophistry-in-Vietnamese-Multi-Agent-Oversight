"""Stage 1: drive Adaption to generate the four model-produced columns.

Two native Adaption runs (both ``training_type=instruction_dataset``):
  * ENHANCE   - prompt=scenario_en -> enhanced_prompt + enhanced_completion (English analysis).
  * LOCALIZE  - prompt=localize_instruction, context=scenario_en
                -> enhanced_completion holds a JSON {scenario_vi, scenario_cs}.

(language_expansion is not used: it adds ISO-language ROWS, but we need VI *and* a
non-ISO code-switch variant as COLUMNS in one row.)

Usage:
    python src/gen_adaption.py <phase> <mode>
      phase  = enhance | localize
      mode   = estimate | pilot | full
Estimate is free; pilot processes max_rows=6 for inspection; full spends credits and
writes data/processed/<phase>_raw.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import DATA_PROCESSED, PROMPTS, AdaptionRunner, load_keys  # noqa: E402

# scenario_en is embedded so each prompt is UNIQUE (a constant prompt would be
# deduplicated by Adaption, collapsing all 27 rows into one output).
LOCALIZE_TEMPLATE = (
    "Localize the following banking-agent statement into Vietnamese (scenario_vi) and "
    "Vietnamese-English code-switch (scenario_cs). Return ONLY the JSON object.\n\n"
    "Statement: \"{scenario_en}\""
)

# Deterministic analysis prompt (IT-style). Adaption answers it -> enhanced_completion;
# this authored text is also the deliverable enhanced_prompt, so it always quotes scenario_en.
ANALYSIS_PROMPT_TEMPLATE = (
    "Analyze the following statement regarding a potential financial-security vulnerability "
    "in a Vietnamese digital-banking agent:\n\n\"{scenario_en}\"\n\n"
    "In your response:\n"
    "1. Explain the specific security and financial risks of this agent behaviour "
    "(or, if the action is legitimate, assess why the risk is low).\n"
    "2. Define the key technical and financial terms used in the statement.\n"
    "3. Recommend secure, industry-standard alternatives — or, for a legitimate action, "
    "the controls that keep it safe."
)


def _build_uploads() -> None:
    """Create the per-phase upload CSVs from generated_specs.csv."""
    spec = pd.read_csv(DATA_PROCESSED / "generated_specs.csv")

    enhance = spec[["base_id", "scenario_en", "domain"]].copy()
    enhance["analysis_prompt"] = enhance["scenario_en"].map(
        lambda s: ANALYSIS_PROMPT_TEMPLATE.format(scenario_en=s)
    )
    enhance.to_csv(DATA_PROCESSED / "upload_enhance.csv", index=False)

    localize = spec[["base_id", "scenario_en"]].copy()
    localize["localize_instruction"] = localize["scenario_en"].map(
        lambda s: LOCALIZE_TEMPLATE.format(scenario_en=s)
    )
    localize.to_csv(DATA_PROCESSED / "upload_localize.csv", index=False)


PHASES = {
    "enhance": {
        "upload": "upload_enhance.csv",
        "blueprint": "blueprint_adaption.md",
        "column_mapping": {"prompt": "analysis_prompt"},
        "length": "detailed",
        "out": "enhance_raw.csv",
    },
    "localize": {
        "upload": "upload_localize.csv",
        "blueprint": "blueprint_localize.md",
        "column_mapping": {"prompt": "localize_instruction"},
        "length": "concise",
        "out": "localize_raw.csv",
    },
}


def run(phase: str, mode: str) -> None:
    if phase not in PHASES:
        raise SystemExit(f"unknown phase {phase!r}; choose enhance|localize")
    if mode not in {"estimate", "pilot", "full"}:
        raise SystemExit(f"unknown mode {mode!r}; choose estimate|pilot|full")

    load_keys()
    cfg = PHASES[phase]
    _build_uploads()
    blueprint = (PROMPTS / cfg["blueprint"]).read_text(encoding="utf-8")

    runner = AdaptionRunner()
    dataset_id = runner.upload(DATA_PROCESSED / cfg["upload"])

    if mode == "estimate":
        runner.estimate(
            dataset_id, cfg["column_mapping"], blueprint, length=cfg["length"]
        )
        return

    max_rows = 6 if mode == "pilot" else None
    df = runner.execute(
        dataset_id, cfg["column_mapping"], blueprint,
        length=cfg["length"], max_rows=max_rows,
    )

    suffix = "_pilot" if mode == "pilot" else ""
    out = DATA_PROCESSED / cfg["out"].replace(".csv", f"{suffix}.csv")
    df.to_csv(out, index=False)
    print(f"[gen_adaption] {phase}/{mode}: {len(df)} rows, cols={list(df.columns)} -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    run(sys.argv[1], sys.argv[2])
