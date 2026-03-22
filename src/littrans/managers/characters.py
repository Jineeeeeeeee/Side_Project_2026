"""
src/littrans/managers/characters.py — Tiered Characters + Identity Tracking + Emotion Tracker.

Tầng:
  Active  (Characters_Active.json)  → nhân vật xuất hiện gần đây
  Archive (Characters_Archive.json) → lâu không xuất hiện
  Staging (Staging_Characters.json) → mới, chờ merge

[v4] Emotion Tracker:
  emotional_state: {current, intensity, reason, last_chapter_index}

[v4.2] Validate name + role trước khi lưu vào DB.
[v4.2] _matches dùng lookaround thay vì \b để hỗ trợ Unicode tốt hơn.

[v5.0] EPS (Emotional Proximity Signal):
  relationships[X].intimacy_level (int 1–5)
  relationships[X].eps_signals    (list[str])
  _fmt_rel() hiển thị EPS bar + hint cho AI dịch
  _apply_rel() cập nhật intimacy_level và eps_signals
"""
from __future__ import annotations

import re
import logging
import threading
from copy import deepcopy

from littrans.config.settings import settings
from littrans.utils.io_utils import load_json, save_json
from littrans.llm.schemas import (
    CharacterDetail, RelationshipUpdate,
    EPS_LABELS, EPS_BAR,
)

_lock  = threading.Lock()
_mlock = threading.Lock()

_EMOTION_DISPLAY = {
    "angry"  : ("TỨC GIẬN",    "Lời thoại có thể gay gắt, cộc cằn, mất kiểm soát"),
    "hurt"   : ("TỔN THƯƠNG",  "Lời thoại có thể trầm, đau đớn, co rút"),
    "changed": ("ĐÃ THAY ĐỔI", "Vừa trải qua sự kiện lớn — tông có thể khác hẳn"),
}

_VALID_ROLES = {
    "MC", "Party Member", "Enemy", "NPC", "Mentor",
    "Rival", "Love Interest", "Antagonist", "Unknown",
}


# ── DB helpers ────────────────────────────────────────────────────

def _empty_db() -> dict:
    return {
        "meta": {
            "schema_version": "3.1",  # bump cho EPS
            "story_genre": "LitRPG",
            "main_character": "",
            "last_updated_chapter": "",
        },
        "characters": {},
    }


def load_active(include_staging: bool = False) -> dict:
    data = load_json(settings.characters_active_file) or _empty_db()
    if include_staging:
        stg   = load_json(settings.staging_chars_file)
        chars = data.setdefault("characters", {})
        for n, p in (stg or {}).get("characters", {}).items():
            if n not in chars:
                chars[n] = p
    return data


def load_archive() -> dict:
    return load_json(settings.characters_archive_file) or _empty_db()


# ── Filter for prompt ─────────────────────────────────────────────

def filter_characters(chapter_text: str) -> dict[str, str]:
    """Trả về {name: formatted_profile} cho nhân vật XUẤT HIỆN trong chương."""
    active  = load_active(include_staging=True)
    archive = load_archive()
    mc_name = active.get("meta", {}).get("main_character", "")
    matched: dict[str, str] = {}

    for name, profile in active.get("characters", {}).items():
        if _matches(name, profile, chapter_text):
            matched[name] = _fmt(name, profile, chapter_text, mc_name)

    for name, profile in archive.get("characters", {}).items():
        if name not in matched and _matches(name, profile, chapter_text):
            matched[name] = _fmt(name, profile, chapter_text, mc_name, archived=True)

    return matched


def _matches(name: str, profile: dict, text: str) -> bool:
    candidates = (
        [name]
        + profile.get("known_aliases", [])
        + profile.get("identity", {}).get("aliases", [])
    )
    for n in candidates:
        if not n:
            continue
        try:
            if re.search(
                rf"(?<![^\W_]){re.escape(n)}(?![^\W_])",
                text,
                re.IGNORECASE | re.UNICODE,
            ):
                return True
        except re.error:
            if n.lower() in text.lower():
                return True
    return False


# ── Format profile ────────────────────────────────────────────────

