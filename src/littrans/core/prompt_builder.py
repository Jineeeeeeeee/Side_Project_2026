"""
src/littrans/core/prompt_builder.py — Xây dựng system prompt.

[Refactor] engine → core, managers → context.
[v5.5] DEAD-2 fix: xoá build() (1-call flow cũ, không còn caller).
       Chỉ giữ build_translation_prompt() dùng bởi pipeline.py.
"""
from __future__ import annotations

import logging

from littrans.config.settings import settings

_BAR = "═" * 62

_CAT_LABELS = {
    "pathways"     : "Hệ thống tu luyện / Sequence",
    "organizations": "Tổ chức & hội phái",
    "items"        : "Vật phẩm & linh vật",
    "locations"    : "Địa danh",
    "general"      : "Thuật ngữ chung",
    "staging"      : "Thuật ngữ mới (chưa phân loại)",
}


# ═══════════════════════════════════════════════════════════════════
# PUBLIC — 3-call flow (Translation call)
# ═══════════════════════════════════════════════════════════════════

def build_translation_prompt(
    instructions    : str,
    glossary_ctx    : dict[str, list[str]],
    char_profiles   : dict[str, str],
    arc_memory_text : str = "",
    context_notes   : str = "",
    name_lock_table : dict[str, str] | None = None,
    known_skills    : dict[str, dict] | None = None,
    chapter_map     = None,
    budget_limit    : int = 0,
    chapter_text    : str = "",
) -> str:
    glossary_ctx, char_profiles, arc_memory_text = _apply_budget_if_needed(
        budget_limit, instructions, "",
        name_lock_table or {}, context_notes, arc_memory_text,
        char_profiles, glossary_ctx, chapter_text,
    )

    parts = [
        "Bạn là AI chuyên dịch truyện LitRPG / Tu Tiên từ tiếng Anh sang tiếng Việt.\n"
        "Nhiệm vụ DUY NHẤT: dịch chapter được cung cấp. "
        "KHÔNG điền JSON, KHÔNG phân tích, KHÔNG thêm chú thích.\n",
        _section("PHẦN 1 — HƯỚNG DẪN DỊCH", instructions),
        _section("PHẦN 2 — TỪ ĐIỂN THUẬT NGỮ", _fmt_glossary(glossary_ctx, known_skills or {})),
    ]

    # Phần 3: Character profiles + EPS summary
    char_body = _fmt_characters(char_profiles)

    if char_profiles and chapter_text:
        try:
            from littrans.context.characters import format_eps_summary
            eps_block = format_eps_summary(char_profiles, chapter_text)
            if eps_block:
                char_body = char_body + "\n\n" + eps_block
        except Exception as _e:
            logging.warning(f"[PromptBuilder] EPS format lỗi: {_e}")

    parts.append(_section("PHẦN 3 — PROFILE NHÂN VẬT", char_body))

    # Phần 4: Chapter Map
    if chapter_map and not chapter_map.is_empty():
        parts.append(_section(
            "PHẦN 4 — CHAPTER MAP (đã phân tích trước — ưu tiên cao)",
            chapter_map.to_prompt_block(),
        ))
    else:
        parts.append(_section(
            "PHẦN 4 — GHI CHÚ CHAPTER",
            "Không có chapter map. Suy luận xưng hô và tên từ các phần trên.",
        ))

    parts.append(_section(
        "PHẦN 5 — YÊU CẦU ĐẦU RA",
        _translation_output_requirements(),
    ))

    parts += _arc_and_notes_sections(arc_memory_text, context_notes)

    from littrans.context.name_lock import format_for_prompt as fmt_lock
    parts.append(_section(
        "PHẦN 8 — NAME LOCK TABLE (bảng tên đã chốt — BẮT BUỘC tuân theo)",
        fmt_lock(name_lock_table or {}),
    ))

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════

def _section(title: str, body: str) -> str:
    return f"{_BAR}\n {title}\n{_BAR}\n{body.strip()}"


