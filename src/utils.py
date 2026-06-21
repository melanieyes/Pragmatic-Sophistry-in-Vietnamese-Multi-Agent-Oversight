"""Shared helpers for the VN banking AI-safety dataset pipeline.

Centralises:
  * environment / API-key loading,
  * the ``AdaptionRunner`` wrapper that isolates every Adaption SDK call,
  * language-detection + embedding helpers used by the validator and diversity gate,
  * a thin Anthropic completion helper for the monitor harness.

Keeping the Adaption surface behind one class means that if the SDK shape ever
changes only this file needs editing (see the plan's "Open Dependency" note).
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any, Optional, Sequence

import pandas as pd

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
PROMPTS = ROOT / "prompts"
RESULTS = ROOT / "results"

for _d in (DATA_RAW, DATA_PROCESSED, RESULTS):
    _d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
def load_keys() -> dict[str, str]:
    """Load ``.env`` and return the API keys we use. Missing keys are empty."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:  # pragma: no cover - dotenv optional at runtime
        pass
    return {
        "adaption": os.environ.get("ADAPTION_API_KEY", ""),
        "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
        "gemini": os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", ""),
        "deepseek": os.environ.get("DEEPSEEK_API_KEY", ""),
    }


# --------------------------------------------------------------------------- #
# Adaption wrapper
# --------------------------------------------------------------------------- #
class AdaptionRunner:
    """Thin, well-logged wrapper around the Adaption datasets resource.

    Verified against adaption==0.4.0:
      * ``client.datasets.upload_file(path)`` -> response with ``.dataset_id``
      * ``client.datasets.get_status(id)``   -> ``.row_count``, ``.status``
      * ``client.datasets.run(id, **params)``-> ``.estimated_credits_consumed`` (estimate)
      * ``client.datasets.wait_for_completion(id)``
      * ``client.datasets.download(id, file_format="csv")`` -> CSV string
    """

    def __init__(self, api_key: Optional[str] = None):
        from adaption import Adaption  # imported lazily so non-gen steps don't need it

        key = api_key or os.environ.get("ADAPTION_API_KEY")
        if not key:
            raise RuntimeError("ADAPTION_API_KEY not set (check .env).")
        self.client = Adaption(api_key=key)

    # -- low level ---------------------------------------------------------- #
    def upload(self, path: str | os.PathLike[str]) -> str:
        import time

        resp = self.client.datasets.upload_file(str(path))
        dataset_id = resp.dataset_id
        status = None
        for _ in range(60):  # wait for row_count to populate (parse finished)
            status = self.client.datasets.get_status(dataset_id)
            if status.row_count is not None:
                break
            time.sleep(2)
        rc = status.row_count if status else "?"
        print(f"[adaption] uploaded {path} -> {dataset_id} ({rc} rows)")
        return dataset_id

    def estimate(
        self,
        dataset_id: str,
        column_mapping: dict[str, Any],
        blueprint: str,
        *,
        length: str = "detailed",
        training_type: str = "instruction_dataset",
        language_expansion: Optional[dict[str, Any]] = None,
    ):
        resp = self.client.datasets.run(
            dataset_id,
            column_mapping=column_mapping,
            brand_controls={"blueprint": blueprint, "length": length},
            training_type=training_type,
            language_expansion=language_expansion,
            estimate=True,
        )
        print(
            f"[adaption] ESTIMATE dataset={dataset_id} "
            f"credits={resp.estimated_credits_consumed} minutes={resp.estimated_minutes}"
        )
        return resp

    def execute(
        self,
        dataset_id: str,
        column_mapping: dict[str, Any],
        blueprint: str,
        *,
        length: str = "detailed",
        training_type: str = "instruction_dataset",
        language_expansion: Optional[dict[str, Any]] = None,
        max_rows: Optional[int] = None,
    ) -> pd.DataFrame:
        """Launch a real run, wait for completion, return the processed rows."""
        kwargs: dict[str, Any] = dict(
            column_mapping=column_mapping,
            brand_controls={"blueprint": blueprint, "length": length},
            training_type=training_type,
            language_expansion=language_expansion,
            estimate=False,
        )
        if max_rows:
            kwargs["job_specification"] = {"max_rows": float(max_rows)}
        resp = self.client.datasets.run(dataset_id, **kwargs)
        print(f"[adaption] RUN started dataset={dataset_id} run_id={getattr(resp, 'run_id', None)}")
        self.client.datasets.wait_for_completion(dataset_id)
        return self.download_df(dataset_id)

    def download_df(self, dataset_id: str) -> pd.DataFrame:
        csv_text = self.client.datasets.download(dataset_id, file_format="csv")
        return pd.read_csv(io.StringIO(csv_text))


# --------------------------------------------------------------------------- #
# Language helpers
# --------------------------------------------------------------------------- #
def detect_lang(text: str) -> str:
    """Best-effort ISO language code via langdetect (deterministic seed)."""
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(text)
    except Exception:
        return "unknown"


