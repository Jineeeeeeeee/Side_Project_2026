"""
core/skills.py — Quản lý Skills.json: kỹ năng đã biết xuyên suốt truyện.

CẤU TRÚC Skills.json:
{
  "meta": {
    "schema_version": "1.0",
    "last_updated_chapter": "Chapter_XX"
  },
  "skills": {
    "Fireball": {
      "vietnamese":   "[Hỏa Cầu]",
      "owner":        "Arthur",
      "skill_type":   "active",
      "evolved_from": "",
      "description":  "Phóng cầu lửa gây sát thương diện rộng",
      "first_seen":   "Chapter_01",
      "evolution_chain": ["[Hỏa Cầu]", "[Đại Hỏa Cầu]"]
    },
    ...
  }
}

MỤC ĐÍCH:
  1. Khi dịch bảng hệ thống (system box): tra cứu tên VN đã chốt trước
     → đảm bảo tên kỹ năng nhất quán, không dịch lại mỗi lần
  2. Khi xuất hiện kỹ năng mới / tiến hóa: AI báo cáo qua skill_updates
     → hệ thống tự cập nhật vào file này
  3. Filter cho prompt: chỉ đưa vào kỹ năng của nhân vật XUẤT HIỆN trong chương
"""
import threading, logging
from .config import SKILLS_FILE
from .io_utils import load_json, save_json

_lock = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────
def _empty_db() -> dict:
    return {
        "meta": {
            "schema_version": "1.0",
            "last_updated_chapter": ""
        },
        "skills": {}
    }

def _load() -> dict:
    return load_json(str(SKILLS_FILE)) or _empty_db()


# ── Public API ───────────────────────────────────────────────────
def load_skills_for_chapter(chapter_text: str) -> dict[str, dict]:
    """
    Trả về {english_name: skill_record} cho các kỹ năng XUẤT HIỆN trong chương.
    Dùng để đưa vào prompt phần System Box.
    """
    import re
    data   = _load()
    skills = data.get("skills", {})
    result = {}
    for eng, rec in skills.items():
        vn = rec.get("vietnamese", "")
        # Match theo tên EN gốc hoặc tên VN (không có dấu ngoặc vuông)
        vn_bare = vn.strip("[]")
        if (eng and re.search(rf"\b{re.escape(eng)}\b", chapter_text, re.IGNORECASE)) or \
           (vn_bare and re.search(rf"\b{re.escape(vn_bare)}\b", chapter_text, re.IGNORECASE)):
            result[eng] = rec
    return result


def format_skills_for_prompt(skills: dict[str, dict]) -> str:
    """
    Format danh sách kỹ năng để đưa vào PHẦN 2 — system box context.
    Chỉ gọi khi có kỹ năng liên quan.
    """
    if not skills:
        return ""
    lines = [
        "**Kỹ năng đã biết (tra cứu khi dịch bảng hệ thống):**",
        "  PHẢI dùng tên VN đã chốt. KHÔNG tự đặt tên mới nếu đã có trong danh sách này.",
        "",
        f"  {'TÊN TIẾNG ANH':<30} TÊN CHUẨN (dùng trong bản dịch)   CHỦ SỞ HỮU",
        "  " + "─" * 72,
    ]
    for eng, rec in sorted(skills.items(), key=lambda x: x[0].lower()):
        vn    = rec.get("vietnamese", "?")
        owner = rec.get("owner", "—")
        evo   = rec.get("evolved_from", "")
        suffix = f"  ← tiến hóa từ [{evo}]" if evo else ""
        lines.append(f"  {eng:<30} {vn:<35} {owner}{suffix}")
    return "\n".join(lines)


def add_skill_updates(updates: list, source_chapter: str) -> int:
    """
    Thêm kỹ năng mới / cập nhật tiến hóa vào Skills.json.
    Trả về số kỹ năng thực sự được thêm/cập nhật.
    """
    if not updates:
        return 0

    # Đảm bảo thư mục tồn tại
    SKILLS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with _lock:
        data   = _load()
        skills = data.setdefault("skills", {})
        count  = 0

        for upd in updates:
            eng = upd.english.strip()
            vn  = upd.vietnamese.strip()
            if not eng or not vn:
                continue

            if eng in skills:
                existing = skills[eng]
                changed  = False

                # Kỹ năng tiến hóa: cập nhật chain
                if upd.evolved_from and upd.evolved_from != existing.get("evolved_from", ""):
                    existing["evolved_from"] = upd.evolved_from
                    chain = existing.setdefault("evolution_chain", [existing.get("vietnamese", vn)])
                    if vn not in chain:
                        chain.append(vn)
                    existing["vietnamese"] = vn
                    changed = True

                # Cập nhật description nếu có thông tin mới
                if upd.description and not existing.get("description"):
                    existing["description"] = upd.description
                    changed = True

                if changed:
                    count += 1
            else:
                # Kỹ năng hoàn toàn mới
                skills[eng] = {
                    "vietnamese"     : vn,
                    "owner"          : upd.owner,
                    "skill_type"     : upd.skill_type,
                    "evolved_from"   : upd.evolved_from,
                    "description"    : upd.description,
                    "first_seen"     : source_chapter,
                    "evolution_chain": [vn] if not upd.evolved_from else [upd.evolved_from, vn],
                }
                count += 1

        if count:
            data["meta"]["last_updated_chapter"] = source_chapter
            save_json(str(SKILLS_FILE), data)

    return count


def skills_stats() -> dict[str, int]:
    data   = _load()
    skills = data.get("skills", {})
    evos   = sum(1 for s in skills.values() if s.get("evolved_from"))
    return {
        "total"    : len(skills),
        "evolution": evos,
        "base"     : len(skills) - evos,
    }