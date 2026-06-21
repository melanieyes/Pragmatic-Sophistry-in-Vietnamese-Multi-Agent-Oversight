"""Stage 3a: hard validation of the assembled dataset_30.csv.

HARD checks (raise -> non-zero exit):
  1. 30 rows, unique base_id, 20 suspicious / 10 benign.
  2. No empty cells in any of the 8 columns.
  3. enhanced_prompt references its scenario_en (quotes a distinctive slice).
  4. Language sanity: VI is Vietnamese w/ low English; CS mixes EN tech tokens + VI
     function words; EN looks English.

SOFT checks (warn + write results/validation_warnings.csv, do not crash):
  5. Risk preservation: suspicious VI/CS keep a risk indicator; benign VI/CS contain
     no violation verb. Borderline generations feed the diversity-gate regenerate list.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (  # noqa: E402
    DATA_PROCESSED, RESULTS, detect_lang, english_token_ratio,
    has_en_tech_token, has_vi_function_word, looks_vietnamese, vi_diacritic_count,
)

FINAL_COLS = [
    "scenario_en", "gold_label", "enhanced_prompt", "enhanced_completion",
    "base_id", "domain", "scenario_cs", "scenario_vi",
]

# Bilingual indicators of a risky action (kept loose; soft check only).
RISK_TERMS = [
    # English markers
    "bypass", "override", "skip", "without", "unauthor", "unverified", "fraud", "fake",
    "hide", "hidden", "delete", "reuse", "cached", "off-market", "swap", "redirect",
    "drain", "waive", "confirmation", "another customer", "third party", "read out",
    # Vietnamese markers
    "bỏ qua", "ghi đè", "không xác minh", "chưa được xác minh", "không có xác nhận",
    "giả mạo", "không thông báo", "vượt hạn mức", "xóa", "tái sử dụng", "chuyển hướng",
    "miễn", "khôi phục", "bên thứ ba", "khách hàng khác", "không phải", "người thụ hưởng",
    "ẩn ", "toàn bộ thông tin", "chưa được",
]
# Stronger violation verbs that should never appear in a benign statement.
VIOLATION_VERBS = ["bypass", "override", "bỏ qua", "ghi đè", "giả mạo", "unauthor", "fraud"]


# Informal / slang markers that signal the aggressive-obfuscation pass actually ran (v2).
SLANG_MARKERS = [
    "củ", "lít", "lát", "xị", "tỏi", "bắn", "ck", "tk", "lách", "lụi", "thông",
    "ẩn", "khỏi cần", "cho qua", "ông anh", "die", "auth", "bypass", "verify",
    "approve", "limit", "token", "transfer", "account",
]


def _norm(t: str) -> str:
    return " ".join(str(t).split()).lower()


def hard_checks(df: pd.DataFrame, n_total: int = 30, n_susp: int = 20, n_benign: int = 10,
                v2: bool = False) -> None:
    assert len(df) == n_total, f"expected {n_total} rows, got {len(df)}"
    assert df["base_id"].is_unique, "base_id not unique"
    counts = df["gold_label"].value_counts().to_dict()
    assert counts.get("suspicious") == n_susp, f"expected {n_susp} suspicious, got {counts.get('suspicious')}"
    assert counts.get("benign") == n_benign, f"expected {n_benign} benign, got {counts.get('benign')}"

    for col in FINAL_COLS:
        empty = df[df[col].isna() | (df[col].astype(str).str.strip() == "")]
        assert empty.empty, f"empty cells in {col}: {list(empty['base_id'])}"

    # enhanced_prompt references scenario_en (distinctive slice present).
    bad_ref = []
    for _, r in df.iterrows():
        en = _norm(r["scenario_en"])
        slice_ = en[10:50] if len(en) > 50 else en
        if slice_ and slice_ not in _norm(r["enhanced_prompt"]):
            bad_ref.append(r["base_id"])
    assert not bad_ref, f"enhanced_prompt does not quote scenario_en for: {bad_ref}"

    # language sanity. v2 obfuscation is heavy slang/teencode, so VI is detected by
    # Vietnamese diacritics (robust) rather than a formal function-word whitelist.
    lang_err = []
    for _, r in df.iterrows():
        if v2:
            if not looks_vietnamese(r["scenario_vi"]):
                lang_err.append((r["base_id"], "vi_not_vietnamese"))
            cs = r["scenario_cs"]
            if not (has_en_tech_token(cs) and (vi_diacritic_count(cs) >= 2 or has_vi_function_word(cs))):
                lang_err.append((r["base_id"], "cs_not_codeswitch"))
        else:
            if english_token_ratio(r["scenario_vi"]) > 0.6 or not has_vi_function_word(r["scenario_vi"]):
                lang_err.append((r["base_id"], "vi_not_vietnamese"))
            if not (has_en_tech_token(r["scenario_cs"]) and has_vi_function_word(r["scenario_cs"])):
                lang_err.append((r["base_id"], "cs_not_codeswitch"))
        if detect_lang(r["scenario_en"]) not in ("en", "unknown"):
            lang_err.append((r["base_id"], "en_not_english"))
    assert not lang_err, f"language sanity failures: {lang_err}"


def soft_checks(df: pd.DataFrame) -> pd.DataFrame:
    warnings = []
    for _, r in df.iterrows():
        vi, cs = _norm(r["scenario_vi"]), _norm(r["scenario_cs"])
        if r["gold_label"] == "suspicious":
            if not any(t in vi for t in RISK_TERMS):
                warnings.append({"base_id": r["base_id"], "issue": "vi_missing_risk_term"})
            if not any(t in cs for t in RISK_TERMS):
                warnings.append({"base_id": r["base_id"], "issue": "cs_missing_risk_term"})
        else:
            if any(v in vi for v in VIOLATION_VERBS):
                warnings.append({"base_id": r["base_id"], "issue": "benign_vi_has_violation_verb"})
            if any(v in cs for v in VIOLATION_VERBS):
                warnings.append({"base_id": r["base_id"], "issue": "benign_cs_has_violation_verb"})
    return pd.DataFrame(warnings)


def oracle_gate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """v2 integrity gate: every row must be oracle-confirmed gold-consistent.

    Disagreement is split by difficulty: on the `clear`/`subtle` tiers a mismatch means
    the obfuscation likely dropped/added the violation (real label drift -> HARD FAIL).
    On the `ambiguous` tier a ~50 case where the oracle leans the other way is expected,
    so it is surfaced as a review note, not a failure.

    Returns (hard_fails, ambiguous_flags, obfuscation_warnings).
    """
    path = DATA_PROCESSED / "oracle_100.csv"
    if not path.exists():
        raise SystemExit(f"oracle gate requires {path.name}; run src/oracle_check.py first")
    ora = pd.read_csv(path)

    meta = pd.read_csv(DATA_PROCESSED / "dataset_100_meta.csv")[["base_id", "difficulty"]]
    ora = ora.merge(meta, on="base_id", how="left")
    bad = ora[ora["gold_consistent"] != True]  # noqa: E712 (handles bool/str/NaN)
    hard_fails = bad[bad["difficulty"] != "ambiguous"]
    ambiguous_flags = bad[bad["difficulty"] == "ambiguous"]

    warnings = []
    for _, r in df.iterrows():
        vi = _norm(r["scenario_vi"])
        if not any(m in vi for m in SLANG_MARKERS):
            warnings.append({"base_id": r["base_id"], "issue": "vi_no_obfuscation_marker"})
    return hard_fails, ambiguous_flags, pd.DataFrame(warnings)


def main_v2() -> int:
    df = pd.read_csv(DATA_PROCESSED / "dataset_100.csv")
    hard_checks(df, n_total=100, n_susp=60, n_benign=40, v2=True)

    hard_fails, ambiguous_flags, warn = oracle_gate(df)
    warn_path = RESULTS / "validation_warnings_100.csv"
    warn.to_csv(warn_path, index=False)

    cols = ["base_id", "lang", "gold", "same_action", "still_violation", "recovered_action"]
    if len(hard_fails):
        print(f"[validate] [v2] ORACLE GATE FAILED: {len(hard_fails)} clear/subtle "
              f"gold-inconsistent rows (real label drift) -> regenerate before proceeding:")
        print(hard_fails[cols].to_string(index=False))
        return 1

    print(f"[validate] [v2] HARD checks + oracle gate passed.")
    if len(ambiguous_flags):
        print(f"\n[validate] [v2] {len(ambiguous_flags)} AMBIGUOUS-tier rows where the oracle "
              f"leaned the other way (expected on this tier; review manually, not a failure):")
        print(ambiguous_flags[cols].to_string(index=False))
    if len(warn):
        print(f"\n[validate] [v2] obfuscation warnings: {len(warn)} (see {warn_path.name})")
        print(warn.to_string(index=False))
    return 0


def main() -> int:
    df = pd.read_csv(DATA_PROCESSED / "dataset_30.csv")
    hard_checks(df)
    warn = soft_checks(df)
    warn_path = RESULTS / "validation_warnings.csv"
    warn.to_csv(warn_path, index=False)
    print(f"[validate] HARD checks passed. SOFT warnings: {len(warn)} (see {warn_path.name})")
    if len(warn):
        print(warn.to_string(index=False))
    return 0


if __name__ == "__main__":
    if "--version" in sys.argv and sys.argv[sys.argv.index("--version") + 1] == "v2":
        raise SystemExit(main_v2())
    raise SystemExit(main())
