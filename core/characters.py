"""
core/characters.py — Tiered Characters + Identity Tracking.

TẦNG:
  Active  (Characters_Active.json)
    → Nhân vật xuất hiện trong ARCHIVE_AFTER_CHAPTERS chương gần nhất
    → Luôn filter theo chapter text → đưa vào prompt nếu tên match

  Archive (Characters_Archive.json)
    → Lâu không xuất hiện → rotate từ Active sang đây
    → Chỉ load khi tên xuất hiện trong chapter (không dump toàn bộ)

IDENTITY TRACKING:
  Mỗi nhân vật có thêm:
    active_identity   : alias đang dùng hiện tại (VD: "Ngu Giả" thay vì "Klein")
    known_aliases     : tất cả alias đã biết
    identity_context  : khi nào dùng alias này
  → Filter sẽ match theo cả aliases, không chỉ tên thật
  → Prompt cảnh báo rõ khi nhân vật đang dùng danh tính khác
"""
import re, threading, logging
from copy import deepcopy
from .config import (
    CHARACTERS_ACTIVE_FILE, CHARACTERS_ARCHIVE_FILE, STAGING_CHARS_FILE,
    IMMEDIATE_MERGE, MIN_BEHAVIOR_CONF, ARCHIVE_AFTER_CHAPTERS,
)
from .io_utils import load_json, save_json
from .models import CharacterDetail, RelationshipUpdate

_lock  = threading.Lock()
_mlock = threading.Lock()

# ── Helpers ──────────────────────────────────────────────────────
def _empty_db() -> dict:
    return {"meta": {"schema_version": "3.0", "story_genre": "LitRPG",
                      "main_character": "", "last_updated_chapter": ""},
            "characters": {}}

def load_active(include_staging=False) -> dict:
    data = load_json(str(CHARACTERS_ACTIVE_FILE)) or _empty_db()
    if include_staging:
        stg = load_json(str(STAGING_CHARS_FILE))
        if stg:
            chars = data.setdefault("characters", {})
            for n, p in stg.get("characters", {}).items():
                if n not in chars:
                    chars[n] = p
    return data

def load_archive() -> dict:
    return load_json(str(CHARACTERS_ARCHIVE_FILE)) or _empty_db()


# ── Filter ───────────────────────────────────────────────────────
def filter_characters(chapter_text: str) -> dict[str, str]:
    """
    Trả về {name: formatted_profile} cho nhân vật XUẤT HIỆN trong chương.
    Active ưu tiên hơn Archive. Archive chỉ load khi tên thực sự có trong text.
    """
    active  = load_active(include_staging=True)
    archive = load_archive()
    mc_name = active.get("meta", {}).get("main_character", "")
    matched = {}

    for name, profile in active.get("characters", {}).items():
        if _matches(name, profile, chapter_text):
            matched[name] = _fmt(name, profile, chapter_text, mc_name)

    for name, profile in archive.get("characters", {}).items():
        if name not in matched and _matches(name, profile, chapter_text):
            matched[name] = _fmt(name, profile, chapter_text, mc_name, archived=True)

    return matched

def _matches(name: str, profile: dict, text: str) -> bool:
    """Match theo tên thật hoặc bất kỳ alias nào."""
    candidates = [name]
    candidates += profile.get("known_aliases", [])
    candidates += profile.get("identity", {}).get("aliases", [])
    return any(
        n and re.search(rf"\b{re.escape(n)}\b", text, re.IGNORECASE)
        for n in candidates
    )

