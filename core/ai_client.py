"""
core/ai_client.py — Gọi Gemini API + parse response an toàn.

[v4] Multi-Key Fallback:
  - ApiKeyPool quản lý nhiều API key (primary + fallbacks từ .env)
  - Mỗi key có error counter riêng
  - Khi rate-limit liên tiếp > KEY_ROTATE_THRESHOLD → tự động rotate sang key tiếp theo
  - Nếu tất cả key đều dead → raise AllKeysExhaustedError
  - Singleton key_pool được dùng xuyên suốt pipeline
"""

import re
import json
import logging
import threading
from pydantic import ValidationError
from google import genai
from google.genai import types
from .config import (
    GEMINI_API_KEYS, GEMINI_MODEL,
    KEY_ROTATE_THRESHOLD,
)
from .models import TranslationResult, GEMINI_SCHEMA


# ═══════════════════════════════════════════════════════════════════
# [v4] API KEY POOL
# ═══════════════════════════════════════════════════════════════════

class AllKeysExhaustedError(Exception):
    """Tất cả API key đều đã hết quota / bị lỗi."""
    pass


class ApiKeyPool:
    """
    Thread-safe pool quản lý nhiều Gemini API key.

    Logic rotate:
      - Mỗi key có consecutive_errors counter
      - is_rate_limit() → tăng counter
      - counter > KEY_ROTATE_THRESHOLD → rotate sang key tiếp theo
      - Sau khi thành công → reset counter của key hiện tại
      - Nếu đã đi hết vòng và không key nào hoạt động → AllKeysExhaustedError

    Khi chỉ có 1 key (FALLBACK_KEY_1/2 không cấu hình):
      Pool vẫn hoạt động bình thường, chỉ không rotate.
    """

    def __init__(self, api_keys: list[str], rotate_threshold: int = 3):
        if not api_keys:
            raise ValueError("Cần ít nhất 1 API key")
        self._keys       = api_keys
        self._threshold  = rotate_threshold
        self._idx        = 0
        self._errors     = {k: 0 for k in api_keys}
        self._dead       = {k: False for k in api_keys}
        self._lock       = threading.Lock()
        self._clients    = {k: genai.Client(api_key=k) for k in api_keys}

    @property
    def current_key(self) -> str:
        return self._keys[self._idx]

    @property
    def current_client(self) -> genai.Client:
        return self._clients[self.current_key]

    def on_success(self) -> None:
        """Gọi sau mỗi API call thành công — reset error counter."""
        with self._lock:
            self._errors[self.current_key] = 0

    def on_rate_limit(self) -> None:
        """
        Gọi khi gặp rate limit / quota error.
        Nếu vượt ngưỡng → rotate sang key tiếp theo.
        """
        with self._lock:
            key = self.current_key
            self._errors[key] += 1
            if self._errors[key] > self._threshold:
                self._dead[key] = True
                logging.warning(f"[ApiKeyPool] Key #{self._idx} đạt ngưỡng lỗi — rotate")
                self._rotate()

    def _rotate(self) -> None:
        """Tìm key tiếp theo còn sống. Không giữ lock khi gọi hàm này."""
        n = len(self._keys)
        for _ in range(n):
            self._idx = (self._idx + 1) % n
            if not self._dead[self._keys[self._idx]]:
                print(f"  🔄 API Key rotate → key #{self._idx + 1}/{n}")
                return
        raise AllKeysExhaustedError(
            f"Tất cả {n} API key đều đã hết quota. "
            f"Nghỉ một lúc rồi thử lại, hoặc thêm key mới vào .env."
        )

    def stats(self) -> dict:
        return {
            "total_keys" : len(self._keys),
            "active_idx" : self._idx,
            "error_counts": dict(self._errors),
            "dead_keys"  : sum(1 for v in self._dead.values() if v),
        }


# Singleton pool — khởi tạo 1 lần, dùng xuyên suốt
key_pool = ApiKeyPool(GEMINI_API_KEYS, rotate_threshold=KEY_ROTATE_THRESHOLD)


# ═══════════════════════════════════════════════════════════════════
# CALL GEMINI
# ═══════════════════════════════════════════════════════════════════

def call_gemini(system_prompt: str, chapter_text: str) -> TranslationResult:
    """
    Gọi Gemini API và parse kết quả về TranslationResult.
    Dùng key_pool.current_client → tự động xử lý key rotation.
    Raise exception nếu thất bại → caller (runner.py) quyết định retry.
    """
    client = key_pool.current_client

    response = client.models.generate_content(
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

    result = _parse(response)
    key_pool.on_success()   # reset error counter sau call thành công
    return result


def call_gemini_simple(system_prompt: str, user_text: str, model: str = None) -> str:
    """
    Gọi Gemini đơn giản (cho Scout, Arc Memory) — trả về text thuần.
    Không dùng structured output.
    """
    client = key_pool.current_client
    from google.genai import types as _types
    response = client.models.generate_content(
        model=model or GEMINI_MODEL,
        contents=user_text,
        config=_types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
        ),
    )
    key_pool.on_success()
    return response.text or ""


# ═══════════════════════════════════════════════════════════════════
# PARSE
# ═══════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "rate limit", "quota", "resource_exhausted"))


def handle_api_error(exc: Exception) -> None:
    """
    Gọi từ runner.py khi gặp exception.
    Nếu là rate limit → thông báo pool để cân nhắc rotate.
    """
    if is_rate_limit(exc):
        key_pool.on_rate_limit()


def _log(msg: str) -> None:
    try:
        from tqdm import tqdm
        tqdm.write(f"  📊 {msg}")
    except Exception:
        print(f"  📊 {msg}")