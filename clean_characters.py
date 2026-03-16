"""
clean_characters.py — Công cụ quản lý Character Profile (v3)

Thay đổi so với v2:
  - Characters.json → Characters_Active.json + Characters_Archive.json
  - Thêm field identity tracking: active_identity, known_aliases, identity_context
  - Staging → Characters_Active.json (không phải Characters.json)
  - Action 'archive': xem danh sách nhân vật đang trong Archive

Actions:
  review    → In toàn bộ profile Active + thống kê Archive
  merge     → Merge Staging_Characters.json → Characters_Active.json
  fix       → Tự động sửa lỗi nhỏ
  export    → Xuất báo cáo Markdown
  validate  → Kiểm tra schema + cảnh báo
  archive   → In danh sách nhân vật trong Archive

Chạy: python clean_characters.py [--action ACTION]
"""

import json
import os
import sys
import argparse
import re
import tempfile
from datetime import datetime
from copy import deepcopy
from pathlib import Path

CHAR_DIR                = Path("data/characters")
CHARACTERS_ACTIVE_FILE  = CHAR_DIR / "Characters_Active.json"
CHARACTERS_ARCHIVE_FILE = CHAR_DIR / "Characters_Archive.json"
STAGING_CHARS_FILE      = CHAR_DIR / "Staging_Characters.json"
EXPORT_DIR              = "Reports"

VALID_ARCHETYPES = {
    "MC_GREMLIN", "SYSTEM_AI", "EDGELORD",
    "ARROGANT_NOBLE", "BRO_COMPANION", "ANCIENT_MAGE", "UNKNOWN"
}
VALID_ROLES = {
    "MC", "Party Member", "Enemy", "NPC", "Mentor",
    "Rival", "Love Interest", "Antagonist", "Unknown"
}
VALID_INTENSITIES = {"subtle", "medium", "strong"}
VALID_FORMALITY   = {"low", "medium-low", "medium", "medium-high", "high"}


# ── I/O helpers ───────────────────────────────────────────────────────────────
def _load_json(filepath) -> dict:
    p = Path(filepath)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8")
    if not raw.strip():
        print(f"⚠️  '{filepath}' rỗng — khởi tạo lại.")
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ JSON lỗi trong '{filepath}': {e}")
        corrupt = str(filepath) + ".corrupt"
        os.rename(filepath, corrupt)
        print(f"   → Đã đổi tên thành '{corrupt}'")
        return {}

def _save_json(filepath, data: dict) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    dir_name = str(Path(filepath).parent)
    fd, tmp  = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, filepath)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print(f"✅ Đã lưu: {filepath}")

def _empty_db() -> dict:
    return {
        "meta": {
            "schema_version"       : "3.0",
            "story_genre"          : "LitRPG",
            "main_character"       : "",
            "last_updated_chapter" : "",
        },
        "characters": {}
    }

def _ensure_dirs():
    CHAR_DIR.mkdir(parents=True, exist_ok=True)
    Path(EXPORT_DIR).mkdir(parents=True, exist_ok=True)


# ── Validation ────────────────────────────────────────────────────────────────
def validate_characters(data: dict, source_label: str = "Active") -> list[str]:
    warnings = []
    characters = data.get("characters", {})

    if not data.get("meta", {}).get("main_character"):
        warnings.append(f"⚠️  [{source_label}] meta.main_character chưa đặt")

    for name, profile in characters.items():
        prefix = f"[{name}]"

        role = profile.get("role", "")
        if role not in VALID_ROLES:
            warnings.append(f"{prefix} role='{role}' không hợp lệ. Hợp lệ: {VALID_ROLES}")

        archetype = profile.get("archetype", "")
        if archetype and archetype not in VALID_ARCHETYPES:
            warnings.append(f"{prefix} archetype='{archetype}' không hợp lệ.")

        speech = profile.get("speech", {})
        if not speech.get("pronoun_self"):
            warnings.append(f"{prefix} speech.pronoun_self bị trống")

        formality = speech.get("formality_level", "")
        if formality and formality not in VALID_FORMALITY:
            warnings.append(f"{prefix} formality_level='{formality}' không hợp lệ.")

        power = profile.get("power", {})
        if not power.get("current_level"):
            warnings.append(f"{prefix} power.current_level chưa có")

        for i, beh in enumerate(profile.get("habitual_behaviors", [])):
            if beh.get("confidence", 1.0) < 0.65:
                warnings.append(f"{prefix} habitual_behaviors[{i}] confidence thấp < 0.65")
            intensity = beh.get("intensity", "")
            if intensity not in VALID_INTENSITIES:
                warnings.append(f"{prefix} habitual_behaviors[{i}].intensity='{intensity}' không hợp lệ")

        rels = profile.get("relationships", {})
        for other, rel in rels.items():
            if not rel.get("type"):
                warnings.append(f"{prefix} relationships[{other}].type bị trống")
            if not rel.get("dynamic"):
                warnings.append(f"{prefix} relationships[{other}].dynamic bị trống")
            if other in characters:
                reverse = characters[other].get("relationships", {})
                if name not in reverse:
                    warnings.append(
                        f"⚠️  {prefix} → [{other}] nhưng [{other}] chưa có chiều ngược lại"
                    )

        arc = profile.get("arc_status", {})
        if not arc.get("current_goal"):
            warnings.append(f"{prefix} arc_status.current_goal chưa có")

    return warnings