def _fmt(name: str, p: dict, text: str, mc_name: str, archived=False) -> str:
    speech = p.get("speech", {})
    power  = p.get("power", {})
    ident  = p.get("identity", {})
    arc    = p.get("arc_status", {})
    rels   = p.get("relationships", {})

    lines = [f"### {name}{'  [ARCHIVE]' if archived else ''}  "
             f"[{p.get('role','?')}] | {p.get('archetype','')}"]

    # ── Identity warning ────────────────────────────────────────────
    ai = p.get("active_identity", "")
    if ai and ai != name:
        lines.append(f"**⚠️  Đang hoạt động với danh tính: {ai}**")
        ic = p.get("identity_context", "")
        if ic:
            lines.append(f"**Ngữ cảnh danh tính:** {ic}")
    aliases = p.get("known_aliases", []) or ident.get("aliases", [])
    if aliases:
        lines.append(f"**Alias đã biết:** {', '.join(aliases)}")

    lines += [
        f"**Danh hiệu:** {ident.get('current_title','—')}  "
        f"**Cấp độ:** {power.get('current_level','—')}  "
        f"**Phe:** {ident.get('faction','—')}",
        "",
        "**Tính cách:**",
        *[f"- {t}" for t in p.get("personality_traits", [])],
    ]

    # ── BẢNG XƯNG HÔ — ƯU TIÊN THEO THỨ TỰ ───────────────────────
    # Quy tắc AI PHẢI tuân theo (theo thứ tự ưu tiên giảm dần):
    #  1. relationships[X].dynamic (strong)  → cao nhất, KHÔNG thay đổi
    #  2. relationships[X].dynamic (weak)    → dùng tạm, cập nhật khi xác nhận
    #  3. how_refers_to_others[X]            → fallback khi chưa có quan hệ với X
    #  4. how_refers_to_others[default_*]    → fallback cuối cùng

    lines += [
        "",
        "**XƯNG HÔ — ĐỌC THEO THỨ TỰ ƯU TIÊN:**",
        f"- Tự xưng mặc định: **{speech.get('pronoun_self', '?')}**",
        f"- Ghi chú formality: {speech.get('formality_note', '—')}",
    ]

    # Nhóm 1: Xưng hô đã xác lập qua quan hệ (ưu tiên cao nhất)
    strong_entries = []
    weak_entries   = []
    for other, r in rels.items():
        if not r.get("dynamic"):
            continue
        # Chỉ hiển thị nếu nhân vật kia xuất hiện trong chương, hoặc là mc_name
        if other == mc_name or re.search(rf"\b{re.escape(other)}\b", text, re.IGNORECASE):
            status = r.get("pronoun_status", "weak")
            entry  = (other, r["dynamic"], status)
            if status == "strong":
                strong_entries.append(entry)
            else:
                weak_entries.append(entry)

    if strong_entries or weak_entries:
        lines.append("")
        lines.append("  ┌─ [NGUỒN 1 — ƯU TIÊN CAO NHẤT] Xưng hô từ quan hệ đã xác lập:")
        for other, dyn, _ in strong_entries:
            lines.append(f"  │  ✅ STRONG  {name} ↔ {other}: **{dyn}**  (đã chốt, KHÔNG thay đổi)")
        for other, dyn, _ in weak_entries:
            lines.append(f"  │  🔸 WEAK    {name} ↔ {other}: **{dyn}**  (tạm thời, xác nhận khi có tương tác)")
        lines.append("  └─")

    # Nhóm 2: Fallback từ how_refers_to_others (chỉ dùng khi không có quan hệ)
    how = speech.get("how_refers_to_others", {})
    if isinstance(how, list):
        how = {e.get("target", ""): e.get("style", "") for e in how}

    # Lọc ra những tên chưa có trong bảng quan hệ ở trên
    covered = {other for other, _, _ in strong_entries + weak_entries}
    fallback_specific = {
        t: s for t, s in how.items()
        if not t.startswith("default") and t not in covered
        and re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE)
    }
    fallback_defaults = {t: s for t, s in how.items() if t.startswith("default")}

    if fallback_specific or fallback_defaults:
        lines.append("")
        lines.append("  ┌─ [NGUỒN 2 — FALLBACK] Dùng khi chưa có quan hệ xác lập với nhân vật X:")
        for t, s in fallback_specific.items():
            lines.append(f"  │  {t}: {s}  (fallback — nên promote_to_strong khi xác nhận)")
        for t, s in fallback_defaults.items():
            lines.append(f"  │  {t}: {s}")
        lines.append("  └─")

    lines.append("")
    lines.append("  ⚠️  Quy tắc đổi xưng hô: CHỈ đổi khi có sự kiện bắt buộc")
    lines.append("      (phản bội / tra khảo / lật mặt / đổi phe / mất kiểm soát cảm xúc cực độ)")

    # ── Speech quirks ───────────────────────────────────────────────
    quirks = speech.get("speech_quirks", [])
    if quirks:
        lines += ["", "**Quirks lời thoại:**", *[f"- {q}" for q in quirks]]

    # ── Habitual behaviors ──────────────────────────────────────────
    strong_b = [b for b in p.get("habitual_behaviors", [])
                if b.get("confidence", 0) >= MIN_BEHAVIOR_CONF]
    if strong_b:
        lines.append("")
        lines.append("**Hành vi đặc trưng:**")
        for b in strong_b:
            lines.append(f"- [{b.get('intensity','?')}] {b.get('behavior','')} "
                         f"(trigger: {b.get('trigger','?')})")

    # ── Arc status ──────────────────────────────────────────────────
    goal = arc.get("current_goal", "")
    conflict = arc.get("current_conflict", "")
    if goal or conflict:
        lines += ["", f"**Mục tiêu:** {goal}", f"**Xung đột nội tâm:** {conflict}"]

    # ── Relationships (phần còn lại: type/feeling/tension/history) ──
    if mc_name and mc_name in rels and name != mc_name:
        lines += _fmt_rel(mc_name, rels[mc_name])
    for other, r in rels.items():
        if other != mc_name and re.search(rf"\b{re.escape(other)}\b", text, re.IGNORECASE):
            lines += _fmt_rel(other, r)

    return "\n".join(lines)

