"""
src/littrans/llm/client.py — Gemini API client + Multi-Key Pool + Anthropic dispatcher.

[FIX BUG-1] ApiKeyPool.on_rate_limit() nhận failed_key thay vì tự lấy current_key.
            Tránh race condition khi nhiều thread cùng báo lỗi.

[FIX BUG-2] Bỏ ThreadPoolExecutor wrapper (_call_with_timeout).
            Dùng http_options={'timeout': API_TIMEOUT} trực tiếp trong genai.Client
            → SDK tự xử lý timeout, không sinh worker thread bị leak.

[FIX BUG-5] handle_api_error() được gọi trong mọi call function của Gemini,
            truyền đúng failed_key về pool.

[FIX IMPORT] Xoá GEMINI_SCHEMA khỏi import — schemas.py đã xoá constant này.
"""
from __future__ import annotations

import re
import json
import logging
import threading
from google import genai
from google.genai import types

from littrans.config.settings import settings
from littrans.llm.schemas import TranslationResult  # ← GEMINI_SCHEMA đã bị xoá khỏi schemas.py

# Timeout cho mọi API call (giây) — áp vào http_options của SDK
API_TIMEOUT: int = 90


# ═══════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════

class AllKeysExhaustedError(Exception):
    """Tất cả API key đều hết quota."""


# ═══════════════════════════════════════════════════════════════════
# API KEY POOL (Gemini)
# ═══════════════════════════════════════════════════════════════════

class ApiKeyPool:
    """Thread-safe pool quản lý nhiều Gemini API key."""

    def __init__(self, api_keys: list[str], rotate_threshold: int = 3) -> None:
        if not api_keys:
            raise ValueError("Cần ít nhất 1 API key")
        self._keys      = api_keys
        self._threshold = rotate_threshold
        self._idx       = 0
        self._errors    = {k: 0 for k in api_keys}
        self._dead      = {k: False for k in api_keys}
        self._lock      = threading.Lock()
        # [FIX BUG-2] Thêm http_options timeout vào Client — SDK tự handle,
        # không cần ThreadPoolExecutor wrapper nữa.
        self._clients   = {
            k: genai.Client(
                api_key=k,
                http_options={"timeout": API_TIMEOUT},
            )
            for k in api_keys
        }

    @property
    def current_key(self) -> str:
        return self._keys[self._idx]

    @property
    def current_client(self) -> genai.Client:
        return self._clients[self.current_key]

    def on_success(self) -> None:
        with self._lock:
            self._errors[self.current_key] = 0

    # [FIX BUG-1] Nhận failed_key thay vì tự lấy self.current_key.
    # Lý do: giữa lúc thread A gặp lỗi và bắt đầu xử lý on_rate_limit(),
    # thread B có thể đã rotate key → self.current_key trỏ sai.
    def on_rate_limit(self, failed_key: str | None = None) -> None:
        with self._lock:
            key = failed_key if failed_key else self.current_key
            self._errors[key] += 1
            if self._errors[key] > self._threshold:
                self._dead[key] = True
                logging.warning(
                    f"[ApiKeyPool] Key ...{key[-4:]} đạt ngưỡng lỗi — rotate"
                )
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


# Singleton Gemini pool
key_pool = ApiKeyPool(settings.gemini_api_keys, rotate_threshold=settings.key_rotate_threshold)


# ═══════════════════════════════════════════════════════════════════
# ANTHROPIC CLIENT (lazy init)
# ═══════════════════════════════════════════════════════════════════

_anthropic_client = None
_anthropic_lock   = threading.Lock()


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    with _anthropic_lock:
        if _anthropic_client is not None:
            return _anthropic_client
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "❌ Cần cài anthropic SDK: pip install anthropic"
            )
        _anthropic_client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=float(API_TIMEOUT),
        )
        return _anthropic_client


# ═══════════════════════════════════════════════════════════════════
# TOKEN LOGGING HELPER
# ═══════════════════════════════════════════════════════════════════

def _try_log_usage(response) -> None:
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        u = response.usage_metadata
        _log_tokens(
            getattr(u, "prompt_token_count", "?"),
            getattr(u, "candidates_token_count", "?"),
            getattr(u, "total_token_count", "?"),
        )
        return
    if hasattr(response, "usage") and response.usage:
        u = response.usage
        _log_tokens(
            getattr(u, "input_tokens", "?"),
            getattr(u, "output_tokens", "?"),
            "—",
        )


