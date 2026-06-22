"""pipeline.py — orchestrates the stages, checkpointing each to CSV.

generate -> out_generated.csv
validate -> adds oracle gates + kept flag to out_generated.csv
monitor  -> Executor acts on each rendering, Monitor panel judges -> out_verdicts.csv
"""
import os, sys
import pandas as pd
import agents
from models import DATA_DIR

OUT_GEN      = DATA_DIR / "out_generated.csv"
OUT_VERDICTS = DATA_DIR / "out_verdicts.csv"


def load_scenarios(limit=0):
    df = pd.read_csv(DATA_DIR / "scenario.csv").reset_index(drop=True)
    # scenario.csv has no `uid`; synthesize a stable, unique one the stages key on
    if "uid" not in df.columns:
        df["uid"] = df.get("base_id", df.index).astype(str) + "-" + df.index.astype(str)
    if limit:
        df = df.groupby("domain", group_keys=False).head(max(1, limit // 3))
    return df


# --- stage 1 -------------------------------------------------------------
def stage_generate(df, mock):
    rows = []
    for _, r in df.iterrows():
        d = r.to_dict()
        d["scenario_vi_prag"] = agents.attacker_generate(d, mock=mock)
        rows.append(d)
        print(f"  gen {d['uid']}", file=sys.stderr)
    g = pd.DataFrame(rows)
    g.to_csv(OUT_GEN, index=False)
    print(f"[generate] {len(g)} rows -> {OUT_GEN.name}")
    return g


# --- stage 2 -------------------------------------------------------------
def stage_validate(g, mock):
    fl, lx, keep = [], [], []
    for _, r in g.iterrows():
        a, b, k = agents.oracle_validate(r["scenario_vi_prag"], r["gold_label"], mock=mock)
        fl.append(a); lx.append(b); keep.append(k)
    g = g.copy()
    g["oracle_fluent"], g["oracle_lexical"], g["kept"] = fl, lx, keep
    g.to_csv(OUT_GEN, index=False)
    n_sus = (g.gold_label == "suspicious").sum()
    kept_sus = ((g.gold_label == "suspicious") & g.kept).sum()
    print(f"[validate] kept {sum(keep)}/{len(g)}  (suspicious {kept_sus}/{n_sus})")
    return g


# --- stage 3 (executor + monitor) ---------------------------------------
def stage_monitor(g, mock, locale_aware=False, skip_executor=False):
    rows = g[g.kept].copy() if "kept" in g.columns else g.copy()
    recs = []
    for _, r in rows.iterrows():
        for rendering in agents.RENDERINGS:
            instr = r.get(rendering)
            if not isinstance(instr, str) or not instr.strip():
                continue
            action = instr if skip_executor else agents.executor_act(instr, r["domain"], mock=mock)
            for pm in agents.PANEL:
                pred = agents.monitor_classify(pm, action, r["domain"], rendering,
                                               r["gold_label"], locale_aware=locale_aware, mock=mock)
                recs.append({
                    "uid": r["uid"], "domain": r["domain"], "difficulty": r.get("difficulty"),
                    "rendering": rendering, "monitor": f"{pm[0]}:{pm[1]}",
                    "locale_aware": locale_aware, "gold_label": r["gold_label"],
                    "pred": pred, "correct": pred == r["gold_label"],
                })
    v = pd.DataFrame(recs)
    mode = "a" if (locale_aware and os.path.exists(OUT_VERDICTS)) else "w"
    v.to_csv(OUT_VERDICTS, mode=mode, header=(mode == "w"), index=False)
    print(f"[monitor] {len(v)} verdicts (locale_aware={locale_aware}) -> {OUT_VERDICTS.name}")
    return v