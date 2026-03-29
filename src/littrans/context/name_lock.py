"""
src/littrans/context/name_lock.py — Bảng Name Lock: chốt tên nhất quán.

Nguồn tên (ưu tiên từ cao → thấp):
  1. Characters_Active + Archive → canonical_name + alias_canonical_map
  2. Glossary_Organizations → tên tổ chức
  3. Glossary_Locations → địa danh
  4. Glossary_General → tên riêng khác

Quy tắc:
  - Tên giữ nguyên tiếng Anh (canonical == tên gốc) → KHÔNG đưa vào bảng
  - Tên đã dịch → LOCK, không thay đổi sau đó
  - Conflict → giữ bản lock đầu tiên, log cảnh báo

[v4.3 FIX] validate_translation: dùng lookaround Unicode thay vì \\b.
  \\b hoạt động kém với tên có dấu tiếng Việt và ký tự đặc biệt (gạch ngang, dấu chấm).
  Lookaround (?<![^\\W_])...(?![^\\W_]) nhất quán với cách xử lý trong characters.py.
"""
from __future__ import annotations

import re
import logging

from littrans.config.settings import settings
from littrans.utils.io_utils import load_json, load_text
from littrans.core.patterns import word_boundary_pattern


# ── Build table ───────────────────────────────────────────────────

# src/littrans/context/name_lock.py
# Thay thế toàn bộ hàm build_name_lock_table() và thêm _extract_from_bible()

def build_name_lock_table() -> dict[str, str]:
    """Trả về {english_name: canonical_vn_name}."""
    table: dict[str, str] = {}
    _extract_from_characters(table)
    for cat in ("organizations", "locations", "general"):
        path = settings.glossary_files.get(cat)
        if path:
            _extract_from_glossary_file(table, path)

    # ── FIX: Khi Bible mode, bổ sung tên từ Bible Store
    # Đảm bảo entities đã scan (characters, locations, factions) vào Name Lock
    if settings.bible_mode and settings.bible_available:
        _extract_from_bible(table)

    return table


def _extract_from_bible(table: dict[str, str]) -> None:
    """
    Trích xuất name lock entries trực tiếp từ Bible Store.
    Chạy khi bible_mode=True để bù đắp cho trường hợp Characters_Active
    chưa được sync đầy đủ từ Bible.

    Bao gồm: character, location, faction (3 loại có tên VN khác EN).
    """
    try:
        from littrans.context.bible_store import BibleStore
        store = BibleStore(settings.bible_dir)

        for entity_type in ("character", "location", "faction"):
            for entity in store.get_all_entities(entity_type):
                en_name   = (entity.get("en_name") or "").strip()
                canonical = (entity.get("canonical_name") or "").strip()

                # Chỉ lock khi EN ≠ VN (western names giữ nguyên → không lock)
                if en_name and canonical and en_name.lower() != canonical.lower():
                    _lock(table, en_name, canonical)

                # Xử lý alias map (vd: "Old Man" → "Lão Trượng")
                alias_map = entity.get("alias_canonical_map") or {}
                for alias_en, alias_vn in alias_map.items():
                    alias_en = (alias_en or "").strip()
                    alias_vn = (alias_vn or "").strip()
                    if alias_en and alias_vn and alias_en.lower() != alias_vn.lower():
                        _lock(table, alias_en, alias_vn)

    except Exception as e:
        logging.warning(f"[NameLock] _extract_from_bible lỗi: {e}")


def _extract_from_characters(table: dict[str, str]) -> None:
    for filepath in [settings.characters_active_file, settings.characters_archive_file]:
        data = load_json(filepath)
        for name, profile in data.get("characters", {}).items():
            canonical = profile.get("canonical_name", "").strip()
            if canonical and canonical.lower() != name.lower():
                _lock(table, name, canonical)

            for alias, alias_canon in profile.get("alias_canonical_map", {}).items():
                alias       = alias.strip()
                alias_canon = alias_canon.strip()
                if alias and alias_canon and alias_canon.lower() != alias.lower():
                    _lock(table, alias, alias_canon)


