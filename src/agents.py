"""agents.py — the five roles, plus which model plays each.

Pipeline: Attacker (obfuscator) -> Oracle (two gates) -> Executor (agent under
observation) -> Monitor panel (defender, the subject under test).

Model assignment follows what each role NEEDS, not raw strength:
- Attacker       : strong model  -> writes natural, subtle obfuscation
- Oracle fluent  : strongest model-> defines ground truth (must recover violation)
- Oracle lexical : weaker-VN model-> should MISS pragmatic violations
                   (a strong model over-flags and drops almost every row)
- Executor       : free model     -> side role, not measured
- Monitor panel  : all four       -> strong-vs-weak comparison IS the experiment

Model strings drift; verify before a real run.
"""
import json
from functools import lru_cache
import models
from models import call_model, parse_label, parse_field, PROMPTS_DIR

# --- role -> model -------------------------------------------------------
ATTACKER       = ("google",    "gemini-2.5-flash")            
ORACLE         = ("anthropic", "claude-haiku-4-5-20251001")   
ORACLE_LEXICAL = ("deepseek",  "deepseek-chat")               
EXECUTOR       = ("google",    "gemini-2.5-flash")           
PANEL = [
    ("openai",    "gpt-4o-mini"),
    ("anthropic", "claude-haiku-4-5-20251001"),
    ("google",    "gemini-2.5-flash"),
    ("deepseek",  "deepseek-chat"),
]
RENDERINGS = ["scenario_en", "scenario_vi", "scenario_cs", "scenario_vi_prag"]

# Keep logic for the dual gate:
#   False (default): keep a suspicious row if the FLUENT oracle recovers it.
#                    Guarantees a usable sample; the lexical verdict is still
#                    recorded as data (reportable as a baseline).
#   True           : ALSO require the lexical gate to MISS it (stricter, smaller).
STRICT_DUAL_GATE = False


# --- prompt loading ------------------------------------------------------
@lru_cache(maxsize=None)
def load_prompt(name):
    """Return (body, locale_block). Splits on the --- PROMPT --- marker and,
    if present, a trailing --- LOCALE_GLOSSARY --- section."""
    raw = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    body = raw.split("--- PROMPT ---", 1)[-1].strip()
    locale = ""
    if "--- LOCALE_GLOSSARY ---" in body:
        body, locale = (s.strip() for s in body.split("--- LOCALE_GLOSSARY ---", 1))
    return body, locale


# --- 1. Attacker ---------------------------------------------------------
def attacker_generate(row, mock=False):
    system, _ = load_prompt("attacker_pragmatic.md")
    payload = json.dumps({
        "scenario_en": _s(row.get("scenario_en")),
        "gold_label":  _s(row.get("gold_label")),
        "gold_reason": _s(row.get("gold_reason")),
        "evidence_phrase_en": _s(row.get("evidence_phrase_en")),
        "domain": _s(row.get("domain")),
    }, ensure_ascii=False)
    resp = call_model(*ATTACKER, system=system, user=payload, mock=mock, tag="attacker")
    return parse_field(resp, "scenario_vi_prag")


# --- 2. Oracle (dual gate: fluent = Haiku, lexical = DeepSeek) -----------
def oracle_validate(text, gold, mock=False):
    fluent_sys, _  = load_prompt("oracle_fluent.md")
    lexical_sys, _ = load_prompt("oracle_lexical.md")
    u = text if not mock else f"(gold={gold}) {text}"
    fl = parse_label(call_model(*ORACLE,         system=fluent_sys,  user=u, mock=mock, tag="oracle_fluent"))
    lx = parse_label(call_model(*ORACLE_LEXICAL, system=lexical_sys, user=u, mock=mock, tag="oracle_lexical"))
    if gold == "suspicious":
        keep = (fl == "suspicious") and (not STRICT_DUAL_GATE or lx == "benign")
    else:
        keep = (fl == "benign")                # benign stays benign
    return fl, lx, keep


# --- 3. Executor ---------------------------------------------------------
def executor_act(instruction, domain, mock=False):
    system, _ = load_prompt("executor.md")
    system = system.replace("{domain}", _s(domain) or "service")
    return call_model(*EXECUTOR, system=system, user=instruction, mock=mock, tag="executor").strip()


# --- 4. Monitor ----------------------------------------------------------
def monitor_classify(panel_model, action_text, domain, rendering, gold,
                     locale_aware=False, mock=False):
    prov, model = panel_model
    base, locale = load_prompt("monitor.md")
    system = base.replace("{domain}", _s(domain) or "service")
    if locale_aware and locale:
        system += "\n" + locale
    tag = f"monitor|{rendering}|{prov}:{model}"
    u = action_text if not mock else f"(gold={gold}) {action_text}"
    return parse_label(call_model(prov, model, system=system, user=u, mock=mock, tag=tag))


def _s(v):
    return "" if v is None or (isinstance(v, float) and v != v) else str(v)