def _fmt(name: str, p: dict, text: str, mc_name: str, archived: bool = False) -> str:
    speech = p.get("speech", {})
    power  = p.get("power", {})
    ident  = p.get("identity", {})
    arc    = p.get("arc_status", {})
    rels   = p.get("relationships", {})

    header = f"### {name}{'  [ARCHIVE]' if archived else ''}  [{p.get('role','?')}] | {p.get('archetype','')}"
    lines  = [header]

    # Emotion warning
    em    = p.get("emotional_state", {})
    state = em.get("current", "normal")
    if state and state != "normal":
        disp = _EMOTION_DISPLAY.get(state)
        if disp:
            state_vn, hint = disp
            intensity = em.get("intensity", "medium")
            reason    = em.get("reason", "")
            lines += [
                "", f"┌{'─'*58}",
                f"│ ⚠️  TRẠNG THÁI CẢM XÚC: **{state_vn}** [{intensity}]",
                f"│ {hint}",
            ]
            if reason:
                lines.append(f"│ Lý do: {reason}")
            lines += [f"└{'─'*58}", ""]

    # Identity warning
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
        "",
        "**XƯNG HÔ — ĐỌC THEO THỨ TỰ ƯU TIÊN:**",
        f"- Tự xưng mặc định: **{speech.get('pronoun_self', '?')}**",
        f"- Ghi chú formality: {speech.get('formality_note', '—')}",
    ]

    # Strong / weak relationship pronouns
    strong_entries, weak_entries = [], []
    for other, r in rels.items():
        if not r.get("dynamic"):
            continue
        if other == mc_name or _name_in_text(other, text):
            entry = (other, r["dynamic"], r.get("pronoun_status", "weak"))
            (strong_entries if entry[2] == "strong" else weak_entries).append(entry)

    if strong_entries or weak_entries:
        lines += ["", "  ┌─ [NGUỒN 1 — ƯU TIÊN CAO NHẤT] Xưng hô từ quan hệ đã xác lập:"]
        for other, dyn, _ in strong_entries:
            lines.append(f"  │  ✅ STRONG  {name} ↔ {other}: **{dyn}**  (đã chốt, KHÔNG thay đổi)")
        for other, dyn, _ in weak_entries:
            lines.append(f"  │  🔸 WEAK    {name} ↔ {other}: **{dyn}**  (tạm thời, xác nhận khi tương tác)")
        lines.append("  └─")

    # Fallback how_refers_to_others
    how = speech.get("how_refers_to_others", {})
    if isinstance(how, list):
        how = {e.get("target", ""): e.get("style", "") for e in how}
    covered = {o for o, _, _ in strong_entries + weak_entries}
    fallback_specific = {
        t: s for t, s in how.items()
        if not t.startswith("default") and t not in covered
        and _name_in_text(t, text)
    }
    fallback_defaults = {t: s for t, s in how.items() if t.startswith("default")}
    if fallback_specific or fallback_defaults:
        lines += ["", "  ┌─ [NGUỒN 2 — FALLBACK]"]
        for t, s in fallback_specific.items():
            lines.append(f"  │  {t}: {s}  (fallback)")
        for t, s in fallback_defaults.items():
            lines.append(f"  │  {t}: {s}")
        lines.append("  └─")

    lines += [
        "", "  ⚠️  Đổi xưng hô CHỈ KHI: phản bội / tra khảo / lật mặt / đổi phe / mất kiểm soát cực độ",
    ]

    quirks = speech.get("speech_quirks", [])
    if quirks:
        lines += ["", "**Quirks lời thoại:**", *[f"- {q}" for q in quirks]]

    strong_b = [b for b in p.get("habitual_behaviors", [])
                if b.get("confidence", 0) >= settings.min_behavior_conf]
    if strong_b:
        lines += ["", "**Hành vi đặc trưng:**"]
        for b in strong_b:
            lines.append(f"- [{b.get('intensity','?')}] {b.get('behavior','')} (trigger: {b.get('trigger','?')})")

    goal, conflict = arc.get("current_goal", ""), arc.get("current_conflict", "")
    if goal or conflict:
        lines += ["", f"**Mục tiêu:** {goal}", f"**Xung đột nội tâm:** {conflict}"]

    if mc_name and mc_name in rels and name != mc_name:
        lines += _fmt_rel(mc_name, rels[mc_name])
    for other, r in rels.items():
        if other != mc_name and _name_in_text(other, text):
            lines += _fmt_rel(other, r)

    return "\n".join(lines)


