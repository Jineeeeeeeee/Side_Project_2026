"""
src/littrans/utils/post_processor.py — 14-pass code-only cleanup sau Trans-call.

Chạy NGAY SAU khi nhận output từ LLM, TRƯỚC khi ghi file và TRƯỚC Post-call.
Không dùng AI — thuần regex/string để tránh hallucination và tiết kiệm token.

14 pass theo thứ tự ưu tiên (nghiêm trọng → nhẹ):
  Pass 1:  Chuẩn hóa line endings
  Pass 2:  Xóa trailing whitespace mỗi dòng
  Pass 3:  Xóa code block wrapper bọc toàn bản dịch (```...```)
  Pass 4:  Xóa lời mở đầu / kết thúc của AI
  Pass 5:  Chuẩn hóa dấu ba chấm (... → …)
  Pass 6:  Chuẩn hóa em dash (-- → —)
  Pass 7:  Chuẩn hóa dấu ngoặc kép ("…" → "…") — typographic quotes
  Pass 8:  Xóa khoảng trắng thừa trước dấu chấm câu
  Pass 9:  Xóa dòng trống thừa TRONG system box
  Pass 10: Tách 2 lượt thoại bị dính dòng
  Pass 11: Đảm bảo mỗi đoạn thoại có dòng trống trước
  Pass 12: Kiểm tra [Kỹ năng] bị thiếu ngoặc vuông đóng
  Pass 13: Chuẩn hóa 3+ dòng trống → 1 dòng trống
  Pass 14: Final trim + kết thúc bằng \n

Trả về (cleaned_text, list[str]) — list chứa mô tả các thay đổi đã làm.
"""
from __future__ import annotations

import re

from littrans.core.patterns import BOX_BORDER_RE as _BOX_BORDER_RE, BOX_CONTENT_RE as _BOX_CONTENT_RE


# ── Patterns compile sẵn ─────────────────────────────────────────

# Pass 3: code block bọc toàn bộ
_CODE_BLOCK_WRAP = re.compile(
    r"^```(?:markdown|text|vn|vi|vietnamese)?\s*\n(.*?)\n```\s*$",
    re.DOTALL | re.IGNORECASE,
)

# Pass 4: lời mở đầu/kết thúc AI thường gặp
_AI_PREAMBLE = re.compile(
    r"^(dưới đây là bản dịch.*?\n|here is the translation.*?\n"
    r"|bản dịch.*?:\s*\n|translation.*?:\s*\n"
    r"|tôi đã dịch.*?\n|i have translated.*?\n"
    r"|chào\s*[,!].*?\n)",
    re.IGNORECASE | re.MULTILINE,
)
_AI_POSTAMBLE = re.compile(
    r"\n(hy vọng bản dịch.*|hope this (translation|helps).*"
    r"|lưu ý.*về bản dịch.*|note:.*translation.*"
    r"|nếu bạn cần.*chỉnh sửa.*)$",
    re.IGNORECASE,
)

# Pass 5: ba chấm
_ELLIPSIS_4PLUS = re.compile(r"\.{4,}")          # 4+ dấu chấm → …
_ELLIPSIS_3     = re.compile(r"(?<!\.)\.{3}(?!\.)") # đúng 3 dấu chấm → …
_ELLIPSIS_SPACE = re.compile(r"\. \. \.")          # ". . ." → …

# Pass 6: em dash
_DOUBLE_DASH = re.compile(r"(?<!\-)\-\-(?!\-)")   # -- nhưng không phải ---

# Pass 7: typographic quotes — chỉ với văn bản tiếng Việt
_STRAIGHT_QUOTE_OPEN  = re.compile(r'(?<!\w)"(?=\S)')
_STRAIGHT_QUOTE_CLOSE = re.compile(r'(?<=\S)"(?!\w)')

# Pass 8: khoảng trắng trước dấu chấm câu
_SPACE_BEFORE_PUNCT = re.compile(r" +([,\.!?:;…])")

# Pass 10: thoại dính dòng
# Phát hiện: dòng kết thúc bằng dấu thoại đóng, liền sau là thoại mở
_DIALOGUE_MERGE = re.compile(r'(["""]\s*)(["""]\s*\S)')

# Pass 11: thoại thiếu dòng trống trước
# Dòng thoại (bắt đầu bằng ") đứng ngay sau dòng nội dung (không trống)
_DIALOGUE_NO_BLANK = re.compile(r'(\S)\n(["""]\s*\S)')

# Pass 12: [Kỹ năng bị thiếu ngoặc vuông đóng
_UNCLOSED_BRACKET = re.compile(r'\[([^\[\]\n]{2,40})(?<!\])\n')

# Pass 13: nhiều dòng trống
_MULTI_BLANK = re.compile(r"\n{3,}")


# ── Public API ────────────────────────────────────────────────────

