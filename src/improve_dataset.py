#!/usr/bin/env python3
"""Push the Adaption quality grade higher by re-adapting the enhanced dataset.

The first adaptation lifted your data D -> B. The remaining gap to A is
*message/prompt* quality (completions are already at reference level). So this
script feeds the already-enhanced columns back in as the prompt/completion and
runs adaptation again — "adapt the adaptive text" — then reads the new grade.

Run it repeatedly (each pass re-feeds the previous output) until the grade hits
A or stops improving.

    python src/improve_dataset.py                 # dry-run: upload + estimate + show grade
    python src/improve_dataset.py --yes           # run adaptation, download, print new grade

Inputs/outputs:
    --src   data/raw/agent_safety_bench.csv       (the enhanced download)
    --out   data/raw/agent_safety_bench_v2.csv    (next, higher-grade version)
By default prompt = enhanced_prompt, completion = enhanced_completion.
"""
import argparse
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

try:
    from adaption import Adaption, DatasetTimeout
except ImportError:
    sys.exit("Run `pip install -r requirements.txt` first (adaption SDK missing).")


def show_grade(client, dataset_id, label):
    """Print the quality grade for a dataset, if the evaluation is ready."""
    try:
        ev = client.datasets.get_evaluation(dataset_id)
        q = ev.quality
        print(f"  {label}: grade {q.grade_before} -> {q.grade_after} "
              f"(score {q.score_before} -> {q.score_after}, "
              f"+{q.improvement_percent}% , percentile {q.percentile_after})")
        return q
    except Exception as e:  # evaluation not ready yet
        print(f"  {label}: evaluation not available yet ({e.__class__.__name__})")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default="data/raw/scenarios_seed_v2_adapted.csv")
    parser.add_argument("--out", default="data/raw/scenarios_seed_v2_adapted2.csv")
    parser.add_argument("--prompt-col", default="enhanced_prompt")
    parser.add_argument("--completion-col", default="enhanced_completion")
    parser.add_argument("--yes", action="store_true",
                        help="Actually run adaptation (spends credits).")
    args = parser.parse_args()

    client = Adaption()

    print(f"Uploading {args.src} (prompt={args.prompt_col}, "
          f"completion={args.completion_col}) ...")
    result = client.datasets.upload_file(args.src)
    dataset_id = result.dataset_id
    print(f"  dataset_id = {dataset_id}")

    print("Waiting for ingestion ...")
    while True:
        status = client.datasets.get_status(dataset_id)
        if getattr(status, "row_count", None) is not None:
            print(f"  ingested {status.row_count} rows")
            break
        time.sleep(2)

    column_mapping = {"prompt": args.prompt_col, "completion": args.completion_col}
    estimate = client.datasets.run(dataset_id, column_mapping=column_mapping,
                                   estimate=True)
    print(f"Estimated cost: {estimate.estimated_credits_consumed} credits")

    if not args.yes:
        print("\nDry run. Re-run with --yes to adapt and read the new grade.")
        return

    run = client.datasets.run(dataset_id, column_mapping=column_mapping)
    print(f"Adapting (run {run.run_id}) ...")
    try:
        final = client.datasets.wait_for_completion(dataset_id, timeout=1800)
        print(f"  finished: {final.status}")
    except DatasetTimeout as e:
        sys.exit(f"Timed out after {e.timeout}s; check the dashboard "
                 f"(dataset {dataset_id}).")

    print("New quality:")
    show_grade(client, dataset_id, "result")

    # datasets.download() returns the file content (str/bytes), not a URL.
    content = client.datasets.download(dataset_id)
    if isinstance(content, str) and content.startswith("http"):
        content = requests.get(content, timeout=120).content
    if isinstance(content, (bytes, bytearray)):
        with open(args.out, "wb") as f:
            f.write(content)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(str(content))
    print(f"Saved higher-grade dataset -> {args.out}")
    print("Re-run with --src", args.out, "to push the grade even further.")


if __name__ == "__main__":
    main()