def _name_in_text(name: str, text: str) -> bool:
    if not name:
        return False
    try:
        return bool(re.search(
            rf"(?<![^\W_]){re.escape(name)}(?![^\W_])",
            text,
            re.IGNORECASE | re.UNICODE,
        ))
    except re.error:
        return name.lower() in text.lower()


def _fmt_rel(other: str, r: dict) -> list[str]:
    status_icon = "✅ strong" if r.get("pronoun_status") == "strong" else "🔸 weak"

    # EPS display
    intimacy = r.get("intimacy_level", 2)
    if not isinstance(intimacy, int) or not (1 <= intimacy <= 5):
        intimacy = 2
    eps_label, eps_hint = EPS_LABELS.get(intimacy, ("NEUTRAL", ""))
    eps_bar   = EPS_BAR.get(intimacy, "██░░░")
    eps_signals = r.get("eps_signals", [])

    out = [
        f"\n**Quan hệ với {other}:**",
        f"- Kiểu: {r.get('type','?')} | Cảm xúc: {r.get('feeling','?')}",
        f"- Xưng hô ({status_icon}): {r.get('dynamic','?')}",
        f"- EPS: {eps_bar} {intimacy}/5 {eps_label} — {eps_hint}",
        f"- Hiện tại: {r.get('current_status','?')}",
    ]

    if eps_signals:
        out.append(f"  📌 EPS signals: {' · '.join(eps_signals[:3])}")

    for t in r.get("tension_points", []):
        out.append(f"  ⚡ {t}")
    for h in r.get("history", [])[-2:]:
        out.append(f"  [{h.get('chapter','?')}] {h.get('event','')}")
    return out


# ── EPS format for prompt_builder ────────────────────────────────

def format_eps_summary(char_profiles: dict[str, str], chapter_text: str) -> str:
    """
    Tạo bảng EPS ngắn gọn để inject vào Trans-call prompt.
    Chỉ hiển thị các cặp nhân vật XUẤT HIỆN trong chương.
    """
    active  = load_active(include_staging=True)
    chars   = active.get("characters", {})

    eps_lines = []
    seen_pairs: set[frozenset] = set()

    for name in char_profiles:
        profile = chars.get(name, {})
        for other, r in profile.get("relationships", {}).items():
            pair_key = frozenset([name, other])
            if pair_key in seen_pairs:
                continue
            if not _name_in_text(other, chapter_text) and not _name_in_text(name, chapter_text):
                continue
            seen_pairs.add(pair_key)

            intimacy = r.get("intimacy_level", 2)
            if not isinstance(intimacy, int) or not (1 <= intimacy <= 5):
                intimacy = 2
            eps_label, eps_hint = EPS_LABELS.get(intimacy, ("NEUTRAL", ""))
            eps_bar   = EPS_BAR.get(intimacy, "██░░░")
            signals   = r.get("eps_signals", [])
            sig_str   = f" [{signals[0]}]" if signals else ""
            eps_lines.append(
                f"  {name} ↔ {other}: {eps_bar} {intimacy}/5 {eps_label}{sig_str}"
                f" → {eps_hint}"
            )

    if not eps_lines:
        return ""

    return (
        "**EPS — Mức độ thân mật (điều chỉnh văn phong xưng hô theo đây):**\n"
        + "\n".join(eps_lines)
    )


# ── Archive rotation ──────────────────────────────────────────────