# ── Format helper ─────────────────────────────────────────────────────────────
def _fmt_char_summary(name: str, p: dict) -> list[str]:
    speech   = p.get("speech", {})
    power    = p.get("power", {})
    arc      = p.get("arc_status", {})
    identity = p.get("identity", {})
    lines = [f"  ── {name} ──────────────────────────────"]
    lines.append(f"     Role      : {p.get('role','?')} ({p.get('archetype','')})")
    lines.append(f"     Cấp độ    : {power.get('current_level','?')}")
    lines.append(f"     Xưng hô   : {speech.get('pronoun_self','?')}")
    # Identity tracking
    ai = p.get("active_identity", "")
    if ai and ai != name:
        lines.append(f"     ⚠️ Danh tính: {ai} ({p.get('identity_context','')})")
    aliases = p.get("known_aliases", []) or identity.get("aliases", [])
    if aliases:
        lines.append(f"     Alias      : {', '.join(aliases)}")
    lines.append(f"     Traits    : {len(p.get('personality_traits',[]))} | "
                 f"Habits: {len(p.get('habitual_behaviors',[]))} | "
                 f"Quan hệ: {len(p.get('relationships',{}))}")
    lines.append(f"     Xuất hiện : {p.get('first_seen','?')}")
    lines.append(f"     Mục tiêu  : {arc.get('current_goal','chưa có')}")
    rels = p.get("relationships", {})
    if rels:
        lines.append("     Quan hệ   :")
        for other, r in rels.items():
            lines.append(f"       → {other}: [{r.get('current_status','?')}] | "
                        f"xưng hô: {r.get('dynamic','?')} | "
                        f"sự kiện: {len(r.get('history',[]))}")
    return lines


# ── Action: review ────────────────────────────────────────────────────────────
def action_review(active_data: dict, archive_data: dict) -> None:
    chars   = active_data.get("characters", {})
    mc      = active_data.get("meta", {}).get("main_character", "?")
    last_ch = active_data.get("meta", {}).get("last_updated_chapter", "?")
    arch_n  = len(archive_data.get("characters", {}))

    print(f"\n{'='*60}")
    print(f"  CHARACTER DATABASE v3 — MC: {mc} | Cập nhật: {last_ch}")
    print(f"  Active: {len(chars)} | Archive: {arch_n}")
    print(f"{'='*60}\n")

    for name, p in chars.items():
        for line in _fmt_char_summary(name, p):
            print(line)
        print()

    warnings = validate_characters(active_data)
    if warnings:
        print(f"{'='*60}")
        print(f"  ⚠️  VẤN ĐỀ CẦN XEM LẠI ({len(warnings)}):")
        print(f"{'='*60}")
        for w in warnings:
            print(f"  {w}")
    else:
        print("  ✅ Không có vấn đề nào.")
    print()


# ── Action: archive (view archive list) ──────────────────────────────────────
def action_archive_view(archive_data: dict) -> None:
    chars = archive_data.get("characters", {})
    print(f"\n{'='*60}")
    print(f"  ARCHIVE — {len(chars)} nhân vật ít xuất hiện")
    print(f"{'='*60}\n")
    if not chars:
        print("  (Trống)")
        return
    for name, p in chars.items():
        for line in _fmt_char_summary(name, p):
            print(line)
        print()


