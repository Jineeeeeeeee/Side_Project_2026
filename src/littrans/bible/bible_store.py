"""
src/littrans/bible/bible_store.py — BibleStore: đọc/ghi 3 tầng Bible.

Structure trên disk:
  data/bible/
    meta.json                  ← BibleMeta
    database/
      characters.json          ← {entities: [BibleCharacter, ...]}
      items.json
      locations.json
      skills.json
      factions.json
      concepts.json
      index.json               ← {name_lower: IndexEntry}
    worldbuilding.json         ← BibleWorldBuilding
    main_lore.json             ← BibleMainLore
    staging/
      stage_chapter_001.json   ← ScanOutput

Thread-safe:
  - _db_lock  : Database (r/w)
  - _wb_lock  : WorldBuilding
  - _lore_lock: MainLore
  - _meta_lock: Meta
  - Staging: tên file unique per chapter → không cần lock

[v1.0] Initial implementation — Bible System Sprint 1
"""
from __future__ import annotations

import re
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from littrans.bible.schemas import (
    BibleCharacter, BibleItem, BibleLocation, BibleSkill,
    BibleFaction, BibleConcept, BibleWorldBuilding, BibleMainLore,
    BibleMeta, ScanOutput, IndexEntry, DATABASE_FILES, ENTITY_MODELS,
    BibleChapterSummary, BibleEvent, BiblePlotThread, BibleRevelation,
    ConsistencyReport,
)
from littrans.utils.io_utils import load_json, save_json, atomic_write


# ═══════════════════════════════════════════════════════════════════
# ID GENERATION
# ═══════════════════════════════════════════════════════════════════

_PREFIXES = {
    "character" : "char",
    "item"      : "item",
    "location"  : "loc",
    "skill"     : "skl",
    "faction"   : "fac",
    "concept"   : "con",
    "event"     : "evt",
    "thread"    : "thr",
    "revelation": "rev",
}


def _make_id(entity_type: str, counter: int) -> str:
    prefix = _PREFIXES.get(entity_type, entity_type[:3])
    return f"{prefix}_{counter:04d}"


# ═══════════════════════════════════════════════════════════════════
# BIBLE STORE
# ═══════════════════════════════════════════════════════════════════