def _fmt_rel(other: str, r: dict) -> list[str]:
    status = r.get("pronoun_status", "weak")
    status_icon = "✅ strong" if status == "strong" else "🔸 weak"
    out = [
        f"\n**Quan hệ với {other}:**",
        f"- Kiểu: {r.get('type','?')} | Cảm xúc: {r.get('feeling','?')}",
        f"- Xưng hô ({status_icon}): {r.get('dynamic','?')}",
        f"- Hiện tại: {r.get('current_status','?')}",
    ]
    for t in r.get("tension_points", []):
        out.append(f"  ⚡ {t}")
    for h in r.get("history", [])[-2:]:
        out.append(f"  [{h.get('chapter','?')}] {h.get('event','')}")
    return out


# ── Archive Rotation ──────────────────────────────────────────────
def rotate_to_archive(current_chapter_index: int) -> int:
    """
    Nhân vật không xuất hiện trong ARCHIVE_AFTER_CHAPTERS chương → Archive.
    Gọi từ runner sau mỗi SCOUT_REFRESH_EVERY chương.
    """
    with _mlock:
        with _lock:
            active_data  = load_active()
            archive_data = load_archive()
            chars        = active_data.get("characters", {})
            arch_chars   = archive_data.setdefault("characters", {})
            to_move = [
                n for n, p in chars.items()
                if (current_chapter_index - p.get("last_seen_chapter_index", 0))
                   > ARCHIVE_AFTER_CHAPTERS
            ]
            for n in to_move:
                arch_chars[n] = chars.pop(n)
            if to_move:
                save_json(str(CHARACTERS_ACTIVE_FILE), active_data)
                save_json(str(CHARACTERS_ARCHIVE_FILE), archive_data)
    return len(to_move)


# ── Update From Response ──────────────────────────────────────────
def update_from_response(
    new_chars     : list[CharacterDetail],
    rel_updates   : list[RelationshipUpdate],
    source_chapter: str,
    chapter_index : int = 0,
) -> tuple[int, int]:
    if not new_chars and not rel_updates:
        return 0, 0
    with _lock:
        active_data = load_active()
        chars       = active_data.setdefault("characters", {})
        stg_data    = load_json(str(STAGING_CHARS_FILE)) or _empty_db()
        stg_chars   = stg_data.setdefault("characters", {})
        chars_added = rels_updated = 0
        stg_dirty   = False

        for char in new_chars:
            name = char.name.strip()
            if not name or name in chars or name in stg_chars:
                continue
            profile = _build_profile(char, source_chapter, chapter_index)
            if IMMEDIATE_MERGE:
                chars[name] = profile
            else:
                stg_chars[name] = profile; stg_dirty = True
            chars_added += 1

        for upd in rel_updates:
            a, b = upd.character_a.strip(), upd.character_b.strip()
            if not a or not b: continue
            ev = {"chapter": source_chapter, "event": upd.event}
            for owner, target, is_a in [(a, b, True), (b, a, False)]:
                if owner in chars:
                    _apply_rel(chars[owner].setdefault("relationships",{}), target, upd, ev, is_a)
            rels_updated += 1

        if IMMEDIATE_MERGE and (chars_added or rels_updated):
            active_data["meta"]["last_updated_chapter"] = source_chapter
            save_json(str(CHARACTERS_ACTIVE_FILE), active_data)
        if stg_dirty:
            stg_data["meta"]["last_updated_chapter"] = source_chapter
            save_json(str(STAGING_CHARS_FILE), stg_data)
    return chars_added, rels_updated

