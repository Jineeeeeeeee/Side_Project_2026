"""
src/littrans/utils/text_normalizer.py — Redirect shim.

[v5.3 Refactor] File đã chuyển về core/text_normalizer.py.
Giữ lại để không break import cũ. Không sửa file này.
"""
from littrans.core.text_normalizer import (  # noqa: F401
    normalize,
)

__all__ = ["normalize"]