def _arc_and_notes_sections(arc_memory_text: str, context_notes: str) -> list[str]:
    parts = []
    if arc_memory_text and arc_memory_text.strip():
        parts.append(_section(
            f"PHẦN 6 — BỘ NHỚ ARC ({settings.arc_memory_window} entry gần nhất)",
            "Bối cảnh dài hạn. Dùng để đảm bảo tính nhất quán xuyên suốt.\n\n" + arc_memory_text,
        ))
    if context_notes and context_notes.strip():
        parts.append(_section(
            f"PHẦN 7 — GHI CHÚ TỨC THÌ (Scout AI · {settings.scout_lookback} chương gần nhất)",
            "⚠️  ĐỌC KỸ TRƯỚC KHI DỊCH. Ưu tiên tuyệt đối cảnh báo xưng hô và mạch truyện đặc biệt.\n\n"
            + context_notes,
        ))
    return parts


def _fmt_glossary(ctx: dict[str, list[str]], known_skills: dict[str, dict]) -> str:
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
        from littrans.context.skills import format_skills_for_prompt
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
        "  2. relationships[X].dynamic (🔸 weak)   → tạm thời; báo cáo promote_to_strong khi xác nhận\n"
        "  3. how_refers_to_others[X]              → fallback khi chưa có quan hệ\n"
        "  4. how_refers_to_others[default_*]      → fallback cuối\n\n"
        "  ⛔ Chỉ đổi xưng hô khi: phản bội / tra khảo / lật mặt / đổi phe / mất kiểm soát cực độ\n\n"
        "QUY TẮC EPS — Điều chỉnh văn phong theo mức độ thân mật:\n"
        "  EPS 1 (FORMAL)   → kính ngữ, câu đầy đủ, trang trọng\n"
        "  EPS 2 (NEUTRAL)  → theo dynamic đã chốt, không đặc biệt\n"
        "  EPS 3 (FRIENDLY) → thoải mái, câu ngắn hơn, có thể bỏ kính ngữ\n"
        "  EPS 4 (CLOSE)    → rất thân, nickname ok, chia sẻ cảm xúc trực tiếp\n"
        "  EPS 5 (INTIMATE) → ngôn ngữ riêng tư, thân mật tuyệt đối\n"
    )
    return header + "\n" + "\n\n---\n\n".join(profiles.values())


def _translation_output_requirements() -> str:
    return (
        "Trả về BẢN DỊCH HOÀN CHỈNH — plain text, không JSON, không markdown code block.\n\n"
        "Quy tắc:\n"
        "  • Giữ nguyên cấu trúc đoạn văn của bản gốc\n"
        "  • Mỗi đoạn văn gốc = một đoạn trong bản dịch\n"
        "  • Dòng trống giữa các đoạn thường — giữ nguyên như gốc\n"
        "  • Bảng hệ thống / System Box — KHÔNG có dòng trống giữa các dòng trong box\n"
        "  • KHÔNG thêm lời mở đầu, kết luận, hay chú thích vào bản dịch\n"
        "  • KHÔNG bọc bản dịch trong dấu ngoặc kép hay code block\n"
        "  • Áp dụng EPS (Phần 3) để điều chỉnh văn phong xưng hô cho đúng mức độ thân mật\n"
        "  • Áp dụng Scene Plan (Phần 4) để hiểu mạch truyện trước khi dịch"
    )


def _apply_budget_if_needed(
    budget_limit, instructions, char_instructions, name_lock_table,
    context_notes, arc_memory_text, char_profiles, glossary_ctx, chapter_text,
):
    if budget_limit <= 0:
        return glossary_ctx, char_profiles, arc_memory_text

    import re as _re
    from littrans.llm.token_budget import BudgetContext, apply_budget
    from littrans.context.name_lock import format_for_prompt as fmt_lock

    arc_entries = (
        [e for e in _re.split(r"\n---\n", arc_memory_text)
         if e.strip().startswith("## Arc:")]
        if arc_memory_text else []
    )
    ctx = BudgetContext(
        instructions      = instructions,
        char_instructions = char_instructions,
        name_lock         = fmt_lock(name_lock_table),
        context_notes     = context_notes,
        arc_memory_text   = arc_memory_text,
        arc_entries_full  = arc_entries,
        char_profiles     = dict(char_profiles),
        glossary_ctx      = {k: list(v) for k, v in glossary_ctx.items()},
        chapter_text      = chapter_text,
        budget_limit      = budget_limit,
    )
    ctx = apply_budget(ctx)
    return ctx.glossary_ctx, ctx.char_profiles, ctx.arc_memory_text