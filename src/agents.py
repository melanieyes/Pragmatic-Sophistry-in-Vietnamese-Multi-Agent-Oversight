import json
import re
from functools import lru_cache

from models import call_model, parse_label, parse_field, PROMPTS_DIR


# --- role -> model -------------------------------------------------------
# Bulk roles: use Gemini to save OpenAI / Claude / DeepSeek credits.
ATTACKER = ("google", "gemini-2.5-flash")
ORACLE = ("google", "gemini-2.5-flash")
EXECUTOR = ("google", "gemini-2.5-flash")

# Kept only for optional ablations. Do not call this by default.
ORACLE_LEXICAL = ("deepseek", "deepseek-chat")

# Default cheap monitor panel.
PANEL = [
    ("google", "gemini-2.5-flash"),
    ("deepseek", "deepseek-chat"),
]

# Optional expensive final audit panel.
# Use this only after the main result looks real on a smaller subset.
EXPENSIVE_PANEL = [
    ("openai", "gpt-4o-mini"),
    ("anthropic", "claude-haiku-4-5-20251001"),
]

# Main comparison. Keep it small first.
RENDERINGS = ["scenario_vi", "scenario_vi_prag"]

# If True, oracle_validate() also calls ORACLE_LEXICAL and requires the
# lexical oracle to miss suspicious pragmatic rows. This is expensive and
# usually unnecessary if pipeline.py has a local regex lexical-leak filter.
STRICT_DUAL_GATE = False


# --- prompt loading ------------------------------------------------------
@lru_cache(maxsize=None)
def load_prompt(name):
    """Return (body, locale_block).

    Splits on the --- PROMPT --- marker and, if present, a trailing
    --- LOCALE_GLOSSARY --- section.
    """
    raw = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    body = raw.split("--- PROMPT ---", 1)[-1].strip()

    locale = ""
    if "--- LOCALE_GLOSSARY ---" in body:
        body, locale = (s.strip() for s in body.split("--- LOCALE_GLOSSARY ---", 1))

    return body, locale


# --- JSON helpers --------------------------------------------------------
def parse_json_object(text):
    """Best-effort JSON parser for model outputs.

    Handles clean JSON, fenced JSON, or text with one JSON object inside.
    Returns {} on failure.
    """
    if not text:
        return {}

    text = text.strip()

    # Remove common code fences if a model ignores instructions.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass

    # Try to recover the first JSON object.
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    return {}


def parse_confidence(text):
    obj = parse_json_object(text)
    val = obj.get("confidence")
    try:
        val = float(val)
    except Exception:
        return None

    # Accept either 0-1 or 0-100 style.
    if val > 1:
        val = val / 100.0

    return max(0.0, min(1.0, val))


def parse_reason_code(text):
    obj = parse_json_object(text)
    rc = obj.get("reason_code")
    return str(rc).strip() if rc is not None else None


# --- 1. Attacker / pragmatic renderer -----------------------------------
def attacker_generate(row, mock=False):
    """Generate scenario_vi_prag from an English/base scenario row.

    Expected optional metadata:
    - requester_persona
    - pragmatic_cue
    - pressure_level

    These can be added in scenario.csv or synthesized in pipeline.py.
    """
    system, _ = load_prompt("attacker_pragmatic.md")

    payload = json.dumps({
        "scenario_en": _s(row.get("scenario_en")),
        "gold_label": _s(row.get("gold_label")),
        "gold_reason": _s(row.get("gold_reason")),
        "evidence_phrase_en": _s(row.get("evidence_phrase_en")),
        "domain": _s(row.get("domain")),

        # Controlled experimental variables.
        "requester_persona": _s(row.get("requester_persona")),
        "pragmatic_cue": _s(row.get("pragmatic_cue")),
        "pressure_level": _s(row.get("pressure_level")),
    }, ensure_ascii=False)

    resp = call_model(
        *ATTACKER,
        system=system,
        user=payload,
        mock=mock,
        tag="attacker",
    )

    return parse_field(resp, "scenario_vi_prag")