def _log_tokens(inp, out, total) -> None:
    try:
        from tqdm import tqdm
        tqdm.write(f"  📊 Tokens — input: {inp} | output: {out} | total: {total}")
    except Exception:
        print(f"  📊 Tokens — input: {inp} | output: {out} | total: {total}")


# ═══════════════════════════════════════════════════════════════════
# PUBLIC — DISPATCHER
# ═══════════════════════════════════════════════════════════════════

def call_translation(system_prompt: str, chapter_text: str) -> str:
    if settings.using_anthropic:
        return call_anthropic_translation(system_prompt, chapter_text)
    else:
        return call_gemini_translation(system_prompt, chapter_text)


def translation_model_info() -> str:
    return f"{settings.translation_model} ({settings.translation_provider})"


# ═══════════════════════════════════════════════════════════════════
# PUBLIC CALL FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def call_gemini_translation(system_prompt: str, chapter_text: str) -> str:
    """Gemini Trans-call — plain text output."""
    model = (
        settings.translation_model
        if settings.translation_provider == "gemini"
        else settings.gemini_model
    )
    # [FIX BUG-1] Chụp key TRƯỚC khi gọi API
    used_key = key_pool.current_key
    try:
        response = key_pool.current_client.models.generate_content(
            model=model,
            contents=chapter_text,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.4,
            ),
        )
        _try_log_usage(response)
        text = response.text or ""
        if not text.strip():
            raise ValueError("Translation call trả về text rỗng.")
        key_pool.on_success()
        return text
    except Exception as exc:
        # [FIX BUG-5] Luôn gọi handle_api_error với đúng key đã dùng
        handle_api_error(exc, failed_key=used_key)
        raise


def call_anthropic_translation(system_prompt: str, chapter_text: str) -> str:
    """Anthropic (Claude) Trans-call — plain text output."""
    client = _get_anthropic_client()
    model  = settings.translation_model
    response = client.messages.create(
        model=model,
        max_tokens=8096,
        temperature=1,
        system=system_prompt,
        messages=[{"role": "user", "content": chapter_text}],
    )
    _try_log_usage(response)
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
    if not text.strip():
        raise ValueError("Anthropic translation call trả về text rỗng.")
    return text


def call_gemini_text(system_prompt: str, user_text: str) -> str:
    """Scout, Arc Memory — plain text, luôn dùng Gemini."""
    # [FIX BUG-1+5] Chụp key trước, truyền vào handle_api_error khi lỗi
    used_key = key_pool.current_key
    try:
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
    except Exception as exc:
        handle_api_error(exc, failed_key=used_key)
        raise


def call_gemini_json(system_prompt: str, user_text: str) -> dict:
    """
    Emotion Tracker, clean_glossary, Pre-call, Post-call, Bible scan — JSON tự do.
    Luôn dùng Gemini.
    """
    # [FIX BUG-1+5] Chụp key trước, truyền vào handle_api_error khi lỗi
    used_key = key_pool.current_key
    try:
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
    except Exception as exc:
        handle_api_error(exc, failed_key=used_key)
        raise

    raw   = response.text or "{}"
    clean = re.sub(r"^```json\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        logging.error(f"[call_gemini_json] JSON parse lỗi: {e} | raw[:200]: {raw[:200]}")
        raise

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                logging.warning(
                    f"[call_gemini_json] Response là JSON array (size={len(data)}) "
                    "— unwrap lấy dict đầu tiên"
                )
                return item
        logging.warning(
            f"[call_gemini_json] Response là list không có dict element: "
            f"{str(data)[:100]}"
        )
        return {}

    return data


# ═══════════════════════════════════════════════════════════════════
# ERROR HELPERS
# ═══════════════════════════════════════════════════════════════════

def is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "rate limit", "quota", "resource_exhausted",
                                   "overloaded", "529"))


# [FIX BUG-1+5] Nhận failed_key để truyền đúng vào on_rate_limit()
def handle_api_error(exc: Exception, failed_key: str | None = None) -> None:
    if is_rate_limit(exc):
        if not settings.using_anthropic:
            key_pool.on_rate_limit(failed_key)