_WORD_RE = re.compile(r"[A-Za-z]+")
# Compact set of English/technical tokens expected to survive in code-switch text.
EN_TECH_TOKENS = {
    "otp", "api", "verification", "verify", "approve", "approval", "credit", "check",
    "bypass", "connect", "transaction", "qr", "transfer", "account", "limit", "token",
    "refund", "loan", "kyc", "card", "balance", "agent", "disable", "production",
    "ssl", "tls", "certificate", "request", "override", "recurring", "fee", "app",
}
# Vietnamese function words used to confirm a Vietnamese matrix in code-switch text.
VI_FUNCTION_WORDS = {
    "và", "của", "cho", "để", "không", "là", "này", "với", "trên", "trong", "một",
    "khi", "việc", "các", "đã", "bị", "lên", "nên", "thì", "mà", "tài", "khoản",
}


def english_token_ratio(text: str) -> float:
    """Fraction of word tokens that are pure-ASCII (English carries no diacritics)."""
    words = re.findall(r"\b[\wà-ỹÀ-Ỹ]+\b", text or "")
    if not words:
        return 0.0
    pure_ascii = [w for w in words if w.isascii()]
    return len(pure_ascii) / len(words)


def has_en_tech_token(text: str) -> bool:
    toks = {w.lower() for w in _WORD_RE.findall(text or "")}
    return bool(toks & EN_TECH_TOKENS)


def has_vi_function_word(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in VI_FUNCTION_WORDS)


# Vietnamese-specific diacritic characters — the most robust signal that text is
# Vietnamese, and (unlike a function-word whitelist) it survives heavy slang/teencode.
_VI_DIACRITICS = set(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
)


def vi_diacritic_count(text: str) -> int:
    return sum(1 for c in (text or "").lower() if c in _VI_DIACRITICS)


def looks_vietnamese(text: str, min_diacritics: int = 3, max_english_ratio: float = 0.85) -> bool:
    """True if text is recognisably Vietnamese even when written in heavy slang/teencode.

    Diacritic presence is the primary signal (robust to informal spelling that drops
    formal function words); the English-token ratio guards against an all-English string
    that happens to contain a stray accented char.
    """
    return vi_diacritic_count(text) >= min_diacritics and english_token_ratio(text) <= max_english_ratio


# --------------------------------------------------------------------------- #
# Embeddings (sentence-transformers if available, else TF-IDF)
# --------------------------------------------------------------------------- #
def embed(texts: Sequence[str]):
    """Return an (n, d) embedding matrix. Prefers sentence-transformers."""
    texts = list(texts)
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        return model.encode(texts, normalize_embeddings=True)
    except Exception:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
        return vec.fit_transform(texts)  # sparse; cosine handles it


def cosine_sim_matrix(embeddings):
    from sklearn.metrics.pairwise import cosine_similarity

    return cosine_similarity(embeddings)


# --------------------------------------------------------------------------- #
# Anthropic helper (monitor harness)
# --------------------------------------------------------------------------- #
def anthropic_complete(
    prompt: str,
    system: str = "",
    model: str = "claude-opus-4-8",
    max_tokens: int = 1024,
    api_key: Optional[str] = None,
) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def gemini_complete(
    prompt: str,
    system: str = "",
    model: str = "gemini-2.5-flash",
    max_tokens: int = 1024,
    json_output: bool = False,
    api_key: Optional[str] = None,
) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    gm = genai.GenerativeModel(model, system_instruction=system or None)
    cfg = {"max_output_tokens": max_tokens, "temperature": 0.0}
    if json_output:
        cfg["response_mime_type"] = "application/json"

    import time as _t

    last_err = None
    for attempt in range(5):  # retry transient errors / rate limits with backoff
        try:
            resp = gm.generate_content(prompt, generation_config=cfg)
            try:
                return resp.text or ""
            except Exception:
                parts = []
                for cand in getattr(resp, "candidates", []) or []:
                    for p in getattr(getattr(cand, "content", None), "parts", []) or []:
                        parts.append(getattr(p, "text", ""))
                return "".join(parts)
        except Exception as e:  # noqa: BLE001 - includes ResourceExhausted (429)
            last_err = e
            _t.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"gemini_complete failed after retries: {last_err}")


def deepseek_complete(
    prompt: str,
    system: str = "",
    model: str = "deepseek-chat",
    max_tokens: int = 1024,
    json_output: bool = False,
    api_key: Optional[str] = None,
) -> str:
    """DeepSeek via its OpenAI-compatible endpoint."""
    import time as _t

    from openai import OpenAI

    client = OpenAI(api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
                    base_url="https://api.deepseek.com")
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    kwargs: dict[str, Any] = {"model": model, "messages": messages,
                              "max_tokens": max_tokens, "temperature": 0.0}
    if json_output:
        kwargs["response_format"] = {"type": "json_object"}

    last_err = None
    for attempt in range(5):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 - rate limits / transient
            last_err = e
            _t.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"deepseek_complete failed after retries: {last_err}")


def llm_complete(prompt: str, system: str = "", provider: str = "gemini", **kw) -> str:
    """Dispatch to the configured monitor LLM provider."""
    if provider == "gemini":
        return gemini_complete(prompt, system=system, **kw)
    if provider == "deepseek":
        return deepseek_complete(prompt, system=system, **kw)
    kw.pop("json_output", None)  # not supported by the anthropic helper
    return anthropic_complete(prompt, system=system, **kw)


# --------------------------------------------------------------------------- #
# Small IO helpers
# --------------------------------------------------------------------------- #
def read_yaml(path: str | os.PathLike[str]) -> dict:
    import yaml

    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
