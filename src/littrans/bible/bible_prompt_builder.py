"""
src/littrans/bible/bible_prompt_builder.py — Bible-aware Trans-call prompt.

Khi BIBLE_MODE=true và bible_available=true:
  - Thay vì filter_glossary() + filter_characters() + Arc Memory
  - Dùng: store.get_entities_for_chapter() + store.get_worldbuilding() + store.get_recent_lore()
  - Giảm ~60-70% Scout/Pre-call cost

Cấu trúc prompt giữ nguyên 9 phần như build_translation_prompt(),
chỉ đổi nguồn dữ liệu → không cần thay đổi gì trong trans-call logic.

Tái dụng:
  _section()          — từ prompt_builder.py
  format_for_prompt() — từ name_lock.py
  _translation_output_requirements() — từ prompt_builder.py

[v1.0] Initial implementation — Bible System Sprint 4
"""
from __future__ import annotations

from littrans.bible.bible_store import BibleStore
from littrans.bible.schemas import BibleCharacter


# ── Re-export helpers từ prompt_builder ──────────────────────────

def _section(title: str, body: str) -> str:
    BAR = "═" * 62
    return f"{BAR}\n {title}\n{BAR}\n{body.strip()}"


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
        "  • Áp dụng EPS (Phần 3) để điều chỉnh văn phong xưng hô\n"
        "  • Áp dụng Scene Plan (Phần 4) để hiểu mạch truyện trước khi dịch"
    )


# ═══════════════════════════════════════════════════════════════════
# FORMATTERS — chuyển Bible entities → prompt text
# ═══════════════════════════════════════════════════════════════════

def _fmt_bible_entities(entities: dict[str, list[dict]], chapter_text: str) -> str:
    """
    Format entities từ BibleStore → Glossary + Character prompt sections.
    
    entities = {
        "character" : [BibleCharacter dicts],
        "skill"     : [BibleSkill dicts],
        "location"  : [BibleLocation dicts],
        ...
    }
    """
    parts = ["**Thực thể đã được xây dựng Bible (dùng CHÍNH XÁC tên đã chốt):**\n"]
    has_content = False

    # Characters
    chars = entities.get("character", [])
    if chars:
        parts.append(f"### Nhân vật ({len(chars)})\n")
        for c in chars:
            cname  = c.get("canonical_name", c.get("en_name", "?"))
            ename  = c.get("en_name", "")
            role   = c.get("role", "?")
            status = c.get("status", "alive")
            realm  = (c.get("cultivation") or {}).get("realm", "")
            pronoun = c.get("pronoun_self", "")

            line = f"**{cname}** ({ename}) [{role}]"
            if status != "alive":
                line += f" ⚠️ {status}"
            if realm:
                line += f" | {realm}"
            if pronoun:
                line += f" | Tự xưng: **{pronoun}**"
            if c.get("personality_summary"):
                line += f"\n  → {c['personality_summary'][:100]}"

            parts.append(line)
        parts.append("")
        has_content = True

    # Skills
    skills = entities.get("skill", [])
    if skills:
        parts.append(f"### Kỹ năng ({len(skills)})\n")
        for s in skills:
            cname = s.get("canonical_name", s.get("en_name", "?"))
            ename = s.get("en_name", "")
            stype = s.get("skill_type", "")
            parts.append(f"  {ename} → **{cname}** [{stype}]")
        parts.append("")
        has_content = True

    # Locations
    locs = entities.get("location", [])
    if locs:
        parts.append(f"### Địa danh ({len(locs)})\n")
        for loc in locs:
            cname = loc.get("canonical_name", loc.get("en_name", "?"))
            ename = loc.get("en_name", "")
            ltype = loc.get("location_type", "")
            parts.append(f"  {ename} → **{cname}** [{ltype}]")
        parts.append("")
        has_content = True

    # Items
    items = entities.get("item", [])
    if items:
        parts.append(f"### Vật phẩm ({len(items)})\n")
        for item in items:
            cname = item.get("canonical_name", item.get("en_name", "?"))
            ename = item.get("en_name", "")
            itype = item.get("item_type", "")
            rarity = item.get("rarity", "")
            parts.append(f"  {ename} → **{cname}** [{itype}/{rarity}]")
        parts.append("")
        has_content = True

    # Factions
    factions = entities.get("faction", [])
    if factions:
        parts.append(f"### Tổ chức ({len(factions)})\n")
        for f in factions:
            cname = f.get("canonical_name", f.get("en_name", "?"))
            ename = f.get("en_name", "")
            parts.append(f"  {ename} → **{cname}**")
        parts.append("")
        has_content = True

    if not has_content:
        return "Không có thực thể đã biết nào liên quan trong chương này."

    return "\n".join(parts).strip()


