"""
main.py — Entry point duy nhất cho toàn bộ pipeline.

Cách dùng:
    python main.py translate
    python main.py retranslate [KEYWORD]
    python main.py clean glossary
    python main.py clean characters [--action merge|review|...]
    python main.py fix-names [--list] [--dry-run]
    python main.py --help
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from littrans.cli import app  # noqa: E402  (phải sau reconfigure)

if __name__ == "__main__":
    app()
