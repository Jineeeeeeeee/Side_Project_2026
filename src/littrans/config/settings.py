"""
src/littrans/config/settings.py — Toàn bộ cấu hình pipeline.

Chỉnh qua .env, KHÔNG sửa file này.

[v4.3 FIX] _env_bool() xử lý đầy đủ các giá trị truthy phổ biến.
[v4.4] Thêm 3 config cho Scout Glossary Suggest.
[v4.5] Dual-Model: TRANSLATION_PROVIDER + TRANSLATION_MODEL + ANTHROPIC_API_KEY.
[v4.5.1] Bỏ ANTHROPIC_MODELS/GEMINI_MODELS chưa dùng → thêm soft validation warning.
[v5.2] Xóa USE_THREE_CALL — pipeline luôn dùng 3-call flow.
[v5.4] Multi-novel: novel_name + active_input_dir + active_output_dir + novel_data_dir.
       Mỗi novel có data riêng lưu trong outputs/<novel_name>/data/.
       Backward compat: novel_name="" → dùng paths cũ (flat structure).
"""
from __future__ import annotations

import sys
import logging
import threading
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
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("true", "1", "yes", "on")

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _default_translation_model() -> str:
    provider = _env("TRANSLATION_PROVIDER", "gemini").strip().lower()
    explicit = _env("TRANSLATION_MODEL", "").strip()
    if explicit:
        return explicit
    if provider == "anthropic":
        return "claude-sonnet-4-6"
    return _env("GEMINI_MODEL", "gemini-2.0-flash-exp")