# ── Action: merge ─────────────────────────────────────────────────────────────
def action_merge(active_data: dict, staging_data: dict) -> dict:
    """Merge Staging_Characters.json → Characters_Active.json."""
    if not staging_data:
        print("ℹ️  Staging_Characters.json trống.")
        return active_data

    main_chars    = active_data.setdefault("characters", {})
    staging_chars = staging_data.get("characters", {})
    added = merged = 0

    for name, sp in staging_chars.items():
        if name not in main_chars:
            main_chars[name] = deepcopy(sp)
            added += 1
            print(f"  ➕ Thêm mới: {name}")
        else:
            existing = main_chars[name]
            for other, rel in sp.get("relationships", {}).items():
                if other not in existing.setdefault("relationships", {}):
                    existing["relationships"][other] = deepcopy(rel)
                    print(f"  🔗 Quan hệ mới: {name} ↔ {other}")
                else:
                    ex_hist   = existing["relationships"][other].setdefault("history", [])
                    ex_events = {h["event"] for h in ex_hist}
                    for h in rel.get("history", []):
                        if h["event"] not in ex_events:
                            ex_hist.append(h)
                    ex_t = existing["relationships"][other].setdefault("tension_points", [])
                    for t in rel.get("tension_points", []):
                        if t not in ex_t:
                            ex_t.append(t)

            ex_beh = {b["behavior"] for b in existing.get("habitual_behaviors", [])}
            for b in sp.get("habitual_behaviors", []):
                if b["behavior"] not in ex_beh and b.get("confidence", 0) >= 0.65:
                    existing.setdefault("habitual_behaviors", []).append(deepcopy(b))

            # Merge identity tracking fields
            for field in ("active_identity", "known_aliases", "identity_context"):
                if field in sp and not existing.get(field):
                    existing[field] = sp[field]

            merged += 1

    if staging_data.get("meta", {}).get("last_updated_chapter"):
        active_data.setdefault("meta", {})["last_updated_chapter"] = \
            staging_data["meta"]["last_updated_chapter"]

    print(f"\n  ✅ Merge xong: {added} mới, {merged} cập nhật.")
    print(f"  💡 Chạy --action validate để kiểm tra.")
    return active_data


# ── Action: fix ───────────────────────────────────────────────────────────────
def action_fix(data: dict) -> dict:
    characters = data.get("characters", {}); fixes = 0
    for name, profile in characters.items():
        if profile.get("archetype") not in VALID_ARCHETYPES:
            old = profile.get("archetype", ""); profile["archetype"] = "UNKNOWN"
            print(f"  🔧 [{name}] archetype '{old}' → 'UNKNOWN'"); fixes += 1
        if profile.get("role") not in VALID_ROLES:
            old = profile.get("role", ""); profile["role"] = "Unknown"
            print(f"  🔧 [{name}] role '{old}' → 'Unknown'"); fixes += 1
        kept = [b for b in profile.get("habitual_behaviors",[]) if b.get("confidence",1.0) >= 0.65]
        removed = len(profile.get("habitual_behaviors",[])) - len(kept)
        if removed:
            profile["habitual_behaviors"] = kept
            print(f"  🗑️  [{name}] Xóa {removed} habit(s) confidence thấp"); fixes += 1
        for beh in profile.get("habitual_behaviors", []):
            if beh.get("intensity") not in VALID_INTENSITIES:
                beh["intensity"] = "medium"; fixes += 1
        if "arc_status" not in profile:
            profile["arc_status"] = {"current_goal":"","hidden_goal":"","current_conflict":"","last_updated":"unknown"}
            print(f"  🔧 [{name}] Khởi tạo arc_status rỗng"); fixes += 1
        if "speech" not in profile:
            profile["speech"] = {"pronoun_self":"","formality_level":"medium","formality_note":"","how_refers_to_others":{},"speech_quirks":[]}
            print(f"  🔧 [{name}] Khởi tạo speech rỗng"); fixes += 1
        # Đảm bảo identity tracking fields tồn tại
        for field, default in [("active_identity", name), ("known_aliases", []), ("identity_context", "")]:
            if field not in profile:
                profile[field] = default; fixes += 1
    print(f"\n  ✅ Fix xong: {fixes} vấn đề.")
    return data


