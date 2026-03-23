"""
src/littrans/context/char_history.py — Character History Engine.

Git-style commit log cho character profiles và relationships.

Commit ID = tên chương (chapter_031.txt), không phải counter.
  Variants:
    "chapter_031.txt"              — profile-level change (post_call)
    "chapter_031.txt#rel:Arthur"   — relationship-level change
    "chapter_031.txt#scout"        — scout-triggered (emotion, goal)
    "chapter_031.txt#manual"       — user edited via UI / CLI
    "__created__"                  — commit đầu tiên khi tạo profile

Cấu trúc lưu trong profile JSON:
  profile["_history"]                  — list[CommitEntry]
  profile["relationships"][X]["_rel_history"] — list[CommitEntry]

[v1.0] Initial implementation
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


# ═══════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════

HISTORY_LIMIT     = 100   # max commits per character profile
REL_HISTORY_LIMIT = 30    # max commits per relationship

# Fields được theo dõi ở cấp profile
TRACKED_FIELDS: frozenset[str] = frozenset({
    # Power
    "power.current_level",
    "power.signature_skills",
    # Identity
    "identity.faction",
    "identity.current_title",
    "identity.cultivation_path",
    "active_identity",
    "role",
    "status",
    # Arc
    "arc_status.current_goal",
    "arc_status.hidden_goal",
    "arc_status.current_conflict",
    # Personality
    "personality_traits",
    # Emotion
    "emotional_state.current",
})

# Fields được theo dõi trong mỗi relationship
REL_TRACKED: frozenset[str] = frozenset({
    "dynamic",
    "pronoun_status",
    "intimacy_level",
    "type",
    "current_status",
    "feeling",
})


# ═══════════════════════════════════════════════════════════════════
# NESTED DICT HELPERS
# ═══════════════════════════════════════════════════════════════════

def _get_nested(d: dict, dotpath: str) -> Any:
    """Lấy giá trị theo dotpath. VD: 'power.current_level'."""
    keys = dotpath.split(".")
    cur  = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur


def _diff_value(old: Any, new: Any, field: str) -> dict | None:
    """
    So sánh old vs new. Trả về diff dict hoặc None nếu không đổi.
    personality_traits là list → dùng set diff.
    """
    if old is None and new is None:
        return None

    if field == "personality_traits":
        old_set = set(old) if isinstance(old, list) else set()
        new_set = set(new) if isinstance(new, list) else set()
        if old_set == new_set:
            return None
        added   = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)
        if not added and not removed:
            return None
        return {"added": added, "removed": removed}

    if field == "power.signature_skills":
        old_list = old if isinstance(old, list) else []
        new_list = new if isinstance(new, list) else []
        if old_list == new_list:
            return None
        old_set  = set(old_list)
        new_set  = set(new_list)
        added    = sorted(new_set - old_set)
        removed  = sorted(old_set - new_set)
        if not added and not removed:
            return None
        return {"added": added, "removed": removed}

    if old == new:
        return None
    if new is None:
        return None

    return {"old": old, "new": new}


# ═══════════════════════════════════════════════════════════════════
# DIFF FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def diff_profile(
    old_profile: dict,
    new_profile: dict,
    chapter    : str,
    trigger    : str = "post_call",
) -> dict | None:
    """
    So sánh old vs new profile theo TRACKED_FIELDS.
    Trả về commit dict hoặc None nếu không có gì thay đổi.

    trigger: "post_call" | "scout" | "manual"
    """
    changes: dict[str, Any] = {}

    for dotpath in TRACKED_FIELDS:
        field_key = dotpath.split(".")[-1]
        old_val   = _get_nested(old_profile, dotpath)
        new_val   = _get_nested(new_profile, dotpath)
        diff      = _diff_value(old_val, new_val, field_key)
        if diff is not None:
            changes[dotpath] = diff

    if not changes:
        return None

    suffix = f"#{trigger}" if trigger not in ("post_call",) else ""
    commit_id = f"{chapter}{suffix}"

    return _make_commit(commit_id, chapter, trigger, changes)


def diff_rel(
    old_rel : dict,
    new_data: dict,   # RelationshipUpdate fields (flattened)
    chapter : str,
    target  : str,
) -> dict | None:
    """
    So sánh relationship cũ vs update mới.
    new_data là dict với keys như "dynamic", "intimacy_level"...
    """
    changes: dict[str, Any] = {}

    field_map = {
        "new_dynamic"       : "dynamic",
        "new_type"          : "type",
        "new_feeling"       : "feeling",
        "new_status"        : "current_status",
        "new_intimacy_level": "intimacy_level",
        "promote_to_strong" : "pronoun_status",
    }

    for update_key, rel_key in field_map.items():
        if rel_key not in REL_TRACKED:
            continue
        new_val = new_data.get(update_key)

        # Special case: promote_to_strong
        if update_key == "promote_to_strong" and new_val:
            old_val = old_rel.get("pronoun_status", "weak")
            if old_val != "strong":
                changes["pronoun_status"] = {"old": old_val, "new": "strong"}
            continue

        if update_key == "new_intimacy_level":
            if not new_val or new_val == 0:
                continue
            old_val = old_rel.get("intimacy_level", 2)
            diff    = _diff_value(old_val, new_val, rel_key)
            if diff:
                changes[rel_key] = diff
            continue

        if not new_val:
            continue

        old_val = old_rel.get(rel_key)
        diff    = _diff_value(old_val, new_val, rel_key)
        if diff:
            changes[rel_key] = diff

    if not changes:
        return None

    commit_id = f"{chapter}#rel:{target}"
    return _make_commit(commit_id, chapter, "relationship_update", changes)


def diff_rel_from_eps(
    old_rel    : dict,
    new_signals: list[str],
    chapter    : str,
    target     : str,
) -> dict | None:
    """Diff riêng cho eps_signals (append-only list)."""
    old_signals = set(old_rel.get("eps_signals", []))
    new_set     = set(new_signals)
    added       = sorted(new_set - old_signals)
    if not added:
        return None
    commit_id = f"{chapter}#rel:{target}"
    return _make_commit(
        commit_id, chapter, "relationship_update",
        {"eps_signals": {"added": added}},
    )


# ═══════════════════════════════════════════════════════════════════
# COMMIT BUILDER
# ═══════════════════════════════════════════════════════════════════

def _make_commit(
    commit_id: str,
    chapter  : str,
    trigger  : str,
    changes  : dict,
) -> dict:
    return {
        "commit"   : commit_id,
        "chapter"  : chapter,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "trigger"  : trigger,
        "changes"  : changes,
    }


def make_created_commit(chapter: str) -> dict:
    """Commit đặc biệt khi profile được tạo lần đầu."""
    return {
        "commit"   : "__created__",
        "chapter"  : chapter,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "trigger"  : "post_call",
        "changes"  : {"__created__": True},
    }


# ═══════════════════════════════════════════════════════════════════
# APPEND + DEDUP
# ═══════════════════════════════════════════════════════════════════

def append_commit(history: list[dict], commit: dict, limit: int) -> list[dict]:
    """
    Append commit vào history list.
    Dedup: nếu chapter prefix đã có → replace (giữ commit mới nhất của chương đó).
    Trim về limit khi vượt quá.
    """
    chapter_prefix = commit["chapter"]

    # Replace nếu cùng chapter + cùng type commit
    commit_id = commit["commit"]
    new_history = [
        c for c in history
        if c["commit"] != commit_id
    ]
    new_history.append(commit)

    # Trim — giữ mới nhất
    if len(new_history) > limit:
        new_history = new_history[-limit:]

    return new_history


# ═══════════════════════════════════════════════════════════════════
# READ / QUERY
# ═══════════════════════════════════════════════════════════════════

def get_log(profile: dict, limit: int = 20) -> list[dict]:
    """Trả về history của profile, mới nhất trước."""
    history = profile.get("_history", [])
    return list(reversed(history[-limit:]))


def get_log_rel(profile: dict, target: str, limit: int = 10) -> list[dict]:
    """Trả về history của 1 relationship."""
    rel     = profile.get("relationships", {}).get(target, {})
    history = rel.get("_rel_history", [])
    return list(reversed(history[-limit:]))


def get_log_all_rels(profile: dict) -> dict[str, list[dict]]:
    """Trả về history của tất cả relationships."""
    result = {}
    for target, rel in profile.get("relationships", {}).items():
        h = rel.get("_rel_history", [])
        if h:
            result[target] = list(reversed(h))
    return result


def get_state_at_chapter(profile: dict, chapter: str) -> dict | None:
    """
    Tái tạo trạng thái profile tại 1 chương cụ thể bằng cách replay commits.
    Trả về dict các field đã tracked, hoặc None nếu không có history.

    NOTE: Đây là snapshot của TRACKED_FIELDS, không phải toàn bộ profile.
    """
    history = profile.get("_history", [])
    if not history:
        return None

    # Sort by chapter name (lexicographic, works for chapter_NNN format)
    sorted_h = sorted(history, key=lambda c: c["chapter"])

    state: dict[str, Any] = {}
    for commit in sorted_h:
        if commit["chapter"] > chapter:
            break
        for field, diff in commit.get("changes", {}).items():
            if field == "__created__":
                continue
            if isinstance(diff, dict) and "new" in diff:
                state[field] = diff["new"]
            # list diffs (personality_traits, signature_skills)
            elif isinstance(diff, dict) and "added" in diff:
                cur = state.get(field, [])
                if isinstance(cur, list):
                    cur     = list(cur)
                    added   = diff.get("added", [])
                    removed = set(diff.get("removed", []))
                    # dedup: chỉ thêm item chưa có
                    cur_set = set(cur)
                    for item in added:
                        if item not in cur_set:
                            cur.append(item)
                            cur_set.add(item)
                    cur = [x for x in cur if x not in removed]
                    state[field] = cur

    return state if state else None


# ═══════════════════════════════════════════════════════════════════
# FORMAT FOR DISPLAY
# ═══════════════════════════════════════════════════════════════════

def format_log_terminal(
    name    : str,
    profile : dict,
    rel_name: str | None = None,
) -> str:
    """
    Format lịch sử kiểu git log cho terminal.
    rel_name: nếu không None → chỉ hiện history của relationship đó.
    """
    lines = []

    if rel_name:
        history = get_log_rel(profile, rel_name)
        lines.append(f"\n  {name} ↔ {rel_name} — {len(history)} relationship commits\n")
    else:
        history = get_log(profile)
        total   = len(profile.get("_history", []))
        lines.append(f"\n  {name} — {total} commits total (showing {len(history)} recent)\n")
        lines.append("  " + "─" * 58)

    for commit in history:
        cid     = commit["commit"]
        ts      = commit.get("timestamp", "")
        trigger = commit.get("trigger", "")
        changes = commit.get("changes", {})

        # Header line
        lines.append(f"\n  commit  {cid}")
        lines.append(f"  trigger {trigger}  ·  {ts}")
        lines.append("")

        for field, diff in changes.items():
            if field == "__created__":
                lines.append("    (nhân vật được tạo lần đầu)")
                continue

            if isinstance(diff, dict) and "added" in diff:
                added   = diff.get("added", [])
                removed = diff.get("removed", [])
                lines.append(f"    {field}:")
                for a in added:
                    lines.append(f"      + {a}")
                for r in removed:
                    lines.append(f"      - {r}")
            elif isinstance(diff, dict) and "old" in diff:
                old_v = diff["old"] or "(trống)"
                new_v = diff["new"] or "(trống)"
                lines.append(f"    {field}")
                lines.append(f"      - {old_v}")
                lines.append(f"      + {new_v}")

    lines.append("")
    return "\n".join(lines)