class BibleStore:
    """
    Đọc/ghi toàn bộ 3 tầng Bible. Thread-safe, atomic write.
    
    Usage:
        store = BibleStore(Path("data/bible"))
        char = store.get_character("Lý Thanh Vân")
        store.upsert_character(char_dict)
    """

    def __init__(self, bible_dir: Path) -> None:
        self._dir        = bible_dir
        self._db_dir     = bible_dir / "database"
        self._staging_dir = bible_dir / "staging"

        # Locks per tầng
        self._db_lock    = threading.Lock()
        self._wb_lock    = threading.Lock()
        self._lore_lock  = threading.Lock()
        self._meta_lock  = threading.Lock()
        self._idx_lock   = threading.Lock()

        # Ensure directories
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

        # ID counters — loaded from meta
        self._counters: dict[str, int] = {}

    # ──────────────────────────────────────────────────────────────
    # META
    # ──────────────────────────────────────────────────────────────

    def _meta_path(self) -> Path:
        return self._dir / "meta.json"

    def load_meta(self) -> BibleMeta:
        with self._meta_lock:
            raw = load_json(self._meta_path())
            return BibleMeta.model_validate(raw) if raw else BibleMeta()

    def save_meta(self, meta: BibleMeta) -> None:
        with self._meta_lock:
            atomic_write(self._meta_path(), meta.model_dump_json(indent=2))

    def update_meta(self, **kwargs) -> None:
        meta = self.load_meta()
        for k, v in kwargs.items():
            if hasattr(meta, k):
                setattr(meta, k, v)
        meta.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.save_meta(meta)

    def get_scan_progress(self) -> dict[str, Any]:
        meta = self.load_meta()
        total = meta.total_chapters or 1
        return {
            "total"       : meta.total_chapters,
            "scanned"     : meta.scanned_chapters,
            "pct"         : round(meta.scanned_chapters / total * 100, 1),
            "last_chapter": meta.last_scanned_chapter,
            "depth"       : meta.scan_depth_used,
            "cross_ref"   : meta.cross_ref_last_run,
        }

    def is_chapter_scanned(self, chapter: str) -> bool:
        """Kiểm tra nhanh qua staging + meta — không load toàn bộ DB."""
        # Staging file sẽ bị xóa sau consolidation
        # → kiểm tra qua main_lore chapter_summaries
        lore = self._load_main_lore()
        scanned = {s.chapter for s in lore.chapter_summaries}
        return chapter in scanned

    def mark_chapter_scanned(self, chapter: str) -> None:
        meta = self.load_meta()
        if chapter not in (meta.last_scanned_chapter or ""):
            meta.scanned_chapters += 1
            meta.last_scanned_chapter = chapter
            meta.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.save_meta(meta)

    def get_stats(self) -> dict[str, Any]:
        meta  = self.load_meta()
        index = self._load_index()
        type_counts: dict[str, int] = {}
        for entry in index.values():
            t = entry.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "meta"       : meta.model_dump(),
            "by_type"    : type_counts,
            "staging"    : len(list(self._staging_dir.glob("*.json"))),
            "lore_chapters": len(self._load_main_lore().chapter_summaries),
        }

    # ──────────────────────────────────────────────────────────────
    # DATABASE — INDEX
    # ──────────────────────────────────────────────────────────────

    def _index_path(self) -> Path:
        return self._db_dir / "index.json"

    def _load_index(self) -> dict[str, dict]:
        raw = load_json(self._index_path())
        return raw if isinstance(raw, dict) else {}

    def _save_index(self, index: dict[str, dict]) -> None:
        save_json(self._index_path(), index)

    def _index_add(self, entity_id: str, entity_type: str,
                   canonical_name: str, en_name: str) -> None:
        """Thêm entry vào index — gọi sau khi upsert entity."""
        with self._idx_lock:
            index = self._load_index()
            key = (canonical_name or en_name).lower().strip()
            if key:
                index[key] = {"id": entity_id, "type": entity_type,
                               "name": canonical_name, "en": en_name}
            # Thêm cả en_name làm key nếu khác
            en_key = en_name.lower().strip()
            if en_key and en_key != key:
                index[en_key] = {"id": entity_id, "type": entity_type,
                                  "name": canonical_name, "en": en_name}
            self._save_index(index)

    def _index_lookup(self, name: str) -> dict | None:
        """Tìm entity trong index theo name. Trả về {id, type, name, en} hoặc None."""
        index = self._load_index()
        key   = name.lower().strip()
        if key in index:
            return index[key]
        # Fuzzy: partial match
        for k, v in index.items():
            if key in k or k in key:
                if len(key) >= 3 and abs(len(key) - len(k)) <= 4:
                    return v
        return None

    # ──────────────────────────────────────────────────────────────
    # DATABASE — ENTITIES
    # ──────────────────────────────────────────────────────────────

    def _db_path(self, entity_type: str) -> Path:
        plural = entity_type + "s" if not entity_type.endswith("s") else entity_type
        return self._db_dir / f"{plural}.json"

    def _load_db_file(self, entity_type: str) -> list[dict]:
        raw = load_json(self._db_path(entity_type))
        if not raw:
            return []
        return raw.get("entities", []) if isinstance(raw, dict) else []

    def _save_db_file(self, entity_type: str, entities: list[dict]) -> None:
        save_json(self._db_path(entity_type), {"entities": entities})

    def _next_id(self, entity_type: str) -> str:
        with self._db_lock:
            entities = self._load_db_file(entity_type)
            counter  = len(entities) + 1
            # Ensure unique
            existing_ids = {e.get("id", "") for e in entities}
            candidate    = _make_id(entity_type, counter)
            while candidate in existing_ids:
                counter   += 1
                candidate  = _make_id(entity_type, counter)
            return candidate

    def get_entity(self, name: str, entity_type: str | None = None) -> dict | None:
        """Tìm entity theo tên (exact + fuzzy). entity_type=None → tìm khắp nơi."""
        entry = self._index_lookup(name)
        if not entry:
            return None
        if entity_type and entry["type"] != entity_type:
            return None

        with self._db_lock:
            entities = self._load_db_file(entry["type"])
            for e in entities:
                if e.get("id") == entry["id"]:
                    return e
        return None

    def get_entity_by_id(self, entity_id: str) -> dict | None:
        """Tìm entity theo ID chính xác."""
        # Xác định type từ prefix
        for prefix, t in [
            ("char", "character"), ("item", "item"), ("loc", "location"),
            ("skl", "skill"), ("fac", "faction"), ("con", "concept"),
        ]:
            if entity_id.startswith(prefix + "_"):
                with self._db_lock:
                    for e in self._load_db_file(t):
                        if e.get("id") == entity_id:
                            return e
        return None

    def upsert_entity(self, entity_type: str, data: dict) -> str:
        """
        Insert hoặc update entity.
        Trả về entity_id đã dùng.
        
        Logic:
          1. Nếu có id trong data → update
          2. Nếu không → tìm qua index (tên)
          3. Nếu không tìm được → insert mới
        """
        if entity_type not in ENTITY_MODELS:
            raise ValueError(f"entity_type không hợp lệ: {entity_type}")

        with self._db_lock:
            entities = self._load_db_file(entity_type)
            entity_id = data.get("id", "")

            if not entity_id:
                # Tìm theo tên
                existing = self._index_lookup(
                    data.get("canonical_name", "") or data.get("en_name", "")
                )
                if existing and existing["type"] == entity_type:
                    entity_id = existing["id"]

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            data["last_updated"] = now

            if entity_id:
                # Update
                for i, e in enumerate(entities):
                    if e.get("id") == entity_id:
                        merged = self._merge_entity(e, data)
                        merged["id"] = entity_id
                        entities[i] = merged
                        self._save_db_file(entity_type, entities)
                        self._index_add(
                            entity_id, entity_type,
                            merged.get("canonical_name", ""),
                            merged.get("en_name", ""),
                        )
                        return entity_id
                # ID không tìm thấy trong file → insert với ID đó
                data["id"] = entity_id
            else:
                # Insert mới
                entity_id = _make_id(entity_type, len(entities) + 1)
                existing_ids = {e.get("id") for e in entities}
                n = len(entities) + 1
                while entity_id in existing_ids:
                    n += 1
                    entity_id = _make_id(entity_type, n)
                data["id"] = entity_id
                data.setdefault("type", entity_type)

            entities.append(data)
            self._save_db_file(entity_type, entities)
            self._index_add(
                entity_id, entity_type,
                data.get("canonical_name", ""),
                data.get("en_name", ""),
            )

            # Update meta counts
            meta = self.load_meta()
            counts = meta.entity_counts
            counts[entity_type] = len(entities)
            meta.entity_counts = counts
            meta.last_updated  = now
            self.save_meta(meta)

            return entity_id

    def _merge_entity(self, existing: dict, new_data: dict) -> dict:
        """
        Merge new_data vào existing entity.
        Quy tắc:
          - Trường rỗng trong existing → dùng new_data
          - List → union, không trùng lặp
          - Số: max (level, count)
          - Trường khác → new_data ghi đè nếu không rỗng
        """
        merged = dict(existing)

        LIST_FIELDS = ("aliases", "skill_ids", "member_ids", "effects",
                       "notable_features", "evolution_chain", "tags",
                       "speech_quirks", "key_moments", "secrets",
                       "relationships", "allied_faction_ids", "enemy_faction_ids",
                       "history_notes", "economy_notes", "cosmology_notes")

        for key, new_val in new_data.items():
            if key in ("id", "type"):
                continue
            old_val = merged.get(key)

            if isinstance(new_val, list) and key in LIST_FIELDS:
                # Union list — tránh trùng
                old_list = old_val if isinstance(old_val, list) else []
                for item in new_val:
                    if item and item not in old_list:
                        old_list.append(item)
                merged[key] = old_list

            elif isinstance(new_val, str):
                # Ghi đè nếu new không rỗng
                if new_val.strip():
                    merged[key] = new_val

            elif isinstance(new_val, dict) and isinstance(old_val, dict):
                # Merge dict đệ quy 1 cấp
                merged[key] = {**old_val, **{k: v for k, v in new_val.items() if v}}

            elif isinstance(new_val, int) and key == "chapter_count":
                merged[key] = max(old_val or 0, new_val)

            elif new_val is not None:
                merged[key] = new_val

        return merged

    # ── Convenience methods per type ──────────────────────────────

    def get_character(self, name: str) -> dict | None:
        return self.get_entity(name, "character")

    def upsert_character(self, data: dict) -> str:
        return self.upsert_entity("character", data)

    def get_all_entities(self, entity_type: str) -> list[dict]:
        with self._db_lock:
            return list(self._load_db_file(entity_type))

    def get_all_characters(self) -> list[dict]:
        return self.get_all_entities("character")

    def get_entities_for_chapter(self, chapter_text: str) -> dict[str, list[dict]]:
        """
        Trả về {type: [entities]} cho các entity XUẤT HIỆN trong chapter_text.
        Dùng index để detect nhanh thay vì regex từng entity.
        """
        text_lower = chapter_text.lower()
        index      = self._load_index()
        matched_ids: dict[str, set] = {}   # {type: {ids}}

        for name_key, entry in index.items():
            if len(name_key) < 3:
                continue
            # Word-boundary check
            pattern = rf"(?<![a-zA-Z0-9_]){re.escape(name_key)}(?![a-zA-Z0-9_])"
            try:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    t = entry["type"]
                    matched_ids.setdefault(t, set()).add(entry["id"])
            except re.error:
                if name_key in text_lower:
                    t = entry["type"]
                    matched_ids.setdefault(t, set()).add(entry["id"])

        result: dict[str, list[dict]] = {}
        for entity_type, ids in matched_ids.items():
            with self._db_lock:
                all_e = self._load_db_file(entity_type)
            result[entity_type] = [e for e in all_e if e.get("id") in ids]

        return result

    def search_entities(self, query: str, entity_type: str | None = None) -> list[dict]:
        """Full-text search trong index + data."""
        query_lower = query.lower().strip()
        index       = self._load_index()
        found_ids: list[tuple[str, str]] = []  # [(type, id)]

        for name_key, entry in index.items():
            if query_lower in name_key or name_key in query_lower:
                t = entry["type"]
                if entity_type and t != entity_type:
                    continue
                found_ids.append((t, entry["id"]))

        results: list[dict] = []
        for t, eid in found_ids[:50]:  # cap at 50
            entity = self.get_entity_by_id(eid)
            if entity:
                results.append(entity)

        return results

    # ──────────────────────────────────────────────────────────────
    # TẦNG 2 — WORLDBUILDING
    # ──────────────────────────────────────────────────────────────

    def _wb_path(self) -> Path:
        return self._dir / "worldbuilding.json"

    def _load_worldbuilding(self) -> BibleWorldBuilding:
        raw = load_json(self._wb_path())
        return BibleWorldBuilding.model_validate(raw) if raw else BibleWorldBuilding()

    def get_worldbuilding(self) -> BibleWorldBuilding:
        with self._wb_lock:
            return self._load_worldbuilding()

    def update_worldbuilding(self, updates: dict[str, Any]) -> None:
        """
        Merge updates vào WorldBuilding.
        List fields → append (không trùng), string fields → ghi đè nếu không rỗng.
        """
        with self._wb_lock:
            wb  = self._load_worldbuilding()
            raw = wb.model_dump()

            for key, val in updates.items():
                if key not in raw:
                    continue
                if isinstance(val, list):
                    existing = raw.get(key, [])
                    if not isinstance(existing, list):
                        existing = []
                    # Serialize mới để so sánh
                    existing_strs = {json.dumps(e, ensure_ascii=False, sort_keys=True)
                                     for e in existing}
                    for item in val:
                        item_str = json.dumps(item, ensure_ascii=False, sort_keys=True)
                        if item_str not in existing_strs:
                            existing.append(item)
                            existing_strs.add(item_str)
                    raw[key] = existing
                elif isinstance(val, str) and val.strip():
                    raw[key] = val
                elif isinstance(val, dict):
                    raw[key] = {**(raw.get(key) or {}), **val}

            raw["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            new_wb = BibleWorldBuilding.model_validate(raw)
            atomic_write(self._wb_path(), new_wb.model_dump_json(indent=2))

    def get_relevant_worldbuilding(self, chapter_text: str) -> str:
        """
        Trả về block text worldbuilding liên quan đến chapter_text.
        Dùng trong Bible-aware prompt builder.
        """
        wb    = self.get_worldbuilding()
        lines = []

        # Cultivation systems có tên xuất hiện trong text
        for cs in wb.cultivation_systems:
            if cs.name and cs.name.lower() in chapter_text.lower():
                lines.append(f"**Hệ thống tu luyện: {cs.name}**")
                for realm in cs.realms[:6]:
                    lines.append(f"  {realm.order}. {realm.name_vn} ({realm.name_en})")

        # Rules
        relevant_rules = [
            r.description for r in wb.confirmed_rules
            if any(word in chapter_text.lower()
                   for word in r.description.lower().split()[:5])
        ]
        if relevant_rules[:3]:
            lines.append("\n**Quy luật thế giới liên quan:**")
            lines.extend(f"  - {r}" for r in relevant_rules[:3])

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────
    # TẦNG 3 — MAIN LORE
    # ──────────────────────────────────────────────────────────────

    def _lore_path(self) -> Path:
        return self._dir / "main_lore.json"

    def _load_main_lore(self) -> BibleMainLore:
        raw = load_json(self._lore_path())
        return BibleMainLore.model_validate(raw) if raw else BibleMainLore()

    def _save_main_lore(self, lore: BibleMainLore) -> None:
        atomic_write(self._lore_path(), lore.model_dump_json(indent=2))

    def append_chapter_summary(self, summary: BibleChapterSummary) -> None:
        with self._lore_lock:
            lore = self._load_main_lore()
            # Không append trùng
            existing_chapters = {s.chapter for s in lore.chapter_summaries}
            if summary.chapter not in existing_chapters:
                lore.chapter_summaries.append(summary)
                lore.last_chapter_scanned = summary.chapter
                self._save_main_lore(lore)

    def append_event(self, event: BibleEvent) -> str:
        with self._lore_lock:
            lore = self._load_main_lore()
            lore.event_counter += 1
            if not event.id:
                event.id = _make_id("event", lore.event_counter)
            lore.events.append(event)
            self._save_main_lore(lore)
            return event.id

    def append_plot_thread(self, thread: BiblePlotThread) -> str:
        with self._lore_lock:
            lore = self._load_main_lore()
            lore.thread_counter += 1
            if not thread.id:
                thread.id = _make_id("thread", lore.thread_counter)
            # Check existing thread với tên tương tự
            for t in lore.plot_threads:
                if t.name.lower() == thread.name.lower():
                    # Update status nếu đóng
                    if thread.status in ("closed", "abandoned") and t.status == "open":
                        t.status          = thread.status
                        t.closed_chapter  = thread.closed_chapter
                        t.resolution      = thread.resolution
                        for ch in thread.key_chapters:
                            if ch not in t.key_chapters:
                                t.key_chapters.append(ch)
                    self._save_main_lore(lore)
                    return t.id
            lore.plot_threads.append(thread)
            self._save_main_lore(lore)
            return thread.id

    def update_plot_thread_status(self, thread_name: str, status: str,
                                   closed_chapter: str = "", resolution: str = "") -> bool:
        with self._lore_lock:
            lore = self._load_main_lore()
            for t in lore.plot_threads:
                if t.name.lower() == thread_name.lower():
                    t.status         = status
                    t.closed_chapter = closed_chapter
                    t.resolution     = resolution
                    self._save_main_lore(lore)
                    return True
        return False

    def append_revelation(self, revelation: BibleRevelation) -> str:
        with self._lore_lock:
            lore = self._load_main_lore()
            lore.revelation_counter += 1
            if not revelation.id:
                revelation.id = _make_id("revelation", lore.revelation_counter)
            lore.revelations.append(revelation)
            self._save_main_lore(lore)
            return revelation.id

    def get_recent_lore(self, n: int = 3) -> list[BibleChapterSummary]:
        """Trả về N chapter summaries gần nhất."""
        lore = self._load_main_lore()
        return lore.chapter_summaries[-n:] if lore.chapter_summaries else []

    def get_plot_threads(self, status: str | None = None) -> list[BiblePlotThread]:
        lore    = self._load_main_lore()
        threads = lore.plot_threads
        if status:
            threads = [t for t in threads if t.status == status]
        return threads

    def get_active_foreshadows(self, current_chapter: str) -> list[str]:
        """Trả về hints về các plot thread đang mở — inject vào prompt."""
        threads = self.get_plot_threads("open")
        if not threads:
            return []
        hints = []
        for t in threads[:5]:
            hints.append(f"⚠️  Tuyến truyện đang mở: {t.name} (từ {t.opened_chapter})")
        return hints

    def format_recent_lore_for_prompt(self, n: int = 3) -> str:
        """Format N chapter summaries gần nhất để inject vào Trans-call prompt."""
        recent = self.get_recent_lore(n)
        if not recent:
            return ""
        lines = [f"**Tóm tắt {len(recent)} chương gần nhất (từ Bible):**"]
        for s in recent:
            lines.append(f"\n**{s.chapter}** [{s.tone}]")
            lines.append(s.summary)
            if s.key_events:
                lines.extend(f"  - {e}" for e in s.key_events[:3])
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────
    # STAGING
    # ──────────────────────────────────────────────────────────────

    def _staging_path(self, chapter: str) -> Path:
        safe = re.sub(r"[^\w\-.]", "_", chapter)
        return self._staging_dir / f"stage_{safe}.json"

    def save_staging(self, chapter: str, scan_output: ScanOutput) -> None:
        """Lưu raw scan output vào staging/."""
        path = self._staging_path(chapter)
        atomic_write(path, scan_output.model_dump_json(indent=2))

    def load_staging(self, chapter: str) -> ScanOutput | None:
        path = self._staging_path(chapter)
        if not path.exists():
            return None
        raw = load_json(path)
        return ScanOutput.model_validate(raw) if raw else None

    def load_all_staging(self) -> list[ScanOutput]:
        """Load tất cả staging files, sắp xếp theo chapter_index."""
        outputs = []
        for p in sorted(self._staging_dir.glob("stage_*.json")):
            raw = load_json(p)
            if raw:
                try:
                    outputs.append(ScanOutput.model_validate(raw))
                except Exception as e:
                    logging.warning(f"[BibleStore] staging lỗi {p.name}: {e}")
        outputs.sort(key=lambda o: o.chapter_index)
        return outputs

    def clear_staging(self, chapters: list[str] | None = None) -> int:
        """
        Xóa staging files sau khi consolidation.
        chapters=None → xóa tất cả.
        Trả về số file đã xóa.
        """
        count = 0
        if chapters:
            for ch in chapters:
                p = self._staging_path(ch)
                if p.exists():
                    p.unlink()
                    count += 1
        else:
            for p in self._staging_dir.glob("stage_*.json"):
                p.unlink()
                count += 1
        return count

    def has_staging(self) -> bool:
        return any(self._staging_dir.glob("stage_*.json"))

    def staging_count(self) -> int:
        return len(list(self._staging_dir.glob("stage_*.json")))

    # ──────────────────────────────────────────────────────────────
    # CONVENIENCE — EXPORT
    # ──────────────────────────────────────────────────────────────

    def export_all_json(self, output_path: Path) -> None:
        """Export toàn bộ Bible sang 1 JSON file."""
        db: dict[str, list] = {}
        for t in ("character", "item", "location", "skill", "faction", "concept"):
            db[t + "s"] = self.get_all_entities(t)

        blob = {
            "meta"         : self.load_meta().model_dump(),
            "database"     : db,
            "worldbuilding": self.get_worldbuilding().model_dump(),
            "main_lore"    : self._load_main_lore().model_dump(),
        }
        atomic_write(output_path, json.dumps(blob, ensure_ascii=False, indent=2))

    def rebuild_index(self) -> int:
        """
        Rebuild toàn bộ search index từ các database files.
        Gọi sau khi import/migrate hoặc khi index corrupt.
        Trả về số entries trong index.
        """
        new_index: dict[str, dict] = {}
        for t in ("character", "item", "location", "skill", "faction", "concept"):
            for e in self._load_db_file(t):
                eid  = e.get("id", "")
                cname = e.get("canonical_name", "")
                ename = e.get("en_name", "")
                if not eid:
                    continue
                for name in [cname, ename] + e.get("aliases", []):
                    k = name.lower().strip()
                    if k and len(k) >= 2:
                        new_index[k] = {"id": eid, "type": t,
                                         "name": cname, "en": ename}

        with self._idx_lock:
            self._save_index(new_index)
        return len(new_index)