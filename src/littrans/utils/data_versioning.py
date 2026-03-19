"""
src/littrans/utils/data_versioning.py — Backup & versioning cho data files.

Dùng để:
  - Backup trước khi ghi đè (clean_glossary, clean_characters)
  - Giữ tối đa N bản backup (auto-rotate)
  - Restore bản backup khi cần

API:
    backup(path)                 → tạo path.bak.YYYYMMDD_HHMMSS
    restore_latest(path)         → restore từ bản backup mới nhất
    list_backups(path)           → list tất cả bản backup
    prune_old_backups(path, n=5) → xóa backup cũ hơn N bản
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def backup(path: str | Path, suffix: str = "") -> Path:
    """
    Tạo bản backup: path → path.bak.YYYYMMDD_HHMMSS[.suffix]
    Trả về đường dẫn file backup.
    """
    src  = Path(path)
    if not src.exists():
        return src  # không có gì để backup

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext  = f".bak.{ts}" + (f".{suffix}" if suffix else "")
    dest = src.with_suffix(src.suffix + ext)
    shutil.copy2(src, dest)
    return dest


def restore_latest(path: str | Path) -> bool:
    """
    Restore từ bản backup mới nhất.
    Trả về True nếu thành công.
    """
    backups = list_backups(path)
    if not backups:
        return False
    latest = backups[-1]
    shutil.copy2(latest, path)
    return True


def list_backups(path: str | Path) -> list[Path]:
    """
    Trả về danh sách backup files, sắp xếp theo thời gian (cũ → mới).
    """
    p       = Path(path)
    pattern = f"{p.name}.bak.*"
    backups = sorted(p.parent.glob(pattern))
    return backups


def prune_old_backups(path: str | Path, keep: int = 5) -> int:
    """
    Xóa backup cũ, giữ lại `keep` bản mới nhất.
    Trả về số file đã xóa.
    """
    backups = list_backups(path)
    to_delete = backups[:-keep] if len(backups) > keep else []
    for f in to_delete:
        f.unlink(missing_ok=True)
    return len(to_delete)
