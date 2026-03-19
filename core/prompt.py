"""
core/prompt.py — Xây dựng system prompt cho AI dịch.

Tách riêng để chỉnh prompt mà không đụng runner.

CẤU TRÚC (8 phần):
  1. Hướng dẫn dịch chung       (translateAGENT_INSTRUCTIONS.md)
  2. Glossary theo category      (filter_glossary() → nhóm theo loại)
  3. Character profiles          (filter_characters() → Active ưu tiên)
     [v4] + Emotion Tone Warning nếu state != normal
  4. Hướng dẫn profiling         (CHARACTER_PROFILING_INSTRUCTIONS.md)
  5. Yêu cầu JSON output         (schema cố định)
  6. Arc Memory gần nhất         (Arc_Memory.md — N entry gần nhất)
  7. Context Notes Scout AI      (Context_Notes.md — ngắn hạn, tức thì)
  8. Name Lock Table             (name_lock.py → bảng tên đã chốt)

[v4] Token Budget:
  build() nhận thêm tham số `budget_limit`.
  Nếu budget_limit > 0: áp dụng smart truncation trước khi assemble prompt.
"""
import os
from .config import MIN_BEHAVIOR_CONF, SCOUT_LOOKBACK, ARC_MEMORY_WINDOW

_BAR = "═" * 62

_CAT_LABELS = {
    "pathways"     : "Hệ thống tu luyện / Sequence",
    "organizations": "Tổ chức & hội phái",
    "items"        : "Vật phẩm & linh vật",
    "locations"    : "Địa danh",
    "general"      : "Thuật ngữ chung",
    "staging"      : "Thuật ngữ mới (chưa phân loại)",
}

# [v4] Icon + màu cho từng emotional state
_EMOTION_DISPLAY = {
    "angry"  : ("⚠️  TRẠNG THÁI CẢM XÚC",   "TỨC GIẬN",   "Lời thoại có thể gay gắt, cộc cằn, mất kiểm soát"),
    "hurt"   : ("⚠️  TRẠNG THÁI CẢM XÚC",   "TỔN THƯƠNG", "Lời thoại có thể trầm, đau đớn, co rút"),
    "changed": ("⚠️  TRẠNG THÁI CẢM XÚC",   "ĐÃ THAY ĐỔI","Nhân vật vừa trải qua sự kiện lớn — tông có thể khác hẳn"),
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
    budget_limit    : int = 0,
    chapter_text    : str = "",
) -> str:
    """
    Xây dựng system prompt 8 phần.

    budget_limit > 0: áp dụng token budget truncation trước khi build.
    """

    # ── [v4] Token Budget truncation ─────────────────────────────
    if budget_limit > 0:
        from .token_budget import BudgetContext, apply_budget, log_budget_stats
        from . import arc_memory as _arc_mod
        import re

        # Parse arc entries (để có thể cắt từng entry)
        arc_entries = []
        if arc_memory_text:
            arc_entries = [e for e in re.split(r"\n---\n", arc_memory_text)
                           if e.strip().startswith("## Arc:")]

        from .name_lock import format_for_prompt as fmt_lock
        from . import arc_memory as arc_mod

        ctx = BudgetContext(
            instructions      = instructions,
            char_instructions = char_instructions,
            name_lock         = (fmt_lock(name_lock_table or {})),
            context_notes     = context_notes,
            arc_memory_text   = arc_memory_text,
            arc_entries_full  = arc_entries,
            char_profiles     = dict(char_profiles),
            glossary_ctx      = {k: list(v) for k, v in glossary_ctx.items()},
            chapter_text      = chapter_text,
            budget_limit      = budget_limit,
        )
        ctx = apply_budget(ctx)

        # Dùng lại giá trị sau truncation
        arc_memory_text = ctx.arc_memory_text
        char_profiles   = ctx.char_profiles
        glossary_ctx    = ctx.glossary_ctx

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


# ── [v4] Emotion warning inject vào character format ─────────────
def inject_emotion_warning(char_name: str, profile_text: str, emotional_state: dict) -> str:
    """
    Inject cảnh báo emotion state vào đầu profile nếu state != normal.
    Gọi từ characters.py::_fmt() khi format profile.
    """
    state = emotional_state.get("current", "normal")
    if state == "normal" or not state:
        return profile_text

    display = _EMOTION_DISPLAY.get(state)
    if not display:
        return profile_text

    label, state_vn, hint = display
    intensity = emotional_state.get("intensity", "medium")
    reason    = emotional_state.get("reason", "")

    warning_lines = [
        f"",
        f"┌{'─'*58}",
        f"│ {label}: **{state_vn}** [{intensity}]",
        f"│ {hint}",
    ]
    if reason:
        warning_lines.append(f"│ Lý do: {reason}")
    warning_lines.append(f"└{'─'*58}")
    warning_lines.append("")

    warning_block = "\n".join(warning_lines)

    # Chèn vào sau dòng header (dòng đầu tiên ### Name)
    lines = profile_text.split("\n", 1)
    if len(lines) == 2:
        return lines[0] + "\n" + warning_block + lines[1]
    return warning_block + profile_text