"""Stage 2: assemble the final wide 30-row dataset.

Merges:
  * scenarios_spec.csv      - 30 ground-truth rows (sidecar diversity record),
  * enhance_raw.csv         - Adaption enhanced_prompt + enhanced_completion (27 generated),
  * localize_raw.csv        - Adaption JSON {scenario_vi, scenario_cs} (27 generated),
  * gold_scenarios.yaml     - 3 fully hand-authored rows.

Output: data/processed/dataset_30.csv (+ .jsonl) in the authoritative 8-column order:
    scenario_en, gold_label, enhanced_prompt, enhanced_completion,
    base_id, domain, scenario_cs, scenario_vi
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import DATA_PROCESSED, DATA_RAW, read_yaml  # noqa: E402

FINAL_COLS = [
    "scenario_en", "gold_label", "enhanced_prompt", "enhanced_completion",
    "base_id", "domain", "scenario_cs", "scenario_vi",
]


def _pick_col(df: pd.DataFrame, *candidates: str) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


def _join_to_specs(spec: pd.DataFrame, raw: pd.DataFrame, label: str) -> pd.DataFrame:
    """Align an Adaption download to the 27 generated specs by base_id, text, or order."""
    bid = _pick_col(raw, "base_id")
    if bid:
        return spec.merge(raw, left_on="base_id", right_on=bid, how="left", suffixes=("", "_raw"))
    sen = _pick_col(raw, "scenario_en")
    if sen:
        raw = raw.copy()
        raw["_k"] = raw[sen].map(_norm)
        spec = spec.copy()
        spec["_k"] = spec["scenario_en"].map(_norm)
        return spec.merge(raw, on="_k", how="left", suffixes=("", "_raw")).drop(columns=["_k"])
    if len(raw) == len(spec):  # last resort: positional
        raw = raw.reset_index(drop=True)
        spec = spec.reset_index(drop=True)
        return pd.concat([spec, raw.add_prefix("raw_")], axis=1)
    raise SystemExit(f"cannot align {label} download to specs (rows {len(raw)} vs {len(spec)})")


def _clean_completion(text: str) -> str:
    """Strip any echoed '**enhanced_prompt** ... **enhanced_completion**' preamble.

    Defends against the model re-printing the prompt/field names despite the blueprint.
    """
    if not isinstance(text, str):
        return ""
    m = re.search(r"\*{0,2}enhanced[_\s]?completion\*{0,2}\s*:?\s*", text, flags=re.IGNORECASE)
    if m:
        return text[m.end():].strip()
    # If it opens by echoing the prompt header, drop up to the first numbered answer block.
    if re.match(r"\s*\*{0,2}enhanced[_\s]?prompt", text, flags=re.IGNORECASE):
        parts = re.split(r"\n\s*\n", text, maxsplit=1)
        return (parts[1].strip() if len(parts) > 1 else text).strip()
    return text.strip()


def _parse_localize_json(text: str) -> tuple[str, str]:
    """Extract scenario_vi / scenario_cs from a JSON-ish completion."""
    if not isinstance(text, str) or not text.strip():
        return "", ""
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    blob = m.group(0) if m else cleaned
    try:
        obj = json.loads(blob)
        return str(obj.get("scenario_vi", "")).strip(), str(obj.get("scenario_cs", "")).strip()
    except Exception:
        return "", ""


def _parse_generate_json(text: str) -> dict:
    """Extract the 4 v2 keys from the single-run JSON completion."""
    keys = ("enhanced_completion", "scenario_vi_literal", "scenario_vi", "scenario_cs")
    if not isinstance(text, str) or not text.strip():
        return {k: "" for k in keys}
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    blob = m.group(0) if m else cleaned
    try:
        obj = json.loads(blob)
        return {k: str(obj.get(k, "")).strip() for k in keys}
    except Exception:
        return {k: "" for k in keys}


def build_v2() -> None:
    """Assemble dataset_100.csv from the single Adaption `generate` run."""
    from gen_adaption import ANALYSIS_PROMPT_TEMPLATE  # authored enhanced_prompt

    spec = pd.read_csv(DATA_PROCESSED / "scenarios_spec_100.csv")
    raw = pd.read_csv(DATA_PROCESSED / "generate_raw.csv")

    gm = _join_to_specs(spec[["base_id", "scenario_en", "domain", "gold_label"]], raw, "generate")
    comp = _pick_col(raw, "enhanced_completion", "completion")
    if comp is None:
        raise SystemExit(f"generate output missing completion col: {list(raw.columns)}")
    parsed = gm[comp].map(_parse_generate_json)

    out = spec[["base_id", "scenario_en", "gold_label", "domain"]].copy()
    out["enhanced_prompt"] = out["scenario_en"].map(
        lambda s: ANALYSIS_PROMPT_TEMPLATE.format(scenario_en=s))
    out["enhanced_completion"] = [p["enhanced_completion"] for p in parsed]
    out["scenario_vi"] = [p["scenario_vi"] for p in parsed]
    out["scenario_cs"] = [p["scenario_cs"] for p in parsed]
    final = out[FINAL_COLS]

    csv_path = DATA_PROCESSED / "dataset_100.csv"
    jsonl_path = DATA_PROCESSED / "dataset_100.jsonl"
    final.to_csv(csv_path, index=False)
    final.to_json(jsonl_path, orient="records", lines=True, force_ascii=False)

    # Sidecar: difficulty (from spec) + faithful VI, for analysis — not in the 8-col deliverable.
    meta = spec[["base_id", "gold_label", "domain", "difficulty", "attack_vector"]].copy()
    meta["scenario_vi_literal"] = [p["scenario_vi_literal"] for p in parsed]
    meta.to_csv(DATA_PROCESSED / "dataset_100_meta.csv", index=False)

    print(f"[build_dataset] [v2] wrote {len(final)} rows -> {csv_path.name} + {jsonl_path.name} "
          f"(+ dataset_100_meta.csv)")


def load_gold() -> pd.DataFrame:
    gold = read_yaml(DATA_RAW / "gold_scenarios.yaml")
    rows = []
    for g in gold:
        rows.append(
            {
                "scenario_en": " ".join(g["scenario_en"].split()),
                "gold_label": g["gold_label"],
                "enhanced_prompt": g["enhanced_prompt"],
                "enhanced_completion": g["enhanced_completion"],
                "base_id": g["base_id"],
                "domain": g["domain"],
                "scenario_cs": " ".join(g["scenario_cs"].split()),
                "scenario_vi": " ".join(g["scenario_vi"].split()),
            }
        )
    return pd.DataFrame(rows)[FINAL_COLS]


def main() -> None:
    spec = pd.read_csv(DATA_PROCESSED / "scenarios_spec.csv")
    gen = spec[spec["source"] == "generated"].reset_index(drop=True)

    enhance = pd.read_csv(DATA_PROCESSED / "enhance_raw.csv")
    localize = pd.read_csv(DATA_PROCESSED / "localize_raw.csv")

    em = _join_to_specs(gen[["base_id", "scenario_en", "domain", "gold_label"]], enhance, "enhance")
    # Prefer the authored analysis_prompt (always quotes scenario_en) over Adaption's rephrase.
    ep = _pick_col(enhance, "analysis_prompt", "enhanced_prompt", "prompt")
    ec = _pick_col(enhance, "enhanced_completion", "completion")
    if ep is None or ec is None:
        raise SystemExit(f"enhance output missing prompt/completion cols: {list(enhance.columns)}")
    # Drop Adaption's auto-rephrased columns so the rename of the authored cols can't collide.
    drop = [c for c in ("enhanced_prompt", "enhanced_completion") if c in em.columns and c not in (ep, ec)]
    em = em.drop(columns=drop)
    em = em.rename(columns={ep: "enhanced_prompt", ec: "enhanced_completion"})
    em["enhanced_completion"] = em["enhanced_completion"].map(_clean_completion)

    lm = _join_to_specs(gen[["base_id", "scenario_en"]], localize, "localize")
    lc = _pick_col(localize, "enhanced_completion", "completion")
    if lc is None:
        raise SystemExit(f"localize output missing completion col: {list(localize.columns)}")
    vi_cs = lm[lc].map(_parse_localize_json)
    lm["scenario_vi"] = [t[0] for t in vi_cs]
    lm["scenario_cs"] = [t[1] for t in vi_cs]

    out = gen[["base_id", "scenario_en", "gold_label", "domain"]].copy()
    out = out.merge(em[["base_id", "enhanced_prompt", "enhanced_completion"]], on="base_id", how="left")
    out = out.merge(lm[["base_id", "scenario_vi", "scenario_cs"]], on="base_id", how="left")
    generated_df = out[FINAL_COLS]

    final = pd.concat([generated_df, load_gold()], ignore_index=True)[FINAL_COLS]

    csv_path = DATA_PROCESSED / "dataset_30.csv"
    jsonl_path = DATA_PROCESSED / "dataset_30.jsonl"
    final.to_csv(csv_path, index=False)
    final.to_json(jsonl_path, orient="records", lines=True, force_ascii=False)
    print(f"[build_dataset] wrote {len(final)} rows -> {csv_path.name} + {jsonl_path.name}")


if __name__ == "__main__":
    if "--version" in sys.argv and sys.argv[sys.argv.index("--version") + 1] == "v2":
        build_v2()
    else:
        main()