def run(text: str) -> tuple[str, list[str]]:
    """
    Chạy toàn bộ 14 pass.
    Trả về (cleaned_text, changes) — changes là list mô tả những gì đã sửa.
    """
    if not text or not text.strip():
        return text, []

    original = text
    changes: list[str] = []

    text, c = _pass1_line_endings(text)
    if c: changes.append(c)

    text, c = _pass2_trailing_ws(text)
    if c: changes.append(c)

    text, c = _pass3_code_block_wrapper(text)
    if c: changes.append(c)

    text, c = _pass4_ai_preamble(text)
    if c: changes.append(c)

    text, c = _pass5_ellipsis(text)
    if c: changes.append(c)

    text, c = _pass6_em_dash(text)
    if c: changes.append(c)

    text, c = _pass7_typographic_quotes(text)
    if c: changes.append(c)

    text, c = _pass8_space_before_punct(text)
    if c: changes.append(c)

    text, c = _pass9_system_box_blanks(text)
    if c: changes.append(c)

    text, c = _pass10_dialogue_merge(text)
    if c: changes.append(c)

    text, c = _pass11_dialogue_blank(text)
    if c: changes.append(c)

    text, c = _pass12_unclosed_bracket(text)
    if c: changes.append(c)

    text, c = _pass13_multi_blank(text)
    if c: changes.append(c)

    text, c = _pass14_final_trim(text)
    if c: changes.append(c)

    return text, changes


def report(changes: list[str]) -> str:
    """Format danh sách thay đổi để in ra log."""
    if not changes:
        return ""
    return "  🧹 Post-processor: " + " · ".join(changes)


# ── Pass implementations ──────────────────────────────────────────

def _pass1_line_endings(text: str) -> tuple[str, str]:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    if cleaned != text:
        return cleaned, "pass1:CRLF→LF"
    return text, ""