def rotate_to_archive(current_chapter_index: int) -> int:
    with _mlock:
        with _lock:
            active_data  = load_active()
            archive_data = load_archive()
            chars        = active_data.get("characters", {})
            arch_chars   = archive_data.setdefault("characters", {})
            to_move = [
                n for n, p in chars.items()
                if (current_chapter_index - p.get("last_seen_chapter_index", 0))
                   > settings.archive_after_chapters
            ]
            for n in to_move:
                arch_chars[n] = chars.pop(n)
            if to_move:
                save_json(settings.characters_active_file, active_data)
                save_json(settings.characters_archive_file, archive_data)
    return len(to_move)


# ── Update from AI response ───────────────────────────────────────

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
        stg_data    = load_json(settings.staging_chars_file) or _empty_db()
        stg_chars   = stg_data.setdefault("characters", {})
        chars_added = rels_updated = 0
        stg_dirty   = False

        for char in new_chars:
            name = char.name.strip()

            if not name or len(name) < 2:
                logging.warning(
                    f"[Characters] Bỏ qua nhân vật tên rỗng/quá ngắn "
                    f"('{char.name}') từ {source_chapter}"
                )
                continue
            if name in chars or name in stg_chars:
                continue

            if char.role not in _VALID_ROLES:
                logging.warning(
                    f"[Characters] '{name}' role='{char.role}' không hợp lệ → đặt NPC"
                )
                char.role = "NPC"

            profile = _build_profile(char, source_chapter, chapter_index)
            if settings.immediate_merge:
                chars[name] = profile
            else:
                stg_chars[name] = profile
                stg_dirty = True
            chars_added += 1

        for upd in rel_updates:
            a, b = upd.character_a.strip(), upd.character_b.strip()
            if not a or not b:
                continue
            ev = {"chapter": source_chapter, "event": upd.event}
            for owner, target, is_a in [(a, b, True), (b, a, False)]:
                if owner in chars:
                    _apply_rel(chars[owner].setdefault("relationships", {}), target, upd, ev, is_a)
            rels_updated += 1

        if settings.immediate_merge and (chars_added or rels_updated):
            active_data["meta"]["last_updated_chapter"] = source_chapter
            save_json(settings.characters_active_file, active_data)
        if stg_dirty:
            stg_data["meta"]["last_updated_chapter"] = source_chapter
            save_json(settings.staging_chars_file, stg_data)

    return chars_added, rels_updated


def touch_seen(names: list[str], chapter_index: int) -> None:
    if not names:
        return
    with _lock:
        data    = load_active()
        chars   = data.get("characters", {})
        changed = False
        for name in names:
            if name in chars:
                chars[name]["last_seen_chapter_index"] = chapter_index
                changed = True
        if changed:
            save_json(settings.characters_active_file, data)


def sync_staging_to_active() -> tuple[int, int]:
    with _mlock:
        with _lock:
            stg = load_json(settings.staging_chars_file)
            if not stg or not stg.get("characters"):
                return 0, 0
            data  = load_active()
            chars = data.setdefault("characters", {})
            added = 0
            for n, p in stg.get("characters", {}).items():
                if n not in chars:
                    chars[n] = deepcopy(p)
                    added += 1
            save_json(settings.characters_active_file, data)
            import os
            if os.path.exists(str(settings.staging_chars_file)):
                os.remove(str(settings.staging_chars_file))
    return added, 0


def has_staging_chars() -> int:
    d = load_json(settings.staging_chars_file)
    return len(d.get("characters", {})) if d else 0


def character_stats() -> dict[str, int]:
    chars     = load_active().get("characters", {})
    non_normal = sum(
        1 for p in chars.values()
        if p.get("emotional_state", {}).get("current", "normal") != "normal"
    )
    return {
        "active"   : len(chars),
        "archive"  : len(load_archive().get("characters", {})),
        "staging"  : has_staging_chars(),
        "emotional": non_normal,
    }


# ── Apply relationship update ─────────────────────────────────────

