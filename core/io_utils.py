"""
core/io_utils.py — Đọc/ghi file an toàn.
Atomic write (tempfile → os.replace) để tránh corrupt khi bị kill giữa chừng.
"""
import os, json, logging, tempfile

def load_text(filepath: str) -> str:
    if not os.path.exists(filepath):
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

def load_json(filepath: str) -> dict:
    raw = load_text(filepath)
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logging.error(f"JSON lỗi '{filepath}': {e}")
        return {}

def save_json(filepath: str, data: dict) -> None:
    _atomic_write_str(filepath, json.dumps(data, ensure_ascii=False, indent=2))

def save_text_atomic(filepath: str, content: str) -> None:
    _atomic_write_str(filepath, content)

def _atomic_write_str(filepath: str, content: str) -> None:
    dir_name = os.path.dirname(filepath) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, filepath)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
