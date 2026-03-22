"""
src/littrans/bible/bible_consolidator.py — Hợp nhất staging → 3 tầng chính.

3 bước xử lý:
  1. Deterministic matching: so tên exact + fuzzy (Levenshtein)
  2. Index lookup: kiểm tra xem entity đã có chưa
  3. LLM arbitration: khi confidence 0.70–0.90 (không chắc merge hay không)

Pipeline:
  ScanOutput list → _consolidate_database → upsert vào BibleStore
                  → _consolidate_worldbuilding → update WorldBuilding
                  → _consolidate_lore → append MainLore

Tái dụng:
  store.upsert_entity()    — BibleStore
  call_gemini_json()       — llm/client.py
  _existing_terms_set()    — pattern từ clean_glossary.py

[v1.0] Initial implementation — Bible System Sprint 2
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime

from littrans.bible.bible_store import BibleStore
from littrans.bible.schemas import (
    ScanOutput, ScanCandidate,
    BibleChapterSummary, BibleEvent, BiblePlotThread, BibleRevelation,
    ENTITY_MODELS,
)


# ── Result ────────────────────────────────────────────────────────

@dataclass
class ConsolidationResult:
    chars_added    : int = 0
    entities_added : int = 0
    entities_updated: int = 0
    wb_clues_added  : int = 0
    lore_chapters   : int = 0
    errors          : list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# STRING SIMILARITY
# ═══════════════════════════════════════════════════════════════════

def _levenshtein_ratio(a: str, b: str) -> float:
    """Tỉ lệ tương đồng Levenshtein — 0.0 (khác hoàn toàn) → 1.0 (giống hệt)."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter = min(len(a), len(b))
        longer  = max(len(a), len(b))
        return shorter / longer

    # DP Levenshtein
    n, m = len(a), len(b)
    if abs(n - m) > max(n, m) * 0.5:
        return 0.0   # quá khác nhau → bỏ qua DP

    dp = list(range(m + 1))
    for i in range(1, n + 1):
        new_dp = [i] + [0] * m
        for j in range(1, m + 1):
            if a[i-1] == b[j-1]:
                new_dp[j] = dp[j-1]
            else:
                new_dp[j] = 1 + min(dp[j], new_dp[j-1], dp[j-1])
        dp = new_dp

    dist = dp[m]
    return 1.0 - dist / max(n, m)


def _name_similarity(candidate: ScanCandidate, existing: dict) -> float:
    """
    Tính độ tương đồng giữa candidate và entity đã có.
    Trả về 0.0–1.0.
    """
    c_names = [
        candidate.en_name.lower(),
        candidate.canonical_name.lower(),
    ]
    e_names = [
        existing.get("en_name", "").lower(),
        existing.get("canonical_name", "").lower(),
    ] + [a.lower() for a in existing.get("aliases", [])]

    best = 0.0
    for cn in c_names:
        for en in e_names:
            if not cn or not en:
                continue
            sim = _levenshtein_ratio(cn, en)
            best = max(best, sim)
    return best


# ═══════════════════════════════════════════════════════════════════
# ENTITY RESOLUTION
# ═══════════════════════════════════════════════════════════════════