@dataclass
class Settings:
    # ── LLM — Gemini (Scout, Pre-call, Post-call, Arc Memory) ─────
    gemini_api_key        : str  = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    fallback_key_1        : str  = field(default_factory=lambda: _env("FALLBACK_KEY_1"))
    fallback_key_2        : str  = field(default_factory=lambda: _env("FALLBACK_KEY_2"))
    key_rotate_threshold  : int  = field(default_factory=lambda: _env_int("KEY_ROTATE_THRESHOLD", 3))
    gemini_model          : str  = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.0-flash-exp"))

    # ── LLM — Translation Model (Dual-Model v4.5) ─────────────────
    anthropic_api_key     : str  = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    translation_provider  : str  = field(default_factory=lambda: _env("TRANSLATION_PROVIDER", "gemini").strip().lower())
    translation_model     : str  = field(default_factory=_default_translation_model)

    # ── Pipeline ─────────────────────────────────────────────────
    max_retries           : int  = field(default_factory=lambda: _env_int("MAX_RETRIES", 5))
    success_sleep         : int  = field(default_factory=lambda: _env_int("SUCCESS_SLEEP", 30))
    rate_limit_sleep      : int  = field(default_factory=lambda: _env_int("RATE_LIMIT_SLEEP", 60))
    min_chars_per_chapter : int  = field(default_factory=lambda: _env_int("MIN_CHARS_PER_CHAPTER", 500))
    min_behavior_conf     : float = 0.65

    # ── 3-Call Architecture ───────────────────────────────────────
    pre_call_sleep        : int  = field(default_factory=lambda: _env_int("PRE_CALL_SLEEP", 5))
    post_call_sleep       : int  = field(default_factory=lambda: _env_int("POST_CALL_SLEEP", 5))
    post_call_max_retries : int  = field(default_factory=lambda: _env_int("POST_CALL_MAX_RETRIES", 2))
    trans_retry_on_quality: bool = field(default_factory=lambda: _env_bool("TRANS_RETRY_ON_QUALITY", True))

    # ── Scout ────────────────────────────────────────────────────
    scout_lookback        : int  = field(default_factory=lambda: _env_int("SCOUT_LOOKBACK", 10))
    scout_refresh_every   : int  = field(default_factory=lambda: _env_int("SCOUT_REFRESH_EVERY", 5))
    arc_memory_window     : int  = field(default_factory=lambda: _env_int("ARC_MEMORY_WINDOW", 3))

    # ── Scout Glossary Suggest ────────────────────────────────────
    scout_suggest_glossary      : bool  = field(default_factory=lambda: _env_bool("SCOUT_SUGGEST_GLOSSARY", True))
    scout_suggest_min_confidence: float = field(default_factory=lambda: _env_float("SCOUT_SUGGEST_MIN_CONFIDENCE", 0.7))
    scout_suggest_max_terms     : int   = field(default_factory=lambda: _env_int("SCOUT_SUGGEST_MAX_TERMS", 20))

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

    # ── Base Paths (cố định, không theo novel) ───────────────────
    input_dir    : Path = field(default_factory=lambda: Path(_env("INPUT_DIR",   "inputs")))
    output_dir   : Path = field(default_factory=lambda: Path(_env("OUTPUT_DIR",  "outputs")))
    data_dir     : Path = field(default_factory=lambda: Path(_env("DATA_DIR",    "data")))
    log_dir      : Path = field(default_factory=lambda: Path(_env("LOG_DIR",     "logs")))
    prompts_dir  : Path = field(default_factory=lambda: Path(_env("PROMPTS_DIR", "prompts")))

    # ── Multi-novel ───────────────────────────────────────────────
    # novel_name = tên subfolder trong inputs/ và outputs/
    # Khi rỗng → backward compat với flat structure (1 truyện)
    novel_name   : str  = field(default_factory=lambda: _env("NOVEL_NAME", ""))

    # ── Bible System ──────────────────────────────────────────────
    bible_mode          : bool = field(default_factory=lambda: _env_bool("BIBLE_MODE", False))
    bible_scan_batch    : int  = field(default_factory=lambda: _env_int("BIBLE_SCAN_BATCH", 5))
    bible_scan_sleep    : int  = field(default_factory=lambda: _env_int("BIBLE_SCAN_SLEEP", 10))
    bible_scan_depth    : str  = field(default_factory=lambda: _env("BIBLE_SCAN_DEPTH", "standard"))
    bible_cross_ref     : bool = field(default_factory=lambda: _env_bool("BIBLE_CROSS_REF", True))
    _bible_dir_raw      : str  = field(default_factory=lambda: _env("BIBLE_DIR", "data/bible"))

    # ── EPUB Processor ────────────────────────────────────────────
    epub_dir_raw        : str  = field(default_factory=lambda: _env("EPUB_DIR",        "epub"))
    epub_images_dir_raw : str  = field(default_factory=lambda: _env("EPUB_IMAGES_DIR", "epub_images"))
    epub_temp_dir_raw   : str  = field(default_factory=lambda: _env("EPUB_TEMP_DIR",   "epub_temp"))

    # ── Known valid model names (soft validation only) ────────────
    _KNOWN_ANTHROPIC_MODELS = frozenset({
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    })
    _KNOWN_GEMINI_MODELS = frozenset({
        "gemini-2.0-flash-exp",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    })

    def __post_init__(self) -> None:
        if not self.gemini_api_key:
            sys.exit("❌ Thiếu GEMINI_API_KEY trong .env")

        if self.translation_provider == "anthropic" and not self.anthropic_api_key:
            sys.exit(
                "❌ TRANSLATION_PROVIDER=anthropic nhưng thiếu ANTHROPIC_API_KEY trong .env\n"
                "   Thêm: ANTHROPIC_API_KEY=sk-ant-..."
            )

        if self.translation_provider not in ("gemini", "anthropic"):
            sys.exit(
                f"❌ TRANSLATION_PROVIDER='{self.translation_provider}' không hợp lệ.\n"
                "   Chỉ chấp nhận: gemini | anthropic"
            )

        known = (
            self._KNOWN_ANTHROPIC_MODELS
            if self.translation_provider == "anthropic"
            else self._KNOWN_GEMINI_MODELS
        )
        if self.translation_model not in known:
            print(
                f"⚠️  TRANSLATION_MODEL='{self.translation_model}' chưa có trong danh sách "
                f"đã biết cho provider '{self.translation_provider}'. "
                f"Nếu sai tên, API sẽ báo lỗi lúc chạy."
            )

        # Tạo thư mục cơ bản (không phụ thuộc novel)
        for p in [self.input_dir, self.output_dir, self.prompts_dir]:
            p.mkdir(parents=True, exist_ok=True)

        # Tạo thư mục theo novel (hoặc fallback)
        self._ensure_novel_dirs()

        self.log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(self.log_dir / "pipeline.log"),
            level=logging.ERROR,
            format="%(asctime)s | %(levelname)s | %(message)s",
            encoding="utf-8",
        )

    def _ensure_novel_dirs(self) -> None:
        """Tạo tất cả thư mục cần thiết cho novel hiện tại."""
        dirs = [
            self.novel_data_dir,
            self.glossary_dir,
            self.char_dir,
            self.memory_dir,
            self.skills_file.parent,
            self.active_output_dir,
            self.log_dir,
        ]
        for p in dirs:
            p.mkdir(parents=True, exist_ok=True)

        if self.bible_mode:
            self.bible_dir.mkdir(parents=True, exist_ok=True)
            (self.bible_dir / "database").mkdir(parents=True, exist_ok=True)
            (self.bible_dir / "staging").mkdir(parents=True, exist_ok=True)

    # ════════════════════════════════════════════════════════════
    # MULTI-NOVEL PATHS
    # ════════════════════════════════════════════════════════════

    @property
    def active_input_dir(self) -> Path:
        """Thư mục chứa file chương của novel hiện tại.

        novel_name set  → inputs/<novel_name>/
        novel_name rỗng → inputs/   (backward compat)
        """
        if self.novel_name:
            return self.input_dir / self.novel_name
        return self.input_dir

    @property
    def active_output_dir(self) -> Path:
        """Thư mục bản dịch + data của novel hiện tại.

        novel_name set  → outputs/<novel_name>/
        novel_name rỗng → outputs/   (backward compat)
        """
        if self.novel_name:
            return self.output_dir / self.novel_name
        return self.output_dir

    @property
    def novel_data_dir(self) -> Path:
        """Thư mục data riêng của novel.

        novel_name set  → outputs/<novel_name>/data/
        novel_name rỗng → data/   (backward compat)
        """
        if self.novel_name:
            return self.output_dir / self.novel_name / "data"
        return self.data_dir

    # ════════════════════════════════════════════════════════════
    # DERIVED PATHS (tất cả đều theo novel_data_dir)
    # ════════════════════════════════════════════════════════════

    @property
    def bible_dir(self) -> Path:
        return self.novel_data_dir / "bible"

    @property
    def bible_available(self) -> bool:
        return (self.bible_dir / "meta.json").exists()

    @property
    def epub_dir(self) -> Path:
        return Path(self.epub_dir_raw)

    @property
    def epub_images_dir(self) -> Path:
        return Path(self.epub_images_dir_raw)

    @property
    def epub_temp_dir(self) -> Path:
        return Path(self.epub_temp_dir_raw)

    @property
    def epub_cut_agent_file(self) -> Path:
        return self.prompts_dir / "epub_cut_agent.md"

    @property
    def epub_pattern_learner_file(self) -> Path:
        return self.prompts_dir / "epub_pattern_learner.md"

    @property
    def epub_structure_analyst_file(self) -> Path:
        return self.prompts_dir / "epub_structure_analyst.md"

    @property
    def glossary_dir(self) -> Path:
        return self.novel_data_dir / "glossary"

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
        return self.novel_data_dir / "characters"

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
        return self.novel_data_dir / "memory"

    @property
    def context_notes_file(self) -> Path:
        return self.memory_dir / "Context_Notes.md"

    @property
    def arc_memory_file(self) -> Path:
        return self.memory_dir / "Arc_Memory.md"

    @property
    def skills_file(self) -> Path:
        return self.novel_data_dir / "skills" / "Skills.json"

    @property
    def log_dir(self) -> Path:
        """Log theo novel khi có novel_name."""
        if self.novel_name:
            return self.output_dir / self.novel_name / "logs"
        return Path(_env("LOG_DIR", "logs"))

    @property
    def prompt_agent_file(self) -> Path:
        return self.prompts_dir / "system_agent.md"

    @property
    def prompt_character_file(self) -> Path:
        return self.prompts_dir / "character_profile.md"

    @property
    def gemini_api_keys(self) -> list[str]:
        return [k for k in [self.gemini_api_key, self.fallback_key_1, self.fallback_key_2] if k]

    @property
    def using_anthropic(self) -> bool:
        return self.translation_provider == "anthropic"


