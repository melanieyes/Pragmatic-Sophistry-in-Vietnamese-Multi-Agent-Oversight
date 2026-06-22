#!/usr/bin/env python3
"""run.py — CLI entrypoint.

  python src/run.py --mock --limit 12 --stage all --locale-aware   # smoke, $0
  python src/run.py --limit 12 --stage generate                    # eyeball quality
  python src/run.py --stage all --locale-aware                      # full run

Stages checkpoint to data/out_*.csv, so a crash never costs re-spend.
"""
import argparse, os
import pandas as pd
import pipeline, metrics
from pipeline import OUT_GEN


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["all", "generate", "validate", "monitor", "metrics"])
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows")
    ap.add_argument("--mock", action="store_true", help="fake models, $0")
    ap.add_argument("--locale-aware", action="store_true", help="also run glossary control")
    ap.add_argument("--skip-executor", action="store_true",
                    help="monitor reads the rendering directly (3-agent mode)")
    ap.add_argument("--force", action="store_true", help="ignore checkpoints")
    args = ap.parse_args()

    g = None
    if args.stage in ("all", "generate"):
        df = pipeline.load_scenarios(args.limit)
        if os.path.exists(OUT_GEN) and not args.force and args.stage == "all":
            print(f"[generate] {OUT_GEN.name} exists; reuse (use --force to regenerate)")
            g = pd.read_csv(OUT_GEN)
        else:
            g = pipeline.stage_generate(df, args.mock)

    if args.stage in ("all", "validate"):
        g = g if g is not None else pd.read_csv(OUT_GEN)
        g = pipeline.stage_validate(g, args.mock)

    if args.stage in ("all", "monitor"):
        g = g if g is not None else pd.read_csv(OUT_GEN)
        pipeline.stage_monitor(g, args.mock, locale_aware=False, skip_executor=args.skip_executor)
        if args.locale_aware:
            pipeline.stage_monitor(g, args.mock, locale_aware=True, skip_executor=args.skip_executor)

    if args.stage in ("all", "metrics"):
        metrics.report()


if __name__ == "__main__":
    main()