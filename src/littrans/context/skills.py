"""
src/littrans/context/skills.py — Quản lý Skills.json.

[Refactor] managers/ → context/. Import: managers.base → context.base.
[FIX] Xoá module-level singleton _manager.
      Dùng _get_manager() factory mỗi lần gọi → đảm bảo đúng path sau set_novel().
      Cách cũ: _manager tạo 1 lần lúc import với settings.skills_file tại thời điểm đó.
      Sau set_novel(), skills_file đổi path nhưng _manager._path vẫn trỏ novel cũ.
"""
from __future__ import annotations
import logging
from littrans.config.settings import settings
from littrans.context.base import BaseManager
from littrans.core.patterns import word_boundary_search


class SkillsManager(BaseManager):

    def _empty_db(self) -> dict:
        return {
            "meta"  : {"schema_version": "1.0", "last_updated_chapter": ""},
            "skills": {},
        }

    def stats(self) -> dict[str, int]:
        skills = self._load().get("skills", {})
        evos   = sum(1 for s in skills.values() if s.get("evolved_from"))
        return {"total": len(skills), "evolution": evos, "base": len(skills) - evos}

    def load_for_chapter(self, chapter_text: str) -> dict[str, dict]:
        skills = self._load().get("skills", {})
        result = {}
        for eng, rec in skills.items():
            vn      = rec.get("vietnamese", "")
            vn_bare = vn.strip("[]")
            if (
                (eng and word_boundary_search(eng, chapter_text))
                or (vn_bare and word_boundary_search(vn_bare, chapter_text))
            ):
                result[eng] = rec
        return result

    def add_updates(self, updates: list, source_chapter: str) -> int:
        if not updates:
            return 0

        self.ensure_dir()

        with self._lock:
            data   = self._load_locked()
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
                    if upd.evolved_from and upd.evolved_from != existing.get("evolved_from", ""):
                        existing["evolved_from"] = upd.evolved_from
                        chain = existing.setdefault(
                            "evolution_chain", [existing.get("vietnamese", vn)]
                        )
                        if vn not in chain:
                            chain.append(vn)
                        existing["vietnamese"] = vn
                        changed = True
                    if upd.description and not existing.get("description"):
                        existing["description"] = upd.description
                        changed = True
                    if changed:
                        count += 1
                else:
                    skills[eng] = {
                        "vietnamese"     : vn,
                        "owner"          : upd.owner,
                        "skill_type"     : upd.skill_type,
                        "evolved_from"   : upd.evolved_from,
                        "description"    : upd.description,
                        "first_seen"     : source_chapter,
                        "evolution_chain": (
                            [vn] if not upd.evolved_from else [upd.evolved_from, vn]
                        ),
                    }
                    count += 1

            if count:
                data["meta"]["last_updated_chapter"] = source_chapter
                self._save(data)

        return count


# ── Factory (thay thế singleton) ─────────────────────────────────
# Gọi settings.skills_file mỗi lần để luôn lấy path của novel hiện tại.

def _get_manager() -> SkillsManager:
    return SkillsManager(settings.skills_file)


# ── Public API ────────────────────────────────────────────────────

def load_skills_for_chapter(chapter_text: str) -> dict[str, dict]:
    result = _get_manager().load_for_chapter(chapter_text)

    # ── FIX: Khi Bible mode, bổ sung skills từ Bible Store
    if settings.bible_mode and settings.bible_available:
        _augment_with_bible_skills(result, chapter_text)

    return result

def _augment_with_bible_skills(skills: dict[str, dict], chapter_text: str) -> None:
    """
    Bổ sung Bible skill entities vào skills dict nếu chúng xuất hiện trong chapter.
    Giải quyết vấn đề Skills: 0 khi Skills.json rỗng nhưng Bible đã có dữ liệu.

    Chỉ thêm skill chưa có trong skills dict để tránh overwrite dữ liệu từ Skills.json.
    """
    try:
        from littrans.context.bible_store import BibleStore
        store = BibleStore(settings.bible_dir)

        for skill_entity in store.get_all_entities("skill"):
            en_name   = (skill_entity.get("en_name") or "").strip()
            canonical = (skill_entity.get("canonical_name") or "").strip()

            if not en_name or not canonical:
                continue
            if en_name in skills:
                continue  # đã có từ Skills.json, không overwrite

            # Chỉ include nếu skill xuất hiện trong chapter này
            vn_bare = canonical.strip("[]")
            if (word_boundary_search(en_name, chapter_text) or
                    word_boundary_search(vn_bare, chapter_text)):
                skills[en_name] = {
                    "vietnamese"     : canonical,
                    "owner"          : "",
                    "skill_type"     : skill_entity.get("skill_type", "active"),
                    "evolved_from"   : "",
                    "description"    : skill_entity.get("description", ""),
                    "first_seen"     : skill_entity.get("first_appearance", ""),
                    "evolution_chain": [canonical],
                }

    except Exception as e:
        logging.warning(f"[Skills] _augment_with_bible_skills lỗi: {e}")

def format_skills_for_prompt(skills: dict[str, dict]) -> str:
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
        vn     = rec.get("vietnamese", "?")
        owner  = rec.get("owner", "—")
        evo    = rec.get("evolved_from", "")
        suffix = f"  ← tiến hóa từ [{evo}]" if evo else ""
        lines.append(f"  {eng:<30} {vn:<35} {owner}{suffix}")
    return "\n".join(lines)


def add_skill_updates(updates: list, source_chapter: str) -> int:
    return _get_manager().add_updates(updates, source_chapter)


def skills_stats() -> dict[str, int]:
    return _get_manager().stats()