def _fmt_bible_character_profiles(chars: list[dict], chapter_text: str) -> str:
    """
    Format character profiles từ Bible → Phần 3 prompt.
    Giữ cấu trúc tương tự _fmt_characters() trong prompt_builder.py.
    """
    if not chars:
        return "Không có nhân vật đã biết nào trong chương này."

    header = (
        "Nhân vật từ Bible — đã được xác nhận qua nhiều chương.\n\n"
        "QUY TẮC XƯNG HÔ — ƯU TIÊN THEO THỨ TỰ:\n"
        "  1. relationships[X] strong dynamic → KHÔNG thay đổi\n"
        "  2. relationships[X] weak dynamic → tạm thời\n"
        "  3. pronoun_self fallback\n\n"
        "  ⛔ Chỉ đổi xưng hô khi: phản bội / tra khảo / lật mặt / đổi phe\n"
    )

    profiles = []
    for c in chars:
        cname   = c.get("canonical_name", c.get("en_name", "?"))
        ename   = c.get("en_name", "")
        role    = c.get("role", "?")
        archetype = c.get("archetype", "")
        pronoun = c.get("pronoun_self", "?")
        realm   = (c.get("cultivation") or {}).get("realm", "—")
        goal    = c.get("current_goal", "")
        psych   = c.get("personality_summary", "")

        block = [f"### {cname} ({ename})  [{role}] | {archetype}"]
        block.append(f"**Cảnh giới:** {realm}  **Tự xưng:** {pronoun}")

        if psych:
            block.append(f"\n**Tính cách:** {psych}")

        # Relationships từ Bible
        rels = c.get("relationships", [])
        if rels:
            block.append("\n**Quan hệ:**")
            for rel in rels[:4]:
                target  = rel.get("target_name") or rel.get("target_id", "?")
                rtype   = rel.get("rel_type", "")
                dynamic = rel.get("dynamic", "")
                eps     = rel.get("eps_level", 2)
                block.append(
                    f"  - {cname} ↔ {target}: [{rtype}] "
                    f"dynamic={dynamic or '?'} | EPS={eps}/5"
                )

        if goal:
            block.append(f"\n**Mục tiêu hiện tại:** {goal}")

        # Skills
        skill_ids = c.get("skill_ids", [])
        if skill_ids:
            block.append(f"**Kỹ năng:** {', '.join(skill_ids[:5])}")

        profiles.append("\n".join(block))

    return header + "\n\n---\n\n".join(profiles)


