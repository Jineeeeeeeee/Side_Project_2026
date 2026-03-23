"""
src/littrans/cli/tool_clean_chars.py — Quản lý Character Profile.

Actions:
  review    → In toàn bộ profile Active + thống kê Archive
  merge     → Merge Staging_Characters.json → Characters_Active.json
  fix       → Tự động sửa lỗi nhỏ
  export    → Xuất báo cáo Markdown
  validate  → Kiểm tra schema + cảnh báo
  archive   → In danh sách nhân vật trong Archive
  log       → Xem lịch sử thay đổi của 1 nhân vật (git-style)
  diff      → So sánh profile của nhân vật giữa 2 chương
"""
from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from littrans.config.settings import settings
from littrans.utils.io_utils import load_json, save_json
from littrans.context.char_history import (
    get_log, get_log_rel, get_log_all_rels,
    get_state_at_chapter,
    format_log_terminal,
    TRACKED_FIELDS,
)

VALID_ARCHETYPES  = {"MC_GREMLIN","SYSTEM_AI","EDGELORD","ARROGANT_NOBLE","BRO_COMPANION","ANCIENT_MAGE","UNKNOWN"}
VALID_ROLES       = {"MC","Party Member","Enemy","NPC","Mentor","Rival","Love Interest","Antagonist","Unknown"}
VALID_INTENSITIES = {"subtle","medium","strong"}
VALID_FORMALITY   = {"low","medium-low","medium","medium-high","high"}

_EXPORT_DIR = Path("Reports")


def run_action(
    action  : str,
    name    : str | None = None,
    chapter : str | None = None,
    chapter2: str | None = None,
    rel     : str | None = None,
) -> None:
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
        "log"     : lambda: _action_log(active_data, archive_data, name, rel),
        "diff"    : lambda: _action_diff(active_data, archive_data, name, chapter, chapter2),
    }
    fn = dispatch.get(action)
    if fn:
        fn()
    else:
        print(f"❌ Action không hợp lệ: {action}")
        print(f"   Các action hợp lệ: {', '.join(dispatch)}")


# ── Helpers ───────────────────────────────────────────────────────

def _empty_db() -> dict:
    return {"meta": {"schema_version": "3.2", "story_genre": "LitRPG",
                      "main_character": "", "last_updated_chapter": ""},
            "characters": {}}


def _resolve_profile(
    name        : str | None,
    active_data : dict,
    archive_data: dict,
) -> tuple[str, dict] | None:
    """
    Tìm profile theo tên (case-insensitive, partial match).
    Trả về (resolved_name, profile) hoặc None.
    """
    if not name:
        return None

    all_chars: dict[str, dict] = {}
    all_chars.update(active_data.get("characters", {}))
    all_chars.update(archive_data.get("characters", {}))

    # Exact match trước
    if name in all_chars:
        return name, all_chars[name]

    # Case-insensitive exact
    for n, p in all_chars.items():
        if n.lower() == name.lower():
            return n, p

    # Partial match
    matches = [(n, p) for n, p in all_chars.items() if name.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"  ⚠️  Nhiều nhân vật khớp với '{name}':")
        for n, _ in matches[:8]:
            print(f"     • {n}")
        print("  → Hãy nhập tên chính xác hơn.")
        return None

    print(f"  ❌ Không tìm thấy nhân vật '{name}'")
    return None


