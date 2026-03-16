"""
core/prompt.py — Xây dựng system prompt cho AI dịch.

Tách riêng để chỉnh prompt mà không đụng runner.

CẤU TRÚC (8 phần):
  1. Hướng dẫn dịch chung       (translateAGENT_INSTRUCTIONS.md)
  2. Glossary theo category      (filter_glossary() → nhóm theo loại)
  3. Character profiles          (filter_characters() → Active ưu tiên)
  4. Hướng dẫn profiling         (CHARACTER_PROFILING_INSTRUCTIONS.md)
  5. Yêu cầu JSON output         (schema cố định)
  6. Arc Memory gần nhất         (Arc_Memory.md — N entry gần nhất)
  7. Context Notes Scout AI      (Context_Notes.md — ngắn hạn, tức thì)
  8. Name Lock Table             (name_lock.py → bảng tên đã chốt)

Thứ tự có chủ ý:
  → Phần 1–5: nền tảng kiến thức (đọc trước)
  → Phần 6: bối cảnh dài hạn
  → Phần 7: cảnh báo tức thì (đọc gần cuối để nhớ lâu hơn)
  → Phần 8: NAME LOCK TABLE — để CUỐI CÙNG, ngay trước lúc dịch,
    vì đây là ràng buộc CỨNG nhất, AI phải nhớ khi bắt đầu gõ bản dịch.
"""
from .config import MIN_BEHAVIOR_CONF, SCOUT_LOOKBACK, ARC_MEMORY_WINDOW

_BAR = "═" * 62

# Tên hiển thị trong prompt cho từng category glossary
_CAT_LABELS = {
    "pathways"     : "Hệ thống tu luyện / Sequence",
    "organizations": "Tổ chức & hội phái",
    "items"        : "Vật phẩm & linh vật",
    "locations"    : "Địa danh",
    "general"      : "Thuật ngữ chung",
    "staging"      : "Thuật ngữ mới (chưa phân loại)",
}

def build(
    instructions    : str,
    glossary_ctx    : dict[str, list[str]],
    char_profiles   : dict[str, str],
    char_instructions: str,
    arc_memory_text : str = "",
    context_notes   : str = "",
    name_lock_table : dict[str, str] = None,
    known_skills    : dict[str, dict] = None,
) -> str:
    parts = [
        "Bạn là AI Agent chuyên dịch truyện LitRPG / Tu Tiên từ tiếng Anh sang tiếng Việt.\n",
        _section("PHẦN 1 — HƯỚNG DẪN DỊCH", instructions),
        _section("PHẦN 2 — TỪ ĐIỂN THUẬT NGỮ", _fmt_glossary(glossary_ctx, known_skills or {})),
        _section("PHẦN 3 — PROFILE NHÂN VẬT", _fmt_characters(char_profiles)),
        _section("PHẦN 4 — HƯỚNG DẪN LẬP PROFILE", char_instructions),
        _section("PHẦN 5 — YÊU CẦU ĐẦU RA JSON", _json_requirements()),
    ]

    if arc_memory_text and arc_memory_text.strip():
        parts.append(_section(
            f"PHẦN 6 — BỘ NHỚ ARC (tích lũy, {ARC_MEMORY_WINDOW} entry gần nhất)",
            "Bối cảnh dài hạn từ các arc đã hoàn thành. "
            "Dùng để đảm bảo tính nhất quán xuyên suốt.\n\n" + arc_memory_text,
        ))

    if context_notes and context_notes.strip():
        parts.append(_section(
            f"PHẦN 7 — GHI CHÚ TỨC THÌ (Scout AI · {SCOUT_LOOKBACK} chương gần nhất)",
            "⚠️  ĐỌC KỸ TRƯỚC KHI DỊCH. Ưu tiên tuyệt đối các cảnh báo về "
            "xưng hô và mạch truyện đặc biệt.\n\n" + context_notes,
        ))

    from .name_lock import format_for_prompt as fmt_lock
    lock_body = fmt_lock(name_lock_table or {})
    parts.append(_section(
        "PHẦN 8 — NAME LOCK TABLE (bảng tên đã chốt — BẮT BUỘC tuân theo)",
        lock_body,
    ))

    return "\n\n".join(parts)


