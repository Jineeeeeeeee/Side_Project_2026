"""
src/littrans/utils/io_utils.py — Đọc/ghi file an toàn.

Atomic write (tempfile → os.replace) tránh corrupt khi bị kill giữa chừng.
"""
from __future__ import annotations

import os
import json
import logging
import tempfile
from pathlib import Path


def load_text(filepath: str | Path) -> str:
    fp = str(filepath)
    if not os.path.exists(fp):
        return ""
    with open(fp, "r", encoding="utf-8") as f:
        return f.read()


def load_json(filepath: str | Path) -> dict:
    raw = load_text(filepath)
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logging.error(f"JSON lỗi '{filepath}': {e}")
        return {}


def save_json(filepath: str | Path, data: dict) -> None:
    atomic_write(str(filepath), json.dumps(data, ensure_ascii=False, indent=2))


def atomic_write(filepath: str | Path, content: str) -> None:
    """Ghi file nguyên tử — không bao giờ để file ở trạng thái không đầy đủ."""
    fp      = str(filepath)
    dir_name = os.path.dirname(fp) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, fp)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