def _fmt_char_summary(name: str, p: dict) -> list[str]:
    speech   = p.get("speech", {})
    power    = p.get("power", {})
    arc      = p.get("arc_status", {})
    ai       = p.get("active_identity", "")
    aliases  = p.get("known_aliases", []) or p.get("identity", {}).get("aliases", [])
    history  = p.get("_history", [])
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
    lines.append(f"     Lịch sử   : {len(history)} commits")
    lines.append(f"     Xuất hiện : {p.get('first_seen','?')}")
    lines.append(f"     Mục tiêu  : {arc.get('current_goal','chưa có')}")
    for other, r in p.get("relationships", {}).items():
        rel_commits = len(r.get("_rel_history", []))
        rel_info    = f"[{r.get('current_status','?')}]"
        if rel_commits:
            rel_info += f" ({rel_commits} commits)"
        lines.append(f"       → {other}: {rel_info}")
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
        # Đảm bảo _history tồn tại
        if "_history" not in profile:
            profile["_history"] = []
            fixes += 1
        # Đảm bảo _rel_history tồn tại trong mỗi relationship
        for rel in profile.get("relationships", {}).values():
            if "_rel_history" not in rel:
                rel["_rel_history"] = []
                fixes += 1
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
        history = p.get("_history", [])
        lines += [
            f"### {name} `[{p.get('role','?')}]`",
            f"**Cấp độ:** {power.get('current_level','—')}  ",
            f"**Tự xưng:** {speech.get('pronoun_self','—')}  ",
            f"**Commits:** {len(history)}  ",
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


# ── LOG action ────────────────────────────────────────────────────

def _action_log(
    active_data : dict,
    archive_data: dict,
    name        : str | None,
    rel         : str | None,
) -> None:
    """In lịch sử thay đổi của 1 nhân vật theo git-style."""
    if not name:
        # Không có tên → in danh sách nhân vật + số commits
        chars = active_data.get("characters", {})
        print(f"\n  CHARACTER HISTORY — {len(chars)} nhân vật active\n")
        print(f"  {'Tên':<30} {'Commits':>8}  {'Rel commits':>12}  {'Chương gần nhất'}")
        print("  " + "─" * 70)
        for n, p in sorted(chars.items()):
            h = p.get("_history", [])
            rel_total = sum(
                len(r.get("_rel_history", []))
                for r in p.get("relationships", {}).values()
            )
            last_ch = h[-1]["chapter"] if h else "—"
            print(f"  {n:<30} {len(h):>8}  {rel_total:>12}  {last_ch}")
        print()
        return

    result = _resolve_profile(name, active_data, archive_data)
    if not result:
        return
    resolved_name, profile = result

    print(format_log_terminal(resolved_name, profile, rel))

    # Nếu không chỉ định rel cụ thể → in tóm tắt tất cả rel histories
    if not rel:
        all_rel_h = get_log_all_rels(profile)
        if all_rel_h:
            print(f"  {'─'*58}")
            print(f"  Relationship commits:\n")
            for target, commits in all_rel_h.items():
                print(f"    {resolved_name} ↔ {target}: {len(commits)} commits")
                for c in commits[:3]:
                    cid   = c["commit"]
                    ch    = c.get("chapter", "")
                    fields = list(c.get("changes", {}).keys())
                    print(f"      {cid}  [{', '.join(fields[:3])}]")
            print()


# ── DIFF action ───────────────────────────────────────────────────

def _action_diff(
    active_data : dict,
    archive_data: dict,
    name        : str | None,
    chapter_a   : str | None,
    chapter_b   : str | None,
) -> None:
    """So sánh trạng thái nhân vật giữa 2 chương."""
    if not name:
        print("  ❌ Cần --name để dùng action diff.")
        return
    if not chapter_a or not chapter_b:
        print("  ❌ Cần --chapter và --chapter2 để dùng action diff.")
        return

    result = _resolve_profile(name, active_data, archive_data)
    if not result:
        return
    resolved_name, profile = result

    state_a = get_state_at_chapter(profile, chapter_a) or {}
    state_b = get_state_at_chapter(profile, chapter_b) or {}

    print(f"\n  DIFF  {resolved_name}")
    print(f"  {chapter_a}  →  {chapter_b}")
    print(f"  {'─'*58}\n")

    all_fields = set(state_a) | set(state_b)
    any_diff   = False

    for field in sorted(all_fields):
        va = state_a.get(field)
        vb = state_b.get(field)
        if va == vb:
            continue
        any_diff = True
        print(f"  {field}")
        if isinstance(va, list) or isinstance(vb, list):
            old_set = set(va or [])
            new_set = set(vb or [])
            for item in sorted(old_set - new_set):
                print(f"    - {item}")
            for item in sorted(new_set - old_set):
                print(f"    + {item}")
        else:
            print(f"    - {va or '(trống)'}")
            print(f"    + {vb or '(trống)'}")
        print()

    if not any_diff:
        print("  (Không có sự thay đổi được track giữa 2 chương này)\n")


# ── Validate helpers ──────────────────────────────────────────────

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
        if "_history" not in profile:
            warnings.append(f"{p} _history chưa có (chạy fix để thêm)")
    return warnings