class EntityResolver:
    """
    Phán đoán: candidate là entity đã có hay entity mới?
    
    Confidence thresholds:
      >= 0.95 → DUPLICATE (merge, no LLM)
      0.70–0.94 → UNCERTAIN (cần LLM arbitration)
      < 0.70 → NEW (insert, no LLM)
    """
    THRESH_SURE  = 0.95
    THRESH_MAYBE = 0.70

    def __init__(self, store: BibleStore) -> None:
        self._store = store

    def resolve(self, candidate: ScanCandidate) -> tuple[str, float]:
        """
        Returns: (existing_id_or_empty, confidence)
        existing_id = "" → candidate là NEW
        existing_id = "char_0001" → candidate trùng với entity đó
        confidence < THRESH_MAYBE → chắc chắn NEW
        """
        # 1. Nếu AI đã đặt existing_id → tin tưởng cao
        if candidate.existing_id:
            entity = self._store.get_entity_by_id(candidate.existing_id)
            if entity:
                return candidate.existing_id, 0.97

        # 2. Index lookup (exact)
        found = self._store._index_lookup(candidate.en_name)
        if not found:
            found = self._store._index_lookup(candidate.canonical_name)

        if found:
            etype = found.get("type", "")
            if etype == candidate.entity_type:
                # Lấy entity để tính similarity chính xác hơn
                entity = self._store.get_entity_by_id(found["id"])
                if entity:
                    sim = _name_similarity(candidate, entity)
                    if sim >= self.THRESH_SURE:
                        return found["id"], sim
                    elif sim >= self.THRESH_MAYBE:
                        return found["id"], sim   # cần LLM arbitration

        # 3. Fuzzy search
        results = self._store.search_entities(
            candidate.en_name or candidate.canonical_name,
            entity_type=candidate.entity_type,
        )
        for entity in results[:3]:
            sim = _name_similarity(candidate, entity)
            if sim >= self.THRESH_SURE:
                return entity["id"], sim
            elif sim >= self.THRESH_MAYBE:
                return entity["id"], sim

        return "", 0.0   # NEW


# ═══════════════════════════════════════════════════════════════════
# BIBLE CONSOLIDATOR
# ═══════════════════════════════════════════════════════════════════

