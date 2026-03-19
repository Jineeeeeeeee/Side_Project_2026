"""
core/config.py — Toàn bộ cấu hình pipeline v4.
Chỉnh qua .env, KHÔNG sửa file này.

.env mẫu:
    GEMINI_API_KEY=AIza...          ← key chính
    FALLBACK_KEY_1=AIza...          ← [v4] key dự phòng 1 (tùy chọn)
    FALLBACK_KEY_2=AIza...          ← [v4] key dự phòng 2 (tùy chọn)
    KEY_ROTATE_THRESHOLD=3          ← [v4] lỗi liên tiếp trước khi rotate key
    GEMINI_MODEL=gemini-2.5-flash

    MAX_RETRIES=5
    SUCCESS_SLEEP=30
    RATE_LIMIT_SLEEP=60
    MIN_CHARS_PER_CHAPTER=500

    SCOUT_LOOKBACK=10
    SCOUT_REFRESH_EVERY=5
    ARC_MEMORY_WINDOW=3

    ARCHIVE_AFTER_CHAPTERS=60
    EMOTION_RESET_CHAPTERS=5       ← [v4] reset emotional_state sau N chương không update

    IMMEDIATE_MERGE=true
    AUTO_MERGE_GLOSSARY=false
    AUTO_MERGE_CHARACTERS=false
    RETRY_FAILED_PASSES=3
"""

import os, sys, logging
from pathlib import Path
from google import genai
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# ── AI Model ─────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
if not GEMINI_API_KEY:
    sys.exit("❌ Thiếu GEMINI_API_KEY trong .env")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ── [v4] Multi-Key Fallback ───────────────────────────────────────
# Thêm FALLBACK_KEY_1 và FALLBACK_KEY_2 vào .env để bật tính năng này.
# Để trống = chỉ dùng key chính.
FALLBACK_KEY_1        = os.environ.get("FALLBACK_KEY_1", "").strip()
FALLBACK_KEY_2        = os.environ.get("FALLBACK_KEY_2", "").strip()
KEY_ROTATE_THRESHOLD  = int(os.environ.get("KEY_ROTATE_THRESHOLD", "3"))

# Build danh sách keys (bỏ key rỗng)
GEMINI_API_KEYS: list[str] = [k for k in [GEMINI_API_KEY, FALLBACK_KEY_1, FALLBACK_KEY_2] if k]

# ── Thư mục gốc ──────────────────────────────────────────────────
RAW_DIR   = "Raw_English"
TRANS_DIR = "Translated_VN"
DATA_DIR  = Path("data")
LOG_DIR   = Path("logs")

# ── Glossary (phân category) ──────────────────────────────────────
GLOSSARY_DIR = DATA_DIR / "glossary"
GLOSSARY_FILES = {
    "pathways"      : GLOSSARY_DIR / "Glossary_Pathways.md",
    "organizations" : GLOSSARY_DIR / "Glossary_Organizations.md",
    "items"         : GLOSSARY_DIR / "Glossary_Items.md",
    "locations"     : GLOSSARY_DIR / "Glossary_Locations.md",
    "general"       : GLOSSARY_DIR / "Glossary_General.md",
}
STAGING_TERMS_FILE = GLOSSARY_DIR / "Staging_Terms.md"

# ── Skills ───────────────────────────────────────────────────────
SKILLS_FILE = DATA_DIR / "skills" / "Skills.json"

# ── Characters (phân tầng) ────────────────────────────────────────
CHAR_DIR               = DATA_DIR / "characters"
CHARACTERS_ACTIVE_FILE  = CHAR_DIR / "Characters_Active.json"
CHARACTERS_ARCHIVE_FILE = CHAR_DIR / "Characters_Archive.json"
STAGING_CHARS_FILE      = CHAR_DIR / "Staging_Characters.json"

# ── Memory ────────────────────────────────────────────────────────
MEM_DIR            = DATA_DIR / "memory"
CONTEXT_NOTES_FILE = MEM_DIR / "Context_Notes.md"
ARC_MEMORY_FILE    = MEM_DIR / "Arc_Memory.md"

# ── Hướng dẫn ────────────────────────────────────────────────────
INSTRUCTIONS_FILE      = "translateAGENT_INSTRUCTIONS.md"
CHAR_INSTRUCTIONS_FILE = "CHARACTER_PROFILING_INSTRUCTIONS.md"

# ── Tham số dịch ─────────────────────────────────────────────────
MAX_RETRIES           = int(os.environ.get("MAX_RETRIES",           "5"))
SUCCESS_SLEEP         = int(os.environ.get("SUCCESS_SLEEP",         "30"))
RATE_LIMIT_SLEEP      = int(os.environ.get("RATE_LIMIT_SLEEP",      "60"))
MIN_CHARS_PER_CHAPTER = int(os.environ.get("MIN_CHARS_PER_CHAPTER", "500"))
MIN_BEHAVIOR_CONF     = 0.65

# ── Scout AI ─────────────────────────────────────────────────────
SCOUT_LOOKBACK      = int(os.environ.get("SCOUT_LOOKBACK",      "10"))
SCOUT_REFRESH_EVERY = int(os.environ.get("SCOUT_REFRESH_EVERY", "5"))
ARC_MEMORY_WINDOW   = int(os.environ.get("ARC_MEMORY_WINDOW",   "3"))

# ── Tiered Characters ─────────────────────────────────────────────
ARCHIVE_AFTER_CHAPTERS  = int(os.environ.get("ARCHIVE_AFTER_CHAPTERS",  "60"))

# ── [v4] Emotion Tracker ──────────────────────────────────────────
# emotional_state reset về "normal" sau N chương nếu scout không update
EMOTION_RESET_CHAPTERS  = int(os.environ.get("EMOTION_RESET_CHAPTERS",  "5"))

# ── Merge & Retry ─────────────────────────────────────────────────
IMMEDIATE_MERGE       = os.environ.get("IMMEDIATE_MERGE",       "true").lower()  == "true"
AUTO_MERGE_GLOSSARY   = os.environ.get("AUTO_MERGE_GLOSSARY",   "false").lower() == "true"
AUTO_MERGE_CHARACTERS = os.environ.get("AUTO_MERGE_CHARACTERS", "false").lower() == "true"
RETRY_FAILED_PASSES   = int(os.environ.get("RETRY_FAILED_PASSES", "3"))

# ── Logging ───────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "translation_errors.log"),
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)