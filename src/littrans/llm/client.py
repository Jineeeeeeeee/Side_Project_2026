"""
src/littrans/llm/client.py — Gemini API client + Multi-Key Pool.

ApiKeyPool quản lý nhiều API key (primary + fallbacks).
  - Mỗi key có error counter riêng
  - Khi rate-limit liên tiếp > KEY_ROTATE_THRESHOLD → rotate sang key tiếp theo
  - Nếu tất cả key dead → AllKeysExhaustedError
  - Singleton key_pool dùng xuyên suốt pipeline
"""
from __future__ import annotations

import re
import json
import logging
import threading
from pydantic import ValidationError
from google import genai
from google.genai import types

from littrans.config.settings import settings
from littrans.llm.schemas import TranslationResult, GEMINI_SCHEMA


# ═══════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════

class AllKeysExhaustedError(Exception):
    """Tất cả API key đều hết quota."""


# ═══════════════════════════════════════════════════════════════════
# API KEY POOL
# ═══════════════════════════════════════════════════════════════════

class ApiKeyPool:
    """
    Thread-safe pool quản lý nhiều Gemini API key.

    Rotate logic:
      - on_rate_limit() → tăng consecutive_errors
      - errors > threshold → mark dead, tìm key tiếp theo
      - on_success() → reset errors của key hiện tại
      - Tất cả dead → AllKeysExhaustedError
    """

    def __init__(self, api_keys: list[str], rotate_threshold: int = 3) -> None:
        if not api_keys:
            raise ValueError("Cần ít nhất 1 API key")
        self._keys      = api_keys
        self._threshold = rotate_threshold
        self._idx       = 0
        self._errors    = {k: 0 for k in api_keys}
        self._dead      = {k: False for k in api_keys}
        self._lock      = threading.Lock()
        self._clients   = {k: genai.Client(api_key=k) for k in api_keys}

    @property
    def current_key(self) -> str:
        return self._keys[self._idx]

    @property
    def current_client(self) -> genai.Client:
        return self._clients[self.current_key]

    def on_success(self) -> None:
        with self._lock:
            self._errors[self.current_key] = 0

    def on_rate_limit(self) -> None:
        with self._lock:
            key = self.current_key
            self._errors[key] += 1
            if self._errors[key] > self._threshold:
                self._dead[key] = True
                logging.warning(f"[ApiKeyPool] Key #{self._idx} đạt ngưỡng lỗi — rotate")
                self._rotate()

    def _rotate(self) -> None:
        n = len(self._keys)
        for _ in range(n):
            self._idx = (self._idx + 1) % n
            if not self._dead[self._keys[self._idx]]:
                print(f"  🔄 API Key rotate → key #{self._idx + 1}/{n}")
                return
        raise AllKeysExhaustedError(
            f"Tất cả {n} API key đều hết quota. "
            "Nghỉ rồi thử lại hoặc thêm key mới vào .env."
        )

    def stats(self) -> dict:
        return {
            "total_keys"  : len(self._keys),
            "active_idx"  : self._idx,
            "error_counts": dict(self._errors),
            "dead_keys"   : sum(1 for v in self._dead.values() if v),
        }


# Singleton
key_pool = ApiKeyPool(settings.gemini_api_keys, rotate_threshold=settings.key_rotate_threshold)


# ═══════════════════════════════════════════════════════════════════
# PUBLIC CALL FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def call_gemini(system_prompt: str, chapter_text: str) -> TranslationResult:
    """
    Gọi Gemini với structured output → TranslationResult.
    Raise exception khi thất bại (caller quyết định retry).
    """
    response = key_pool.current_client.models.generate_content(
        model=settings.gemini_model,
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
        _log_tokens(
            getattr(u, "prompt_token_count", "?"),
            getattr(u, "candidates_token_count", "?"),
            getattr(u, "total_token_count", "?"),
        )

    result = _parse_response(response)
    key_pool.on_success()
    return result


def call_gemini_text(system_prompt: str, user_text: str) -> str:
    """
    Gọi Gemini đơn giản (Scout, Arc Memory) → plain text.
    Không dùng structured output.
    """
    response = key_pool.current_client.models.generate_content(
        model=settings.gemini_model,
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
        ),
    )
    key_pool.on_success()
    return response.text or ""


def call_gemini_json(system_prompt: str, user_text: str) -> dict:
    """
    Gọi Gemini với yêu cầu trả về JSON tự do (Emotion Tracker, clean_glossary).
    """
    response = key_pool.current_client.models.generate_content(
        model=settings.gemini_model,
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    key_pool.on_success()
    raw   = response.text or "{}"
    clean = re.sub(r"^```json\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)
    return json.loads(clean)


# ═══════════════════════════════════════════════════════════════════
# ERROR HELPERS
# ═══════════════════════════════════════════════════════════════════

def is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "rate limit", "quota", "resource_exhausted"))


def handle_api_error(exc: Exception) -> None:
    """Gọi từ pipeline khi gặp exception — thông báo pool để cân nhắc rotate."""
    if is_rate_limit(exc):
        key_pool.on_rate_limit()


# ═══════════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ═══════════════════════════════════════════════════════════════════

def _parse_response(response) -> TranslationResult:
    if response.parsed is not None:
        p = response.parsed
        if isinstance(p, TranslationResult) and p.translation.strip():
            return p

    raw  = response.text or ""
    text = re.sub(r"^```json\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON không hợp lệ: {e}\n[300 ký đầu]: {raw[:300]}")

    try:
        result = TranslationResult.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Response không khớp schema: {e}")

    if not result.translation.strip():
        raise ValueError("Bản dịch rỗng sau parse.")

    return result


def _log_tokens(inp, out, total) -> None:
    try:
        from tqdm import tqdm
        tqdm.write(f"  📊 Tokens — input: {inp} | output: {out} | total: {total}")
    except Exception:
        print(f"  📊 Tokens — input: {inp} | output: {out} | total: {total}")
