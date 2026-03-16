"""
core/name_lock.py — Bảng Name Lock: chốt tên nhất quán xuyên suốt bản dịch.

VẤN ĐỀ GIẢI QUYẾT:
  Dịch hàng trăm chương → AI có thể dùng nhiều cách khác nhau cho cùng 1 tên.
  VD: "Hội Bình Minh" vs "Dawn Association" vs "Hội Dawn" → đều SAI nếu
  bản chuẩn đã chốt là "Hội Bình Minh".

  Tương tự với alias danh tính:
  VD: "Klein" đang dùng danh tính "Zaratul" → phải luôn dùng đúng tên đó
  trong đúng ngữ cảnh, không được lẫn lộn.

NGUỒN TÊN (theo thứ tự ưu tiên):
  1. Characters_Active.json + Characters_Archive.json → tên nhân vật + alias
  2. Glossary_Organizations.md → tên tổ chức, hội phái
  3. Glossary_Locations.md → địa danh
  4. Glossary_General.md → tên riêng khác
  (Pathways + Items = thuật ngữ kỹ năng/vật phẩm → đã có Phần 2 Glossary xử lý)

QUY TẮC LOCK:
  - Tên người nước ngoài thường: GIỮ NGUYÊN tiếng Anh (Arthur, Klein...)
    → không cần lock vì không có nguy cơ dịch sai.
  - Danh hiệu / biệt danh / alias: dịch Hán Việt hoặc Thuần Việt → LOCK
    → VD: "The Fool" → "Gã Ngốc"; "Shadow Scythe" → "Hắc Liêm Thần"
  - Địa danh / Tổ chức: một khi đã chọn bản dịch → LOCK
    → VD: "Backlund" → "Backlund" (giữ nguyên) hoặc "Ba Khắc Lân" → LOCK
  - Một khi đã LOCK → không thay đổi, mọi chương phải dùng bản chuẩn đó.

CONFLICT HANDLING:
  Nếu cùng 1 tên tiếng Anh có 2 bản dịch khác nhau (từ 2 nguồn khác nhau)
  → Giữ nguyên bản cũ hơn (đã lock trước), log cảnh báo để người dùng xử lý.
"""
import re
import logging
from .io_utils import load_json, load_text
from .config import (
    CHARACTERS_ACTIVE_FILE, CHARACTERS_ARCHIVE_FILE,
    GLOSSARY_FILES,
)


# ═══════════════════════════════════════════════════════════════════
# BUILD BẢNG LOCK
# ═══════════════════════════════════════════════════════════════════

def build_name_lock_table() -> dict[str, str]:
    """
    Trả về {english_name: canonical_vn_name}.

    CHỈ gồm tên THỰC SỰ ĐÃ ĐƯỢC DỊCH/PHIÊN ÂM (khác tiếng Anh gốc).
    Tên giữ nguyên tiếng Anh (canonical == tên gốc) KHÔNG đưa vào bảng —
    không cần lock vì không có nguy cơ dùng sai.
    """
    table: dict[str, str] = {}

    # 1. Tên nhân vật + alias (ưu tiên cao nhất)
    _extract_from_characters(table)

    # 2. Tổ chức → Địa danh → Thuật ngữ chung
    for cat in ("organizations", "locations", "general"):
        path = GLOSSARY_FILES.get(cat)
        if path:
            _extract_from_glossary_file(table, str(path))

    return table


def _extract_from_characters(table: dict[str, str]) -> None:
    """Đọc canonical_name và alias_canonical_map từ Active + Archive."""
    for filepath in [CHARACTERS_ACTIVE_FILE, CHARACTERS_ARCHIVE_FILE]:
        data = load_json(str(filepath))
        for name, profile in data.get("characters", {}).items():
            # Tên chính
            canonical = profile.get("canonical_name", "").strip()
            if canonical and canonical.lower() != name.lower():
                _lock(table, name, canonical)

            # Alias → bản chuẩn (VD: "The Fool" → "Gã Ngốc")
            alias_map: dict = profile.get("alias_canonical_map", {})
            for alias, alias_canon in alias_map.items():
                alias = alias.strip(); alias_canon = alias_canon.strip()
                if alias and alias_canon and alias_canon.lower() != alias.lower():
                    _lock(table, alias, alias_canon)


