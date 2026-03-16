"""
translate.py — Entry point.
Chạy: python translate.py
Cấu hình qua .env (xem core/config.py).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from core.runner import process_chapters
if __name__ == "__main__":
    process_chapters()