# ── Format helpers ────────────────────────────────────────────────
def _section(title: str, body: str) -> str:
    return f"{_BAR}\n {title}\n{_BAR}\n{body.strip()}"

def _fmt_glossary(ctx: dict[str, list[str]], known_skills: dict[str, dict] = None) -> str:
    parts = ["Chỉ dùng các bản dịch có trong danh sách sau. KHÔNG tự ý thay đổi.\n"]
    has_content = False

    for cat, lines in ctx.items():
        if not lines:
            continue
        label = _CAT_LABELS.get(cat, cat.title())
        parts.append(f"**{label}** ({len(lines)} thuật ngữ)")
        parts.extend(lines)
        parts.append("")
        has_content = True

    # Skills đã biết — tra cứu BẮT BUỘC khi gặp bảng hệ thống
    if known_skills:
        from .skills import format_skills_for_prompt
        skill_block = format_skills_for_prompt(known_skills)
        if skill_block:
            parts.append(skill_block)
            parts.append("")
            has_content = True

    if not has_content:
        return "Không có thuật ngữ nào liên quan trong chương này."
    return "\n".join(parts).strip()


def _fmt_characters(profiles: dict[str, str]) -> str:
    if not profiles:
        return "Không có nhân vật đã biết nào trong chương này."
    header = (
        "Nhân vật xuất hiện trong chương này.\n\n"
        "QUY TẮC XƯNG HÔ — ƯU TIÊN THEO THỨ TỰ (từ cao xuống thấp):\n"
        "  1. relationships[X].dynamic (✅ strong) → ĐÃ CHỐT, KHÔNG thay đổi trừ sự kiện bắt buộc\n"
        "  2. relationships[X].dynamic (🔸 weak)   → dùng tạm; báo cáo promote_to_strong khi xác nhận\n"
        "  3. how_refers_to_others[X]              → fallback khi chưa có quan hệ với X\n"
        "  4. how_refers_to_others[default_*]      → fallback cuối cùng\n\n"
        "  ⛔ Chỉ đổi xưng hô khi: phản bội / tra khảo / lật mặt / đổi phe / mất kiểm soát cực độ\n"
        "  ⛔ Khi gặp nhân vật lần đầu và chưa có quan hệ → chọn xưng hô tạm, đặt weak\n"
    )
    body = "\n\n---\n\n".join(profiles.values())
    return header + "\n" + body

def _json_requirements() -> str:
    return (
        "Trả về JSON với ĐÚNG 5 trường sau. KHÔNG bỏ sót trường nào:\n\n"
        "1. `translation`\n"
        "   Bản dịch hoàn chỉnh, giữ nguyên Markdown gốc.\n\n"
        "2. `new_terms`\n"
        "   Thuật ngữ MỚI chưa có trong Glossary (tên người, địa danh, tổ chức, danh hiệu...).\n"
        "   ⚠️  BẮT BUỘC báo cáo TẤT CẢ tên mới — kể cả tên GIỮ NGUYÊN tiếng Anh.\n"
        "   Lý do: hệ thống cần biết tên đó đã xuất hiện để lock nhất quán.\n"
        "   Phải có trường `category` (pathways|organizations|items|locations|general).\n"
        "   Nếu không có tên mới nào → [].\n\n"
        "3. `new_characters`\n"
        "   Nhân vật CÓ TÊN xuất hiện LẦN ĐẦU trong chương này. Điền đầy đủ profile.\n"
        "   Nếu không có → [].\n\n"
        "4. `relationship_updates`\n"
        "   Thay đổi quan hệ THỰC SỰ quan trọng trong chương này.\n"
        "   Chỉ điền field thực sự thay đổi. Nếu không có → [].\n\n"
        "5. `skill_updates`\n"
        "   Kỹ năng / chiêu thức MỚI hoặc TIẾN HÓA xuất hiện lần đầu trong chương.\n"
        "   Điền `evolved_from` nếu là kỹ năng tiến hóa từ kỹ năng cũ.\n"
        "   Kỹ năng đã có trong danh sách kỹ năng đã biết → KHÔNG báo cáo lại.\n"
        "   Nếu không có → []."
    )