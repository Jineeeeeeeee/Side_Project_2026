"""
src/littrans/utils/logger.py — Logging helpers.

Cung cấp get_logger() trả về logger có tên module,
và log_warning() / log_error() tắt try/except lặp đi lặp lại.
"""
from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Lấy logger với tên module — dùng thay cho logging.error/warning trực tiếp."""
    return logging.getLogger(name)


def log_error(name: str, msg: str, exc: Exception | None = None) -> None:
    logger = get_logger(name)
    if exc:
        logger.error(f"{msg}: {exc}", exc_info=False)
    else:
        logger.error(msg)


def log_warning(name: str, msg: str) -> None:
    get_logger(name).warning(msg)