def _fmt_bible_lore_context(store: BibleStore, n: int = 3) -> str:
    """Format recent lore từ Bible → thay thế Arc Memory."""
    summaries = store.get_recent_lore(n)
    threads   = store.get_plot_threads("open")

    if not summaries and not threads:
        return ""

    lines = [f"**Bối cảnh từ Bible ({n} chương gần nhất):**\n"]

    for s in summaries:
        lines.append(f"**{s.chapter}** [{s.tone}]")
        lines.append(s.summary)
        if s.key_events:
            lines.extend(f"  - {e}" for e in s.key_events[:3])
        lines.append("")

    if threads:
        lines.append("**Plot threads đang mở:**")
        for t in threads[:5]:
            lines.append(f"  ⚠️ {t.name} (từ {t.opened_chapter}): {t.summary[:80]}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# MAIN BUILDER
# ═══════════════════════════════════════════════════════════════════

def build_bible_translation_prompt(
    instructions    : str,
    chapter_text    : str,
    chapter_filename: str,
    store           : BibleStore,
    chapter_map     = None,   # ChapterMap | None — từ Pre-call
    name_lock_table : dict[str, str] | None = None,
    budget_limit    : int = 0,
) -> str:
    """
    Bible-aware Trans-call system prompt.

    Thay thế:
      filter_glossary()       → store.get_entities_for_chapter() [skills, items, locs, factions]
      filter_characters()     → store.get_entities_for_chapter() [characters]
      load_arc_memory()       → store.format_recent_lore_for_prompt()
      load_context_notes()    → store.get_active_foreshadows()

    Giữ nguyên:
      instructions (Phần 1)
      chapter_map (Phần 4) — vẫn từ Pre-call
      name_lock_table (Phần 8)
    """
    # Query Bible
    entities        = store.get_entities_for_chapter(chapter_text)
    all_chars       = entities.get("character", [])
    wb_context      = store.get_relevant_worldbuilding(chapter_text)
    lore_context    = _fmt_bible_lore_context(store, n=3)
    foreshadow_hints = store.get_active_foreshadows(chapter_filename)

    # Token budget nếu cần
    if budget_limit > 0:
        entities, all_chars = _apply_bible_budget(
            entities, all_chars, chapter_text, budget_limit
        )

    total_entities = sum(len(v) for v in entities.values())
    print(f"     Bible entities: {total_entities} "
          f"({len(all_chars)} chars) · WB: {'✓' if wb_context else '—'} "
          f"· Lore: {'✓' if lore_context else '—'}")

    # Build sections
    parts = [
        "Bạn là AI chuyên dịch truyện LitRPG / Tu Tiên từ tiếng Anh sang tiếng Việt.\n"
        "Nhiệm vụ DUY NHẤT: dịch chapter được cung cấp. "
        "KHÔNG điền JSON, KHÔNG phân tích, KHÔNG thêm chú thích.\n"
        "[BIBLE MODE] Dùng thông tin từ Bible — đã được verify qua nhiều chương.\n",

        _section("PHẦN 1 — HƯỚNG DẪN DỊCH", instructions),

        _section(
            "PHẦN 2 — TỪ ĐIỂN & THỰC THỂ (từ Bible)",
            _fmt_bible_entities(entities, chapter_text),
        ),

        _section(
            "PHẦN 3 — PROFILE NHÂN VẬT (từ Bible)",
            _fmt_bible_character_profiles(all_chars, chapter_text)
            + (_eps_from_bible(all_chars, chapter_text) if all_chars else ""),
        ),
    ]

    # Phần 4: Chapter Map (Pre-call)
    if chapter_map and not chapter_map.is_empty():
        parts.append(_section(
            "PHẦN 4 — CHAPTER MAP (đã phân tích trước — ưu tiên cao)",
            chapter_map.to_prompt_block(),
        ))
    else:
        hints_block = ""
        if foreshadow_hints:
            hints_block = "\n⚠️ Foreshadow đang active:\n" + "\n".join(foreshadow_hints)
        parts.append(_section(
            "PHẦN 4 — GHI CHÚ CHAPTER",
            "Không có chapter map.\n"
            "Suy luận xưng hô và tên từ các phần trên."
            + hints_block,
        ))

    parts.append(_section("PHẦN 5 — YÊU CẦU ĐẦU RA", _translation_output_requirements()))

    # Phần 6: Lore Context (thay Arc Memory)
    if lore_context:
        parts.append(_section(
            "PHẦN 6 — BỐI CẢNH TỪ BIBLE (thay thế Arc Memory)",
            lore_context,
        ))

    # Phần 7: WorldBuilding context
    if wb_context:
        parts.append(_section(
            "PHẦN 7 — WORLDBUILDING (quy luật & hệ thống liên quan)",
            wb_context,
        ))

    # Phần 8: Name Lock
    from littrans.managers.name_lock import format_for_prompt as fmt_lock
    parts.append(_section(
        "PHẦN 8 — NAME LOCK TABLE (bảng tên đã chốt — BẮT BUỘC tuân theo)",
        fmt_lock(name_lock_table or {}),
    ))

    return "\n\n".join(parts)


def _eps_from_bible(chars: list[dict], chapter_text: str) -> str:
    """EPS summary từ Bible relationships — inject vào Phần 3."""
    eps_lines = []
    seen: set[frozenset] = set()

    for c in chars:
        cname = c.get("canonical_name", c.get("en_name", "?"))
        for rel in c.get("relationships", [])[:5]:
            target = rel.get("target_name") or rel.get("target_id", "")
            pair   = frozenset([cname, target])
            if pair in seen or not target:
                continue
            seen.add(pair)

            from littrans.llm.schemas import EPS_LABELS, EPS_BAR
            eps   = rel.get("eps_level", 2)
            if not isinstance(eps, int) or not (1 <= eps <= 5):
                eps = 2
            label, hint = EPS_LABELS.get(eps, ("NEUTRAL", ""))
            bar = EPS_BAR.get(eps, "██░░░")
            eps_lines.append(
                f"  {cname} ↔ {target}: {bar} {eps}/5 {label} → {hint}"
            )

    if not eps_lines:
        return ""
    return (
        "\n\n**EPS — Mức độ thân mật (điều chỉnh văn phong):**\n"
        + "\n".join(eps_lines)
    )


def _apply_bible_budget(
    entities: dict[str, list[dict]],
    all_chars: list[dict],
    chapter_text: str,
    budget_limit: int,
) -> tuple[dict, list[dict]]:
    """
    Simple budget: nếu có quá nhiều entities → cắt bớt chars phụ.
    Tái dụng logic từ token_budget.py.
    """
    try:
        from littrans.llm.token_budget import estimate_tokens, SOFT_LIMIT_RATIO
        soft = int(budget_limit * SOFT_LIMIT_RATIO)

        # Ước tính token của entity block
        entity_text = _fmt_bible_entities(entities, chapter_text)
        char_text   = _fmt_bible_character_profiles(all_chars, chapter_text)
        total_est   = estimate_tokens(entity_text) + estimate_tokens(char_text)

        if total_est <= soft * 0.6:  # dưới 60% budget → OK
            return entities, all_chars

        # Cắt characters phụ → giữ top 5 relevant nhất
        if len(all_chars) > 5:
            text_lower = chapter_text.lower()
            scored = []
            for c in all_chars:
                name = c.get("en_name", "") or c.get("canonical_name", "")
                count = len(
                    __import__("re").findall(
                        rf"(?<![a-zA-Z0-9]){__import__('re').escape(name.lower())}(?![a-zA-Z0-9])",
                        text_lower
                    )
                ) if name else 0
                scored.append((count, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            all_chars = [c for _, c in scored[:5]]
            entities["character"] = all_chars
            print(f"  ✂️  [BibleBudget] Cắt chars → {len(all_chars)} relevant nhất")

    except Exception:
        pass

    return entities, all_chars