"""
src/littrans/context/bible_enricher.py — Enrichment pass trước khi consolidate.

Flow trong 1 batch (5 chương):
  1. Load tất cả staging của batch
  2. Gom candidates có existing_id (entity đã biết)
  3. Group theo existing_id → 1 entity có thể xuất hiện nhiều lần trong batch
  4. Load profile hiện tại từ BibleStore
  5. Gom delta: tất cả description/raw_data mới từ các lần xuất hiện
  6. Batch tối đa MAX_PER_CALL entities/call → 1 AI call duy nhất per batch
  7. AI trả về enriched fields (description, skills, personality, goal, v.v.)
  8. Cập nhật trực tiếp vào BibleStore TRƯỚC khi consolidate

Tiết kiệm request:
  - 1 call AI per batch, không phải per entity
  - Chỉ enrich khi có delta thực sự (skip entity không có thông tin mới)
  - Max 20 entities/call để response không quá lớn
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from littrans.context.bible_store import BibleStore
from littrans.context.schemas import ScanOutput, ScanCandidate


# ── Config ────────────────────────────────────────────────────────

MAX_PER_CALL = 20   # max entities gửi trong 1 enrichment call


# ── Result ────────────────────────────────────────────────────────

@dataclass
class EnrichmentResult:
    entities_enriched: int = 0
    entities_skipped : int = 0
    errors           : list[str] = field(default_factory=list)


# ── System Prompt ─────────────────────────────────────────────────

_ENRICH_SYSTEM = """Bạn là AI chuyên làm giàu thông tin nhân vật/thực thể trong truyện LitRPG / Tu Tiên.

Bạn nhận được danh sách entities. Mỗi entity có:
  - "current": profile hiện tại đã biết
  - "new_observations": thông tin mới thu thập được từ các chương gần đây

Nhiệm vụ: đọc "new_observations", trích xuất thông tin THỰC SỰ MỚI so với "current",
rồi trả về bản cập nhật CHỈ chứa các field có thông tin mới/đầy đủ hơn.

QUY TẮC:
  - CHỈ trả về field có giá trị MỚI hoặc ĐẦY ĐỦ HƠN so với current
  - KHÔNG lặp lại thông tin đã có trong current
  - KHÔNG bịa đặt — chỉ dùng thông tin rõ ràng từ new_observations
  - Nếu không có gì mới → trả về {} cho entity đó

Trả về JSON. KHÔNG thêm text ngoài JSON:
{
  "updates": [
    {
      "existing_id": "char_001",
      "fields": {
        "description": "mô tả đầy đủ hơn nếu có thêm thông tin",
        "personality_summary": "cập nhật nếu lộ ra tính cách mới",
        "current_goal": "cập nhật nếu mục tiêu thay đổi",
        "cultivation": {"realm": "cập nhật nếu đột phá"},
        "skills_mentioned": ["skill mới nếu có"],
        "status": "alive|dead|unknown nếu thay đổi"
      }
    }
  ]
}

