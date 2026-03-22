"""
patch_settings.py — Tự động thêm Bible config vào settings.py.
Chạy từ thư mục gốc project: python patch_settings.py
"""
from pathlib import Path

TARGET = Path("src/littrans/config/settings.py")
if not TARGET.exists():
    print(f"❌ Không tìm thấy {TARGET}")
    exit(1)

content = TARGET.read_text(encoding="utf-8")

# Kiểm tra đã patch chưa
if "bible_mode" in content:
    print("✅ Settings đã có Bible config — bỏ qua.")
    exit(0)

# 1. Thêm fields vào class Settings
BIBLE_FIELDS = """
    # ── Bible System ──────────────────────────────────────────────
    bible_mode          : bool = field(default_factory=lambda: _env_bool("BIBLE_MODE", False))
    bible_scan_batch    : int  = field(default_factory=lambda: _env_int("BIBLE_SCAN_BATCH", 5))
    bible_scan_sleep    : int  = field(default_factory=lambda: _env_int("BIBLE_SCAN_SLEEP", 10))
    bible_scan_depth    : str  = field(default_factory=lambda: _env("BIBLE_SCAN_DEPTH", "standard"))
    bible_cross_ref     : bool = field(default_factory=lambda: _env_bool("BIBLE_CROSS_REF", True))
    _bible_dir_raw      : str  = field(default_factory=lambda: _env("BIBLE_DIR", "data/bible"))

"""

INSERT_BEFORE = "    # ── Known valid model names"
content = content.replace(INSERT_BEFORE, BIBLE_FIELDS + INSERT_BEFORE)

# 2. Thêm properties
BIBLE_PROPS = """
    @property
    def bible_dir(self) -> Path:
        return Path(self._bible_dir_raw)

    @property
    def bible_available(self) -> bool:
        \"\"\"True nếu Bible đã được scan ít nhất một phần.\"\"\"
        return (self.bible_dir / "meta.json").exists()

"""

INSERT_BEFORE_PROP = "    @property\n    def glossary_dir"
content = content.replace(INSERT_BEFORE_PROP, BIBLE_PROPS + "    @property\n    def glossary_dir")

# 3. Thêm mkdir vào __post_init__
BIBLE_MKDIR = """
        if self.bible_mode:
            self.bible_dir.mkdir(parents=True, exist_ok=True)
            (self.bible_dir / "database").mkdir(parents=True, exist_ok=True)
            (self.bible_dir / "staging").mkdir(parents=True, exist_ok=True)
"""

INSERT_BEFORE_MKDIR = "\n        self.log_dir.mkdir(parents=True, exist_ok=True)"
content = content.replace(INSERT_BEFORE_MKDIR, BIBLE_MKDIR + "\n        self.log_dir.mkdir(parents=True, exist_ok=True)")

TARGET.write_text(content, encoding="utf-8")
print("✅ Đã patch settings.py thành công!")
print("   Thêm các biến vào .env nếu muốn dùng Bible System:")
print("   BIBLE_MODE=true")
print("   BIBLE_SCAN_DEPTH=standard  # quick|standard|deep")
print("   BIBLE_SCAN_BATCH=5")
print("   BIBLE_DIR=data/bible")