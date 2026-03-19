"""
src/littrans/engine/prompt_builder.py — Xây dựng system prompt 8 phần.

Cấu trúc:
  1. Hướng dẫn dịch chung  (prompts/system_agent.md)
  2. Glossary + Skills đã biết
  3. Character profiles (+ Emotion warning)
  4. Hướng dẫn lập profile  (prompts/character_profile.md)
  5. Yêu cầu JSON output
  6. Arc Memory (N entry gần nhất)
  7. Context Notes Scout AI
  8. Name Lock Table  ← ràng buộc CỨNG nhất, để CUỐI

[v4] Token Budget: nếu budget_limit > 0 → smart truncation trước khi assemble.
"""
from __future__ import annotations

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


def build(
    instructions     : str,
    glossary_ctx     : dict[str, list[str]],
    char_profiles    : dict[str, str],
    char_instructions: str,
    arc_memory_text  : str = "",
    context_notes    : str = "",
    name_lock_table  : dict[str, str] | None = None,
    known_skills     : dict[str, dict] | None = None,
    budget_limit     : int = 0,
    chapter_text     : str = "",
) -> str:
    """Assemble system prompt. budget_limit > 0 → apply token budget truncation."""

    # ── Token Budget ──────────────────────────────────────────────
    if budget_limit > 0:
        import re as _re
        from littrans.llm.token_budget import BudgetContext, apply_budget
        from littrans.managers.name_lock import format_for_prompt as fmt_lock

        arc_entries = (
            [e for e in _re.split(r"\n---\n", arc_memory_text)
             if e.strip().startswith("## Arc:")]
            if arc_memory_text else []
        )
        ctx = BudgetContext(
            instructions      = instructions,
            char_instructions = char_instructions,
            name_lock         = fmt_lock(name_lock_table or {}),
            context_notes     = context_notes,
            arc_memory_text   = arc_memory_text,
            arc_entries_full  = arc_entries,
            char_profiles     = dict(char_profiles),
            glossary_ctx      = {k: list(v) for k, v in glossary_ctx.items()},
            chapter_text      = chapter_text,
            budget_limit      = budget_limit,
        )
        ctx            = apply_budget(ctx)
        arc_memory_text = ctx.arc_memory_text
        char_profiles   = ctx.char_profiles
        glossary_ctx    = ctx.glossary_ctx

    # ── Assemble ─────────────────────────────────────────────────
    parts = [
        "Bạn là AI Agent chuyên dịch truyện LitRPG / Tu Tiên từ tiếng Anh sang tiếng Việt.\n",
        _section("PHẦN 1 — HƯỚNG DẪN DỊCH", instructions),
        _section("PHẦN 2 — TỪ ĐIỂN THUẬT NGỮ", _fmt_glossary(glossary_ctx, known_skills or {})),
        _section("PHẦN 3 — PROFILE NHÂN VẬT",   _fmt_characters(char_profiles)),
        _section("PHẦN 4 — HƯỚNG DẪN LẬP PROFILE", char_instructions),
        _section("PHẦN 5 — YÊU CẦU ĐẦU RA JSON",  _json_requirements()),
    ]

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

    from littrans.managers.name_lock import format_for_prompt as fmt_lock
    parts.append(_section(
        "PHẦN 8 — NAME LOCK TABLE (bảng tên đã chốt — BẮT BUỘC tuân theo)",
        fmt_lock(name_lock_table or {}),
    ))

    return "\n\n".join(parts)


# ── Section formatters ────────────────────────────────────────────

def _section(title: str, body: str) -> str:
    return f"{_BAR}\n {title}\n{_BAR}\n{body.strip()}"


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
        from littrans.managers.skills import format_skills_for_prompt
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
        "  ⛔ Chỉ đổi xưng hô khi: phản bội / tra khảo / lật mặt / đổi phe / mất kiểm soát cực độ\n"
    )
    return header + "\n" + "\n\n---\n\n".join(profiles.values())


def _json_requirements() -> str:
    return (
        "Trả về JSON với ĐÚNG 5 trường sau. KHÔNG bỏ sót trường nào:\n\n"
        "1. `translation`\n"
        "   Bản dịch hoàn chỉnh, giữ nguyên Markdown gốc.\n\n"
        "2. `new_terms`\n"
        "   Thuật ngữ MỚI chưa có trong Glossary (kể cả tên GIỮ NGUYÊN tiếng Anh).\n"
        "   Phải có trường `category`. Nếu không có → [].\n\n"
        "3. `new_characters`\n"
        "   Nhân vật CÓ TÊN xuất hiện LẦN ĐẦU. Điền đầy đủ profile. Nếu không có → [].\n\n"
        "4. `relationship_updates`\n"
        "   Thay đổi quan hệ THỰC SỰ quan trọng. Chỉ điền field thực sự thay đổi. Nếu không có → [].\n\n"
        "5. `skill_updates`\n"
        "   Kỹ năng MỚI hoặc TIẾN HÓA lần đầu. Kỹ năng đã có → KHÔNG báo cáo lại. Nếu không có → []."
    )
