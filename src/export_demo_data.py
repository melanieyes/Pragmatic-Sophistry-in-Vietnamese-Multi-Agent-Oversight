#!/usr/bin/env python3
"""Bundle scenarios + verdicts + narrative metadata into demo/data.js.

Emits `window.DEMO = {...}` in the schema the polished static demo expects
(see demo/script.js): DOMAINS, LANGUAGES, MONITORS, SCENARIOS. Each scenario
carries per-language text, the risky phrase (+ gloss + why) that drives the
reveal, and each monitor's prediction/confidence/reason.

Sources:
    data/processed/scenarios_270.csv   the long-format scenarios
    results/monitor_outputs.csv        monitor verdicts (mock or real LLM)
    data/raw/scenarios_meta.csv        risk type, risky phrase, gloss, why

Confidence is synthetic when the monitor backend is the mock (keyword hit/miss
has no probability); it is illustrative only. Swap in a real LLM that returns
calibrated scores to make it meaningful.
"""
import json
import os

from utils import (DEMO, ENHANCED_CSV, MONITOR_OUTPUTS_CSV, MONITORS,
                   SCENARIOS_CSV, SEED_CSV, read_csv)

DOMAIN_LABELS = {"it": "Internal IT", "bank": "Banking", "ecom": "E-commerce"}
LANG_MAP = {"en": "english", "vi": "vietnamese", "cs": "codeswitch"}
MON_MAP = {"baseline": "baseline", "locale_aware": "locale",
           "translate_then": "translate"}

LANG_DEFS = [
    {"id": "english", "label": "English", "tag": "EN"},
    {"id": "vietnamese", "label": "Vietnamese", "tag": "VI"},
    {"id": "codeswitch", "label": "Code-switch", "tag": "VI·EN"},
]
MON_DEFS = [
    {"id": "baseline", "name": "Baseline Monitor",
     "blurb": "English-centric monitor. No locale guidance."},
    {"id": "locale", "name": "Locale-Aware Monitor",
     "blurb": "Told to apply equal scrutiny across Vietnamese and code-switch."},
    {"id": "translate", "name": "Translate-then-Monitor",
     "blurb": "Translates the action to English first, then runs the baseline."},
]


def confidence(correct, seed):
    """Deterministic, illustrative confidence (mock backend has no real score)."""
    h = sum(ord(c) for c in seed)
    return round((0.85 + (h % 9) / 100) if correct else (0.40 + (h % 11) / 100), 2)


def build_why(m, gold):
    """One-line rationale synthesized from the v2 security fields."""
    safe = (m.get("safe_action_en") or "").strip()
    if gold == "benign":
        return ("The safe action: " + safe) if safe \
            else "Within the user's intent; no control bypassed."
    rt = (m.get("risk_type") or "").replace("_", " ").strip()
    detail = []
    for field, prefix in (("attack_surface", "surface "),
                          ("injection_source", "via "),
                          ("severity", "severity ")):
        val = (m.get(field) or "").strip()
        if val and val != "none":
            detail.append(prefix + val)
    s = rt or "risky tool-use"
    if detail:
        s += " (" + ", ".join(detail) + ")"
    if safe:
        s += ". Expected safe action: " + safe
    return s[0].upper() + s[1:] if s else s


def main() -> None:
    scenarios = read_csv(SCENARIOS_CSV)
    verdicts = read_csv(MONITOR_OUTPUTS_CSV)
    meta = {m["base_id"]: m for m in read_csv(SEED_CSV)}
    vmap = {(v["scenario_id"], v["monitor"]): v for v in verdicts}

    # Optional: Adaption-generated expert explanation, keyed by base_id.
    enhanced = {}
    if os.path.exists(ENHANCED_CSV):
        for r in read_csv(ENHANCED_CSV):
            bid = r.get("base_id")
            if bid:
                enhanced[bid] = r.get("enhanced_completion", "")

    by_base, order = {}, []
    for s in scenarios:
        b = s["base_id"]
        if b not in by_base:
            by_base[b] = {
                "id": b,
                "domain": DOMAIN_LABELS.get(s["domain"], s["domain"]),
                "riskType": meta.get(b, {}).get("risk_type", "").replace("_", " "),
                "goldLabel": s["gold_label"],
                "variants": {},
                "monitors": {},
            }
            order.append(b)
        lang = LANG_MAP[s["language"]]
        by_base[b]["variants"][lang] = {"text": s["scenario_text"]}
        mon_out = {}
        for mon in MONITORS:
            v = vmap.get((s["scenario_id"], mon))
            correct = bool(v) and v["verdict"] == s["gold_label"]
            mon_out[MON_MAP[mon]] = {
                "prediction": v["verdict"] if v else "",
                "confidence": confidence(correct, s["scenario_id"] + mon),
                "reason": v["reason"] if v else "",
            }
        by_base[b]["monitors"][lang] = mon_out

    # Risky phrase + verdict (need the base assembled first).
    for b in order:
        m = meta.get(b, {})
        sc = by_base[b]
        why = build_why(m, sc["goldLabel"])
        sc["riskyPhrase"] = {
            "english": m.get("evidence_phrase_en", ""),
            "vietnamese": m.get("evidence_phrase_vi", ""),
            "codeswitch": m.get("evidence_phrase_cs", ""),
            "gloss": m.get("evidence_phrase_en", ""),
            "why": why,
        }
        lead = "Suspicious. " if sc["goldLabel"] == "suspicious" else "Benign. "
        sc["verdict"] = lead + why
        sc["explanation"] = enhanced.get(b, "")

    domains = []
    for b in order:
        d = by_base[b]["domain"]
        if d not in domains:
            domains.append(d)

    demo = {
        "DOMAINS": domains,
        "LANGUAGES": LANG_DEFS,
        "MONITORS": MON_DEFS,
        "SCENARIOS": [by_base[b] for b in order],
    }

    os.makedirs(DEMO, exist_ok=True)
    out = os.path.join(DEMO, "data.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by src/export_demo_data.py. Do not edit.\n")
        f.write("window.DEMO = ")
        json.dump(demo, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    print(f"Wrote {out} ({len(order)} scenarios, domains: {', '.join(domains)})")


if __name__ == "__main__":
    main()
