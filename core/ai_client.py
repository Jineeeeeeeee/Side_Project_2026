"""
core/ai_client.py — Gọi Gemini API + parse response an toàn.
"""

import re
import json
import logging
from pydantic import ValidationError
from google.genai import types
from .config import gemini_client, GEMINI_MODEL
from .models import TranslationResult, GEMINI_SCHEMA


def call_gemini(system_prompt: str, chapter_text: str) -> TranslationResult:
    """
    Gọi Gemini API và parse kết quả về TranslationResult.
    Raise exception nếu thất bại → caller (runner.py) quyết định retry.
    """
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=chapter_text,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.4,
            response_schema=GEMINI_SCHEMA,
            response_mime_type="application/json",
        ),
    )

    if hasattr(response, "usage_metadata") and response.usage_metadata:
        u = response.usage_metadata
        _log(
            f"Token — input: {getattr(u,'prompt_token_count','?')} | "
            f"output: {getattr(u,'candidates_token_count','?')} | "
            f"total: {getattr(u,'total_token_count','?')}"
        )

    return _parse(response)


def _parse(response) -> TranslationResult:
    """
    Parse response Gemini → TranslationResult.
    Thử response.parsed trước, fallback về JSON thủ công.
    Raise ValueError (retryable) nếu parse thất bại.
    """
    if response.parsed is not None:
        p = response.parsed
        if isinstance(p, TranslationResult) and p.translation.strip():
            return p

    raw  = response.text or ""
    text = re.sub(r"^```json\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON không hợp lệ: {e}\n[300 ký tự đầu]: {raw[:300]}")

    try:
        result = TranslationResult.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Response không khớp schema: {e}")

    if not result.translation.strip():
        raise ValueError("Bản dịch rỗng sau parse.")

    return result


def is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "rate limit", "quota", "resource_exhausted"))


def _log(msg: str) -> None:
    try:
        from tqdm import tqdm
        tqdm.write(f"  📊 {msg}")
    except Exception:
        print(f"  📊 {msg}")
