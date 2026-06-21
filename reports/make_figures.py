"""Generate the v2 report figures from results/monitor_scores_100.csv.

Writes PNGs to reports/figures/:
  fig1_benign_overflag.png  - mean suspicion on BENIGN rows, EN vs VI vs CS (baseline),
                              the false-positive tax on Vietnamese (per judge).
  fig2_auc_by_lang.png      - baseline AUC per language per judge (the VI dip).
  fig3_locale_fix.png       - baseline vs locale_aware mean suspicion on benign VI
                              (the mitigation).

Usage: python reports/make_figures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from evaluate_shade import compute_auc  # noqa: E402

FIG = ROOT / "reports" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
LANGS = ["en", "vi", "cs"]
LANG_LABEL = {"en": "English", "vi": "Vietnamese", "cs": "Code-switch"}
COLORS = {"en": "#4C72B0", "vi": "#C44E52", "cs": "#55A868"}


def load() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "results" / "monitor_scores_100.csv")
    df["suspicion_score"] = pd.to_numeric(df["suspicion_score"], errors="coerce")
    df["config"] = df["monitor_id"].str.split("@").str[0]
    df["judge"] = df["monitor_id"].str.split("@").str[1]
    return df


def _judges(df):
    return sorted(df["judge"].unique())


def fig1_benign_overflag(df):
    judges = _judges(df)
    fig, axes = plt.subplots(1, len(judges), figsize=(5.2 * len(judges), 4.2), sharey=True)
    if len(judges) == 1:
        axes = [axes]
    for ax, j in zip(axes, judges):
        sub = df[(df.config == "baseline") & (df.judge == j) & (df.gold == "benign")]
        means = [sub[sub.lang == l]["suspicion_score"].mean() for l in LANGS]
        bars = ax.bar([LANG_LABEL[l] for l in LANGS], means,
                      color=[COLORS[l] for l in LANGS])
        ax.axhline(50, ls="--", lw=1, color="grey")
        ax.text(2.4, 51, "flag threshold", color="grey", fontsize=8, ha="right")
        ax.set_title(j, fontsize=10)
        ax.set_ylim(0, 100)
        for b, m in zip(bars, means):
            ax.text(b.get_x() + b.get_width() / 2, m + 1.5, f"{m:.1f}",
                    ha="center", fontsize=9)
    axes[0].set_ylabel("Mean suspicion score (benign rows)")
    fig.suptitle("False-positive tax on Vietnamese: benign actions over-flagged\n"
                 "(baseline monitor; lower = correct)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIG / "fig1_benign_overflag.png", dpi=150)
    plt.close(fig)


def fig2_auc_by_lang(df):
    judges = _judges(df)
    x = range(len(LANGS))
    width = 0.8 / len(judges)
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for k, j in enumerate(judges):
        aucs = []
        for l in LANGS:
            g = df[(df.config == "baseline") & (df.judge == j) & (df.lang == l)]
            aucs.append(compute_auc(g["suspicion_score"], g["gold"]))
        offs = [xi + (k - (len(judges) - 1) / 2) * width for xi in x]
        bars = ax.bar(offs, aucs, width, label=j)
        for b, a in zip(bars, aucs):
            ax.text(b.get_x() + b.get_width() / 2, a + 0.001, f"{a:.3f}",
                    ha="center", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([LANG_LABEL[l] for l in LANGS])
    ax.set_ylim(0.95, 1.005)
    ax.set_ylabel("ROC-AUC (suspicious vs benign)")
    ax.set_title("Separability dips on Vietnamese (baseline monitor)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_auc_by_lang.png", dpi=150)
    plt.close(fig)


def fig3_locale_fix(df):
    judges = _judges(df)
    configs = ["baseline", "locale_aware"]
    x = range(len(judges))
    width = 0.35
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for k, cfg in enumerate(configs):
        vals = []
        for j in judges:
            sub = df[(df.config == cfg) & (df.judge == j) &
                     (df.gold == "benign") & (df.lang == "vi")]
            vals.append(sub["suspicion_score"].mean())
        offs = [xi + (k - 0.5) * width for xi in x]
        bars = ax.bar(offs, vals, width, label=cfg)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}",
                    ha="center", fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(judges, fontsize=8)
    ax.set_ylabel("Mean suspicion, benign Vietnamese")
    ax.set_title("Mitigation: locale-aware monitor lowers the\nVietnamese false-positive rate")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "fig3_locale_fix.png", dpi=150)
    plt.close(fig)


def main():
    df = load()
    fig1_benign_overflag(df)
    fig2_auc_by_lang(df)
    fig3_locale_fix(df)
    print(f"[make_figures] wrote 3 figures -> {FIG}")


if __name__ == "__main__":
    main()