def _extract_from_glossary_file(table: dict[str, str], filepath: str) -> None:
    """Parse file glossary dạng '- English: Vietnamese' → thêm vào bảng lock."""
    text = load_text(filepath)
    for line in text.splitlines():
        # Bỏ bullet point ở đầu
        clean = re.sub(r"^[\*\-\+]\s*", "", line.strip())
        if ":" not in clean or clean.startswith("#"):
            continue
        eng, _, vn = clean.partition(":")
        eng = eng.strip()
        # Loại bỏ ghi chú trong ngoặc đơn cuối dòng: "Hội Bình Minh (Sáng lập năm...)"
        vn  = re.sub(r"\s*\(.*?\)\s*$", "", vn.strip()).strip()
        if eng and vn and eng.lower() != vn.lower():
            _lock(table, eng, vn)


def _lock(table: dict[str, str], eng: str, vn: str) -> None:
    """Thêm vào bảng. Nếu conflict → giữ nguyên bản cũ, log cảnh báo."""
    key = eng.strip()
    if not key:
        return
    existing = table.get(key)
    if existing:
        if existing.lower() != vn.lower():
            logging.warning(
                f"[NameLock] Conflict '{key}': "
                f"đang lock '{existing}', bỏ qua bản mới '{vn}'. "
                f"Kiểm tra thủ công nếu cần đổi."
            )
        # Giữ nguyên bản lock đầu tiên
    else:
        table[key] = vn


# ═══════════════════════════════════════════════════════════════════
# FORMAT CHO PROMPT
# ═══════════════════════════════════════════════════════════════════

def format_for_prompt(table: dict[str, str]) -> str:
    """
    Tạo nội dung PHẦN 8 — NAME LOCK TABLE để đưa vào system prompt.
    Thiết kế để AI đọc → nhớ → áp dụng ngay.
    """
    if not table:
        return (
            "Chưa có tên nào được chốt.\n"
            "→ Dùng tên gốc tiếng Anh cho nhân vật, địa danh chưa được định nghĩa.\n"
            "→ Khi gặp tên mới cần dịch, ghi vào new_terms để hệ thống chốt cho các chương sau."
        )

    lines = [
        "⛔ QUY TẮC CỨNG — KHÔNG ĐƯỢC VI PHẠM:",
        "  1. Mỗi tên tiếng Anh CHỈ CÓ ĐÚNG MỘT bản dịch chuẩn (cột 'BẢN CHUẨN').",
        "  2. Tuyệt đối KHÔNG dùng tên tiếng Anh gốc nếu bảng này đã có bản chuẩn.",
        "  3. Tuyệt đối KHÔNG tự ý dùng bản dịch khác dù có vẻ hợp lý hơn.",
        "  4. Nếu thấy tên tiếng Anh gốc không có trong bảng → GIỮ NGUYÊN tiếng Anh.",
        "",
        f"  {'TÊN TIẾNG ANH GỐC':<35} BẢN CHUẨN (dùng trong bản dịch)",
        "  " + "─" * 68,
    ]

    for eng in sorted(table, key=str.lower):
        lines.append(f"  {eng:<35} {table[eng]}")

    lines += [
        "",
        "⚠️  Nếu trong chương này xuất hiện tên tiếng Anh đã có trong bảng trên",
        "    → BẮT BUỘC thay bằng BẢN CHUẨN tương ứng, không ngoại lệ.",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# VALIDATE BẢN DỊCH
# ═══════════════════════════════════════════════════════════════════

def validate_translation(translation: str, table: dict[str, str]) -> list[str]:
    """
    Quét bản dịch → phát hiện tên tiếng Anh còn sót chưa được thay bằng bản chuẩn.

    Trả về list cảnh báo. List rỗng = không vi phạm.

    Lưu ý: false positive có thể xảy ra với tên ngắn (<= 3 ký tự).
    Ngưỡng MIN_LEN = 4 để giảm thiểu.
    """
    if not table or not translation:
        return []

    MIN_LEN = 4  # Bỏ qua tên quá ngắn (dễ nhầm với từ thường)
    warnings = []

    for eng, vn in table.items():
        if len(eng) < MIN_LEN:
            continue
        try:
            pattern = rf"\b{re.escape(eng)}\b"
            if re.search(pattern, translation, re.IGNORECASE):
                warnings.append(
                    f"  ⚠️  Tên gốc '{eng}' còn sót → phải dùng '{vn}'"
                )
        except re.error:
            pass

    return warnings


# ═══════════════════════════════════════════════════════════════════
# THỐNG KÊ
# ═══════════════════════════════════════════════════════════════════

def lock_stats() -> dict[str, int]:
    """Thống kê nhanh bảng lock."""
    table = build_name_lock_table()
    return {"total_locked": len(table)}