def _extract_from_glossary_file(table: dict[str, str], filepath) -> None:
    for line in load_text(filepath).splitlines():
        clean = re.sub(r"^[\*\-\+]\s*", "", line.strip())
        if ":" not in clean or clean.startswith("#"):
            continue
        eng, _, vn = clean.partition(":")
        eng = eng.strip()
        vn  = re.sub(r"\s*\(.*?\)\s*$", "", vn.strip()).strip()
        if eng and vn and eng.lower() != vn.lower():
            _lock(table, eng, vn)


def _lock(table: dict[str, str], eng: str, vn: str) -> None:
    key = eng.strip()
    if not key:
        return
    existing = table.get(key)
    if existing:
        if existing.lower() != vn.lower():
            logging.warning(
                f"[NameLock] Conflict '{key}': lock '{existing}', bỏ qua '{vn}'"
            )
    else:
        table[key] = vn


# ── Format for prompt ─────────────────────────────────────────────

def format_for_prompt(table: dict[str, str]) -> str:
    if not table:
        return (
            "Chưa có tên nào được chốt.\n"
            "→ Dùng tên gốc tiếng Anh cho nhân vật/địa danh chưa định nghĩa.\n"
            "→ Ghi vào new_terms khi gặp tên mới cần dịch."
        )
    lines = [
        "⛔ QUY TẮC CỨNG — KHÔNG ĐƯỢC VI PHẠM:",
        "  1. Mỗi tên tiếng Anh CHỈ CÓ ĐÚNG MỘT bản dịch chuẩn.",
        "  2. Tuyệt đối KHÔNG dùng tên tiếng Anh gốc nếu đã có bản chuẩn.",
        "  3. Tuyệt đối KHÔNG tự dùng bản dịch khác dù có vẻ hợp lý hơn.",
        "  4. Tên tiếng Anh không có trong bảng → GIỮ NGUYÊN tiếng Anh.",
        "",
        f"  {'TÊN TIẾNG ANH GỐC':<35} BẢN CHUẨN (dùng trong bản dịch)",
        "  " + "─" * 68,
    ]
    for eng in sorted(table, key=str.lower):
        lines.append(f"  {eng:<35} {table[eng]}")
    lines += [
        "",
        "⚠️  Tên tiếng Anh đã có trong bảng → BẮT BUỘC thay bằng BẢN CHUẨN, không ngoại lệ.",
    ]
    return "\n".join(lines)


# ── Validate translation ──────────────────────────────────────────

def validate_translation(translation: str, table: dict[str, str]) -> list[str]:
    """
    Quét bản dịch → phát hiện tên tiếng Anh còn sót.

    [FIX] Dùng lookaround Unicode thay vì \\b để xử lý đúng:
      - Tên có dấu tiếng Việt (ký tự ngoài ASCII)
      - Tên có ký tự đặc biệt: "T-Rex", "Mr.X", "System.Core"
      - \\b định nghĩa biên dựa trên [\\w] = [a-zA-Z0-9_] → bỏ sót ký tự có dấu

    Pattern (?<![^\\W_])...(?![^\\W_]) tương đương với characters.py và token_budget.py.
    """
    if not table or not translation:
        return []
    MIN_LEN  = 4
    warnings = []
    for eng, vn in table.items():
        if len(eng) < MIN_LEN:
            continue
        try:
            pattern = word_boundary_pattern(eng)
            if re.search(pattern, translation, re.IGNORECASE | re.UNICODE):
                warnings.append(f"  ⚠️  Tên gốc '{eng}' còn sót → phải dùng '{vn}'")
        except re.error:
            pass
    return warnings


# ── Stats ─────────────────────────────────────────────────────────

def lock_stats() -> dict[str, int]:
    return {"total_locked": len(build_name_lock_table())}