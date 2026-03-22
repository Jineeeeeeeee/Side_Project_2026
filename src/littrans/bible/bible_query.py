"""
src/littrans/bible/bible_query.py — BibleQuery: truy vấn Bible.

2 modes:
  Deterministic: search, get_entity, timeline, relationships — không LLM
  LLM Q&A: ask() — complex questions cần context rộng

[v1.0] Initial implementation — Bible System Sprint 3
"""
from __future__ import annotations

import logging
from littrans.bible.bible_store import BibleStore


class BibleQuery:
    """
    Truy vấn Bible — deterministic + optional LLM Q&A.
    
    Usage:
        q = BibleQuery(store)
        q.search("Arthur")
        q.get_character_timeline("Klein")
        q.ask("Ai là kẻ thù chính của Arthur?")
    """

    def __init__(self, store: BibleStore) -> None:
        self._store = store

    def search(self, query: str, entity_type: str | None = None) -> list[dict]:
        """Full-text search trong index."""
        return self._store.search_entities(query, entity_type)

    def get_entity(self, name: str, entity_type: str | None = None) -> dict | None:
        """Exact + fuzzy lookup."""
        return self._store.get_entity(name, entity_type)

    def get_character_timeline(self, char_name: str) -> list[dict]:
        """Tất cả events có nhân vật này, sắp xếp theo chapter."""
        lore   = self._store._load_main_lore()
        name_l = char_name.lower()
        events = [
            {
                "chapter"    : ev.chapter,
                "type"       : ev.event_type,
                "title"      : ev.title,
                "description": ev.description,
                "consequence": ev.consequence,
            }
            for ev in lore.events
            if any(p.lower() == name_l or name_l in p.lower()
                   for p in ev.participants)
        ]
        return sorted(events, key=lambda e: e["chapter"])

    def get_chapter_entities(self, chapter: str) -> dict:
        """Entities xuất hiện trong chương — từ chapter summary + scan output."""
        lore = self._store._load_main_lore()
        # Lấy summary cho chapter này
        summary = next(
            (s for s in lore.chapter_summaries if s.chapter == chapter), None
        )
        result = {"chapter": chapter, "summary": None, "entities": {}}
        if summary:
            result["summary"] = {
                "text"       : summary.summary,
                "tone"       : summary.tone,
                "key_events" : summary.key_events,
            }

        # Entities từ events trong chapter
        chars_mentioned: set[str] = set()
        for ev in lore.events:
            if ev.chapter == chapter:
                chars_mentioned.update(ev.participants)

        if chars_mentioned:
            result["entities"]["characters"] = [
                self.get_entity(name, "character")
                for name in chars_mentioned
                if self.get_entity(name, "character")
            ]

        return result

    def get_relationship_arc(self, char_a: str, char_b: str) -> list[dict]:
        """Lịch sử quan hệ giữa 2 nhân vật — từ events."""
        lore   = self._store._load_main_lore()
        a_l, b_l = char_a.lower(), char_b.lower()

        arc = []
        for ev in sorted(lore.events, key=lambda e: e.chapter):
            parts_l = [p.lower() for p in ev.participants]
            if a_l in parts_l and b_l in parts_l:
                arc.append({
                    "chapter"    : ev.chapter,
                    "type"       : ev.event_type,
                    "title"      : ev.title,
                    "consequence": ev.consequence,
                })
        return arc

    def get_open_plot_threads(self) -> list[dict]:
        """Plot threads đang mở."""
        return [
            {"name": t.name, "opened": t.opened_chapter, "summary": t.summary}
            for t in self._store.get_plot_threads("open")
        ]

    def ask(self, question: str) -> str:
        """
        Complex Q&A — gọi LLM với Bible context.
        Inject relevant entities + recent lore vào prompt.
        """
        # Build context
        recent    = self._store.get_recent_lore(5)
        threads   = self._store.get_plot_threads("open")
        all_chars = self._store.get_all_entities("character")

        context = "## Nhân vật\n"
        for c in all_chars[:20]:
            context += (f"- {c.get('en_name','')} ({c.get('canonical_name','')}): "
                        f"{c.get('description','')} [{c.get('status','')}]\n")

        if recent:
            context += "\n## Tóm tắt gần nhất\n"
            for s in recent:
                context += f"- {s.chapter}: {s.summary}\n"

        if threads:
            context += "\n## Plot threads đang mở\n"
            for t in threads[:5]:
                context += f"- {t.name}: {t.summary}\n"

        system = (
            "Bạn là AI chuyên gia về nội dung truyện LitRPG / Tu Tiên này.\n"
            "Dựa trên Bible được cung cấp, trả lời câu hỏi chính xác và ngắn gọn.\n"
            "Nếu không có đủ thông tin, nói rõ điều đó.\n\n"
            f"## BIBLE CONTEXT\n{context}"
        )

        try:
            from littrans.llm.client import call_gemini_text
            return call_gemini_text(system, question)
        except Exception as e:
            logging.error(f"[BibleQuery.ask] {e}")
            return f"❌ Lỗi: {e}"