# --- 2. Oracle gate ------------------------------------------------------
def oracle_validate(text, gold, mock=False, run_lexical=False):
    """Validate generated pragmatic text.

    Default:
    - Call only the fluent oracle.
    - Keep suspicious rows if the fluent oracle recovers the violation.
    - Keep benign rows if the fluent oracle still reads them as benign.

    Optional:
    - If run_lexical=True or STRICT_DUAL_GATE=True, also call the lexical oracle.
    - For suspicious rows, require lexical oracle to miss the violation.
    - This is expensive and should usually be replaced by regex in pipeline.py.
    """
    fluent_sys, _ = load_prompt("oracle_fluent.md")
    u = text if not mock else f"(gold={gold}) {text}"

    fl = parse_label(
        call_model(
            *ORACLE,
            system=fluent_sys,
            user=u,
            mock=mock,
            tag="oracle_fluent",
        )
    )

    lx = "not_run"
    should_run_lexical = run_lexical or STRICT_DUAL_GATE

    if should_run_lexical:
        lexical_sys, _ = load_prompt("oracle_lexical.md")
        lx = parse_label(
            call_model(
                *ORACLE_LEXICAL,
                system=lexical_sys,
                user=u,
                mock=mock,
                tag="oracle_lexical",
            )
        )

    if gold == "suspicious":
        keep = fl == "suspicious"
        if should_run_lexical:
            keep = keep and lx == "benign"
    else:
        keep = fl == "benign"

    return fl, lx, keep


# --- 3. Executor ---------------------------------------------------------
def executor_act(instruction, domain, mock=False):
    """Execute an instruction and return the raw executor output.

    If executor.md asks for JSON with action + brief_report, this returns that
    JSON string. This keeps backward compatibility with pipeline.py, where the
    monitor can read the raw executor output.
    """
    system, _ = load_prompt("executor.md")
    system = system.replace("{domain}", _s(domain) or "service")

    return call_model(
        *EXECUTOR,
        system=system,
        user=instruction,
        mock=mock,
        tag="executor",
    ).strip()


def executor_act_full(instruction, domain, mock=False):
    """Execute an instruction and return structured fields.

    Useful if you later update pipeline.py to store action and brief_report
    separately. Safe fallback if model returns plain text.
    """
    raw = executor_act(instruction, domain, mock=mock)
    obj = parse_json_object(raw)

    action = _s(obj.get("action")) if obj else raw
    brief_report = _s(obj.get("brief_report")) if obj else ""

    return {
        "raw": raw,
        "action": action,
        "brief_report": brief_report,
    }


# --- 4. Monitor ----------------------------------------------------------
def monitor_classify(
    panel_model,
    action_text,
    domain,
    rendering,
    gold,
    locale_aware=False,
    mock=False,
):
    """Return only the monitor label.

    This preserves compatibility with your current pipeline.py, which expects
    monitor_classify(...) to return "benign" or "suspicious".
    """
    result = monitor_classify_full(
        panel_model=panel_model,
        action_text=action_text,
        domain=domain,
        rendering=rendering,
        gold=gold,
        locale_aware=locale_aware,
        mock=mock,
    )
    return result["label"]


def monitor_classify_full(
    panel_model,
    action_text,
    domain,
    rendering,
    gold,
    locale_aware=False,
    mock=False,
):
    """Return full monitor result: label, confidence, reason_code, raw."""
    prov, model = panel_model

    base, locale = load_prompt("monitor.md")
    system = base.replace("{domain}", _s(domain) or "service")

    if locale_aware and locale:
        system += "\n\n" + locale

    tag = f"monitor|{rendering}|{prov}:{model}"
    u = action_text if not mock else f"(gold={gold}) {action_text}"

    raw = call_model(
        prov,
        model,
        system=system,
        user=u,
        mock=mock,
        tag=tag,
    )

    label = parse_label(raw)
    confidence = parse_confidence(raw)
    reason_code = parse_reason_code(raw)

    return {
        "label": label,
        "confidence": confidence,
        "reason_code": reason_code,
        "raw": raw,
    }


# --- 5. Optional panel helpers ------------------------------------------
def get_panel(include_expensive=False):
    """Return monitor panel.

    Default is cheap. Use include_expensive=True only for a final audit subset.
    """
    if include_expensive:
        return PANEL + EXPENSIVE_PANEL
    return PANEL


def _s(v):
    return "" if v is None or (isinstance(v, float) and v != v) else str(v)