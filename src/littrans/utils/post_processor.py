"""
src/littrans/utils/post_processor.py — Redirect shim.

[v5.3 Refactor] File đã chuyển về core/post_processor.py.
Giữ lại để không break import cũ. Không sửa file này.
"""
from littrans.core.post_processor import (  # noqa: F401
    run,
    report,
)

__all__ = ["run", "report"]
