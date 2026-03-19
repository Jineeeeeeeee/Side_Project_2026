"""
src/littrans/engine/quality_guard.py — Kiểm tra chất lượng bản dịch.

4 tiêu chí:
  1. Dính dòng nghiêm trọng  → dòng vượt MAX_LINE_LENGTH ký tự
  2. Quá ít dòng             → tổng dòng không rỗng < MIN_TRANSLATION_LINES
  3. Mất dòng so với bản gốc → tỉ lệ mất > MAX_MERGED_LINE_RATIO
  4. Thiếu dòng trống        → blank_ratio < MIN_BLANK_LINE_RATIO

Trả về (True, "") nếu ổn, (False, mô_tả_lỗi) nếu phát hiện vấn đề.

Nếu vi phạm → pipeline yêu cầu AI dịch lại với cảnh báo cụ thể.
Tối đa MAX_RETRIES lần.  Cảnh báo reset sau mỗi chương.
"""
from __future__ import annotations

MIN_TRANSLATION_LINES  = 10
MAX_LINE_LENGTH        = 1000
MAX_MERGED_LINE_RATIO  = 0.75
MIN_BLANK_LINE_RATIO   = 0.20


def check(translation: str, source_text: str = "") -> tuple[bool, str]:
    """
    Kiểm tra bản dịch.
    Trả về (True, "") nếu ổn, (False, mô_tả_lỗi) nếu phát hiện vấn đề.
    """
    if not translation or not translation.strip():
        return False, "Bản dịch rỗng."

    all_lines       = translation.splitlines()
    non_empty_lines = [l for l in all_lines if l.strip()]
    blank_lines     = [l for l in all_lines if not l.strip()]
    line_count      = len(non_empty_lines)
    total_lines     = len(all_lines)

    # Kiểm tra 1: dính dòng nghiêm trọng
    long_lines = [l for l in non_empty_lines if len(l) > MAX_LINE_LENGTH]
    if long_lines:
        longest = max(len(l) for l in long_lines)
        return False, (
            f"DÍNH DÒNG NGHIÊM TRỌNG: {len(long_lines)} dòng vượt {MAX_LINE_LENGTH} ký tự "
            f"(dài nhất: {longest} ký tự). Toàn bộ nội dung bị gộp vào một số dòng duy nhất."
        )

    # Kiểm tra 2: quá ít dòng
    if line_count < MIN_TRANSLATION_LINES:
        return False, (
            f"DÍNH DÒNG: Bản dịch chỉ có {line_count} dòng "
            f"(tối thiểu: {MIN_TRANSLATION_LINES}). "
            f"Nhiều đoạn văn bị gộp thành một dòng."
        )

    # Kiểm tra 3: mất dòng so với bản gốc
    if source_text and source_text.strip():
        src_lines = len([l for l in source_text.splitlines() if l.strip()])
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

    # Kiểm tra 4: thiếu dòng trống
    if total_lines >= MIN_TRANSLATION_LINES:
        blank_ratio = len(blank_lines) / total_lines if total_lines > 0 else 0
        if blank_ratio < MIN_BLANK_LINE_RATIO:
            blank_pct = int(blank_ratio * 100)
            return False, (
                f"THIẾU DÒNG TRỐNG: {len(blank_lines)}/{total_lines} dòng trống "
                f"({blank_pct}%, ngưỡng: {int(MIN_BLANK_LINE_RATIO*100)}%). "
                f"Mỗi đoạn văn phải cách nhau đúng 1 dòng trống."
            )

    return True, ""


def build_retry_prompt(original_text: str, quality_msg: str) -> str:
    """
    Tạo input text có gắn cảnh báo khi yêu cầu AI dịch lại.
    """
    return (
        f"⚠️ CẢNH BÁO: Bản dịch lần trước bị lỗi — {quality_msg}\n"
        f"Hãy dịch lại TOÀN BỘ chương dưới đây, đảm bảo:\n"
        f"  • GIỮ NGUYÊN cấu trúc đoạn văn của bản gốc\n"
        f"  • MỖI đoạn văn gốc = MỘT đoạn văn trong bản dịch\n"
        f"  • KHÔNG gộp nhiều đoạn thành một dòng\n"
        f"  • Xuống dòng và dòng trống đúng như bản gốc\n\n"
        f"--- NỘI DUNG GỐC ---\n\n{original_text}"
    )
