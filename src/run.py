#!/usr/bin/env python3
"""run.py — CLI entrypoint.

Examples:

  # Smoke test, no cost
  python src/run.py --mock --limit 12 --stage all --context-mode instruction --force

  # Reuse existing data/out_generated.csv and validate it
  python src/run.py --stage validate

  # Run three monitor context modes
  rm -f data/out_verdicts.csv
  python src/run.py --stage monitor --context-mode instruction
  python src/run.py --stage monitor --context-mode action
  python src/run.py --stage monitor --context-mode trace
  python src/run.py --stage metrics
"""

import argparse
import os
import pandas as pd

import pipeline
import metrics
from pipeline import OUT_GEN, OUT_VERDICTS


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--stage",
        default="all",
        choices=["all", "generate", "validate", "monitor", "metrics"],
    )

    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="0 = all rows",
    )

    ap.add_argument(
        "--mock",
        action="store_true",
        help="fake models, $0",
    )

    ap.add_argument(
        "--locale-aware",
        action="store_true",
        help="also run glossary control",
    )

    ap.add_argument(
        "--context-mode",
        default="action",
        choices=["instruction", "action", "trace"],
        help="what the monitor sees",
    )

    ap.add_argument(
        "--include-expensive-panel",
        action="store_true",
        help="include GPT-4o-mini and Claude in monitor panel; use only on small final subset",
    )

    ap.add_argument(
        "--audit-benign",
        action="store_true",
        help="also call fluent oracle on benign rows during validation",
    )

    ap.add_argument(
        "--no-cheap-gate",
        action="store_true",
        help="disable regex lexical-leak dropping during validation",
    )

    ap.add_argument(
        "--fresh-verdicts",
        action="store_true",
        help="delete data/out_verdicts.csv before monitor stage",
    )

    ap.add_argument(
        "--force",
        action="store_true",
        help="ignore generation checkpoint and regenerate",
    )

    args = ap.parse_args()

    if args.fresh_verdicts and os.path.exists(OUT_VERDICTS):
        os.remove(OUT_VERDICTS)
        print(f"[run] removed {OUT_VERDICTS}")

    g = None

    # ------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------
    if args.stage in ("all", "generate"):
        df = pipeline.load_scenarios(args.limit)

        if os.path.exists(OUT_GEN) and not args.force and args.stage == "all":
            print(f"[generate] {OUT_GEN.name} exists; reuse (use --force to regenerate)")
            g = pd.read_csv(OUT_GEN)
        else:
            g = pipeline.stage_generate(df, args.mock)

    # ------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------
    if args.stage in ("all", "validate"):
        if g is None:
            if not os.path.exists(OUT_GEN):
                raise FileNotFoundError(
                    f"{OUT_GEN} not found. Run --stage generate first or place out_generated.csv in data/."
                )
            g = pd.read_csv(OUT_GEN)

        g = pipeline.stage_validate(
            g,
            mock=args.mock,
            cheap_gate=not args.no_cheap_gate,
            audit_benign=args.audit_benign,
        )

    # ------------------------------------------------------------
    # Monitor
    # ------------------------------------------------------------
    if args.stage in ("all", "monitor"):
        if g is None:
            if not os.path.exists(OUT_GEN):
                raise FileNotFoundError(
                    f"{OUT_GEN} not found. Run --stage generate first or place out_generated.csv in data/."
                )
            g = pd.read_csv(OUT_GEN)

        pipeline.stage_monitor(
            g,
            mock=args.mock,
            locale_aware=False,
            context_mode=args.context_mode,
            include_expensive_panel=args.include_expensive_panel,
            append=True,
        )

        if args.locale_aware:
            pipeline.stage_monitor(
                g,
                mock=args.mock,
                locale_aware=True,
                context_mode=args.context_mode,
                include_expensive_panel=args.include_expensive_panel,
                append=True,
            )

    # ------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------
    if args.stage in ("all", "metrics"):
        metrics.report()


if __name__ == "__main__":
    main()