Với location/item/skill/faction — chỉ cập nhật description và các field đặc trưng."""


# ── Core Logic ────────────────────────────────────────────────────

class BibleEnricher:
    """
    Enrichment pass: gom delta từ staging → enrich profile đã biết → update store.
    Chạy TRƯỚC BibleConsolidator trong mỗi batch.
    """

    def __init__(self, store: BibleStore) -> None:
        self._store = store

    def run(self, staging: list[ScanOutput]) -> EnrichmentResult:
        """
        Entry point. Nhận staging list của 1 batch, enrich entities đã biết.
        Không raise — lỗi được log và bỏ qua.
        """
        result = EnrichmentResult()

        # Step 1: Gom delta từ tất cả staging
        delta_map = self._collect_deltas(staging)

        if not delta_map:
            return result

        # Step 2: Load profile hiện tại từ store
        enrichable = self._load_current_profiles(delta_map)

        if not enrichable:
            result.entities_skipped = len(delta_map)
            return result

        print(f"  🔮 Enrichment: {len(enrichable)} entities có thông tin mới...")

        # Step 3: Batch và call AI
        entity_ids = list(enrichable.keys())
        for batch_start in range(0, len(entity_ids), MAX_PER_CALL):
            batch_ids  = entity_ids[batch_start:batch_start + MAX_PER_CALL]
            batch_data = {eid: enrichable[eid] for eid in batch_ids}

            try:
                updates = self._call_enrich(batch_data)
                applied = self._apply_updates(updates)
                result.entities_enriched += applied
            except Exception as e:
                logging.error(f"[BibleEnricher] Batch lỗi: {e}")
                result.errors.append(str(e))
                print(f"  ⚠️  Enrichment batch lỗi: {e}")

        result.entities_skipped = len(delta_map) - result.entities_enriched
        return result

    # ── Step 1: Collect deltas ─────────────────────────────────────

    def _collect_deltas(
        self, staging: list[ScanOutput]
    ) -> dict[str, dict]:
        """
        Gom tất cả thông tin mới về entity đã biết từ staging.

        Returns:
          {existing_id: {
            "entity_type": str,
            "en_name": str,
            "canonical_name": str,
            "observations": [str],   # description từ các lần xuất hiện
            "raw_data_list": [dict], # raw_data từ các ScanCandidate
            "source_chapters": [str],
          }}
        """
        delta_map: dict[str, dict] = {}

        for scan_output in staging:
            for candidate in scan_output.database_candidates:
                # Chỉ xử lý entity ĐÃ BIẾT
                if not candidate.existing_id or candidate.is_new:
                    continue

                eid = candidate.existing_id
                if eid not in delta_map:
                    delta_map[eid] = {
                        "entity_type"   : candidate.entity_type,
                        "en_name"       : candidate.en_name,
                        "canonical_name": candidate.canonical_name,
                        "observations"  : [],
                        "raw_data_list" : [],
                        "source_chapters": [],
                    }

                entry = delta_map[eid]

                # Gom description mới (tránh trùng)
                if candidate.description and candidate.description not in entry["observations"]:
                    entry["observations"].append(candidate.description)

                # Gom context snippet
                if candidate.context_snippet and candidate.context_snippet not in entry["observations"]:
                    entry["observations"].append(f"[context] {candidate.context_snippet}")

                # Gom raw_data nếu có
                if candidate.raw_data:
                    entry["raw_data_list"].append(candidate.raw_data)

                # Track source chapters
                chap = scan_output.source_chapter
                if chap not in entry["source_chapters"]:
                    entry["source_chapters"].append(chap)

        return delta_map

    # ── Step 2: Load current profiles ─────────────────────────────

    def _load_current_profiles(
        self, delta_map: dict[str, dict]
    ) -> dict[str, dict]:
        """
        Load profile hiện tại từ store cho mỗi entity có delta.
        Chỉ giữ lại entity có observations thực sự (tránh call vô nghĩa).

        Returns:
          {existing_id: {
            "current": dict,       # profile hiện tại từ store
            "delta": dict,         # từ delta_map
          }}
        """
        enrichable: dict[str, dict] = {}

        for eid, delta in delta_map.items():
            # Bỏ qua nếu không có gì để enrich
            if not delta["observations"] and not delta["raw_data_list"]:
                continue

            # Load profile hiện tại
            current = self._store.get_entity_by_id(eid)
            if not current:
                logging.warning(f"[BibleEnricher] Không tìm thấy entity {eid} trong store")
                continue

            enrichable[eid] = {
                "current": current,
                "delta"  : delta,
            }

        return enrichable

    # ── Step 3: Call AI ────────────────────────────────────────────

    def _call_enrich(self, batch_data: dict[str, dict]) -> list[dict]:
        """
        1 AI call cho tối đa MAX_PER_CALL entities.

        Returns: list of {existing_id, fields} từ AI.
        """
        from littrans.llm.client import call_gemini_json

        # Build user message
        entities_for_prompt = []
        for eid, data in batch_data.items():
            current = data["current"]
            delta   = data["delta"]

            # Rút gọn profile hiện tại — chỉ giữ fields quan trọng
            current_summary = {
                "id"                : eid,
                "entity_type"       : current.get("type", delta["entity_type"]),
                "en_name"           : current.get("en_name", ""),
                "canonical_name"    : current.get("canonical_name", ""),
                "description"       : current.get("description", ""),
                "personality_summary": current.get("personality_summary", ""),
                "current_goal"      : current.get("current_goal", ""),
                "status"            : current.get("status", ""),
                "cultivation"       : current.get("cultivation", {}),
            }

            # Gom new_observations: description + raw_data có ích
            new_obs = list(delta["observations"])
            for rd in delta["raw_data_list"][:3]:  # tối đa 3 raw_data per entity
                for k in ("personality_summary", "current_goal", "constitution",
                          "cultivation_realm", "skills_mentioned", "status"):
                    if rd.get(k):
                        new_obs.append(f"{k}: {rd[k]}")

            entities_for_prompt.append({
                "existing_id"     : eid,
                "current"         : current_summary,
                "new_observations": new_obs[:10],  # tối đa 10 observations
                "source_chapters" : delta["source_chapters"],
            })

        import json
        user_msg = (
            f"Enrich {len(entities_for_prompt)} entities sau:\n\n"
            + json.dumps(entities_for_prompt, ensure_ascii=False, indent=2)
        )

        raw = call_gemini_json(_ENRICH_SYSTEM, user_msg)

        # Guard: AI có thể trả về list hoặc dict
        if isinstance(raw, list):
            # AI trả về list of updates trực tiếp
            return raw
        return raw.get("updates", [])

    # ── Step 4: Apply updates ──────────────────────────────────────

    def _apply_updates(self, updates: list) -> int:
        """
        Áp dụng enriched fields vào BibleStore.
        Chỉ update field có giá trị không rỗng.

        Returns: số entity đã được update.
        """
        applied = 0

        for upd in updates:
            if not isinstance(upd, dict):
                continue

            eid    = upd.get("existing_id", "")
            fields = upd.get("fields", {})

            if not eid or not fields:
                continue

            # Load entity hiện tại
            entity = self._store.get_entity_by_id(eid)
            if not entity:
                continue

            entity_type = entity.get("type", "")
            if not entity_type:
                continue

            # Merge fields mới vào entity
            changed = False
            for key, new_val in fields.items():
                if not new_val:
                    continue

                old_val = entity.get(key)

                # String: chỉ update nếu mới dài hơn hoặc cũ rỗng
                if isinstance(new_val, str):
                    if not old_val or len(new_val) > len(str(old_val)):
                        entity[key] = new_val
                        changed = True

                # List: append items mới
                elif isinstance(new_val, list):
                    old_list = old_val if isinstance(old_val, list) else []
                    for item in new_val:
                        if item and item not in old_list:
                            old_list.append(item)
                            changed = True
                    if changed:
                        entity[key] = old_list

                # Dict (vd: cultivation): merge
                elif isinstance(new_val, dict) and isinstance(old_val, dict):
                    for k, v in new_val.items():
                        if v and not old_val.get(k):
                            old_val[k] = v
                            changed = True

                # Dict nhưng old là empty/None
                elif isinstance(new_val, dict) and not old_val:
                    entity[key] = new_val
                    changed = True

            if changed:
                entity["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                try:
                    self._store.upsert_entity(entity_type, entity)
                    applied += 1
                except Exception as e:
                    logging.warning(f"[BibleEnricher] upsert {eid} lỗi: {e}")

        return applied