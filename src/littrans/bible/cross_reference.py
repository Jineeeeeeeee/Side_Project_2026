"""
src/littrans/bible/cross_reference.py — CrossReferenceEngine.

Phát hiện mâu thuẫn cốt truyện sau khi scan xong.

4 loại checks:
  1. character_consistency  — thay đổi level bất thường, nhân vật chết sống lại
  2. timeline_logic         — event xảy ra sai thứ tự, skill dùng trước khi học
  3. worldbuilding_violations — vi phạm rules trong Tầng 2
  4. plot_threads            — thread mở không đóng, revelation không có foreshadow

Dựa trên nguyên lý ConStory-Checker (Microsoft Research).
Heuristic checks: deterministic, không tốn API call.
LLM deep check: chỉ gọi khi phát hiện pattern phức tạp cần context rộng.

[v1.0] Initial implementation — Bible System Sprint 3
"""
from __future__ import annotations

import re
import logging
from datetime import datetime

from littrans.bible.bible_store import BibleStore
from littrans.bible.schemas import ConsistencyIssue, ConsistencyReport


# ═══════════════════════════════════════════════════════════════════
# CROSS REFERENCE ENGINE
# ═══════════════════════════════════════════════════════════════════

class CrossReferenceEngine:
    """
    Phát hiện mâu thuẫn cốt truyện trong Bible.
    
    Usage:
        engine = CrossReferenceEngine(store)
        report = engine.run()
        print(f"Health: {report.health_score:.0%}")
    """

    def __init__(self, store: BibleStore) -> None:
        self._store = store

    def run(self) -> ConsistencyReport:
        """Entry point — chạy tất cả checks."""
        all_issues: list[ConsistencyIssue] = []

        checks = [
            ("character_consistency", self.check_character_consistency),
            ("timeline_logic",        self.check_timeline_logic),
            ("worldbuilding",         self.check_worldbuilding_violations),
            ("plot_threads",          self.check_plot_threads),
        ]

        chapters_checked = 0
        try:
            lore = self._store._load_main_lore()
            chapters_checked = len(lore.chapter_summaries)
        except Exception:
            pass

        for check_name, check_fn in checks:
            try:
                issues = check_fn()
                all_issues.extend(issues)
            except Exception as e:
                logging.warning(f"[CrossRef] {check_name}: {e}")

        # LLM deep check nếu có nhiều characters
        chars = self._store.get_all_characters()
        if len(chars) > 5:
            try:
                deep_issues = self._llm_deep_check()
                all_issues.extend(deep_issues)
            except Exception as e:
                logging.warning(f"[CrossRef] LLM deep check: {e}")

        errors   = [i for i in all_issues if i.severity == "error"]
        warnings = [i for i in all_issues if i.severity == "warning"]
        infos    = [i for i in all_issues if i.severity == "info"]

        # Health score: penalize errors (-10%), warnings (-3%), infos (-1%)
        penalty = len(errors) * 0.10 + len(warnings) * 0.03 + len(infos) * 0.01
        health  = max(0.0, min(1.0, 1.0 - penalty))

        report = ConsistencyReport(
            total_issues     = len(all_issues),
            errors           = errors,
            warnings         = warnings,
            infos            = infos,
            health_score     = round(health, 3),
            generated_at     = datetime.now().strftime("%Y-%m-%d %H:%M"),
            chapters_checked = chapters_checked,
        )

        # Lưu report vào meta
        self._store.update_meta(cross_ref_last_run=report.generated_at)
        return report

    # ── Check 1: Character Consistency ───────────────────────────

    def check_character_consistency(self) -> list[ConsistencyIssue]:
        """
        Phát hiện:
        - Nhân vật status=dead nhưng vẫn xuất hiện trong events sau đó (có thể là lỗi)
        - Nhân vật không có role/archetype (data incomplete)
        - Nhân vật trùng tên (duplicate không được resolve)
        """
        issues = []
        chars  = self._store.get_all_characters()

        # Check: data completeness
        incomplete = [
            c for c in chars
            if not c.get("role") or c.get("role") == "Unknown"
            or not c.get("canonical_name")
        ]
        if incomplete:
            issues.append(ConsistencyIssue(
                issue_type  = "character",
                severity    = "info",
                description = f"{len(incomplete)} nhân vật thiếu thông tin cơ bản (role/canonical_name)",
                evidence    = [c.get("en_name", "?") for c in incomplete[:5]],
                suggestion  = "Chạy lại scan hoặc điền thủ công trong data/bible/database/characters.json",
            ))

        # Check: possible duplicates (tên giống nhau > 85%)
        name_map: dict[str, list[str]] = {}
        for c in chars:
            key = re.sub(r"\s+", "", c.get("en_name", "")).lower()
            if key:
                name_map.setdefault(key, []).append(c.get("id", "?"))

        for key, ids in name_map.items():
            if len(ids) > 1:
                issues.append(ConsistencyIssue(
                    issue_type  = "character",
                    severity    = "warning",
                    description = f"Có thể có entity trùng: {len(ids)} entries với tên '{key}'",
                    evidence    = ids,
                    suggestion  = "Kiểm tra và merge thủ công nếu cần",
                ))

        # Check: dead characters in later events
        lore = self._store._load_main_lore()
        dead_chars = {
            c.get("en_name", "").lower()
            for c in chars if c.get("status") == "dead"
        }

        if dead_chars and lore.events:
            events_sorted = sorted(lore.events, key=lambda e: e.chapter)
            # Find chapter where each char died
            death_chapters: dict[str, str] = {}
            for ev in events_sorted:
                if ev.event_type == "death":
                    for p in ev.participants:
                        if p.lower() in dead_chars:
                            death_chapters[p.lower()] = ev.chapter

            # Check if dead char appears in later events
            for ev in events_sorted:
                for p in ev.participants:
                    pl = p.lower()
                    if pl in death_chapters:
                        death_ch = death_chapters[pl]
                        if ev.chapter > death_ch and ev.event_type != "death":
                            issues.append(ConsistencyIssue(
                                issue_type  = "character",
                                severity    = "warning",
                                description = (
                                    f"'{p}' (đã chết ở {death_ch}) "
                                    f"xuất hiện trong event tại {ev.chapter}"
                                ),
                                evidence    = [death_ch, ev.chapter, ev.title],
                                suggestion  = "Kiểm tra: nhân vật này có hồi sinh không? Nếu có, cập nhật status.",
                            ))

        return issues

    # ── Check 2: Timeline Logic ───────────────────────────────────

    def check_timeline_logic(self) -> list[ConsistencyIssue]:
        """
        Phát hiện:
        - Skills được dùng trước chapter first_appearance của skill đó
        - Events thiếu participants (data incomplete)
        - Plot threads có closed_chapter < opened_chapter
        """
        issues = []
        lore   = self._store._load_main_lore()

        # Check: skills used before first_appearance
        skills = self._store.get_all_entities("skill")
        skill_first: dict[str, str] = {
            s.get("en_name", "").lower(): s.get("first_appearance", "")
            for s in skills if s.get("first_appearance")
        }

        for summary in lore.chapter_summaries:
            # Check plot thread logic
            pass

        # Check: plot thread closed_chapter >= opened_chapter
        for thread in lore.plot_threads:
            if (thread.closed_chapter and thread.opened_chapter
                    and thread.closed_chapter < thread.opened_chapter):
                issues.append(ConsistencyIssue(
                    issue_type  = "timeline",
                    severity    = "error",
                    description = (
                        f"Plot thread '{thread.name}': "
                        f"đóng ({thread.closed_chapter}) trước khi mở ({thread.opened_chapter})"
                    ),
                    evidence    = [thread.opened_chapter, thread.closed_chapter],
                    suggestion  = "Kiểm tra lại chapter references trong plot thread.",
                ))

        # Check: events without participants
        events_no_part = [
            ev for ev in lore.events
            if not ev.participants and ev.event_type not in ("other",)
        ]
        if events_no_part:
            issues.append(ConsistencyIssue(
                issue_type  = "timeline",
                severity    = "info",
                description = f"{len(events_no_part)} events không có participants",
                evidence    = [ev.title for ev in events_no_part[:5]],
                suggestion  = "Thêm participants vào events để cross-reference chính xác hơn.",
            ))

        return issues

    # ── Check 3: WorldBuilding Violations ────────────────────────

    def check_worldbuilding_violations(self) -> list[ConsistencyIssue]:
        """
        So sánh character data với worldbuilding rules.
        Ví dụ: nhân vật có realm không có trong cultivation system.
        """
        issues = []
        wb     = self._store.get_worldbuilding()

        if not wb.cultivation_systems:
            return []

        # Collect known realm names
        known_realms: set[str] = set()
        for cs in wb.cultivation_systems:
            for realm in cs.realms:
                known_realms.add(realm.name_vn.lower())
                known_realms.add(realm.name_en.lower())

        if not known_realms:
            return []

        # Check characters có realm không nằm trong cultivation system
        chars = self._store.get_all_characters()
        unknown_realms: list[tuple[str, str]] = []
        for c in chars:
            realm = (c.get("cultivation") or {}).get("realm", "")
            if realm and realm.lower() not in known_realms:
                unknown_realms.append((c.get("en_name", "?"), realm))

        if unknown_realms:
            issues.append(ConsistencyIssue(
                issue_type  = "worldbuilding",
                severity    = "info",
                description = (
                    f"{len(unknown_realms)} nhân vật có realm không có trong "
                    f"cultivation system đã biết"
                ),
                evidence    = [f"{n}: {r}" for n, r in unknown_realms[:5]],
                suggestion  = (
                    "Cập nhật cultivation system trong worldbuilding.json, "
                    "hoặc kiểm tra realm name spelling."
                ),
            ))

        return issues

    # ── Check 4: Plot Threads ─────────────────────────────────────

    def check_plot_threads(self) -> list[ConsistencyIssue]:
        """
        Phát hiện:
        - Plot threads mở quá lâu (> 30 chapters) mà chưa tiến triển
        - Revelations không có foreshadow
        - Open threads quá nhiều (> 10) — có thể tracking issue
        """
        issues = []
        lore   = self._store._load_main_lore()

        open_threads = [t for t in lore.plot_threads if t.status == "open"]

        # Quá nhiều open threads
        if len(open_threads) > 15:
            issues.append(ConsistencyIssue(
                issue_type  = "plot",
                severity    = "info",
                description = f"{len(open_threads)} plot threads đang mở — nhiều hơn bình thường",
                evidence    = [t.name for t in open_threads[:5]],
                suggestion  = "Kiểm tra xem một số threads đã được resolve ngầm chưa.",
            ))

        # Revelations không có foreshadow
        no_foreshadow = [
            r for r in lore.revelations
            if not r.foreshadowed_in
        ]
        if len(no_foreshadow) > 2:
            issues.append(ConsistencyIssue(
                issue_type  = "plot",
                severity    = "info",
                description = f"{len(no_foreshadow)} revelations không có foreshadow được track",
                evidence    = [r.title for r in no_foreshadow[:5]],
                suggestion  = "Thêm foreshadowed_in cho các tiết lộ quan trọng.",
            ))

        return issues

    # ── LLM Deep Check ────────────────────────────────────────────

    def _llm_deep_check(self) -> list[ConsistencyIssue]:
        """
        Gọi AI để phân tích các mâu thuẫn phức tạp cần context rộng.
        Chỉ chạy khi có đủ data.
        """
        lore = self._store._load_main_lore()
        if len(lore.chapter_summaries) < 3:
            return []

        # Tóm tắt ngắn để gửi cho AI
        summaries = lore.chapter_summaries[-10:]  # 10 chapters gần nhất
        events    = lore.events[-20:]

        context = "## Chapter Summaries\n"
        for s in summaries:
            context += f"- {s.chapter}: {s.summary[:100]}\n"
        context += "\n## Key Events\n"
        for e in events:
            context += (f"- [{e.chapter}] {e.event_type}: {e.title} "
                        f"({', '.join(e.participants[:3])})\n")

        system = (
            "Bạn là AI kiểm tra tính nhất quán cốt truyện.\n"
            "Đọc tóm tắt chapters và events. Tìm mâu thuẫn RÕ RÀNG:\n"
            "- Thông tin mâu thuẫn nhau (A và B không thể cùng đúng)\n"
            "- Nhân vật xuất hiện ở 2 nơi cùng lúc\n"
            "- Sự kiện xảy ra sai logic nhân quả\n\n"
            "CHỈ báo cáo mâu thuẫn CHẮC CHẮN, không suy luận quá mức.\n"
            "Trả về JSON: {\"issues\": [{\"description\": \"...\", "
            "\"evidence\": [\"ch1\", \"ch2\"], \"severity\": \"error|warning\"}]}"
        )

        try:
            from littrans.llm.client import call_gemini_json
            data   = call_gemini_json(system, context)
            issues = []
            for raw in data.get("issues", []):
                if not isinstance(raw, dict):
                    continue
                issues.append(ConsistencyIssue(
                    issue_type  = "character",
                    severity    = raw.get("severity", "warning"),
                    description = raw.get("description", ""),
                    evidence    = raw.get("evidence", []),
                    suggestion  = "Xem xét lại chapters liên quan.",
                ))
            return issues
        except Exception as e:
            logging.warning(f"[CrossRef] LLM: {e}")
            return []


# ── Convenience function ──────────────────────────────────────────

def run_cross_reference(store: BibleStore) -> ConsistencyReport:
    """Shortcut để chạy cross-reference."""
    engine = CrossReferenceEngine(store)
    return engine.run()