class BibleConsolidator:
    """
    Hợp nhất staging → 3 tầng chính của BibleStore.
    
    Usage:
        consolidator = BibleConsolidator(store)
        result = consolidator.run(staging_outputs)
    """

    def __init__(self, store: BibleStore) -> None:
        self._store    = store
        self._resolver = EntityResolver(store)

    def run(self, staging: list[ScanOutput]) -> ConsolidationResult:
        """Entry point — consolidate list ScanOutput → 3 tầng."""
        result = ConsolidationResult()

        for scan_output in staging:
            try:
                self._consolidate_one(scan_output, result)
                self._store.mark_chapter_scanned(scan_output.source_chapter)
            except Exception as e:
                msg = f"{scan_output.source_chapter}: {e}"
                logging.error(f"[Consolidator] {msg}")
                result.errors.append(msg)

        return result

    def _consolidate_one(self, scan: ScanOutput, result: ConsolidationResult) -> None:
        """Consolidate 1 ScanOutput."""
        # Tầng 1: Database
        self._consolidate_database(scan, result)

        # Tầng 2: WorldBuilding
        if scan.worldbuilding_clues:
            self._consolidate_worldbuilding(scan, result)

        # Tầng 3: Main Lore
        self._consolidate_lore(scan, result)

    # ── Tầng 1: Database ─────────────────────────────────────────

    def _consolidate_database(self, scan: ScanOutput, result: ConsolidationResult) -> None:
        for candidate in scan.database_candidates:
            if not candidate.en_name and not candidate.canonical_name:
                continue
            if candidate.entity_type not in ENTITY_MODELS:
                candidate.entity_type = "concept"
            try:
                entity_id, action = self._resolve_and_upsert(
                    candidate, scan.source_chapter
                )
                if action == "added":
                    result.entities_added += 1
                    if candidate.entity_type == "character":
                        result.chars_added += 1
                elif action == "updated":
                    result.entities_updated += 1
            except Exception as e:
                logging.warning(
                    f"[Consolidator] {candidate.en_name} | {candidate.entity_type} | {e}"
                )

    def _resolve_and_upsert(
        self, candidate: ScanCandidate, source_chapter: str
    ) -> tuple[str, str]:
        """
        Returns: (entity_id, action) where action = "added"|"updated"|"skipped"
        """
        existing_id, confidence = self._resolver.resolve(candidate)
        
        # Cần LLM arbitration?
        if (existing_id and
                EntityResolver.THRESH_MAYBE <= confidence < EntityResolver.THRESH_SURE):
            existing_id = self._llm_arbitration(candidate, existing_id, confidence)

        # Build entity dict từ candidate
        entity_data = self._candidate_to_entity(candidate, source_chapter)

        if existing_id:
            entity_data["id"] = existing_id
            entity_id = self._store.upsert_entity(candidate.entity_type, entity_data)
            return entity_id, "updated"
        else:
            entity_id = self._store.upsert_entity(candidate.entity_type, entity_data)
            return entity_id, "added"

    def _candidate_to_entity(self, c: ScanCandidate, source_chapter: str) -> dict:
        """Convert ScanCandidate → entity dict phù hợp với BibleStore."""
        base = {
            "en_name"         : c.en_name,
            "canonical_name"  : c.canonical_name,
            "type"            : c.entity_type,
            "description"     : c.description,
            "first_appearance": source_chapter,
            "confidence"      : c.confidence,
            "last_updated"    : datetime.now().strftime("%Y-%m-%d"),
        }

        raw = c.raw_data or {}

        if c.entity_type == "character":
            base.update({
                "status"              : raw.get("status", "alive"),
                "role"                : raw.get("role", "Unknown"),
                "archetype"           : raw.get("archetype", "UNKNOWN"),
                "faction_id"          : "",   # sẽ resolve sau
                "cultivation"         : {"realm": raw.get("cultivation_realm", "")},
                "personality_summary" : raw.get("personality_summary", ""),
                "pronoun_self"        : raw.get("pronoun_self", ""),
                "current_goal"        : raw.get("current_goal", ""),
                "aliases"             : raw.get("aliases", []),
            })
        elif c.entity_type == "item":
            base.update({
                "item_type" : raw.get("item_type", "other"),
                "rarity"    : raw.get("rarity", ""),
                "effects"   : raw.get("effects", []),
            })
        elif c.entity_type == "location":
            base.update({
                "location_type"   : raw.get("location_type", "other"),
                "notable_features": raw.get("notable_features", []),
            })
        elif c.entity_type == "skill":
            base.update({
                "skill_type"     : raw.get("skill_type", "active"),
                "effects"        : raw.get("effects", []),
                "evolution_chain": [c.canonical_name] if c.canonical_name else [],
            })
        elif c.entity_type == "faction":
            base.update({
                "faction_type"     : raw.get("faction_type", "other"),
                "power_level"      : raw.get("power_level", ""),
            })

        return base

    def _llm_arbitration(
        self, candidate: ScanCandidate, existing_id: str, confidence: float
    ) -> str:
        """
        Gọi AI khi không chắc candidate = entity đã có hay mới.
        Trả về existing_id nếu là cùng entity, "" nếu là entity mới.
        """
        existing = self._store.get_entity_by_id(existing_id)
        if not existing:
            return ""

        system = (
            "Bạn là AI chuyên phán xét entity resolution cho tiểu thuyết.\n"
            "Câu hỏi: entity A và entity B có phải là CÙNG MỘT nhân vật/địa điểm/vật phẩm không?\n"
            "Trả về JSON: {\"same\": true/false, \"reason\": \"lý do ngắn\"}"
        )
        user = (
            f"Entity A (từ scan): {candidate.en_name} → {candidate.canonical_name}\n"
            f"  Loại: {candidate.entity_type}\n"
            f"  Mô tả: {candidate.description}\n"
            f"  Context: {candidate.context_snippet[:150]}\n\n"
            f"Entity B (đã có [{existing_id}]): {existing.get('en_name','')} → "
            f"{existing.get('canonical_name','')}\n"
            f"  Mô tả: {existing.get('description','')}"
        )

        try:
            from littrans.llm.client import call_gemini_json
            result = call_gemini_json(system, user)
            if result.get("same"):
                return existing_id
        except Exception as e:
            logging.warning(f"[Consolidator] LLM arbitration lỗi: {e}")

        return ""   # treat as new nếu không chắc

    # ── Tầng 2: WorldBuilding ─────────────────────────────────────

    def _consolidate_worldbuilding(self, scan: ScanOutput, result: ConsolidationResult) -> None:
        """Merge worldbuilding clues vào WorldBuilding tầng 2."""
        cfg = _get_wb_updates(scan)
        if not cfg:
            return

        try:
            self._store.update_worldbuilding(cfg)
            result.wb_clues_added += len(scan.worldbuilding_clues)
        except Exception as e:
            logging.warning(f"[Consolidator] WorldBuilding update lỗi: {e}")


    # ── Tầng 3: Main Lore ─────────────────────────────────────────

    def _consolidate_lore(self, scan: ScanOutput, result: ConsolidationResult) -> None:
        """Append lore_entry vào MainLore tầng 3."""
        lore = scan.lore_entry
        if not lore.chapter_summary:
            return   # không có lore → bỏ qua

        # Chapter summary
        summary = BibleChapterSummary(
            chapter       = scan.source_chapter,
            chapter_index = scan.chapter_index,
            summary       = lore.chapter_summary,
            tone          = lore.tone,
            pov_char_id   = "",   # sẽ resolve từ pov_char name sau
            location_id   = "",
            key_events    = [e.get("title", "") for e in lore.key_events],
            new_entity_ids= [],
            scanned_at    = scan.scanned_at,
        )
        self._store.append_chapter_summary(summary)
        result.lore_chapters += 1

        # Events
        for ev_raw in lore.key_events:
            if not isinstance(ev_raw, dict):
                continue
            event = BibleEvent(
                chapter      = scan.source_chapter,
                event_type   = ev_raw.get("type", "other"),
                title        = ev_raw.get("title", ""),
                description  = ev_raw.get("description", ""),
                participants = ev_raw.get("participants", []),
                consequence  = ev_raw.get("consequence", ""),
            )
            if event.title:
                self._store.append_event(event)

        # Plot threads opened
        for t_raw in lore.plot_threads_opened:
            if not isinstance(t_raw, dict) or not t_raw.get("name"):
                continue
            thread = BiblePlotThread(
                name           = t_raw["name"],
                opened_chapter = scan.source_chapter,
                status         = "open",
                summary        = t_raw.get("summary", ""),
                key_chapters   = [scan.source_chapter],
            )
            self._store.append_plot_thread(thread)

        # Plot threads closed
        for t_raw in lore.plot_threads_closed:
            if not isinstance(t_raw, dict):
                continue
            self._store.update_plot_thread_status(
                thread_name    = t_raw.get("thread_name", ""),
                status         = "closed",
                closed_chapter = scan.source_chapter,
                resolution     = t_raw.get("resolution", ""),
            )

        # Revelations
        for r_raw in lore.revelations:
            if not isinstance(r_raw, dict) or not r_raw.get("title"):
                continue
            rev = BibleRevelation(
                chapter        = scan.source_chapter,
                title          = r_raw["title"],
                description    = r_raw.get("description", ""),
                foreshadowed_in = r_raw.get("foreshadowed_in", []),
            )
            self._store.append_revelation(rev)


# ── WorldBuilding helper ──────────────────────────────────────────

def _get_wb_updates(scan: ScanOutput) -> dict:
    """Convert worldbuilding_clues → dict phù hợp với store.update_worldbuilding()."""
    if not scan.worldbuilding_clues:
        return {}

    updates: dict = {
        "confirmed_rules"  : [],
        "history_notes"    : [],
        "economy_notes"    : [],
        "cosmology_notes"  : [],
    }

    CAT_MAP = {
        "rule"        : "confirmed_rules",
        "history"     : "history_notes",
        "economy"     : "economy_notes",
        "cosmological": "cosmology_notes",
        "cosmology"   : "cosmology_notes",
    }

    has_any = False
    for clue in scan.worldbuilding_clues:
        cat = clue.category.lower()
        key = CAT_MAP.get(cat)
        if key:
            if key == "confirmed_rules":
                updates["confirmed_rules"].append({
                    "description"   : clue.description,
                    "source_chapter": scan.source_chapter,
                    "category"      : cat,
                    "confidence"    : clue.confidence,
                })
            else:
                updates[key].append(f"[{scan.source_chapter}] {clue.description}")
            has_any = True

    return updates if has_any else {}