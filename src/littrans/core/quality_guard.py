"""
src/littrans/engine/quality_guard.py — Kiểm tra chất lượng bản dịch.

7 tiêu chí (thêm system_box so với v4.2):
  1. Dính dòng nghiêm trọng  → dòng vượt MAX_LINE_LENGTH ký tự
  2. Quá ít dòng             → tổng dòng không rỗng < MIN_TRANSLATION_LINES
  3. Mất dòng so với bản gốc → tỉ lệ mất > MAX_MERGED_LINE_RATIO  (0.50)
  4. Thiếu dòng trống        → blank_ratio < MIN_BLANK_LINE_RATIO
  5. Bản dịch quá ngắn       → char_ratio < MIN_CHAR_RATIO
  6. Còn nhiều dòng tiếng Anh chưa dịch
  7. [MỚI] System box có dòng trống thừa GIỮA các dòng nội dung

Trả về (True, "") nếu ổn, (False, mô_tả_lỗi) nếu phát hiện vấn đề.
"""
from __future__ import annotations

import re

from littrans.core.patterns import BOX_BORDER_RE as _BOX_BORDER_RE, BOX_CONTENT_RE as _BOX_CONTENT_RE

MIN_TRANSLATION_LINES  = 10
MAX_LINE_LENGTH        = 1000
MAX_MERGED_LINE_RATIO  = 0.50
MIN_BLANK_LINE_RATIO   = 0.20
MIN_CHAR_RATIO         = 0.45
MAX_UNTRANSLATED_RATIO = 0.15


# ── System box checker ────────────────────────────────────────────

def _check_system_box_blanks(translation: str) -> tuple[bool, str]:
    """
    Kiểm tra dòng trống thừa TRONG system box.

    Thuật toán: nhận diện box bằng ký tự border (─ ═ ...).
    Khi inside_box=True, dòng trống tiếp theo sau nội dung là lỗi.

    Trả về (True, "") nếu ổn.
    """
    lines   = translation.splitlines()
    in_box  = False
    issues  = 0
    example = ""

    prev_was_content = False  # dòng trước là nội dung box (không phải border)

    for i, line in enumerate(lines):
        stripped = line.strip()
        is_border = bool(_BOX_BORDER_RE.search(stripped)) and len(stripped) >= 3

        if is_border:
            in_box           = True
            prev_was_content = False
            continue

        if in_box:
            if not stripped:
                # Dòng trống trong box sau nội dung → lỗi nếu còn nội dung box tiếp theo
                # Look ahead
                for j in range(i + 1, min(i + 5, len(lines))):
                    next_s = lines[j].strip()
                    if next_s and (_BOX_CONTENT_RE.match(next_s)
                                   or _BOX_BORDER_RE.search(next_s)
                                   or (len(next_s) < 80 and ":" in next_s)):
                        issues += 1
                        if not example:
                            example = f"«{lines[i - 1].strip()[:40]}» ← dòng trống thừa"
                        break
                    elif next_s:
                        # Dòng tiếp theo là văn thường → kết thúc box
                        in_box = False
                        break
            else:
                prev_was_content = True
                # Nếu rời xa box (đoạn văn thường > 100 chars) → thoát box
                if len(stripped) > 100 and not _BOX_CONTENT_RE.match(stripped):
                    in_box = False

    if issues >= 3:
        return False, (
            f"SYSTEM BOX CÓ DÒNG TRỐNG THỪA: phát hiện {issues} chỗ dòng trống "
            f"nằm giữa các dòng nội dung system box. {example}\n"
            f"Quy tắc: nội dung trong box PHẢI liền nhau, không có dòng trống ở giữa."
        )
    return True, ""


# ── Untranslated lines checker ────────────────────────────────────

def _count_untranslated_lines(lines: list[str]) -> int:
    count = 0
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 20:
            continue
        ascii_alpha = sum(1 for c in stripped if c.isascii() and c.isalpha())
        if ascii_alpha / len(stripped) > 0.70:
            count += 1
    return count


# ── Main check ────────────────────────────────────────────────────

