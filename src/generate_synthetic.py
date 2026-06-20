#!/usr/bin/env python3
"""Generate synthetic English scenarios with the Adaption Labs API.

IMPORTANT — how this API actually works:
    Adaption "Adaptive Data" is a DATASET AUGMENTATION service, not a chat API.
    You give it a seed dataset (a `prompt` column, optionally a `completion`
    column) and it produces MORE rows in the same style. There is no endpoint
    that takes a free-form instruction like "write 90 scenarios".

So the flow here is:
    1. Upload data/raw/scenarios_seed.csv   (our hand-written seed scenarios)
    2. Wait for the server to finish ingesting it
    3. Estimate the credit cost of an augmentation run (cheap, no spend)
    4. (with --yes) start the run, wait for it, and download the augmented rows

The result is MORE English scenarios. Translating them into Vietnamese and
Vietnamese-English code-switch is a separate step (see build_dataset.py) because
that needs a chat LLM, which Adaption does not provide.

Usage:
    python src/generate_synthetic.py                 # upload + estimate cost only
    python src/generate_synthetic.py --yes           # actually run + download
    python src/generate_synthetic.py --seed data/raw/scenarios_seed.csv \
        --out data/raw/scenarios_augmented.csv --yes
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


def _save_download(content, path):
    """datasets.download() returns the file content (str/bytes), not a URL.
    Some deployments hand back a presigned URL instead — handle both."""
    if isinstance(content, str) and content.startswith("http"):
        content = requests.get(content, timeout=120).content
    if isinstance(content, (bytes, bytearray)):
        with open(path, "wb") as f:
            f.write(content)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(content))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="data/raw/scenarios_seed_v2.csv",
                        help="Seed CSV to augment (needs a 'scenario_en' column).")
    parser.add_argument("--out", default="data/raw/scenarios_augmented.csv",
                        help="Where to save the downloaded augmented dataset.")
    parser.add_argument("--prompt-col", default="scenario_en",
                        help="Column holding the scenario text (the 'prompt').")
    parser.add_argument("--completion-col", default="gold_label",
                        help="Optional column to carry as the 'completion'.")
    parser.add_argument("--yes", action="store_true",
                        help="Actually run the augmentation (spends credits). "
                             "Without this flag the script stops after the estimate.")
    args = parser.parse_args()

    client = Adaption()  

    # Upload the seed dataset 
    print(f"Uploading {args.seed} ...")
    result = client.datasets.upload_file(args.seed)
    dataset_id = result.dataset_id
    print(f"  dataset_id = {dataset_id}")

    # Wait for the server to finish ingesting it
    while True:
        status = client.datasets.get_status(dataset_id)
        if getattr(status, "row_count", None) is not None:
            print(f"  ingested {status.row_count} rows (status: {status.status})")
            break
        time.sleep(2)

    column_mapping = {"prompt": args.prompt_col}
    if args.completion_col:
        column_mapping["completion"] = args.completion_col

    # 3. Estimate the cost first (no spend) 
    estimate = client.datasets.run(dataset_id, column_mapping=column_mapping,
                                   estimate=True)
    print(f"Estimated cost: {estimate.estimated_credits_consumed} credits")

    if not args.yes:
        print("\nDry run only. Re-run with --yes to start the augmentation and "
              "download results.")
        return

    # 4. Start the real run, wait, and download 
    run = client.datasets.run(dataset_id, column_mapping=column_mapping)
    print(f"Run started: {run.run_id} "
          f"(~{getattr(run, 'estimated_minutes', '?')} min, "
          f"{run.estimated_credits_consumed} credits)")

    try:
        final = client.datasets.wait_for_completion(dataset_id, timeout=1800)
        print(f"Run finished: {final.status}")
        if getattr(final, "error", None):
            sys.exit(f"Run failed: {final.error.message}")
    except DatasetTimeout as e:
        sys.exit(f"Still running after {e.timeout}s (last status: {e.last_status}). "
                 f"Check the app, then download manually with dataset_id={dataset_id}.")

    print("Downloading augmented dataset ...")
    _save_download(client.datasets.download(dataset_id), args.out)
    print(f"Saved -> {args.out}")


if __name__ == "__main__":
    main()
