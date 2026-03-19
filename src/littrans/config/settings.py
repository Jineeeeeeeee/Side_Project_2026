"""
src/littrans/config/settings.py — Toàn bộ cấu hình pipeline.

Chỉnh qua .env, KHÔNG sửa file này.

.env mẫu:
    # API
    GEMINI_API_KEY=AIza...
    FALLBACK_KEY_1=AIza...
    FALLBACK_KEY_2=AIza...
    KEY_ROTATE_THRESHOLD=3
    GEMINI_MODEL=gemini-2.5-flash

    # Pipeline
    MAX_RETRIES=5
    SUCCESS_SLEEP=30
    RATE_LIMIT_SLEEP=60
    MIN_CHARS_PER_CHAPTER=500

    # Scout
    SCOUT_LOOKBACK=10
    SCOUT_REFRESH_EVERY=5
    ARC_MEMORY_WINDOW=3

    # Characters
    ARCHIVE_AFTER_CHAPTERS=60
    EMOTION_RESET_CHAPTERS=5

    # Merge
    IMMEDIATE_MERGE=true
    AUTO_MERGE_GLOSSARY=false
    AUTO_MERGE_CHARACTERS=false
    RETRY_FAILED_PASSES=3

    # Token budget (0 = off)
    BUDGET_LIMIT=150000

    # Paths (thường không cần đổi)
    INPUT_DIR=inputs
    OUTPUT_DIR=outputs
    DATA_DIR=data
    LOG_DIR=logs
    PROMPTS_DIR=prompts
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import os

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)))

def _env_bool(key: str, default: bool) -> bool:
    return os.environ.get(key, str(default)).lower() == "true"


@dataclass
class Settings:
    # ── LLM ─────────────────────────────────────────────────────
    gemini_api_key        : str  = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    fallback_key_1        : str  = field(default_factory=lambda: _env("FALLBACK_KEY_1"))
    fallback_key_2        : str  = field(default_factory=lambda: _env("FALLBACK_KEY_2"))
    key_rotate_threshold  : int  = field(default_factory=lambda: _env_int("KEY_ROTATE_THRESHOLD", 3))
    gemini_model          : str  = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))

    # ── Pipeline ─────────────────────────────────────────────────
    max_retries           : int  = field(default_factory=lambda: _env_int("MAX_RETRIES", 5))
    success_sleep         : int  = field(default_factory=lambda: _env_int("SUCCESS_SLEEP", 30))
    rate_limit_sleep      : int  = field(default_factory=lambda: _env_int("RATE_LIMIT_SLEEP", 60))
    min_chars_per_chapter : int  = field(default_factory=lambda: _env_int("MIN_CHARS_PER_CHAPTER", 500))
    min_behavior_conf     : float = 0.65

    # ── Scout ────────────────────────────────────────────────────
    scout_lookback        : int  = field(default_factory=lambda: _env_int("SCOUT_LOOKBACK", 10))
    scout_refresh_every   : int  = field(default_factory=lambda: _env_int("SCOUT_REFRESH_EVERY", 5))
    arc_memory_window     : int  = field(default_factory=lambda: _env_int("ARC_MEMORY_WINDOW", 3))

    # ── Characters ───────────────────────────────────────────────
    archive_after_chapters: int  = field(default_factory=lambda: _env_int("ARCHIVE_AFTER_CHAPTERS", 60))
    emotion_reset_chapters: int  = field(default_factory=lambda: _env_int("EMOTION_RESET_CHAPTERS", 5))

    # ── Merge & Retry ────────────────────────────────────────────
    immediate_merge       : bool = field(default_factory=lambda: _env_bool("IMMEDIATE_MERGE", True))
    auto_merge_glossary   : bool = field(default_factory=lambda: _env_bool("AUTO_MERGE_GLOSSARY", False))
    auto_merge_characters : bool = field(default_factory=lambda: _env_bool("AUTO_MERGE_CHARACTERS", False))
    retry_failed_passes   : int  = field(default_factory=lambda: _env_int("RETRY_FAILED_PASSES", 3))

    # ── Token Budget ─────────────────────────────────────────────
    budget_limit          : int  = field(default_factory=lambda: _env_int("BUDGET_LIMIT", 150_000))

    # ── Paths ────────────────────────────────────────────────────
    input_dir    : Path = field(default_factory=lambda: Path(_env("INPUT_DIR",   "inputs")))
    output_dir   : Path = field(default_factory=lambda: Path(_env("OUTPUT_DIR",  "outputs")))
    data_dir     : Path = field(default_factory=lambda: Path(_env("DATA_DIR",    "data")))
    log_dir      : Path = field(default_factory=lambda: Path(_env("LOG_DIR",     "logs")))
    prompts_dir  : Path = field(default_factory=lambda: Path(_env("PROMPTS_DIR", "prompts")))

    def __post_init__(self) -> None:
        if not self.gemini_api_key:
            sys.exit("❌ Thiếu GEMINI_API_KEY trong .env")

        # Đảm bảo thư mục tồn tại
        for p in [self.input_dir, self.output_dir, self.data_dir, self.log_dir,
                  self.glossary_dir, self.char_dir, self.memory_dir, self.skills_file.parent]:
            p.mkdir(parents=True, exist_ok=True)

        # Logging
        self.log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(self.log_dir / "pipeline.log"),
            level=logging.ERROR,
            format="%(asctime)s | %(levelname)s | %(message)s",
            encoding="utf-8",
        )

    # ── Derived paths ─────────────────────────────────────────────
    @property
    def glossary_dir(self) -> Path:
        return self.data_dir / "glossary"

    @property
    def glossary_files(self) -> dict[str, Path]:
        return {
            "pathways"      : self.glossary_dir / "Glossary_Pathways.md",
            "organizations" : self.glossary_dir / "Glossary_Organizations.md",
            "items"         : self.glossary_dir / "Glossary_Items.md",
            "locations"     : self.glossary_dir / "Glossary_Locations.md",
            "general"       : self.glossary_dir / "Glossary_General.md",
        }

    @property
    def staging_terms_file(self) -> Path:
        return self.glossary_dir / "Staging_Terms.md"

    @property
    def char_dir(self) -> Path:
        return self.data_dir / "characters"

    @property
    def characters_active_file(self) -> Path:
        return self.char_dir / "Characters_Active.json"

    @property
    def characters_archive_file(self) -> Path:
        return self.char_dir / "Characters_Archive.json"

    @property
    def staging_chars_file(self) -> Path:
        return self.char_dir / "Staging_Characters.json"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def context_notes_file(self) -> Path:
        return self.memory_dir / "Context_Notes.md"

    @property
    def arc_memory_file(self) -> Path:
        return self.memory_dir / "Arc_Memory.md"

    @property
    def skills_file(self) -> Path:
        return self.data_dir / "skills" / "Skills.json"

    @property
    def prompt_agent_file(self) -> Path:
        return self.prompts_dir / "system_agent.md"

    @property
    def prompt_character_file(self) -> Path:
        return self.prompts_dir / "character_profile.md"

    @property
    def gemini_api_keys(self) -> list[str]:
        return [k for k in [self.gemini_api_key, self.fallback_key_1, self.fallback_key_2] if k]


# Singleton — import từ bất kỳ đâu
settings = Settings()
