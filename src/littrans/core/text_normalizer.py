"""
src/littrans/utils/text_normalizer.py — Chuẩn hóa raw text trước khi dịch.

Xử lý các vấn đề phổ biến của raw LitRPG / Tu Tiên text:
  ① Câu bị cắt giữa chừng (mid-sentence line break)
  ② Nhiều dòng trống liên tiếp (3, 4, 5+) → đúng 1 dòng trống
  ③ Khoảng trắng thừa cuối dòng
  ④ Dòng trống thừa TRONG system box

BẢO TỒN — không đụng vào:
  ✅ System box / bảng (─ ═ │ ▸ ◆ ...)  → giữ nguyên cấu trúc
  ✅ Heading markdown (# ## ###)
  ✅ Dòng trống (ranh giới đoạn)
  ✅ Dòng hội thoại ("...") đứng riêng
  ✅ Dòng ngắn ≤ 60 chars (stats, tên, sfx, danh hiệu)
"""
from __future__ import annotations

import re

from littrans.core.patterns import (
    BOX_CHARS_RE as _BOX_CHARS_RE,
    RULE_LINE_RE as _RULE_LINE_RE,
    BOX_KEYWORD_RE as _BOX_KEYWORD_RE,
)


# ── Patterns ──────────────────────────────────────────────────────

# Heading Markdown
_HEADING_RE = re.compile(r"^#{1,6}\s")

# Dòng thoại mở đầu bằng dấu ngoặc kép các loại
_DIALOGUE_OPEN_RE = re.compile(r'^["\u201c\u2018\u300c\u300e\u3010\u00ab\u2039]')

# Kết thúc câu hoàn chỉnh
_COMPLETE_END_RE = re.compile(
    r'[.!?\u2026"\u201d\u2019\u300d\u300f\u3011\u3015\u00bb\u203a:;\-\u2014\])]$'
)

# 3+ dòng trống liên tiếp
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# Trailing whitespace per line
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)

# Dấu mở của system box (dùng để detect bắt đầu một box)
_BOX_OPEN_CHARS = {"─", "═", "━", "╔", "┌", "╠", "║", "│", "▓", "▒"}


# ── Public API ────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """
    Entry point. Chuẩn hóa raw EN text — an toàn, không mất nội dung.
    Thực hiện theo thứ tự:
      1. Chuẩn hóa line endings & trailing spaces
      2. Gom dòng bị cắt giữa câu (mid-sentence break)
      3. Xóa dòng trống thừa trong system box
      4. Chuẩn hóa 3+ dòng trống → 1 dòng trống
    """
    if not text or not text.strip():
        return text

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_WS_RE.sub("", text)
    text = _rejoin_broken_lines(text)
    text = _clean_box_blank_lines(text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


# ── Step 2: Gom dòng vỡ ──────────────────────────────────────────

def _rejoin_broken_lines(text: str) -> str:
    """
    Duyệt từng dòng, gom các dòng bị cắt giữa câu.

    Điều kiện để GOM dòng hiện tại vào dòng trước:
      - Dòng trước không kết thúc hoàn chỉnh (không có dấu câu cuối)
      - Dòng trước dài ≥ 60 chars (không phải dòng ngắn có chủ đích)
      - Dòng hiện tại KHÔNG phải: rỗng / heading / box / hội thoại / ngắn

    Điều kiện KHÔNG GOM (bảo tồn):
      - Dòng rỗng → luôn giữ
      - Heading (# ##) → luôn giữ
      - Box line (─ ═ ...) → luôn giữ
      - Dòng hội thoại đứng riêng ("...") → luôn giữ
      - Dòng ngắn ≤ 60 chars → luôn giữ
    """
    lines   = text.split("\n")
    result  : list[str] = []
    pending : str       = ""   # buffer dòng chưa kết thúc

    for line in lines:
        stripped = line.rstrip()

        # Dòng rỗng
        if not stripped.strip():
            if pending:
                result.append(pending)
                pending = ""
            result.append("")
            continue

        # Dòng đặc biệt → flush + giữ nguyên
        if _is_special_line(stripped):
            if pending:
                result.append(pending)
                pending = ""
            result.append(stripped)
            continue

        # Dòng ngắn ≤ 60 chars → không gom, coi là intentional
        if len(stripped.strip()) <= 60:
            if pending:
                result.append(pending)
                pending = ""
            result.append(stripped)
            continue

        # Dòng dài
        if pending:
            # Đang có buffer → nối vào
            pending = pending + " " + stripped.strip()
            if _COMPLETE_END_RE.search(pending):
                result.append(pending)
                pending = ""
        else:
            # Bắt đầu buffer mới nếu dòng chưa kết thúc hoàn chỉnh
            if _COMPLETE_END_RE.search(stripped):
                result.append(stripped)
            else:
                pending = stripped

    if pending:
        result.append(pending)

    return "\n".join(result)


def _is_special_line(line: str) -> bool:
    """Trả về True nếu dòng cần được bảo tồn nguyên vẹn."""
    stripped = line.strip()
    if _HEADING_RE.match(stripped):
        return True
    if _RULE_LINE_RE.match(stripped):
        return True
    if _BOX_CHARS_RE.search(stripped):
        return True
    if _DIALOGUE_OPEN_RE.match(stripped):
        return True
    if _BOX_KEYWORD_RE.match(stripped):
        return True
    if stripped.startswith(("|", ">", "+")):
        return True
    return False


# ── Step 3: Xóa dòng trống thừa trong system box ─────────────────

def _clean_box_blank_lines(text: str) -> str:
    """
    System box không được có dòng trống ở giữa các dòng nội dung.

    Thuật toán: nhận diện "đang trong box" dựa trên ký tự mở box.
    Khi inside_box=True → xóa dòng trống giữa các dòng nội dung.
    """
    lines   = text.split("\n")
    result  : list[str] = []
    in_box  = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Nhận diện ranh giới box
        is_box_border = bool(
            _BOX_CHARS_RE.search(stripped) or
            _RULE_LINE_RE.match(stripped)
        )

        if is_box_border:
            in_box = True
            result.append(line)
            continue

        if in_box:
            if not stripped:
                # Dòng trống trong box: kiểm tra dòng tiếp theo
                # Nếu dòng tiếp theo là nội dung box → bỏ dòng trống này
                next_non_empty = _peek_next_non_empty(lines, i)
                if next_non_empty is not None and _looks_like_box_content(next_non_empty):
                    continue   # bỏ dòng trống
                else:
                    # Dòng trống trước đoạn văn thường → kết thúc box
                    in_box = False
                    result.append(line)
            else:
                result.append(line)
        else:
            result.append(line)

    return "\n".join(result)


def _peek_next_non_empty(lines: list[str], current: int) -> str | None:
    """Tìm dòng không rỗng tiếp theo sau vị trí current."""
    for j in range(current + 1, len(lines)):
        if lines[j].strip():
            return lines[j].strip()
    return None


def _looks_like_box_content(line: str) -> bool:
    """
    Heuristic: dòng có vẻ là nội dung box không?
    → có ký tự box, hoặc là keyword system, hoặc ngắn và có dấu :
    """
    stripped = line.strip()
    if _BOX_CHARS_RE.search(stripped):
        return True
    if _BOX_KEYWORD_RE.match(stripped):
        return True
    if _RULE_LINE_RE.match(stripped):
        return True
    # Dòng ngắn có dấu ":" → thường là stat (HP: 100, Level: 5)
    if len(stripped) < 60 and ":" in stripped:
        return True
    return False