def _apply_rel(rels: dict, target: str, upd: RelationshipUpdate, event: dict, is_a: bool) -> None:
    if target not in rels:
        rels[target] = {
            "type": "", "feeling": "", "dynamic": "",
            "pronoun_status": "weak",
            "current_status": "", "tension_points": [], "history": [],
            "intimacy_level": 2, "eps_signals": [],
        }
    r = rels[target]
    r.setdefault("history", []).append(event)
    r.setdefault("pronoun_status", "weak")
    r.setdefault("intimacy_level", 2)
    r.setdefault("eps_signals", [])

    if is_a:
        if upd.new_type:    r["type"]           = upd.new_type
        if upd.new_feeling: r["feeling"]        = upd.new_feeling
        if upd.new_status:  r["current_status"] = upd.new_status
        if upd.new_tension:
            ts = r.setdefault("tension_points", [])
            if upd.new_tension not in ts:
                ts.append(upd.new_tension)
        if upd.new_dynamic:
            r["dynamic"]        = upd.new_dynamic
            r["pronoun_status"] = "strong"
        elif upd.promote_to_strong:
            r["pronoun_status"] = "strong"

    # ── EPS update — ĐỐI XỨNG, áp dụng cả 2 chiều ───────────────
    # Intimacy là property của mối quan hệ, không phải cá nhân.
    # Log chỉ 1 lần từ phía A (is_a=True).
    if upd.new_intimacy_level and 1 <= upd.new_intimacy_level <= 5:
        old = r.get("intimacy_level", 2)
        r["intimacy_level"] = upd.new_intimacy_level
        if old != upd.new_intimacy_level and is_a:
            logging.info(
                f"[EPS] {upd.character_a} ↔ {target}: "
                f"{old} → {upd.new_intimacy_level} ({upd.event[:50]})"
            )
    if upd.new_eps_signals:
        existing = set(r.get("eps_signals", []))
        for sig in upd.new_eps_signals:
            if sig and sig not in existing:
                r["eps_signals"].append(sig)
                existing.add(sig)
        r["eps_signals"] = r["eps_signals"][-10:]


def _build_profile(char: CharacterDetail, src: str, idx: int) -> dict:
    how  = {e.target: e.style for e in char.how_refers_to_others}
    rels = {}
    for rel in char.relationships:
        rels[rel.with_character] = {
            "type"          : rel.rel_type,
            "feeling"       : rel.feeling,
            "dynamic"       : rel.dynamic,
            "pronoun_status": rel.pronoun_status,
            "current_status": rel.current_status,
            "tension_points": rel.tension_points,
            "history"       : [{"chapter": src, "event": rel.current_status or "Gặp lần đầu"}],
            # EPS fields
            "intimacy_level": max(1, min(5, rel.intimacy_level)),
            "eps_signals"   : list(rel.eps_signals)[:10],
        }
    return {
        "identity"         : {
            "full_name": char.full_name or char.name, "aliases": char.aliases,
            "current_title": char.current_title, "faction": char.faction,
            "cultivation_path": char.cultivation_path,
        },
        "power"            : {
            "current_level": char.current_level,
            "signature_skills": char.signature_skills,
            "combat_style": char.combat_style,
        },
        "canonical_name"   : char.canonical_name.strip(),
        "alias_canonical_map": {k.strip(): v.strip()
                                 for k, v in char.alias_canonical_map.items()
                                 if k.strip() and v.strip()},
        "active_identity"  : char.active_identity or char.name,
        "known_aliases"    : char.aliases,
        "identity_context" : char.identity_context,
        "role"             : char.role if char.role in _VALID_ROLES else "NPC",
        "archetype"        : char.archetype,
        "personality_traits": char.personality_traits,
        "speech"           : {
            "pronoun_self"        : char.pronoun_self,
            "formality_level"     : char.formality_level,
            "formality_note"      : char.formality_note,
            "how_refers_to_others": how,
            "speech_quirks"       : char.speech_quirks,
        },
        "habitual_behaviors": [
            b.model_dump() for b in char.habitual_behaviors
            if b.confidence >= settings.min_behavior_conf
        ],
        "relationships"    : rels,
        "arc_status"       : {
            "current_goal": char.current_goal,
            "hidden_goal": char.hidden_goal,
            "current_conflict": char.current_conflict,
        },
        "emotional_state"  : {
            "current": "normal", "intensity": "low",
            "reason": "", "last_chapter_index": idx,
        },
        "first_seen"              : src,
        "last_seen_chapter_index" : idx,
    }