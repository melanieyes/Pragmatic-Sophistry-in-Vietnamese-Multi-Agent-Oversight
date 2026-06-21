"""Stage 2b (v2 integrity gate): independent oracle label back-check.

Aggressive VI/CS obfuscation can silently drop the violation (label drift), and the old
keyword risk-preservation check can't catch that once the keywords are gone. So a STRONG
model (deepseek/claude) that is *not* one of the weak judges reads each obfuscated
scenario_vi / scenario_cs on its own terms and decides whether it still describes the same
action and whether that action is a violation.

  gold_consistent = same_action AND (still_violation == (gold_label == "suspicious"))

This both (a) gates label integrity and (b) records the "strong-reader ceiling": if the
strong oracle recovers the risk but a weak judge later misses it, that gap is the finding.

The oracle is a direct llm_complete call (NOT an Adaption run), keeping it independent.

Writes data/processed/oracle_100.csv:
    base_id, lang (vi|cs), gold, same_action, still_violation, gold_consistent,
    recovered_action, raw_oracle_output

Usage:
    python src/oracle_check.py                         # deepseek-chat, dataset_100.csv
    python src/oracle_check.py --provider deepseek --model deepseek-chat --workers 8
    python src/oracle_check.py --dataset dataset_100.csv
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import DATA_PROCESSED, PROMPTS, llm_complete, load_keys  # noqa: E402

ORACLE_SYS = (PROMPTS / "blueprint_oracle.md").read_text(encoding="utf-8")
LANG_COL = {"vi": "scenario_vi", "cs": "scenario_cs"}


def _parse(text: str) -> tuple[bool | None, bool | None, str]:
    """Extract (same_action, still_violation, recovered_action) from the oracle JSON."""
    if not isinstance(text, str) or not text.strip():
        return None, None, ""
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None, None, ""
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None, None, ""

    def _b(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "1")
        return None

    return (_b(obj.get("same_action")), _b(obj.get("still_violation")),
            str(obj.get("recovered_action", "")).strip())


def _task(args):
    r, lang, provider, model = args
    user = (f'English reference statement:\n"{r["scenario_en"]}"\n\n'
            f'Vietnamese/code-switch version to review:\n"{r[LANG_COL[lang]]}"')
    raw = llm_complete(user, system=ORACLE_SYS, provider=provider, model=model,
                       max_tokens=1024, json_output=True)
    same, viol, recovered = _parse(raw)
    gold_susp = r["gold_label"] == "suspicious"
    gold_consistent = (
        bool(same) and viol is not None and bool(viol) == gold_susp
        if (same is not None and viol is not None) else False
    )
    return {
        "base_id": r["base_id"], "lang": lang, "gold": r["gold_label"],
        "same_action": same, "still_violation": viol,
        "gold_consistent": gold_consistent, "recovered_action": recovered,
        "raw_oracle_output": raw,
    }


def main(dataset: str = "dataset_100.csv", provider: str = "deepseek",
         model: str = "deepseek-chat", workers: int = 8) -> None:
    load_keys()
    df = pd.read_csv(DATA_PROCESSED / dataset)
    tasks = [(r, lang, provider, model)
             for _, r in df.iterrows() for lang in LANG_COL]

    if workers <= 1:
        out = [_task(t) for t in tasks]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            out = list(ex.map(_task, tasks))

    res = pd.DataFrame(out).sort_values(["base_id", "lang"]).reset_index(drop=True)
    res.to_csv(DATA_PROCESSED / "oracle_100.csv", index=False)

    n_fail = int((~res["gold_consistent"]).sum())
    n_parse = int(res["same_action"].isna().sum())
    print(f"[oracle_check] [{provider}:{model}] checked {len(res)} rows "
          f"({df.shape[0]} scenarios x {len(LANG_COL)} langs) -> oracle_100.csv")
    print(f"[oracle_check] parse failures: {n_parse} | gold-inconsistent (review): {n_fail}")
    if n_fail:
        bad = res[~res["gold_consistent"]][
            ["base_id", "lang", "gold", "same_action", "still_violation", "recovered_action"]]
        print(bad.to_string(index=False))


def _arg(flag: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


if __name__ == "__main__":
    main(
        dataset=_arg("--dataset", "dataset_100.csv"),
        provider=_arg("--provider", "deepseek"),
        model=_arg("--model", "deepseek-chat"),
        workers=int(_arg("--workers", "8")),
    )
