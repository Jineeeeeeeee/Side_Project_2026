"""
src/littrans/tools/clean_characters.py — Quản lý Character Profile.

Actions:
  review    → In toàn bộ profile Active + thống kê Archive
  merge     → Merge Staging_Characters.json → Characters_Active.json
  fix       → Tự động sửa lỗi nhỏ
  export    → Xuất báo cáo Markdown
  validate  → Kiểm tra schema + cảnh báo
  archive   → In danh sách nhân vật trong Archive
"""
from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from littrans.config.settings import settings
from littrans.utils.io_utils import load_json, save_json

VALID_ARCHETYPES  = {"MC_GREMLIN","SYSTEM_AI","EDGELORD","ARROGANT_NOBLE","BRO_COMPANION","ANCIENT_MAGE","UNKNOWN"}
VALID_ROLES       = {"MC","Party Member","Enemy","NPC","Mentor","Rival","Love Interest","Antagonist","Unknown"}
VALID_INTENSITIES = {"subtle","medium","strong"}
VALID_FORMALITY   = {"low","medium-low","medium","medium-high","high"}

_EXPORT_DIR = Path("Reports")


def run_action(action: str) -> None:
    """Điểm vào từ CLI."""
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    active_data  = load_json(settings.characters_active_file) or _empty_db()
    archive_data = load_json(settings.characters_archive_file) or _empty_db()

    dispatch = {
        "review"  : lambda: _action_review(active_data, archive_data),
        "archive" : lambda: _action_archive_view(archive_data),
        "merge"   : lambda: _action_merge(active_data),
        "fix"     : lambda: _action_fix(active_data),
        "export"  : lambda: _action_export(active_data, archive_data),
        "validate": lambda: _action_validate(active_data),
    }
    fn = dispatch.get(action)
    if fn:
        fn()
    else:
        print(f"❌ Action không hợp lệ: {action}")


# ── Helpers ───────────────────────────────────────────────────────

def _empty_db() -> dict:
    return {"meta": {"schema_version": "3.0", "story_genre": "LitRPG",
                      "main_character": "", "last_updated_chapter": ""},
            "characters": {}}


def _fmt_char_summary(name: str, p: dict) -> list[str]:
    speech   = p.get("speech", {})
    power    = p.get("power", {})
    arc      = p.get("arc_status", {})
    ai       = p.get("active_identity", "")
    aliases  = p.get("known_aliases", []) or p.get("identity", {}).get("aliases", [])
    lines    = [f"  ── {name} ──────────────────────────────"]
    lines.append(f"     Role      : {p.get('role','?')} ({p.get('archetype','')})")
    lines.append(f"     Cấp độ    : {power.get('current_level','?')}")
    lines.append(f"     Xưng hô   : {speech.get('pronoun_self','?')}")
    if ai and ai != name:
        lines.append(f"     ⚠️ Danh tính: {ai} ({p.get('identity_context','')})")
    if aliases:
        lines.append(f"     Alias      : {', '.join(aliases)}")
    lines.append(f"     Traits    : {len(p.get('personality_traits',[]))} | "
                 f"Habits: {len(p.get('habitual_behaviors',[]))} | "
                 f"Quan hệ: {len(p.get('relationships',{}))}")
    lines.append(f"     Xuất hiện : {p.get('first_seen','?')}")
    lines.append(f"     Mục tiêu  : {arc.get('current_goal','chưa có')}")
    for other, r in p.get("relationships", {}).items():
        lines.append(f"       → {other}: [{r.get('current_status','?')}]")
    return lines


# ── Actions ───────────────────────────────────────────────────────

def _action_review(active_data: dict, archive_data: dict) -> None:
    chars   = active_data.get("characters", {})
    mc      = active_data.get("meta", {}).get("main_character", "?")
    last_ch = active_data.get("meta", {}).get("last_updated_chapter", "?")
    arch_n  = len(archive_data.get("characters", {}))

    print(f"\n{'='*60}")
    print(f"  CHARACTER DB — MC: {mc} | Cập nhật: {last_ch}")
    print(f"  Active: {len(chars)} | Archive: {arch_n}")
    print(f"{'='*60}\n")
    for name, p in chars.items():
        for line in _fmt_char_summary(name, p): print(line)
        print()
    warnings = _validate_chars(active_data)
    if warnings:
        print(f"{'='*60}")
        print(f"  ⚠️  VẤN ĐỀ ({len(warnings)}):")
        for w in warnings: print(f"  {w}")
    else:
        print("  ✅ Không có vấn đề nào.")
    print()


def _action_archive_view(archive_data: dict) -> None:
    chars = archive_data.get("characters", {})
    print(f"\n{'='*60}")
    print(f"  ARCHIVE — {len(chars)} nhân vật")
    print(f"{'='*60}\n")
    if not chars:
        print("  (Trống)")
        return
    for name, p in chars.items():
        for line in _fmt_char_summary(name, p): print(line)
        print()


