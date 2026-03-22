"""
src/littrans/bible/bible_exporter.py — BibleExporter: xuất Bible sang nhiều định dạng.

Formats:
  markdown  → readable report với headers, tables
  json      → raw full Bible JSON
  characters_sheet → character reference sheet
  timeline  → chronological event list

[v1.0] Initial implementation — Bible System Sprint 3
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from littrans.bible.bible_store import BibleStore
from littrans.utils.io_utils import atomic_write


class BibleExporter:
    """
    Xuất Bible sang file.
    
    Usage:
        exporter = BibleExporter(store)
        exporter.export_markdown(Path("Reports/bible.md"))
        exporter.export_json(Path("Reports/bible.json"))
    """

    def __init__(self, store: BibleStore) -> None:
        self._store = store

    # ── Markdown ──────────────────────────────────────────────────

    def export_markdown(self, output_path: Path, scope: str = "full") -> None:
        """Xuất sang Markdown — readable report."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        meta  = self._store.load_meta()
        lines = [
            "# Bible Report",
            f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
            f"Chapters scanned: {meta.scanned_chapters}/{meta.total_chapters}",
            f"> Health: see cross-reference report",
            "",
        ]

        if scope in ("full", "characters"):
            lines += self._md_characters()
        if scope in ("full", "worldbuilding"):
            lines += self._md_worldbuilding()
        if scope in ("full", "lore"):
            lines += self._md_lore()

        atomic_write(output_path, "\n".join(lines))
        print(f"  ✅ Xuất Markdown: {output_path}")

    def _md_characters(self) -> list[str]:
        chars = self._store.get_all_entities("character")
        lines = ["---", "## Characters\n"]
        for c in sorted(chars, key=lambda x: x.get("role", "z")):
            lines += [
                f"### {c.get('canonical_name', c.get('en_name', '?'))} "
                f"`[{c.get('role','?')}]`",
                f"**EN:** {c.get('en_name','')} · "
                f"**Status:** {c.get('status','')} · "
                f"**Cấp:** {(c.get('cultivation') or {}).get('realm','')}",
                f"**Faction:** {c.get('faction_id','')} · "
                f"**Archetype:** {c.get('archetype','')}",
            ]
            if c.get("personality_summary"):
                lines.append(f"\n> {c['personality_summary']}")
            if c.get("current_goal"):
                lines.append(f"\n**Goal:** {c['current_goal']}")
            lines.append("")
        return lines

    def _md_worldbuilding(self) -> list[str]:
        wb    = self._store.get_worldbuilding()
        lines = ["---", "## WorldBuilding\n"]

        if wb.cultivation_systems:
            lines.append("### Cultivation Systems\n")
            for cs in wb.cultivation_systems:
                lines.append(f"**{cs.name}** ({cs.pathway_type})")
                for realm in cs.realms:
                    lines.append(f"  {realm.order}. {realm.name_vn} ({realm.name_en})")
                lines.append("")

        if wb.confirmed_rules:
            lines.append("### Confirmed Rules\n")
            for rule in wb.confirmed_rules:
                lines.append(f"- [{rule.source_chapter}] {rule.description}")
            lines.append("")

        return lines

    def _md_lore(self) -> list[str]:
        lore  = self._store._load_main_lore()
        lines = ["---", "## Main Lore\n"]

        # Plot threads
        if lore.plot_threads:
            lines.append("### Plot Threads\n")
            open_t   = [t for t in lore.plot_threads if t.status == "open"]
            closed_t = [t for t in lore.plot_threads if t.status == "closed"]
            if open_t:
                lines.append("**🟢 Đang mở:**")
                for t in open_t:
                    lines.append(f"- **{t.name}** (từ {t.opened_chapter}): {t.summary}")
            if closed_t:
                lines.append("\n**✅ Đã đóng:**")
                for t in closed_t:
                    lines.append(f"- **{t.name}** ({t.opened_chapter}→{t.closed_chapter}): {t.resolution}")
            lines.append("")

        # Chapter summaries
        if lore.chapter_summaries:
            lines.append("### Chapter Summaries\n")
            for s in lore.chapter_summaries[-20:]:   # 20 gần nhất
                lines.append(f"**{s.chapter}** [{s.tone}]: {s.summary}")
            lines.append("")

        return lines

    # ── JSON ──────────────────────────────────────────────────────

    def export_json(self, output_path: Path) -> None:
        """Xuất raw JSON — full Bible."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._store.export_all_json(output_path)
        print(f"  ✅ Xuất JSON: {output_path}")

    # ── Characters Sheet ──────────────────────────────────────────

    def export_characters_sheet(self, output_path: Path) -> None:
        """Character reference sheet — compact."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        chars = self._store.get_all_entities("character")
        lines = [
            "# Character Reference Sheet",
            f"> {len(chars)} nhân vật · {datetime.now().strftime('%Y-%m-%d')}",
            "",
            f"| Tên VN | Tên EN | Role | Status | Cảnh giới | Tự xưng | Phe |",
            f"|---|---|---|---|---|---|---|",
        ]
        for c in sorted(chars, key=lambda x: x.get("canonical_name", "")):
            realm = (c.get("cultivation") or {}).get("realm", "—")
            lines.append(
                f"| {c.get('canonical_name','?')} "
                f"| {c.get('en_name','?')} "
                f"| {c.get('role','?')} "
                f"| {c.get('status','?')} "
                f"| {realm} "
                f"| {c.get('pronoun_self','—')} "
                f"| {c.get('faction_id','—')} |"
            )
        atomic_write(output_path, "\n".join(lines))
        print(f"  ✅ Xuất character sheet: {output_path}")

    # ── Timeline ──────────────────────────────────────────────────

    def export_timeline(self, output_path: Path) -> None:
        """Timeline document — sắp xếp theo chapter."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lore   = self._store._load_main_lore()
        events = sorted(lore.events, key=lambda e: e.chapter)

        lines = [
            "# Story Timeline",
            f"> {len(events)} events · {datetime.now().strftime('%Y-%m-%d')}",
            "",
        ]

        last_chapter = ""
        for ev in events:
            if ev.chapter != last_chapter:
                lines += ["", f"## {ev.chapter}", ""]
                last_chapter = ev.chapter
            parts_str = ", ".join(ev.participants[:4]) if ev.participants else "—"
            icon = {
                "battle"     : "⚔️",
                "revelation" : "💡",
                "death"      : "💀",
                "alliance"   : "🤝",
                "betrayal"   : "🗡️",
                "breakthrough": "⬆️",
            }.get(ev.event_type, "📌")
            lines.append(f"{icon} **{ev.title}** [{ev.event_type}]")
            lines.append(f"   {ev.description}")
            if parts_str != "—":
                lines.append(f"   *Tham gia: {parts_str}*")
            if ev.consequence:
                lines.append(f"   → {ev.consequence}")
            lines.append("")

        atomic_write(output_path, "\n".join(lines))
        print(f"  ✅ Xuất timeline: {output_path}")

    # ── Consistency Report ────────────────────────────────────────

    def export_consistency_report(
        self, output_path: Path, report
    ) -> None:
        """Export ConsistencyReport sang Markdown."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Bible Consistency Report",
            f"> Generated: {report.generated_at} | "
            f"Health: {report.health_score:.0%} | "
            f"Chapters: {report.chapters_checked}",
            "",
            f"**Tổng:** {report.total_issues} issues "
            f"({len(report.errors)} errors · "
            f"{len(report.warnings)} warnings · "
            f"{len(report.infos)} infos)",
            "",
        ]

        for severity, items, icon in [
            ("Errors",   report.errors,   "🔴"),
            ("Warnings", report.warnings, "🟡"),
            ("Info",     report.infos,    "🔵"),
        ]:
            if items:
                lines += [f"## {icon} {severity}\n"]
                for issue in items:
                    lines += [
                        f"### [{issue.issue_type}] {issue.description}",
                        f"**Evidence:** {', '.join(issue.evidence[:5])}",
                        f"**Suggestion:** {issue.suggestion}",
                        "",
                    ]

        atomic_write(output_path, "\n".join(lines))
        print(f"  ✅ Xuất consistency report: {output_path}")