def _pass2_trailing_ws(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    if cleaned != text:
        n = sum(1 for a, b in zip(text.splitlines(), cleaned.splitlines()) if a != b)
        return cleaned, f"pass2:trailing_ws({n}dòng)"
    return text, ""


def _pass3_code_block_wrapper(text: str) -> tuple[str, str]:
    """Xóa code block bọc toàn bộ bản dịch."""
    stripped = text.strip()
    m = _CODE_BLOCK_WRAP.match(stripped)
    if m:
        return m.group(1).strip() + "\n", "pass3:code_block_wrapper"
    # Kiểm tra thêm: bắt đầu bằng ``` và kết thúc bằng ```
    if stripped.startswith("```") and stripped.endswith("```"):
        # Xóa dòng đầu (```) và dòng cuối (```)
        lines = stripped.splitlines()
        if len(lines) > 2:
            inner = "\n".join(lines[1:-1])
            return inner.strip() + "\n", "pass3:code_block_wrapper"
    return text, ""


def _pass4_ai_preamble(text: str) -> tuple[str, str]:
    """Xóa lời mở đầu / kết thúc của AI."""
    changed = False
    cleaned = _AI_PREAMBLE.sub("", text, count=3)
    if cleaned != text:
        changed = True
        text = cleaned
    cleaned = _AI_POSTAMBLE.sub("", text, count=2)
    if cleaned != text:
        changed = True
        text = cleaned
    return text, "pass4:ai_boilerplate" if changed else ""


def _pass5_ellipsis(text: str) -> tuple[str, str]:
    """Chuẩn hóa dấu ba chấm."""
    cleaned = _ELLIPSIS_SPACE.sub("…", text)
    cleaned = _ELLIPSIS_4PLUS.sub("…", cleaned)
    cleaned = _ELLIPSIS_3.sub("…", cleaned)
    if cleaned != text:
        n = text.count("...") + text.count(". . .")
        return cleaned, f"pass5:ellipsis({n})"
    return text, ""


def _pass6_em_dash(text: str) -> tuple[str, str]:
    """Chuẩn hóa -- → —."""
    cleaned = _DOUBLE_DASH.sub("—", text)
    if cleaned != text:
        n = len(_DOUBLE_DASH.findall(text))
        return cleaned, f"pass6:em_dash({n})"
    return text, ""


def _pass7_typographic_quotes(text: str) -> tuple[str, str]:
    """
    Chuyển straight quotes → typographic quotes.
    Chỉ áp dụng nếu văn bản có nhiều straight quotes hơn typographic quotes
    (tránh đảo ngược những gì đã đúng).
    """
    straight_count = text.count('"')
    typo_count = text.count('\u201c') + text.count('\u201d')

    if straight_count == 0 or typo_count > straight_count / 2:
        return text, ""

    # Áp dụng đơn giản: thay đổi context-aware
    cleaned = _STRAIGHT_QUOTE_OPEN.sub('\u201c', text)   # " → "
    cleaned = _STRAIGHT_QUOTE_CLOSE.sub('\u201d', cleaned)  # " → "

    if cleaned != text:
        return cleaned, f"pass7:typographic_quotes({straight_count})"
    return text, ""


def _pass8_space_before_punct(text: str) -> tuple[str, str]:
    """Xóa khoảng trắng thừa TRƯỚC dấu chấm câu (không phải sau)."""
    # Chỉ xử lý trong đoạn văn thường, bỏ qua system box
    lines = text.splitlines(keepends=True)
    result = []
    changed_count = 0
    for line in lines:
        # Bỏ qua dòng box
        if _BOX_BORDER_RE.search(line.strip()):
            result.append(line)
            continue
        cleaned_line = _SPACE_BEFORE_PUNCT.sub(r"\1", line)
        if cleaned_line != line:
            changed_count += 1
        result.append(cleaned_line)
    cleaned = "".join(result)
    if changed_count:
        return cleaned, f"pass8:space_before_punct({changed_count}dòng)"
    return text, ""


def _pass9_system_box_blanks(text: str) -> tuple[str, str]:
    """Xóa dòng trống thừa TRONG system box."""
    lines   = text.split("\n")
    result  : list[str] = []
    in_box  = False
    removed = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        is_border = bool(_BOX_BORDER_RE.search(stripped)) and len(stripped) >= 3

        if is_border:
            in_box = True
            result.append(line)
            continue

        if in_box:
            if not stripped:
                # Kiểm tra dòng không rỗng tiếp theo
                next_content = None
                for j in range(i + 1, min(i + 6, len(lines))):
                    if lines[j].strip():
                        next_content = lines[j].strip()
                        break

                if next_content and (
                    _BOX_CONTENT_RE.match(next_content)
                    or _BOX_BORDER_RE.search(next_content)
                    or (len(next_content) < 80 and ":" in next_content)
                ):
                    removed += 1
                    continue  # Bỏ dòng trống này
                else:
                    in_box = False
                    result.append(line)
            else:
                result.append(line)
                # Thoát box nếu gặp đoạn văn dài
                if len(stripped) > 120 and not _BOX_CONTENT_RE.match(stripped):
                    in_box = False
        else:
            result.append(line)

    cleaned = "\n".join(result)
    if removed:
        return cleaned, f"pass9:box_blanks({removed})"
    return text, ""


def _pass10_dialogue_merge(text: str) -> tuple[str, str]:
    """
    Phát hiện 2 lượt thoại bị dính dòng:
    "...câu A." "Câu B..." → tách thành 2 đoạn.
    """
    # Pattern: dấu ngoặc kép đóng → khoảng trắng → dấu ngoặc kép mở → nội dung
    pattern = re.compile(r'(["""])\s{0,2}(["""](?=[^\s]))')
    cleaned = pattern.sub(r'\1\n\n\2', text)
    if cleaned != text:
        n = len(pattern.findall(text))
        return cleaned, f"pass10:dialogue_split({n})"
    return text, ""


def _pass11_dialogue_blank(text: str) -> tuple[str, str]:
    """
    Đảm bảo dòng thoại có dòng trống trước nó.
    Chỉ áp dụng khi dòng trước là nội dung (không phải dòng trống).
    """
    # Dòng bắt đầu bằng " đứng ngay sau dòng có nội dung
    pattern = re.compile(r'([^\n])\n([""\u201c\u201d][^\n]{3,})')
    cleaned = pattern.sub(r'\1\n\n\2', text)
    if cleaned != text:
        n = len(pattern.findall(text))
        return cleaned, f"pass11:dialogue_blank({n})"
    return text, ""


def _pass12_unclosed_bracket(text: str) -> tuple[str, str]:
    """
    Phát hiện [Kỹ năng bị thiếu ] đóng cuối dòng.
    Chỉ sửa khi bracket rõ ràng là tên kỹ năng (2–40 ký tự, không có newline).
    """
    def fix_bracket(m: re.Match) -> str:
        content = m.group(1)
        return f"[{content}]\n"

    cleaned = _UNCLOSED_BRACKET.sub(fix_bracket, text)
    if cleaned != text:
        n = len(_UNCLOSED_BRACKET.findall(text))
        return cleaned, f"pass12:unclosed_bracket({n})"
    return text, ""


def _pass13_multi_blank(text: str) -> tuple[str, str]:
    """3+ dòng trống → 1 dòng trống."""
    cleaned = _MULTI_BLANK.sub("\n\n", text)
    if cleaned != text:
        n = len(_MULTI_BLANK.findall(text))
        return cleaned, f"pass13:multi_blank({n})"
    return text, ""


def _pass14_final_trim(text: str) -> tuple[str, str]:
    """Trim đầu/cuối, đảm bảo kết thúc bằng đúng 1 dòng trống."""
    cleaned = text.strip() + "\n"
    if cleaned != text:
        return cleaned, "pass14:trim"
    return text, ""