# ── Singleton ─────────────────────────────────────────────────────
settings = Settings()

# ── Thread-safe lock cho set_novel ───────────────────────────────
_novel_lock = threading.Lock()


def set_novel(name: str) -> None:
    """Đặt novel hiện tại và tạo thư mục cần thiết.

    Gọi trước khi chạy pipeline hoặc khi người dùng đổi truyện trong UI.
    Thread-safe: dùng object.__setattr__ để bypass frozen dataclass.

    Args:
        name: Tên subfolder trong inputs/. Rỗng = reset về flat structure.
    """
    with _novel_lock:
        name = name.strip()
        object.__setattr__(settings, "novel_name", name)
        # Tạo thư mục cho novel mới
        settings._ensure_novel_dirs()

        # Reset logging handler về file log mới
        _reset_logging()

        if name:
            print(f"  📚 Novel: '{name}' → {settings.active_output_dir}")
        else:
            print(f"  📚 Novel: flat mode → {settings.output_dir}")


def _reset_logging() -> None:
    """Đổi log file khi novel thay đổi."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            handler.close()
            root_logger.removeHandler(handler)

    log_path = settings.log_dir / "pipeline.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    new_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    new_handler.setLevel(logging.ERROR)
    new_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    root_logger.addHandler(new_handler)


def get_available_novels() -> list[str]:
    """Liệt kê tất cả novel có trong inputs/ (là subfolder).

    Returns:
        Danh sách tên novel đã sort, hoặc [] nếu chỉ có flat structure.
    """
    inp = settings.input_dir
    if not inp.exists():
        return []

    novels = sorted([
        d.name for d in inp.iterdir()
        if d.is_dir() and not d.name.startswith(".")
        and any(f.suffix in (".txt", ".md") for f in d.iterdir())
    ])
    return novels