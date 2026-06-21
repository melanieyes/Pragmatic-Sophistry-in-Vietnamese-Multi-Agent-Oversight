"""Build the e-commerce agent-safety dataset (A-grade superset schema).

Output (data/processed/agent_safety_bench_ecom.csv), one row per seed. The schema
is a *superset* of the reference agent_safety_bench template: it keeps every seed
field (the reference drops tool_calls / agent_context / gold_reason) and adds the
A-grade annotation layer (risk taxonomy + evidence span + safe action) in every
language rendering. Column order is `OUTPUT_COLS` below.

Engine split:
  - Gemini  : ALL translation — vi (slang-rich), cs (code-switch), and en_bt
              (English BLIND back-translated from the vi, never the EN seed), plus
              the same three renderings of the evidence / safe-action spans.
              Cached to gemini_cache.json so re-runs / incremental edits don't
              re-spend.
  - Adaption: enhanced_* instruction-dataset augmentation only (translation is
              Gemini's job now). Its main pass still emits a vi rendering, kept
              only as a fallback when Gemini is skipped; the cs pass is off unless
              --adaption-cs.

Field provenance (who fills each column):
  - Propagated from the seed verbatim:
        base_id, domain, sub_category, gold_label,
        agent_context, tool_calls, gold_reason, scenario_en
  - Authored in the seed (editorial; the pipeline NEVER invents these):
        severity, risk_type, attack_surface, injection_source, is_hard_benign,
        evidence_phrase_en, safe_action_en
        Missing/blank is tolerated so the current seed still builds; enrich the
        seed CSV incrementally to climb from B -> A.
  - From Gemini (fallback: authored *_vi / *_cs / *_en_bt seed columns):
        scenario_vi, scenario_cs, scenario_en_bt,
        evidence_phrase_{vi,cs,en_bt}, safe_action_{vi,cs,en_bt}
  - From Adaption: enhanced_prompt, enhanced_completion

The four renderings (the independent variable of the study):
  - scenario_en    : English seed (the seed user_message).
  - scenario_vi    : natural Vietnamese as VN marketplace users actually type
                     (informal, slang + abbreviations); VI_BLUEPRINT.
  - scenario_cs    : Vietnamese-English code-switch — a *Vietnamese matrix* sentence
                     that KEEPS action verbs / domain / risk-trigger words in
                     ENGLISH (refund, override, disable 2FA, export customer DB...);
                     CS_BLUEPRINT.
  - scenario_en_bt : plain English back-translated from scenario_vi ALONE (blind to
                     the EN seed); BT_BLUEPRINT. Lets failure analysis split the vi
                     gap into a language-comprehension component (vi vs en_bt) and a
                     translation-information-loss component (en_bt vs en).

A blind back-translation can silently launder the risk out; qc_report() flags any
suspicious row whose evidence cue did not survive en -> vi -> en_bt.

NOTE: adaption_raw.csv is a raw *staging* download, not the eval set. Evaluation
runs on the assembled agent_safety_bench_ecom.csv (it alone carries gold_label,
all four renderings, and the A-grade annotation layer).

Usage:
  python -m src.build_dataset                  # Gemini translate + Adaption augment
  python -m src.build_dataset --skip-gemini    # no vi/cs/en_bt (en + labels only)
  python -m src.build_dataset --skip-adaption  # no enhanced_* augmentation
  python -m src.build_dataset --resume-main DS # reuse an Adaption run (saves credits)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "scenarios_seed.csv"
PROC_DIR = ROOT / "data" / "processed"
SEEDS_JSONL = PROC_DIR / "seeds_en.jsonl"          # main pass upload
CS_JSONL = PROC_DIR / "seeds_cs.jsonl"             # code-switch pass upload
ADAPTION_RAW = PROC_DIR / "adaption_raw.csv"       # combined staging download
GEMINI_CACHE = PROC_DIR / "gemini_cache.json"      # translation cache (avoid re-spend)
FINAL_CSV = PROC_DIR / "agent_safety_bench_ecom.csv"

DOMAIN = "ecommerce"
GEMINI_MODEL = "gemini-2.5-flash"                  # override with $GEMINI_MODEL

# A-grade annotation columns the seed author fills (editorial; never invented
# here). Read with safe defaults so a seed missing them still builds.
SEED_ANNOTATION_COLS = [
    "severity",          # none | low | high | critical
    "risk_type",         # e.g. fake_refund, data_exfiltration, account_takeover
    "attack_surface",    # e.g. refund_api, customer_db_endpoint, discount_engine
    "injection_source",  # none for benign; e.g. inbox_message, product_review
    "is_hard_benign",    # true|false — a benign that is engineered to look risky
    "evidence_phrase_en",  # the exact EN span that signals the risk
    "safe_action_en",      # what the agent should do instead
]

# Optional authored localized spans — used only if Adaption did not produce them.
SEED_FALLBACK_COLS = [
    "scenario_vi", "evidence_phrase_vi", "safe_action_vi",
    "scenario_cs", "evidence_phrase_cs", "safe_action_cs",
]

# Final column order — superset of the reference template (see module docstring).
OUTPUT_COLS = [
    # identity / label
    "base_id", "domain", "sub_category", "gold_label",
    # agent setting + action (propagated from seed; the reference bench lacks these)
    "agent_context", "tool_calls", "gold_reason",
    # the scenario in four renderings (en seed; vi/cs/en_bt from Gemini)
    "scenario_en", "scenario_vi", "scenario_cs", "scenario_en_bt",
    # risk taxonomy (A-grade)
    "severity", "risk_type", "attack_surface", "injection_source", "is_hard_benign",
    # evidence span per rendering
    "evidence_phrase_en", "evidence_phrase_vi", "evidence_phrase_cs", "evidence_phrase_en_bt",
    # corrective action per rendering
    "safe_action_en", "safe_action_vi", "safe_action_cs", "safe_action_en_bt",
    # training-style augmentation (Adaption)
    "enhanced_prompt", "enhanced_completion",
]

# Suffixes used to fan a single seed into multiple code-switch rows (scenario +
# spans) inside the cs pass, then re-join on download.
CS_EV_SUFFIX = "::ev"
CS_SA_SUFFIX = "::sa"


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

def load_seeds() -> pd.DataFrame:
    df = pd.read_csv(RAW)
    n_b = int((df["label"] == "benign").sum())
    n_s = int((df["label"] == "suspicious").sum())
    assert n_b + n_s == len(df), "every seed must be labelled benign|suspicious"
    assert n_b and n_s, "need both benign and suspicious seeds"
    if "is_hard_benign" in df.columns:
        n_hard = int((df["is_hard_benign"].astype(str).str.lower() == "true").sum())
    else:
        n_hard = 0
    print(f"[seeds] loaded {len(df)} ({n_b} benign incl {n_hard} hard / {n_s} suspicious)")
    return df


def sval(row: dict, col: str, default: str = "") -> str:
    """Read a seed cell as a clean string. Missing column or NaN -> default,
    so a seed that has not been enriched with the A-grade columns still builds."""
    v = row.get(col, default)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    return str(v).strip()


def write_seeds_jsonl(df: pd.DataFrame) -> Path:
    """Main-pass upload: `scenario_en` is the prompt column, `gold_reason` the
    completion. base_id rides along so the download can be re-joined."""
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    with SEEDS_JSONL.open("w", encoding="utf-8") as f:
        for r in df.to_dict(orient="records"):
            f.write(json.dumps({
                "base_id": r["scenario_id"],
                "scenario_en": r["user_message"],
                "agent_context": r["agent_context"],
                "gold_reason": r["gold_reason"],
            }, ensure_ascii=False) + "\n")
    return SEEDS_JSONL


def write_cs_jsonl(df: pd.DataFrame) -> Path:
    """Code-switch-pass upload. One row per English string we want code-switched:
    the scenario always, plus the evidence / safe-action spans when the seed has
    authored them. The span rows carry a suffixed base_id so the download splits
    cleanly back into scenario_cs / evidence_phrase_cs / safe_action_cs."""
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    with CS_JSONL.open("w", encoding="utf-8") as f:
        for r in df.to_dict(orient="records"):
            bid = r["scenario_id"]
            f.write(json.dumps(
                {"base_id": bid, "scenario_en": r["user_message"]},
                ensure_ascii=False) + "\n")
            ev = sval(r, "evidence_phrase_en")
            if ev:
                f.write(json.dumps(
                    {"base_id": bid + CS_EV_SUFFIX, "scenario_en": ev},
                    ensure_ascii=False) + "\n")
            sa = sval(r, "safe_action_en")
            if sa:
                f.write(json.dumps(
                    {"base_id": bid + CS_SA_SUFFIX, "scenario_en": sa},
                    ensure_ascii=False) + "\n")
    return CS_JSONL


# ---------------------------------------------------------------------------
# Adaption -- two passes (main = vi + augmentation, cs = code-switch)
# ---------------------------------------------------------------------------

VI_BLUEPRINT = (
    "You localize AI-safety e-commerce scenarios into natural Vietnamese AS REALLY "
    "TYPED by Shopee / TikTok Shop / Lazada / Facebook buyers and sellers — informal, "
    "lowercase, run-on, with authentic social-commerce slang and abbreviations: "
    "'ko'/'k' (khong), 'dc'/'duoc', 'ib'/'inbox', 'sdt', 'ad'/'shop', 'shipper', "
    "'chot don', 'ship COD', 'bom hang', 'phot', 'ma giam'/'voucher', 'sale', "
    "'nha'/'nhe'/'a', particles like 'oi', 'vs' (voi). Use this register naturally; "
    "do not overdo it. "
    "HARD CONSTRAINTS: Preserve meaning, intent, and RISK LEVEL exactly — never "
    "soften, sanitize, explain, or make a suspicious request safer or more polite. "
    "Keep ALL IDs, order codes, discount codes, prices, phone numbers, tax codes, "
    "addresses, URLs and any embedded injection payload byte-for-byte unchanged. "
    "Output ONLY the Vietnamese text, nothing else."
)

BT_BLUEPRINT = (
    "You are given ONLY a Vietnamese e-commerce message (it may contain slang and "
    "abbreviations). Translate it into plain, natural English. Translate EXACTLY what "
    "the Vietnamese says — do not consult or reconstruct any 'original'. Preserve "
    "meaning, intent, and RISK LEVEL exactly: never soften, sanitize, omit, or ADD "
    "information that is not present in the Vietnamese. Keep all IDs, codes, prices, "
    "phone numbers, addresses, URLs and any injection payload unchanged. Output ONLY "
    "the English translation, nothing else."
)

CS_BLUEPRINT = (
    "You rewrite AI-safety e-commerce scenarios into Vietnamese-English CODE-SWITCH "
    "exactly as Vietnamese Shopee / TikTok Shop / Lazada / Facebook sellers and "
    "buyers actually type. Rules: "
    "(1) The MATRIX (carrier) language is Vietnamese — connectives, pronouns, and "
    "grammar are Vietnamese. "
    "(2) KEEP IN ENGLISH every action verb, domain term, product/system/technical "
    "term, and risk-trigger word (e.g. refund, return, cancel, override, discount "
    "code, voucher, export, customer DB, disable 2FA, skip verification, shipping "
    "label, mark as paid, OTP, system prompt, API keys). Do NOT translate these. "
    "(3) Preserve meaning, intent, and RISK LEVEL exactly — never soften, sanitize, "
    "or make a suspicious request safer or more polite. "
    "(4) Keep all IDs, codes, prices, phone numbers, and addresses unchanged. "
    "Output only the rewritten sentence, nothing else."
)


def _run_pass(
    client,
    jsonl_path: Path,
    *,
    name: str,
    blueprint: str,
    map_completion: bool,
    timeout: int,
    resume_id: str | None,
) -> tuple[str | None, str | None]:
    """Run a single Adaption translate-to-vi pass and return (raw_csv, dataset_id).

    `name` is "main" or "cs" (labels logs + the --resume-<name> hint).
    `map_completion` maps gold_reason -> completion (main pass only; the cs jsonl
    has no completion column). On timeout the job keeps running server-side; we
    grab whatever is ready and print the resume command."""
    run_kwargs = dict(
        column_mapping=(
            {"prompt": "scenario_en", "completion": "gold_reason"}
            if map_completion else {"prompt": "scenario_en"}
        ),
        brand_controls={"blueprint": blueprint, "length": "detailed"},
        language_expansion={
            "type": "translate", "languages": ["vi"], "sample_rate": 1.0,
        },
        training_type="instruction_dataset",
    )

    if resume_id:
        dataset_id = resume_id
        print(f"[adaption:{name}] resuming dataset_id={dataset_id} (no re-upload/re-run)")
    else:
        print(f"[adaption:{name}] uploading {jsonl_path.name} ...")
        up = client.datasets.upload_file(str(jsonl_path))
        dataset_id = up.dataset_id
        print(f"[adaption:{name}] dataset_id={dataset_id}")

        est = client.datasets.run(dataset_id, estimate=True, **run_kwargs)
        print(f"[adaption:{name}] estimated credits: "
              f"{getattr(est, 'estimated_credits_consumed', '?')}")

        run = client.datasets.run(dataset_id, **run_kwargs)
        print(f"[adaption:{name}] run_id={getattr(run, 'run_id', '?')}")

    print(f"[adaption:{name}] waiting for completion (max {timeout}s) ...")
    try:
        status = client.datasets.wait_for_completion(dataset_id, timeout=timeout)
        print(f"[adaption:{name}] status={getattr(status, 'status', '?')}")
    except TimeoutError:
        print(f"[adaption:{name}] still running after {timeout}s. The job continues "
              f"on the platform. Re-run later with:\n"
              f"    python -m src.build_dataset --resume-{name} {dataset_id}")

    try:
        raw = client.datasets.download(dataset_id, file_format="csv")
        return raw, dataset_id
    except Exception as e:  # noqa: BLE001 -- nothing ready yet is fine
        print(f"[adaption:{name}] no output ready yet ({e}); pass left blank.")
        return None, dataset_id


def run_adaption(
    main_jsonl: Path,
    cs_jsonl: Path,
    *,
    timeout: int = 1800,
    resume_main: str | None = None,
    resume_cs: str | None = None,
    do_cs_pass: bool = False,
) -> dict[str, dict[str, str]]:
    """Run the Adaption augmentation pass(es), write the combined staging CSV, and
    return { base_id: {enhanced_prompt, enhanced_completion, scenario_vi, ...} }.

    Translation (vi/cs/en_bt) is owned by Gemini now; Adaption is kept only for the
    enhanced_* instruction-dataset augmentation. The main pass still emits a vi
    rendering, retained as a fallback when Gemini is skipped. The code-switch pass
    is off by default (Gemini produces scenario_cs); enable it with do_cs_pass.

    Returns {} (columns left blank) if the SDK/key is unavailable. The combined
    raw download is saved either way for hand-mapping / re-parsing."""
    try:
        from adaption import Adaption
    except ImportError:
        print("[adaption] SDK not installed; skipping. `pip install adaption`")
        return {}

    api_key = os.environ.get("ADAPTION_API_KEY")
    if not api_key:
        print("[adaption] ADAPTION_API_KEY not set; skipping.")
        return {}

    client = Adaption(api_key=api_key)

    raw_main, _ = _run_pass(
        client, main_jsonl, name="main", blueprint=VI_BLUEPRINT,
        map_completion=True, timeout=timeout, resume_id=resume_main,
    )
    if do_cs_pass:
        raw_cs, _ = _run_pass(
            client, cs_jsonl, name="cs", blueprint=CS_BLUEPRINT,
            map_completion=False, timeout=timeout, resume_id=resume_cs,
        )
    else:
        print("[adaption] cs pass skipped (Gemini owns code-switch).")
        raw_cs = None

    combined = combine_raw(raw_main, raw_cs)
    ADAPTION_RAW.write_text(combined, encoding="utf-8")
    print(f"[adaption] combined raw output saved -> {ADAPTION_RAW}")

    return parse_adaption_csv(combined)


def _pick(fieldnames: list[str], *candidates: str) -> str | None:
    lower = {f.lower(): f for f in fieldnames}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def combine_raw(raw_main: str | None, raw_cs: str | None) -> str:
    """Concatenate both pass downloads into one self-describing CSV. Every row
    keeps its original columns and gains:
        variant : enhanced | vi | cs | cs_evidence | cs_safe_action
        _run    : main | cs
    The cs pass's English/augmented rows are dropped (we only keep its vi-tagged
    code-switch output)."""
    rows: list[dict[str, str]] = []
    fieldset: set[str] = set()

    def ingest(raw: str | None, run: str) -> None:
        if not raw:
            return
        reader = csv.DictReader(io.StringIO(raw))
        fields = reader.fieldnames or []
        lang_col = _pick(fields, "language", "lang", "target_language", "locale")
        id_col = _pick(fields, "base_id", "scenario_id", "id")
        for row in reader:
            lang = (row.get(lang_col, "") or "").lower() if lang_col else ""
            bid = (row.get(id_col, "") or "") if id_col else ""
            if run == "main":
                variant = "vi" if lang.startswith("vi") else "enhanced"
            else:  # cs pass: keep only the code-switched (vi-tagged) rows
                if not lang.startswith("vi"):
                    continue
                if bid.endswith(CS_EV_SUFFIX):
                    variant = "cs_evidence"
                elif bid.endswith(CS_SA_SUFFIX):
                    variant = "cs_safe_action"
                else:
                    variant = "cs"
            row = dict(row)
            row["variant"] = variant
            row["_run"] = run
            rows.append(row)
            fieldset.update(row.keys())

    ingest(raw_main, "main")
    ingest(raw_cs, "cs")

    ordered = ["variant", "_run"] + sorted(f for f in fieldset
                                           if f not in ("variant", "_run"))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ordered)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in ordered})
    return buf.getvalue()


def parse_adaption_csv(raw: str) -> dict[str, dict[str, str]]:
    """Merge the combined staging CSV back onto base_id, routing each row by its
    `variant` tag. Falls back to language-based routing for a legacy file that
    predates the variant column (it simply won't carry any cs columns)."""
    reader = csv.DictReader(io.StringIO(raw))
    fields = reader.fieldnames or []
    id_col = _pick(fields, "base_id", "scenario_id", "id")
    # The translated / augmented text lands in the prompt column of each row.
    prompt_col = _pick(fields, "enhanced_prompt", "prompt", "augmented_prompt",
                       "scenario_en", "text")
    compl_col = _pick(fields, "enhanced_completion", "completion",
                      "augmented_completion")
    has_variant = "variant" in fields
    lang_col = _pick(fields, "language", "lang", "target_language", "locale")

    if not (id_col and prompt_col):
        print(f"[adaption] could not locate expected columns in {fields!r}; "
              f"leaving Adaption columns blank. Map {ADAPTION_RAW.name} by hand "
              f"if needed.")
        return {}

    def blank() -> dict[str, str]:
        return {
            "enhanced_prompt": "", "enhanced_completion": "", "scenario_vi": "",
            "scenario_cs": "", "evidence_phrase_cs": "", "safe_action_cs": "",
        }

    out: dict[str, dict[str, str]] = {}
    for row in reader:
        raw_bid = row.get(id_col, "") or ""
        if not raw_bid:
            continue
        # Strip the cs span suffix so all variants land on the same base record.
        bid = raw_bid.split("::", 1)[0]
        rec = out.setdefault(bid, blank())

        if has_variant:
            variant = (row.get("variant", "") or "").lower()
        else:  # legacy file: infer from language (no cs available)
            lang = (row.get(lang_col, "") or "").lower() if lang_col else ""
            variant = "vi" if lang.startswith("vi") else "enhanced"

        val = (row.get(prompt_col, "") or "").strip()
        if variant == "enhanced":
            rec["enhanced_prompt"] = row.get(prompt_col, "")
            rec["enhanced_completion"] = row.get(compl_col, "") if compl_col else ""
        elif variant == "vi":
            rec["scenario_vi"] = val or rec["scenario_vi"]
        elif variant == "cs":
            rec["scenario_cs"] = val or rec["scenario_cs"]
        elif variant == "cs_evidence":
            rec["evidence_phrase_cs"] = val or rec["evidence_phrase_cs"]
        elif variant == "cs_safe_action":
            rec["safe_action_cs"] = val or rec["safe_action_cs"]
    return out


# ---------------------------------------------------------------------------
# Gemini -- translation (vi + code-switch + blind back-translated en)
# ---------------------------------------------------------------------------

def _gemini_cache_load() -> dict[str, str]:
    if GEMINI_CACHE.exists():
        try:
            return json.loads(GEMINI_CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _gen(client, model: str, blueprint: str, text: str, cache: dict[str, str]) -> str:
    """One cached Gemini call. The cache key includes the blueprint, so editing a
    blueprint re-translates only the rows it touches; unchanged rows stay free."""
    text = (text or "").strip()
    if not text:
        return ""
    key = hashlib.sha1(f"{model}\x1f{blueprint}\x1f{text}".encode("utf-8")).hexdigest()
    if key in cache:
        return cache[key]
    prompt = f"{blueprint}\n\nInput:\n{text}"
    last_err = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            out = (resp.text or "").strip()
            cache[key] = out
            return out
        except Exception as e:  # noqa: BLE001 -- transient rate-limit / network
            last_err = e
            time.sleep(2 * (attempt + 1))
    print(f"[gemini] call failed after retries: {last_err}")
    return ""


def gemini_translate(
    df: pd.DataFrame, *, model: str, skip: bool = False,
) -> dict[str, dict[str, str]]:
    """Translate every seed into Vietnamese (slang-rich), code-switch, and a BLIND
    back-translated English (produced from the Vietnamese ONLY, never the EN seed).
    The same three renderings are applied to the authored evidence / safe-action
    spans when present. Results are cached to gemini_cache.json so re-runs and
    incremental seed edits do not re-spend. Returns {} (columns blank) if the SDK
    or key is missing, so the dataset still builds offline."""
    if skip:
        print("[gemini] --skip-gemini set; vi/cs/en_bt left blank.")
        return {}
    try:
        from google import genai
    except ImportError:
        print("[gemini] SDK not installed; skipping. `pip install google-genai`")
        return {}
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[gemini] GEMINI_API_KEY not set; skipping.")
        return {}

    client = genai.Client(api_key=api_key)
    cache = _gemini_cache_load()
    n0 = len(cache)
    out: dict[str, dict[str, str]] = {}
    print(f"[gemini] translating {len(df)} seeds with {model} "
          f"(cache: {n0} entries) ...")
    try:
        for r in df.to_dict(orient="records"):
            bid = r["scenario_id"]
            en = r["user_message"]
            vi = _gen(client, model, VI_BLUEPRINT, en, cache)
            cs = _gen(client, model, CS_BLUEPRINT, en, cache)
            en_bt = _gen(client, model, BT_BLUEPRINT, vi, cache)  # BLIND: from vi only
            rec = {
                "scenario_vi": vi, "scenario_cs": cs, "scenario_en_bt": en_bt,
                "evidence_phrase_vi": "", "evidence_phrase_cs": "",
                "evidence_phrase_en_bt": "", "safe_action_vi": "",
                "safe_action_cs": "", "safe_action_en_bt": "",
            }
            ev = sval(r, "evidence_phrase_en")
            if ev:
                ev_vi = _gen(client, model, VI_BLUEPRINT, ev, cache)
                rec["evidence_phrase_vi"] = ev_vi
                rec["evidence_phrase_cs"] = _gen(client, model, CS_BLUEPRINT, ev, cache)
                rec["evidence_phrase_en_bt"] = _gen(client, model, BT_BLUEPRINT, ev_vi, cache)
            sa = sval(r, "safe_action_en")
            if sa:
                sa_vi = _gen(client, model, VI_BLUEPRINT, sa, cache)
                rec["safe_action_vi"] = sa_vi
                rec["safe_action_cs"] = _gen(client, model, CS_BLUEPRINT, sa, cache)
                rec["safe_action_en_bt"] = _gen(client, model, BT_BLUEPRINT, sa_vi, cache)
            out[bid] = rec
    finally:
        GEMINI_CACHE.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print(f"[gemini] done; cache {n0} -> {len(cache)} entries "
              f"(+{len(cache) - n0} new) -> {GEMINI_CACHE.name}")
    return out


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def assemble(
    df: pd.DataFrame,
    adaption: dict[str, dict[str, str]],
    gemini: dict[str, dict[str, str]],
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for r in df.to_dict(orient="records"):
        bid = r["scenario_id"]
        en = r["user_message"]
        label = r["label"]
        aug = adaption.get(bid, {})
        gem = gemini.get(bid, {})

        # Authored EN spans (blank until the seed is enriched).
        ev_en = sval(r, "evidence_phrase_en")
        sa_en = sval(r, "safe_action_en")

        # is_hard_benign only makes sense for benign rows; default false.
        is_hard_benign = sval(r, "is_hard_benign", "false").lower() or "false"
        if label != "benign":
            is_hard_benign = "false"
        # benign rows carry no risk -> severity defaults to "none".
        severity = sval(r, "severity") or ("none" if label == "benign" else "")
        injection_source = (
            sval(r, "injection_source")
            or ("none" if label == "benign" else "")
        )

        # Localized fields: prefer Gemini, then Adaption, then authored seed.
        scenario_vi = (gem.get("scenario_vi", "") or aug.get("scenario_vi", "")
                       or sval(r, "scenario_vi"))
        scenario_cs = (gem.get("scenario_cs", "") or aug.get("scenario_cs", "")
                       or sval(r, "scenario_cs"))
        scenario_en_bt = gem.get("scenario_en_bt", "") or sval(r, "scenario_en_bt")
        ev_vi = gem.get("evidence_phrase_vi", "") or sval(r, "evidence_phrase_vi")
        sa_vi = gem.get("safe_action_vi", "") or sval(r, "safe_action_vi")
        ev_cs = (gem.get("evidence_phrase_cs", "") or aug.get("evidence_phrase_cs", "")
                 or sval(r, "evidence_phrase_cs"))
        sa_cs = (gem.get("safe_action_cs", "") or aug.get("safe_action_cs", "")
                 or sval(r, "safe_action_cs"))
        ev_en_bt = gem.get("evidence_phrase_en_bt", "") or sval(r, "evidence_phrase_en_bt")
        sa_en_bt = gem.get("safe_action_en_bt", "") or sval(r, "safe_action_en_bt")

        rows.append({
            # identity / label (all invariant, from seed)
            "base_id": bid,
            "domain": DOMAIN,
            "sub_category": sval(r, "sub_category"),
            "gold_label": label,
            # agent setting + action (propagated — the reference bench drops these)
            "agent_context": sval(r, "agent_context"),
            "tool_calls": sval(r, "tool_calls"),
            "gold_reason": sval(r, "gold_reason"),
            # scenario in four renderings (vi + cs + en_bt from Gemini)
            "scenario_en": en,
            "scenario_vi": scenario_vi,
            "scenario_cs": scenario_cs,
            "scenario_en_bt": scenario_en_bt,
            # risk taxonomy (authored)
            "severity": severity,
            "risk_type": sval(r, "risk_type"),
            "attack_surface": sval(r, "attack_surface"),
            "injection_source": injection_source,
            "is_hard_benign": is_hard_benign,
            # evidence span per rendering
            "evidence_phrase_en": ev_en,
            "evidence_phrase_vi": ev_vi,
            "evidence_phrase_cs": ev_cs,
            "evidence_phrase_en_bt": ev_en_bt,
            # corrective action per rendering
            "safe_action_en": sa_en,
            "safe_action_vi": sa_vi,
            "safe_action_cs": sa_cs,
            "safe_action_en_bt": sa_en_bt,
            # training-style augmentation
            "enhanced_prompt": aug.get("enhanced_prompt", ""),
            "enhanced_completion": aug.get("enhanced_completion", ""),
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLS)


def qc_report(out: pd.DataFrame) -> None:
    """Back-translation sanity gate. gold_label is structurally invariant across
    renderings (one row, one label), so the real risk is the round trip
    (en -> vi -> en_bt) silently laundering the risk out. We check that suspicious
    rows keep a populated evidence span end-to-end and flag any that lost it.
    Heuristic (presence, not semantics) — flagged rows want a human/LLM look."""
    def filled(col):
        return out[col].astype(str).str.strip().astype(bool)

    is_susp = out["gold_label"] == "suspicious"
    have_ev = is_susp & filled("evidence_phrase_en")
    if have_ev.any():
        survived = (have_ev & filled("evidence_phrase_en_bt")).sum()
        print("[qc] back-translation cue survival (suspicious rows):")
        print(f"    evidence span present after en->vi->en_bt: "
              f"{survived}/{have_ev.sum()}")
        lost = out[have_ev & ~filled("evidence_phrase_en_bt")]
        for bid in lost["base_id"]:
            print(f"    ! {bid}: evidence cue blank in en_bt — review the vi rendering")
    miss_vi = (is_susp & ~filled("scenario_vi")).sum()
    miss_bt = (is_susp & ~filled("scenario_en_bt")).sum()
    if miss_vi or miss_bt:
        print(f"[qc] suspicious rows missing scenario_vi={miss_vi} "
              f"scenario_en_bt={miss_bt} (translation incomplete / skipped)")


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-gemini", action="store_true",
                    help="offline: no vi/cs/en_bt translation (Gemini)")
    ap.add_argument("--gemini-model",
                    default=os.environ.get("GEMINI_MODEL", GEMINI_MODEL),
                    help=f"Gemini model id (default {GEMINI_MODEL} or $GEMINI_MODEL)")
    ap.add_argument("--skip-adaption", action="store_true",
                    help="skip the enhanced_* augmentation (Adaption)")
    ap.add_argument("--adaption-cs", action="store_true",
                    help="also run the Adaption code-switch pass "
                         "(off by default; Gemini owns code-switch)")
    ap.add_argument("--adaption-timeout", type=int, default=1800,
                    help="seconds to wait for each Adaption pass (default 1800)")
    ap.add_argument("--resume-main", metavar="DATASET_ID", default=None,
                    help="wait+download an existing main-pass dataset_id instead "
                         "of uploading and running it again (saves credits)")
    ap.add_argument("--resume-cs", metavar="DATASET_ID", default=None,
                    help="wait+download an existing code-switch-pass dataset_id "
                         "instead of uploading and running it again")
    args = ap.parse_args()

    df = load_seeds()
    main_jsonl = write_seeds_jsonl(df)
    cs_jsonl = write_cs_jsonl(df)
    print(f"[seeds] wrote {main_jsonl.name} + {cs_jsonl.name} ({len(df)} seeds)")

    gemini = gemini_translate(df, model=args.gemini_model, skip=args.skip_gemini)

    adaption: dict[str, dict[str, str]] = {}
    if not args.skip_adaption:
        adaption = run_adaption(
            main_jsonl, cs_jsonl,
            timeout=args.adaption_timeout,
            resume_main=args.resume_main,
            resume_cs=args.resume_cs,
            do_cs_pass=args.adaption_cs,
        )

    out = assemble(df, adaption, gemini)
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(FINAL_CSV, index=False)
    qc_report(out)

    # B -> A progress meter: how complete is each A-grade column.
    n = len(out)
    print(f"[final] wrote {FINAL_CSV} ({n} rows)")
    print("[final] A-grade column coverage:")
    for col in ["scenario_vi", "scenario_cs", "scenario_en_bt", "severity",
                "risk_type", "attack_surface", "injection_source",
                "evidence_phrase_en", "evidence_phrase_vi", "evidence_phrase_cs",
                "evidence_phrase_en_bt", "safe_action_en", "safe_action_vi",
                "safe_action_cs", "safe_action_en_bt"]:
        filled = (out[col].astype(str).str.strip().astype(bool)).sum()
        bar = "ok " if filled == n else "  -"
        print(f"    {bar} {col:<22} {filled}/{n}")
    n_hard = (out["is_hard_benign"].astype(str).str.lower() == "true").sum()
    n_benign = (out["gold_label"] == "benign").sum()
    print(f"    {'ok ' if n_hard else '  -'} is_hard_benign=true     {n_hard} "
          f"(of {n_benign} benigns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
