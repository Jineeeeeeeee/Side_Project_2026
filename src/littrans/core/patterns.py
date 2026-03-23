"""
src/littrans/core/patterns.py — Shared regex patterns cho toàn bộ pipeline.

Tập trung tất cả patterns box detection, word boundary, v.v. vào 1 nơi.
Import từ đây để tránh trùng lặp giữa:
  quality_guard.py, post_processor.py, text_normalizer.py, characters.py,...

[v5.5] Tách ra từ quality_guard + post_processor + text_normalizer.
"""
from __future__ import annotations

import re


# ── System box detection ─────────────────────────────────────────

# Ký tự đặc trưng của system box
BOX_BORDER_RE = re.compile(
    r"[─═━╔╗╚╝╠╣╦╩╬│┌┐└┘■▸◆►●▓▒░]"
    r"|^\s*[-=*~]{3,}\s*$",
    re.MULTILINE,
)

# Dòng kẻ ASCII (---, ===, ***,  ~~~, ...)
RULE_LINE_RE = re.compile(r"^\s*[-=*~_+|]{3,}\s*$")

# Keyword thường xuất hiện TRONG system box
BOX_CONTENT_RE = re.compile(
    r"^\s*(\[.+\]|ding!?|level up|thăng cấp|cấp độ|chỉ số|kỹ năng"
    r"|hp:|mp:|exp:|xp:|str:|agi:|int:|vit:|luk:|cd:|phát hiện|hệ thống)",
    re.IGNORECASE,
)

# Ký tự box mở rộng (dùng bởi text_normalizer)
BOX_CHARS_RE = re.compile(
    r"[─═━┄┈╌╍■□▪▫▸◆◇►●○•│┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬▓▒░✦✧✫✬]"
)

# Keyword system box thường gặp trong LitRPG (text_normalizer)
BOX_KEYWORD_RE = re.compile(
    r"^\s*(ding!?|level up!?|you have|congratulations|quest|system notification"
    r"|skill learned|achievement|status window|class:|race:|title:|hp:|mp:|xp:|exp:"
    r"|\[.+\]$)",
    re.IGNORECASE,
)


# ── Unicode word boundary ────────────────────────────────────────

def word_boundary_pattern(name: str) -> str:
    """
    Tạo regex pattern cho tên với Unicode word boundary.

    Dùng lookaround Unicode (?<![^\\W_])...(?![^\\W_]) thay vì \\b
    để xử lý đúng với tiếng Việt và ký tự đặc biệt.

    Returns:
        Regex pattern string (chưa compile).
    """
    return rf"(?<![^\W_]){re.escape(name)}(?![^\W_])"


def word_boundary_search(name: str, text: str) -> bool:
    """
    Kiểm tra tên có xuất hiện trong text với word boundary.

    Dùng Unicode word boundary, fallback sang str.count() nếu regex lỗi.
    """
    if not name or not text:
        return False
    try:
        return bool(re.search(
            word_boundary_pattern(name),
            text,
            re.IGNORECASE | re.UNICODE,
        ))
    except re.error:
        return name.lower() in text.lower()


def word_boundary_count(name: str, text: str) -> int:
    """
    Đếm số lần tên xuất hiện trong text với word boundary.

    Dùng Unicode word boundary, fallback sang str.count() nếu regex lỗi.
    """
    if not name or not text:
        return 0
    try:
        return len(re.findall(
            word_boundary_pattern(name),
            text,
            re.IGNORECASE | re.UNICODE,
        ))
    except re.error:
        return text.lower().count(name.lower())