# ── Action: export ────────────────────────────────────────────────────────────
def action_export(active_data: dict, archive_data: dict) -> None:
    _ensure_dirs()
    characters = active_data.get("characters", {})
    mc         = active_data.get("meta", {}).get("main_character", "?")
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M")
    filepath   = os.path.join(EXPORT_DIR, f"character_report_{timestamp}.md")

    lines = [
        "# Character Report (v3)",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"MC: {mc} | Active: {len(characters)} | "
        f"Archive: {len(archive_data.get('characters',{}))}",
        "\n---\n",
        "## 📊 Relationship Matrix (Active)\n",
    ]

    names = list(characters.keys())
    if names:
        header = "| Nhân vật | " + " | ".join(names) + " |"
        sep    = "|---|" + "---|" * len(names)
        lines.extend([header, sep])
        for name in names:
            rels = characters[name].get("relationships", {})
            cells = []
            for other in names:
                if other == name:
                    cells.append("—")
                elif other in rels:
                    s = rels[other].get("current_status","?")
                    cells.append((s[:20] + "…") if len(s) > 20 else s)
                else:
                    cells.append("")
            lines.append(f"| **{name}** | " + " | ".join(cells) + " |")
        lines.append("\n---\n")

    lines.append("## 👤 Character Summaries (Active)\n")
    for name, p in characters.items():
        speech   = p.get("speech", {})
        power    = p.get("power", {})
        arc      = p.get("arc_status", {})
        identity = p.get("identity", {})
        ai       = p.get("active_identity", "")
        aliases  = p.get("known_aliases", []) or identity.get("aliases", [])

        lines += [
            f"### {name} `[{p.get('role','?')}]` `{p.get('archetype','')}`",
            f"**Danh hiệu:** {identity.get('current_title','—')}  ",
            f"**Phe:** {identity.get('faction','—')}  ",
            f"**Cấp độ:** {power.get('current_level','—')}  ",
            f"**Tự xưng:** {speech.get('pronoun_self','—')}  ",
        ]
        if ai and ai != name:
            lines.append(f"**⚠️ Đang dùng danh tính:** {ai}  ")
        if aliases:
            lines.append(f"**Alias:** {', '.join(aliases)}  ")
        lines += [
            f"**Mục tiêu:** {arc.get('current_goal','—')}  ",
            f"**Ẩn:** {arc.get('hidden_goal','—')}  \n",
        ]
        traits = p.get("personality_traits", [])
        if traits:
            lines.append("**Tính cách:**")
            for t in traits:
                lines.append(f"- {t}")
            lines.append("")
        rels = p.get("relationships", {})
        if rels:
            lines.append("**Quan hệ:**")
            for other, r in rels.items():
                lines.append(f"- **{other}**: {r.get('type','?')} | "
                             f"Cảm xúc: {r.get('feeling','?')} | "
                             f"Xưng hô: {r.get('dynamic','?')}")
            lines.append("")
        lines.append("---\n")

    # Archive summary
    arch_chars = archive_data.get("characters", {})
    if arch_chars:
        lines.append(f"## 📦 Archive ({len(arch_chars)} nhân vật)\n")
        for name, p in arch_chars.items():
            lines.append(f"- **{name}** [{p.get('role','?')}] | "
                        f"Cấp: {p.get('power',{}).get('current_level','?')} | "
                        f"Xuất hiện lần cuối: {p.get('last_seen_chapter_index','?')}")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  ✅ Xuất báo cáo: {filepath}")


# ── Action: validate ──────────────────────────────────────────────────────────
def action_validate(active_data: dict) -> None:
    warnings = validate_characters(active_data)
    if not warnings:
        print("  ✅ Tất cả profile Active hợp lệ.")
    else:
        print(f"  ⚠️  Tìm thấy {len(warnings)} vấn đề:\n")
        for w in warnings:
            print(f"    {w}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Quản lý Character Profile v3")
    parser.add_argument(
        "--action",
        choices=["review", "merge", "fix", "export", "validate", "archive"],
        default="review",
        help="Hành động (mặc định: review)"
    )
    args = parser.parse_args()

    _ensure_dirs()
    print(f"\n🎭 Clean Characters v3 — [{args.action.upper()}]")
    print(f"{'─'*55}")

    active_data = _load_json(CHARACTERS_ACTIVE_FILE)
    if not active_data:
        active_data = _empty_db()
        print("ℹ️  Characters_Active.json chưa tồn tại — khởi tạo mới.\n")

    archive_data = _load_json(CHARACTERS_ARCHIVE_FILE)
    if not archive_data:
        archive_data = _empty_db()

    if args.action == "review":
        action_review(active_data, archive_data)

    elif args.action == "archive":
        action_archive_view(archive_data)

    elif args.action == "merge":
        staging_data = _load_json(STAGING_CHARS_FILE)
        if not staging_data:
            print("ℹ️  Không tìm thấy Staging_Characters.json.")
        else:
            active_data = action_merge(active_data, staging_data)
            _save_json(CHARACTERS_ACTIVE_FILE, active_data)
            if STAGING_CHARS_FILE.exists():
                os.remove(STAGING_CHARS_FILE)
                print(f"  🗑️  Đã xóa {STAGING_CHARS_FILE.name} sau khi merge.")

    elif args.action == "fix":
        active_data = action_fix(active_data)
        _save_json(CHARACTERS_ACTIVE_FILE, active_data)

    elif args.action == "export":
        action_export(active_data, archive_data)

    elif args.action == "validate":
        action_validate(active_data)

    print(f"{'─'*55}\n")


if __name__ == "__main__":
    main()