def check(translation: str, source_text: str = "") -> tuple[bool, str]:
    """
    Kiểm tra bản dịch.
    Trả về (True, "") nếu ổn, (False, mô_tả_lỗi) nếu phát hiện vấn đề.
    Thứ tự: lỗi nghiêm trọng nhất → nhẹ nhất.
    """
    if not translation or not translation.strip():
        return False, "Bản dịch rỗng."

    all_lines       = translation.splitlines()
    non_empty_lines = [l for l in all_lines if l.strip()]
    blank_lines     = [l for l in all_lines if not l.strip()]
    line_count      = len(non_empty_lines)
    total_lines     = len(all_lines)

    # ── Kiểm tra 1: dính dòng nghiêm trọng ───────────────────────
    long_lines = [l for l in non_empty_lines if len(l) > MAX_LINE_LENGTH]
    if long_lines:
        longest = max(len(l) for l in long_lines)
        return False, (
            f"DÍNH DÒNG NGHIÊM TRỌNG: {len(long_lines)} dòng vượt {MAX_LINE_LENGTH} ký tự "
            f"(dài nhất: {longest} ký tự). Toàn bộ nội dung bị gộp vào một số dòng duy nhất."
        )

    # ── Kiểm tra 2: quá ít dòng ──────────────────────────────────
    if line_count < MIN_TRANSLATION_LINES:
        return False, (
            f"DÍNH DÒNG: Bản dịch chỉ có {line_count} dòng "
            f"(tối thiểu: {MIN_TRANSLATION_LINES}). "
            f"Nhiều đoạn văn bị gộp thành một dòng."
        )

    src_lines = 0
    if source_text and source_text.strip():
        src_lines = len([l for l in source_text.splitlines() if l.strip()])

    # ── Kiểm tra 3: mất dòng so với bản gốc ─────────────────────
    if src_lines >= MIN_TRANSLATION_LINES:
        lost_ratio = (src_lines - line_count) / src_lines
        if lost_ratio > MAX_MERGED_LINE_RATIO:
            lost_pct = int(lost_ratio * 100)
            return False, (
                f"DÍNH DÒNG NHIỀU CHỖ: Bản gốc {src_lines} dòng, "
                f"bản dịch còn {line_count} dòng "
                f"(mất {lost_pct}%, ngưỡng: {int(MAX_MERGED_LINE_RATIO*100)}%). "
                f"Cần xuống dòng đúng như bản gốc."
            )

    # ── Kiểm tra 4: thiếu dòng trống ─────────────────────────────
    if total_lines >= MIN_TRANSLATION_LINES:
        blank_ratio = len(blank_lines) / total_lines if total_lines > 0 else 0
        if blank_ratio < MIN_BLANK_LINE_RATIO:
            blank_pct = int(blank_ratio * 100)
            return False, (
                f"THIẾU DÒNG TRỐNG: {len(blank_lines)}/{total_lines} dòng trống "
                f"({blank_pct}%, ngưỡng: {int(MIN_BLANK_LINE_RATIO*100)}%). "
                f"Mỗi đoạn văn phải cách nhau đúng 1 dòng trống."
            )

    # ── Kiểm tra 5: bản dịch quá ngắn ────────────────────────────
    if source_text and source_text.strip():
        src_char_count = len(source_text.strip())
        trl_char_count = len(translation.strip())
        if src_char_count > 200:
            char_ratio = trl_char_count / src_char_count
            if char_ratio < MIN_CHAR_RATIO:
                return False, (
                    f"BẢN DỊCH QUÁ NGẮN: chỉ {int(char_ratio*100)}% độ dài bản gốc "
                    f"({trl_char_count:,} / {src_char_count:,} ký tự, "
                    f"ngưỡng tối thiểu: {int(MIN_CHAR_RATIO*100)}%). "
                    f"Nhiều đoạn văn có thể bị bỏ qua."
                )

    # ── Kiểm tra 6: còn dòng tiếng Anh chưa dịch ─────────────────
    if line_count >= MIN_TRANSLATION_LINES:
        untranslated       = _count_untranslated_lines(non_empty_lines)
        untranslated_ratio = untranslated / line_count
        if untranslated_ratio > MAX_UNTRANSLATED_RATIO and untranslated >= 5:
            return False, (
                f"CÒN DÒNG CHƯA DỊCH: {untranslated}/{line_count} dòng "
                f"({int(untranslated_ratio*100)}%) vẫn là tiếng Anh "
                f"(ngưỡng: {int(MAX_UNTRANSLATED_RATIO*100)}%). "
                f"Kiểm tra lại và dịch các dòng còn sót."
            )

    # ── Kiểm tra 7: dòng trống thừa trong system box ─────────────
    if total_lines >= MIN_TRANSLATION_LINES:
        ok_box, box_msg = _check_system_box_blanks(translation)
        if not ok_box:
            return False, box_msg

    return True, ""


# ── Retry prompt ──────────────────────────────────────────────────

def build_retry_prompt(original_text: str, quality_msg: str) -> str:
    """Tạo input text có gắn cảnh báo khi yêu cầu AI dịch lại."""
    if "DÍNH DÒNG" in quality_msg or "THIẾU DÒNG TRỐNG" in quality_msg:
        specific = (
            "  • TUYỆT ĐỐI KHÔNG gộp nhiều đoạn thành một dòng\n"
            "  • Mỗi đoạn văn gốc = MỘT đoạn văn trong bản dịch\n"
            "  • Sau mỗi đoạn văn PHẢI có đúng 1 dòng trống\n"
            "  • Đối thoại mỗi lượt thoại = 1 đoạn + 1 dòng trống\n"
        )
    elif "QUÁ NGẮN" in quality_msg:
        specific = (
            "  • KHÔNG bỏ qua bất kỳ đoạn văn, câu, hay hội thoại nào\n"
            "  • Dịch ĐẦY ĐỦ 100% nội dung, không tóm tắt hay rút gọn\n"
            "  • Mỗi đoạn gốc phải có đoạn dịch tương ứng\n"
        )
    elif "CHƯA DỊCH" in quality_msg:
        specific = (
            "  • Dịch TẤT CẢ các dòng tiếng Anh sang tiếng Việt\n"
            "  • Chỉ giữ nguyên tên riêng đã có trong Name Lock Table\n"
            "  • Hội thoại, mô tả, kỹ năng — tất cả phải được dịch\n"
        )
    elif "SYSTEM BOX" in quality_msg:
        specific = (
            "  • Nội dung trong system box / bảng hệ thống PHẢI liền nhau\n"
            "  • KHÔNG có dòng trống giữa các dòng trong box (─═│▸◆ ...)\n"
            "  • Chỉ có 1 dòng trống TRƯỚC và SAU box để phân tách với đoạn văn thường\n"
        )
    else:
        specific = (
            "  • GIỮ NGUYÊN cấu trúc đoạn văn của bản gốc\n"
            "  • Xuống dòng và dòng trống đúng như bản gốc\n"
        )

    return (
        f"⚠️ CẢNH BÁO: Bản dịch lần trước bị lỗi — {quality_msg}\n\n"
        f"Hãy dịch lại TOÀN BỘ chương dưới đây, đảm bảo:\n"
        f"{specific}"
        f"  • Số dòng bản dịch phải xấp xỉ số dòng bản gốc\n\n"
        f"--- NỘI DUNG GỐC ---\n\n{original_text}"
    )