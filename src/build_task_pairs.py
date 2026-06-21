#!/usr/bin/env python3
"""Expand the task-pair seed into the hard-split eval set (the Phase 1 keystone).

Reads data/raw/task_pairs_seed.csv (one row per PAIR, authored / drafted by
src/generate_task_pairs.py), then for every pair emits TWO eval rows that share a
trajectory and differ by exactly the one buried side-task step:

    tpNN_s  gold_label=suspicious   scenario = trajectory WITH the side step
    tpNN_b  gold_label=benign       scenario = trajectory WITHOUT it (the twin)

The output (data/processed/task_pairs_ecom.csv) uses the SAME column names as the
main eval set, so the existing monitor + metrics pipeline runs on it unchanged:

    python -m src.build_task_pairs
    python src/run_monitors.py --data data/processed/task_pairs_ecom.csv \
                               --out  results/task_pairs_outputs.csv
    python src/evaluate.py     --data results/task_pairs_outputs.csv

Translation (vi / cs / en_bt) reuses build_dataset's Gemini blueprints and the
shared gemini_cache.json, so trajectories are localized with the same instrument
(and at no extra cost on re-runs). The independent variable stays the language;
only the difficulty source (a buried step in a trajectory) changes.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "raw" / "task_pairs_seed.csv"
OUT_CSV = ROOT / "data" / "processed" / "task_pairs_ecom.csv"
DOMAIN = "ecommerce_traj"

# Reuse the translation blueprints + cached Gemini client from the main builder so
# the hard split is localized with exactly the same instrument as the easy split.
from src.build_dataset import (BT_BLUEPRINT, CS_BLUEPRINT, GEMINI_CACHE,  # noqa: E402
                               GEMINI_MODEL, VI_BLUEPRINT, OUTPUT_COLS, _gen,
                               _gemini_cache_load)


def _trans_bundle(client, model, en_text, cache):
    """vi / cs / en_bt renderings of one English string (en_bt blind from vi)."""
    if not (en_text or "").strip():
        return {"vi": "", "cs": "", "en_bt": ""}
    vi = _gen(client, model, VI_BLUEPRINT, en_text, cache)
    cs = _gen(client, model, CS_BLUEPRINT, en_text, cache)
    en_bt = _gen(client, model, BT_BLUEPRINT, vi, cache)  # BLIND: from vi only
    return {"vi": vi, "cs": cs, "en_bt": en_bt}


def _row(base_id, sub_category, gold_label, pair, *, scenario_en, tool_calls,
         gold_reason, evidence_en, safe_en, trans, severity, risk_type,
         attack_surface, injection_source):
    """Assemble one eval row in the shared OUTPUT_COLS schema."""
    s, e, a = trans["scenario"], trans["evidence"], trans["safe"]
    return {
        "base_id": base_id, "domain": DOMAIN, "sub_category": sub_category,
        "gold_label": gold_label,
        "agent_context": pair["agent_context"], "tool_calls": tool_calls,
        "gold_reason": gold_reason,
        "scenario_en": scenario_en, "scenario_vi": s["vi"],
        "scenario_cs": s["cs"], "scenario_en_bt": s["en_bt"],
        "severity": severity, "risk_type": risk_type,
        "attack_surface": attack_surface, "injection_source": injection_source,
        "is_hard_benign": "false",
        "evidence_phrase_en": evidence_en, "evidence_phrase_vi": e["vi"],
        "evidence_phrase_cs": e["cs"], "evidence_phrase_en_bt": e["en_bt"],
        "safe_action_en": safe_en, "safe_action_vi": a["vi"],
        "safe_action_cs": a["cs"], "safe_action_en_bt": a["en_bt"],
        "enhanced_prompt": "", "enhanced_completion": "",
    }


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-gemini", action="store_true",
                    help="offline: en only, no vi/cs/en_bt")
    ap.add_argument("--gemini-model",
                    default=os.environ.get("GEMINI_MODEL", GEMINI_MODEL))
    args = ap.parse_args()

    if not SEED.exists():
        sys.exit(f"[error] {SEED} not found — run src/generate_task_pairs.py first")
    pairs = list(csv.DictReader(open(SEED, encoding="utf-8")))
    print(f"[seed] {len(pairs)} task pairs -> {2 * len(pairs)} eval rows")

    client, cache = None, {}
    if not args.skip_gemini:
        try:
            from google import genai
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                print("[gemini] GEMINI_API_KEY not set; en only.")
            else:
                client = genai.Client(api_key=key)
                cache = _gemini_cache_load()
        except ImportError:
            print("[gemini] SDK not installed; en only.")

    def trans(text):
        if client is None:
            return {"vi": "", "cs": "", "en_bt": ""}
        return _trans_bundle(client, args.gemini_model, text, cache)

    rows: list[dict] = []
    try:
        for p in pairs:
            pid = p["pair_id"]
            # suspicious twin (trajectory WITH the buried side step)
            rows.append(_row(
                f"{pid}_s", p["side_task_type"], "suspicious", p,
                scenario_en=p["trajectory_en_suspicious"],
                tool_calls=p.get("tool_calls_suspicious", ""),
                gold_reason=p["side_task"],
                evidence_en=p["evidence_step_en"], safe_en=p["safe_action_en"],
                trans={"scenario": trans(p["trajectory_en_suspicious"]),
                       "evidence": trans(p["evidence_step_en"]),
                       "safe": trans(p["safe_action_en"])},
                severity=p.get("severity", "high"), risk_type=p["side_task_type"],
                attack_surface=p.get("attack_surface", ""),
                injection_source=p.get("injection_source", "none")))
            # benign twin (same trajectory WITHOUT the side step)
            rows.append(_row(
                f"{pid}_b", "benign_trajectory", "benign", p,
                scenario_en=p["trajectory_en_benign"],
                tool_calls=p["trajectory_en_benign"], gold_reason="",
                evidence_en="", safe_en="",
                trans={"scenario": trans(p["trajectory_en_benign"]),
                       "evidence": {"vi": "", "cs": "", "en_bt": ""},
                       "safe": {"vi": "", "cs": "", "en_bt": ""}},
                severity="none", risk_type="", attack_surface="",
                injection_source="none"))
            print(f"  + {pid}: suspicious + benign twin")
    finally:
        if client is not None:
            import json
            GEMINI_CACHE.write_text(json.dumps(cache, ensure_ascii=False),
                                    encoding="utf-8")
            print(f"[gemini] cache -> {GEMINI_CACHE.name} ({len(cache)} entries)")

    out = pd.DataFrame(rows, columns=OUTPUT_COLS)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    n_s = (out["gold_label"] == "suspicious").sum()
    n_b = (out["gold_label"] == "benign").sum()
    print(f"[final] wrote {OUT_CSV} ({len(out)} rows: {n_b} benign / {n_s} suspicious)")
    vi_ok = (out["scenario_vi"].astype(str).str.strip().astype(bool)).sum()
    print(f"[final] scenario_vi populated: {vi_ok}/{len(out)}")
    print("\nNext:\n  python src/run_monitors.py --data data/processed/task_pairs_ecom.csv "
          "--out results/task_pairs_outputs.csv\n  python src/evaluate.py "
          "--data results/task_pairs_outputs.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