def touch_seen(names: list[str], chapter_index: int) -> None:
    """Cập nhật last_seen_chapter_index để rotation hoạt động đúng."""
    if not names: return
    with _lock:
        data = load_active(); chars = data.get("characters", {}); changed = False
        for name in names:
            if name in chars:
                chars[name]["last_seen_chapter_index"] = chapter_index; changed = True
        if changed:
            save_json(str(CHARACTERS_ACTIVE_FILE), data)

def _apply_rel(rels, target, upd, event, is_a):
    if target not in rels:
        rels[target] = {
            "type": "", "feeling": "", "dynamic": "",
            "pronoun_status": "weak",
            "current_status": "", "tension_points": [], "history": []
        }
    r = rels[target]
    r.setdefault("history", []).append(event)
    r.setdefault("pronoun_status", "weak")

    if is_a:
        if upd.new_type:    r["type"]           = upd.new_type
        if upd.new_feeling: r["feeling"]        = upd.new_feeling
        if upd.new_status:  r["current_status"] = upd.new_status
        if upd.new_tension:
            ts = r.setdefault("tension_points", [])
            if upd.new_tension not in ts:
                ts.append(upd.new_tension)
        # Cập nhật dynamic: chỉ khi promote_to_strong HOẶC đây là thay đổi bắt buộc
        if upd.new_dynamic:
            r["dynamic"]        = upd.new_dynamic
            r["pronoun_status"] = "strong"   # đổi dynamic = sự kiện bắt buộc → strong
        elif upd.promote_to_strong:
            r["pronoun_status"] = "strong"   # xác nhận cặp hiện tại, không đổi dynamic

def _build_profile(char: CharacterDetail, src: str, idx: int) -> dict:
    how  = {e.target: e.style for e in char.how_refers_to_others}
    rels = {}
    for rel in char.relationships:
        rels[rel.with_character] = {
            "type"          : rel.rel_type,
            "feeling"       : rel.feeling,
            "dynamic"       : rel.dynamic,
            "pronoun_status": rel.pronoun_status,   # "weak" | "strong"
            "current_status": rel.current_status,
            "tension_points": rel.tension_points,
            "history"       : [{"chapter": src, "event": rel.current_status or "Gặp lần đầu"}],
        }
    return {
        "identity": {"full_name": char.full_name or char.name, "aliases": char.aliases,
                     "current_title": char.current_title, "faction": char.faction,
                     "cultivation_path": char.cultivation_path},
        "power": {"current_level": char.current_level,
                  "signature_skills": char.signature_skills, "combat_style": char.combat_style},
        "canonical_name":      char.canonical_name.strip(),
        "alias_canonical_map": {k.strip(): v.strip()
                                 for k, v in char.alias_canonical_map.items()
                                 if k.strip() and v.strip()},
        "active_identity"  : char.active_identity or char.name,
        "known_aliases"    : char.aliases,
        "identity_context" : char.identity_context,
        "role"             : char.role,
        "archetype"        : char.archetype,
        "personality_traits": char.personality_traits,
        "speech": {
            "pronoun_self"        : char.pronoun_self,
            "formality_level"     : char.formality_level,
            "formality_note"      : char.formality_note,
            "how_refers_to_others": how,
            "speech_quirks"       : char.speech_quirks,
        },
        "habitual_behaviors": [b.model_dump() for b in char.habitual_behaviors
                                if b.confidence >= MIN_BEHAVIOR_CONF],
        "relationships": rels,
        "arc_status": {"current_goal": char.current_goal, "hidden_goal": char.hidden_goal,
                       "current_conflict": char.current_conflict},
        "first_seen": src, "last_seen_chapter_index": idx,
    }


# ── Sync Staging → Active ─────────────────────────────────────────
def sync_staging_to_active() -> tuple[int, int]:
    with _mlock:
        with _lock:
            stg = load_json(str(STAGING_CHARS_FILE))
            if not stg or not stg.get("characters"): return 0, 0
            data  = load_active(); chars = data.setdefault("characters",{}); added = 0
            for n, p in stg.get("characters",{}).items():
                if n not in chars: chars[n] = deepcopy(p); added += 1
            save_json(str(CHARACTERS_ACTIVE_FILE), data)
            import os; os.path.exists(str(STAGING_CHARS_FILE)) and os.remove(str(STAGING_CHARS_FILE))
    return added, 0

def has_staging_chars() -> int:
    d = load_json(str(STAGING_CHARS_FILE)); return len(d.get("characters",{})) if d else 0

def character_stats() -> dict[str, int]:
    return {"active": len(load_active().get("characters",{})),
            "archive": len(load_archive().get("characters",{})),
            "staging": has_staging_chars()}