def _action_merge(active_data: dict) -> None:
    staging_data = load_json(settings.staging_chars_file)
    if not staging_data or not staging_data.get("characters"):
        print("ℹ️  Staging_Characters.json trống.")
        return

    chars     = active_data.setdefault("characters", {})
    stg_chars = staging_data.get("characters", {})
    added = merged = 0

    for name, sp in stg_chars.items():
        if name not in chars:
            chars[name] = deepcopy(sp)
            added += 1
            print(f"  ➕ Thêm mới: {name}")
        else:
            existing = chars[name]
            for other, rel in sp.get("relationships", {}).items():
                if other not in existing.setdefault("relationships", {}):
                    existing["relationships"][other] = deepcopy(rel)
                    print(f"  🔗 Quan hệ mới: {name} ↔ {other}")
            for field in ("active_identity", "known_aliases", "identity_context"):
                if field in sp and not existing.get(field):
                    existing[field] = sp[field]
            merged += 1

    if staging_data.get("meta", {}).get("last_updated_chapter"):
        active_data.setdefault("meta", {})["last_updated_chapter"] = \
            staging_data["meta"]["last_updated_chapter"]

    save_json(settings.characters_active_file, active_data)
    if settings.staging_chars_file.exists():
        os.remove(str(settings.staging_chars_file))
        print(f"  🗑️  Đã xóa Staging_Characters.json sau khi merge.")
    print(f"\n  ✅ Merge xong: {added} mới, {merged} cập nhật.")


def _action_fix(data: dict) -> None:
    chars = data.get("characters", {})
    fixes = 0
    for name, profile in chars.items():
        if profile.get("archetype") not in VALID_ARCHETYPES:
            profile["archetype"] = "UNKNOWN"; fixes += 1
        if profile.get("role") not in VALID_ROLES:
            profile["role"] = "Unknown"; fixes += 1
        kept = [b for b in profile.get("habitual_behaviors", []) if b.get("confidence", 1.0) >= 0.65]
        removed = len(profile.get("habitual_behaviors", [])) - len(kept)
        if removed:
            profile["habitual_behaviors"] = kept; fixes += 1
        if "arc_status" not in profile:
            profile["arc_status"] = {"current_goal":"","hidden_goal":"","current_conflict":"","last_updated":"unknown"}; fixes += 1
        for field, default in [("active_identity", name), ("known_aliases", []), ("identity_context", "")]:
            if field not in profile:
                profile[field] = default; fixes += 1
    save_json(settings.characters_active_file, data)
    print(f"\n  ✅ Fix xong: {fixes} vấn đề.")


def _action_export(active_data: dict, archive_data: dict) -> None:
    characters = active_data.get("characters", {})
    mc         = active_data.get("meta", {}).get("main_character", "?")
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M")
    filepath   = _EXPORT_DIR / f"character_report_{timestamp}.md"
    names      = list(characters.keys())

    lines = [
        "# Character Report",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | MC: {mc} | Active: {len(characters)}",
        "\n---\n",
    ]

    if names:
        lines.append("## Relationship Matrix\n")
        header = "| Nhân vật | " + " | ".join(names) + " |"
        sep    = "|---|" + "---|" * len(names)
        lines.extend([header, sep])
        for name in names:
            rels  = characters[name].get("relationships", {})
            cells = []
            for other in names:
                if other == name: cells.append("—")
                elif other in rels:
                    s = rels[other].get("current_status", "?")
                    cells.append(s[:20] + "…" if len(s) > 20 else s)
                else: cells.append("")
            lines.append(f"| **{name}** | " + " | ".join(cells) + " |")
        lines.append("\n---\n")

    lines.append("## Character Summaries\n")
    for name, p in characters.items():
        speech  = p.get("speech", {})
        power   = p.get("power", {})
        arc     = p.get("arc_status", {})
        ai      = p.get("active_identity", "")
        aliases = p.get("known_aliases", [])
        lines += [
            f"### {name} `[{p.get('role','?')}]`",
            f"**Cấp độ:** {power.get('current_level','—')}  ",
            f"**Tự xưng:** {speech.get('pronoun_self','—')}  ",
        ]
        if ai and ai != name: lines.append(f"**⚠️ Danh tính:** {ai}  ")
        if aliases:           lines.append(f"**Alias:** {', '.join(aliases)}  ")
        lines += [f"**Mục tiêu:** {arc.get('current_goal','—')}  \n", "---\n"]

    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✅ Xuất báo cáo: {filepath}")


def _action_validate(active_data: dict) -> None:
    warnings = _validate_chars(active_data)
    if not warnings:
        print("  ✅ Tất cả profile hợp lệ.")
    else:
        print(f"  ⚠️  {len(warnings)} vấn đề:\n")
        for w in warnings: print(f"    {w}")


def _validate_chars(data: dict) -> list[str]:
    warnings = []
    characters = data.get("characters", {})
    if not data.get("meta", {}).get("main_character"):
        warnings.append("⚠️  meta.main_character chưa đặt")
    for name, profile in characters.items():
        p = f"[{name}]"
        if profile.get("role") not in VALID_ROLES:
            warnings.append(f"{p} role='{profile.get('role')}' không hợp lệ")
        if not profile.get("speech", {}).get("pronoun_self"):
            warnings.append(f"{p} speech.pronoun_self bị trống")
        if not profile.get("power", {}).get("current_level"):
            warnings.append(f"{p} power.current_level chưa có")
        if not profile.get("arc_status", {}).get("current_goal"):
            warnings.append(f"{p} arc_status.current_goal chưa có")
    return warnings
