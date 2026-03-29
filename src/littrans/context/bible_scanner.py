"""
src/littrans/context/bible_scanner.py — BibleScanner: scan engine chính.

[FIX v1] _parse_scan_response: guard khi AI trả về JSON array thay vì dict.
[FIX v2] scan_one: retry với backoff cho network/timeout errors.
[FIX v3] Chunk splitting cho chương dài:
         n_chunks = ceil(total / CHUNK_SIZE)
         chunk_size = total / n_chunks  (chia đều)
         Ví dụ: 24,926 ký tự, CHUNK_SIZE=10,000
           → ceil(24926/10000) = 3 chunks, mỗi chunk ~8,309 ký tự
         Mỗi chunk được scan riêng, kết quả merge lại thành 1 ScanOutput.
         Cắt tại ranh giới đoạn văn (dòng trống) để không cắt giữa câu.
"""
from __future__ import annotations

import math
import re
import time
import logging
from datetime import datetime
from pathlib import Path

from littrans.context.bible_store import BibleStore
from littrans.context.schemas import (
    ScanOutput, ScanCandidate, ScanWorldBuildingClue,
    ScanLoreEntry,
)
from littrans.utils.io_utils import load_text


def _normalize_list_of_dicts(items: list, string_key: str = "title") -> list[dict]:
    """
    Model đôi khi trả về list of strings thay vì list of dicts.
    "Arrival in Elysium" → {"title": "Arrival in Elysium"}
    """
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, str) and item.strip():
            result.append({string_key: item.strip()})
    return result



# ── Constants ─────────────────────────────────────────────────────

# Ngưỡng mỗi chunk (ký tự). Trên ngưỡng này sẽ chia chunk.
CHUNK_SIZE = 15_000

# Retry config cho network errors
_SCAN_MAX_RETRIES  = 3
_SCAN_RETRY_DELAYS = [15, 30, 60]   # giây chờ giữa các lần thử


# ── Helpers ───────────────────────────────────────────────────────

def _get_settings():
    from littrans.config.settings import settings
    return settings


def _normalize(text: str) -> str:
    try:
        from littrans.core.text_normalizer import normalize
        return normalize(text)
    except ImportError:
        return text.replace("\r\n", "\n").strip()


def _call_json(system: str, user: str) -> dict:
    from littrans.llm.client import call_gemini_json
    return call_gemini_json(system, user)


def _is_network_error(exc: Exception) -> bool:
    """True nếu lỗi là do mạng/timeout — nên retry."""
    msg = str(exc).lower()
    return any(k in msg for k in (
        "10060", "10061", "connection", "timeout", "timed out",
        "winerror", "connecttimeout", "readtimeout", "connection reset",
        "remote end closed", "connection aborted", "connection refused",
        "network", "socket", "ssl",
    ))


# ── Chunk splitter ────────────────────────────────────────────────

def _split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """
    Chia text thành n_chunks chunk bằng nhau, cắt tại ranh giới đoạn văn.

    Logic:
      n_chunks  = ceil(len(text) / chunk_size)
      target    = len(text) / n_chunks   (kích thước mục tiêu mỗi chunk)

    Ví dụ: 24,926 ký tự, chunk_size=10,000
      n_chunks = ceil(24926/10000) = 3
      target   = 24926/3 ≈ 8,309 ký tự mỗi chunk

    Cắt tại dòng trống gần nhất với vị trí target để không cắt giữa câu.
    """
    total = len(text)
    if total <= chunk_size:
        return [text]

    n_chunks = math.ceil(total / chunk_size)
    target   = total / n_chunks   # float: kích thước lý tưởng mỗi chunk

    chunks = []
    start  = 0

    for i in range(n_chunks - 1):   # n-1 lần cắt, chunk cuối lấy phần còn lại
        ideal_end = int(start + target)
        ideal_end = min(ideal_end, total - 1)

        # Tìm dòng trống gần vị trí ideal_end nhất (trong window ±500 ký tự)
        window_start = max(start + 1, ideal_end - 500)
        window_end   = min(total,     ideal_end + 500)
        search_area  = text[window_start:window_end]

        # Tìm vị trí "\n\n" gần nhất với ideal_end trong window
        best_pos = None
        best_dist = float("inf")
        for m in re.finditer(r"\n\n", search_area):
            abs_pos = window_start + m.end()
            dist    = abs(abs_pos - ideal_end)
            if dist < best_dist:
                best_dist = dist
                best_pos  = abs_pos

        # Nếu không tìm thấy dòng trống → cắt tại dòng mới gần nhất
        if best_pos is None:
            for m in re.finditer(r"\n", search_area):
                abs_pos = window_start + m.end()
                dist    = abs(abs_pos - ideal_end)
                if dist < best_dist:
                    best_dist = dist
                    best_pos  = abs_pos

        # Fallback: cắt đúng tại ideal_end
        cut = best_pos if best_pos is not None else ideal_end

        chunks.append(text[start:cut].strip())
        start = cut

    # Chunk cuối: phần còn lại
    if start < total:
        chunks.append(text[start:].strip())

    # Lọc chunk rỗng
    return [c for c in chunks if c.strip()]


# ── System Prompt Builder ─────────────────────────────────────────

def _load_scan_system_prompt(depth: str) -> str:
    cfg  = _get_settings()
    path = cfg.prompts_dir / "bible_scan.md"
    raw  = load_text(path)
    if not raw:
        return _fallback_system_prompt(depth)
    role       = _extract_xml(raw, "ROLE")
    principles = _extract_xml(raw, "PRINCIPLES")
    depth_txt  = _extract_xml_attr(raw, "DEPTH", "id", depth)
    schemas    = _extract_xml(raw, "RAW_DATA_SCHEMAS") if depth != "quick" else ""
    naming     = _extract_xml(raw, "NAMING")
    base = "\n\n".join(filter(None, [
        role, principles,
        f"OUTPUT FORMAT ({depth.upper()}):\n{depth_txt}",
        schemas, naming,
    ]))
    # Luôn append format reminder cứng để model không tự ý đổi structure
    format_reminder = """
QUAN TRỌNG — ĐỊNH DẠNG JSON BẮT BUỘC:
Trả về ĐÚNG cấu trúc sau. KHÔNG trả về array trực tiếp. KHÔNG thêm text ngoài JSON:
{
  "database_candidates": [ { "entity_type": "...", "en_name": "...", "canonical_name": "...", "description": "...", "confidence": 0.9, "raw_data": {}, "context_snippet": "..." } ],
  "worldbuilding_clues": [ { "category": "...", "description": "...", "raw_text": "...", "confidence": 0.8 } ],
  "lore_entry": { "chapter_summary": "...", "tone": "...", "pov_char": "...", "location": "...", "key_events": [], "plot_threads_opened": [], "plot_threads_closed": [], "revelations": [], "relationship_changes": [] }
}"""
    return base + format_reminder


def _extract_xml(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_xml_attr(text: str, tag: str, attr: str, val: str) -> str:
    m = re.search(rf'<{tag}\s+{attr}="{val}"[^>]*>(.*?)</{tag}>', text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _fallback_system_prompt(depth: str) -> str:
    base = (
        "Bạn là AI phân tích truyện LitRPG / Tu Tiên. "
        "Đọc chương được cung cấp, trích xuất thông tin CÓ CẤU TRÚC. "
        "CHỈ ghi những gì RÕ RÀNG trong văn bản. KHÔNG suy luận. "
        "Trả về JSON. KHÔNG thêm text ngoài JSON.\n\n"
    )
    if depth == "quick":
        return base + '{"database_candidates": [...], "worldbuilding_clues": [], "lore_entry": {}}'
    return base + '{"database_candidates": [...], "worldbuilding_clues": [...], "lore_entry": {...}}'


# ── User Message Builder ──────────────────────────────────────────

def _build_user_message(
    chunk_text: str,
    chapter_filename: str,
    known_entities: dict[str, dict],
    chunk_label: str = "",      # ví dụ: "chunk 1/3"
) -> str:
    parts = []
    if known_entities:
        known_lines = []
        for etype, entities in known_entities.items():
            for e in entities[:20]:
                known_lines.append(
                    f"  [{e.get('id','?')}] {e.get('en_name','')} → "
                    f"{e.get('canonical_name','')} ({etype})"
                )
        if known_lines:
            parts.append(
                "## ENTITIES ĐÃ BIẾT — KHÔNG TẠO MỚI, CHỈ DÙNG existing_id\n"
                + "\n".join(known_lines[:100])
            )
    header = f"## CHƯƠNG: {chapter_filename}"
    if chunk_label:
        header += f"  [{chunk_label}]"
    parts.append(f"{header}\n\n{chunk_text}")
    return "\n\n---\n\n".join(parts)


# ── Response Parser ───────────────────────────────────────────────

def _parse_scan_response(
    raw_data,
    source_chapter: str,
    chapter_index: int,
    depth: str,
    model_used: str,
) -> ScanOutput:
    # [FIX v1] Guard khi AI trả về JSON array hoặc kiểu khác thay vì dict
    if isinstance(raw_data, list):
        # Model trả về array entities trực tiếp thay vì {"database_candidates": [...]}
        # → wrap lại đúng format
        logging.warning(
            f"[BibleScanner] raw_data là list (size={len(raw_data)}) "
            f"cho '{source_chapter}' — wrap thành database_candidates"
        )
        raw_data = {"database_candidates": raw_data}
    elif not isinstance(raw_data, dict):
        logging.warning(
            f"[BibleScanner] raw_data là {type(raw_data).__name__} "
            f"(không phải dict) cho '{source_chapter}' — bỏ qua"
        )
        raw_data = {}

    candidates = []
    for c in raw_data.get("database_candidates", []):
        if not isinstance(c, dict):
            continue
        # Normalize field names — model đôi khi dùng "type" thay vì "entity_type",
        # "full_name" thay vì "en_name", "name" thay vì "en_name"
        if "entity_type" not in c and "type" in c:
            c = dict(c)
            c["entity_type"] = c.pop("type")
        if "en_name" not in c:
            c = dict(c)
            c["en_name"] = (c.get("full_name") or c.get("name") or "").strip()
        en = c.get("en_name", "").strip()
        if not en:
            continue
        try:
            conf = float(c.get("confidence", 0.9))
        except Exception:
            conf = 0.9
        candidates.append(ScanCandidate(
            entity_type=c.get("entity_type", "concept"),
            en_name=en,
            canonical_name=c.get("canonical_name", "").strip(),
            existing_id=c.get("existing_id", "").strip(),
            is_new=bool(c.get("is_new", True)),
            description=c.get("description", "").strip(),
            raw_data=c.get("raw_data", {}),
            confidence=min(1.0, max(0.0, conf)),
            context_snippet=c.get("context_snippet", "").strip()[:200],
        ))

    clues = []
    for w in raw_data.get("worldbuilding_clues", []):
        if not isinstance(w, dict):
            continue
        try:
            conf = float(w.get("confidence", 0.8))
        except Exception:
            conf = 0.8
        clues.append(ScanWorldBuildingClue(
            category=w.get("category", "other"),
            description=w.get("description", "").strip(),
            raw_text=w.get("raw_text", "").strip()[:300],
            confidence=min(1.0, max(0.0, conf)),
        ))

    lr = raw_data.get("lore_entry", {})
    if not isinstance(lr, dict):
        lr = {}
    lore = ScanLoreEntry(
        chapter_summary=lr.get("chapter_summary", "").strip(),
        tone=lr.get("tone", "").strip(),
        pov_char=lr.get("pov_char", "").strip(),
        location=lr.get("location", "").strip(),
        key_events=_normalize_list_of_dicts(
            lr.get("key_events", []) if isinstance(lr.get("key_events"), list) else [],
            string_key="title"),
        plot_threads_opened=_normalize_list_of_dicts(
            lr.get("plot_threads_opened", []) if isinstance(lr.get("plot_threads_opened"), list) else [],
            string_key="name"),
        plot_threads_closed=_normalize_list_of_dicts(
            lr.get("plot_threads_closed", []) if isinstance(lr.get("plot_threads_closed"), list) else [],
            string_key="thread_name"),
        revelations=_normalize_list_of_dicts(
            lr.get("revelations", []) if isinstance(lr.get("revelations"), list) else [],
            string_key="title"),
        relationship_changes=_normalize_list_of_dicts(
            lr.get("relationship_changes", []) if isinstance(lr.get("relationship_changes"), list) else [],
            string_key="event"),
    )
    return ScanOutput(
        source_chapter=source_chapter,
        chapter_index=chapter_index,
        scan_depth=depth,
        database_candidates=candidates,
        worldbuilding_clues=clues,
        lore_entry=lore,
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        model_used=model_used,
        raw_response=raw_data,
    )


# ── Chunk merger ──────────────────────────────────────────────────

def _merge_scan_outputs(outputs: list[ScanOutput], source_chapter: str, chapter_index: int, depth: str, model_used: str) -> ScanOutput:
    """
    Gộp nhiều ScanOutput từ các chunk thành 1 ScanOutput hoàn chỉnh.

    Candidates: dedup theo en_name (giữ bản confidence cao hơn).
    Clues: dedup theo description.
    Lore: lấy chunk đầu tiên có chapter_summary; merge key_events, plot_threads, revelations.
    """
    if len(outputs) == 1:
        return outputs[0]

    # ── Merge candidates (dedup theo en_name, giữ confidence cao nhất) ──
    seen_entities: dict[str, ScanCandidate] = {}
    for out in outputs:
        for c in out.database_candidates:
            key = c.en_name.lower().strip()
            if key not in seen_entities or c.confidence > seen_entities[key].confidence:
                seen_entities[key] = c
    merged_candidates = list(seen_entities.values())

    # ── Merge worldbuilding clues (dedup theo description) ──────────────
    seen_clues: dict[str, ScanWorldBuildingClue] = {}
    for out in outputs:
        for w in out.worldbuilding_clues:
            key = w.description.lower().strip()[:80]
            if key and key not in seen_clues:
                seen_clues[key] = w
    merged_clues = list(seen_clues.values())

    # ── Merge lore ───────────────────────────────────────────────────────
    # chapter_summary: lấy cái đầu tiên có nội dung; nếu nhiều hơn 1 chunk
    # có summary thì nối lại ngắn gọn
    summaries = [o.lore_entry.chapter_summary for o in outputs if o.lore_entry.chapter_summary]
    if len(summaries) > 1:
        merged_summary = " | ".join(summaries)
    elif summaries:
        merged_summary = summaries[0]
    else:
        merged_summary = ""

    # tone, pov_char, location: lấy từ chunk đầu tiên có giá trị
    def _first(attr: str) -> str:
        for o in outputs:
            v = getattr(o.lore_entry, attr, "")
            if v:
                return v
        return ""

    # key_events, plot_threads, revelations, relationship_changes: gộp tất cả, dedup theo title/name
    def _merge_list_by_key(items_list: list[list[dict]], key: str) -> list[dict]:
        seen: set[str] = set()
        result: list[dict] = []
        for items in items_list:
            for item in items:
                if not isinstance(item, dict):
                    continue
                k = str(item.get(key, "")).lower().strip()
                if k and k not in seen:
                    seen.add(k)
                    result.append(item)
        return result

    merged_lore = ScanLoreEntry(
        chapter_summary=merged_summary,
        tone=_first("tone"),
        pov_char=_first("pov_char"),
        location=_first("location"),
        key_events=_merge_list_by_key(
            [o.lore_entry.key_events for o in outputs], "title"
        ),
        plot_threads_opened=_merge_list_by_key(
            [o.lore_entry.plot_threads_opened for o in outputs], "name"
        ),
        plot_threads_closed=_merge_list_by_key(
            [o.lore_entry.plot_threads_closed for o in outputs], "thread_name"
        ),
        revelations=_merge_list_by_key(
            [o.lore_entry.revelations for o in outputs], "title"
        ),
        relationship_changes=_merge_list_by_key(
            [o.lore_entry.relationship_changes for o in outputs], "event"
        ),
    )

    return ScanOutput(
        source_chapter=source_chapter,
        chapter_index=chapter_index,
        scan_depth=depth,
        database_candidates=merged_candidates,
        worldbuilding_clues=merged_clues,
        lore_entry=merged_lore,
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        model_used=model_used,
        raw_response={},
    )


# ── Single chunk scan (với retry) ────────────────────────────────

def _scan_chunk(
    chunk_text: str,
    filename: str,
    chapter_index: int,
    depth: str,
    known_entities: dict,
    system_prompt: str,
    chunk_label: str,
    model_used: str,
) -> ScanOutput | None:
    """
    Scan 1 chunk văn bản với retry cho network errors.
    Trả về ScanOutput hoặc None nếu thất bại hoàn toàn.
    """
    last_error: Exception | None = None

    for attempt in range(_SCAN_MAX_RETRIES):
        if attempt > 0:
            delay = _SCAN_RETRY_DELAYS[min(attempt - 1, len(_SCAN_RETRY_DELAYS) - 1)]
            print(f"      🔄 Retry {attempt}/{_SCAN_MAX_RETRIES - 1} — chờ {delay}s...")
            time.sleep(delay)

        user_message = _build_user_message(
            chunk_text, filename, known_entities, chunk_label,
        )

        try:
            raw_data = _call_json(system_prompt, user_message)
            output   = _parse_scan_response(
                raw_data, filename, chapter_index, depth, model_used,
            )
            return output
        except Exception as e:
            last_error = e
            if _is_network_error(e):
                logging.warning(
                    f"[BibleScanner] Network error '{filename}' {chunk_label} "
                    f"attempt {attempt + 1}/{_SCAN_MAX_RETRIES}: {e}"
                )
                print(
                    f"      ⚠️  Network error (attempt {attempt + 1}/{_SCAN_MAX_RETRIES}): "
                    f"{str(e)[:100]}"
                )
                continue
            else:
                logging.error(f"[BibleScanner] {filename} {chunk_label}: {e}")
                print(f"      ❌ Lỗi (không retry): {e}")
                return None

    logging.error(
        f"[BibleScanner] '{filename}' {chunk_label} hết retry. Last: {last_error}"
    )
    print(f"      ❌ Thất bại sau {_SCAN_MAX_RETRIES} lần: {last_error}")
    return None


# ── Bible Scanner ─────────────────────────────────────────────────

class BibleScanner:
    """Scan engine chính — đọc inputs/ → gọi AI → lưu staging → consolidation."""

    def __init__(self, store: BibleStore | None = None) -> None:
        cfg         = _get_settings()
        self._store = store or BibleStore(cfg.bible_dir)
        self._depth = getattr(cfg, "bible_scan_depth", "standard")
        self._batch = getattr(cfg, "bible_scan_batch", 5)
        self._sleep = getattr(cfg, "bible_scan_sleep", 10)

    def scan_all(self, force: bool = False) -> dict[str, int]:
        cfg       = _get_settings()
        all_files = self._sorted_inputs(cfg.active_input_dir)  # FIX: was cfg.input_dir
        if not all_files:
            print(f"❌ Không có file nào trong '{cfg.active_input_dir}'.")  # FIX
            return {"scanned": 0, "skipped": 0, "failed": 0}
        self._store.update_meta(total_chapters=len(all_files))
        print(f"\n{'═'*62}")
        print(f"  📖 BIBLE SCAN — {len(all_files)} chương")
        print(f"  Depth: {self._depth} · Batch: {self._batch} · Sleep: {self._sleep}s")
        print(f"  Chunk size: {CHUNK_SIZE:,} ký tự")
        print(f"{'═'*62}\n")
        return self._scan_loop(all_files, force=force)

    def scan_new_only(self) -> dict[str, int]:
        return self.scan_all(force=False)

    def scan_one(
        self,
        filename: str,
        chapter_text: str,
        chapter_index: int = 0,
        force: bool = False,
    ) -> bool:
        """
        Scan 1 chương. Nếu dài hơn CHUNK_SIZE → chia chunk đều, scan từng phần, merge.

        Ví dụ: 24,926 ký tự, CHUNK_SIZE=10,000
          n_chunks = ceil(24926/10000) = 3
          target   = 24926/3 ≈ 8,309 ký tự mỗi chunk
          → 3 lần gọi API, merge thành 1 ScanOutput
        """
        if not force and self._store.is_chapter_scanned(filename):
            print(f"  ⏭️  Đã scan: {filename}")
            return True

        text = _normalize(chapter_text)
        if not text.strip():
            print(f"  ⚠️  File rỗng: {filename}")
            return False

        chunks      = _split_into_chunks(text, CHUNK_SIZE)
        n_chunks    = len(chunks)
        known       = self._store.get_entities_for_chapter(text)
        known_count = sum(len(v) for v in known.values())
        model_used  = self._current_model()

        if n_chunks == 1:
            print(
                f"  🔍 Scan [{self._depth}]: {filename} "
                f"({len(text):,} ký tự · {known_count} entities đã biết)"
            )
        else:
            chunk_sizes = ", ".join(f"{len(c):,}" for c in chunks)
            print(
                f"  🔍 Scan [{self._depth}]: {filename} "
                f"({len(text):,} ký tự → {n_chunks} chunks: [{chunk_sizes}] · "
                f"{known_count} entities đã biết)"
            )

        system_prompt = _load_scan_system_prompt(self._depth)
        chunk_outputs: list[ScanOutput] = []

        for i, chunk in enumerate(chunks):
            chunk_label = f"chunk {i+1}/{n_chunks}" if n_chunks > 1 else ""
            if n_chunks > 1:
                print(f"    📄 {chunk_label} ({len(chunk):,} ký tự)...")

            output = _scan_chunk(
                chunk_text=chunk,
                filename=filename,
                chapter_index=chapter_index,
                depth=self._depth,
                known_entities=known,
                system_prompt=system_prompt,
                chunk_label=chunk_label,
                model_used=model_used,
            )

            if output is None:
                # Chunk này thất bại hoàn toàn
                if n_chunks == 1:
                    print(f"  ❌ Scan thất bại: {filename}")
                    return False
                else:
                    print(f"    ⚠️  {chunk_label} thất bại — bỏ qua chunk này, tiếp tục")
                    continue

            chunk_outputs.append(output)

            # Ngủ ngắn giữa các chunk để tránh rate limit
            if i < n_chunks - 1:
                time.sleep(3)

        if not chunk_outputs:
            print(f"  ❌ Tất cả chunks thất bại: {filename}")
            return False

        # Merge tất cả chunk outputs
        final_output = _merge_scan_outputs(
            chunk_outputs, filename, chapter_index, self._depth, model_used,
        )

        # Verification call (deep mode) trên kết quả đã merge
        if self._depth == "deep" and final_output.database_candidates:
            final_output = self._verification_call(final_output, text, filename)

        self._store.save_staging(filename, final_output)
        print(
            f"  ✅ Staged: {len(final_output.database_candidates)} entities · "
            f"{len(final_output.worldbuilding_clues)} WB clues · "
            f"lore: {'✓' if final_output.lore_entry.chapter_summary else '—'}"
            + (f"  [{n_chunks} chunks merged]" if n_chunks > 1 else "")
        )
        return True

    def _scan_loop(self, all_files: list[str], force: bool) -> dict[str, int]:
        cfg     = _get_settings()
        stats   = {"scanned": 0, "skipped": 0, "failed": 0}
        batch_n = 0
        for i, filename in enumerate(all_files):
            print(f"\n[{i+1}/{len(all_files)}] {filename}")
            fp   = cfg.active_input_dir / filename  # FIX: was cfg.input_dir
            text = load_text(fp)
            if not text.strip():
                print(f"  ⚠️  File rỗng — bỏ qua.")
                stats["skipped"] += 1
                continue
            ok = self.scan_one(filename, text, chapter_index=i, force=force)
            if ok:
                stats["scanned"] += 1
                batch_n += 1
            else:
                stats["failed"] += 1
            if batch_n >= self._batch:
                self._run_consolidation(f"batch_{i+1}")
                batch_n = 0
            if i < len(all_files) - 1:
                time.sleep(self._sleep)
        if self._store.has_staging():
            self._run_consolidation("final")
        cfg_xref = getattr(cfg, "bible_cross_ref", True)
        if cfg_xref and stats["scanned"] > 0:
            self._run_cross_reference()
        self._print_final_stats(stats, len(all_files))
        return stats

    def _run_consolidation(self, batch_label: str) -> None:
        staging = self._store.load_all_staging()
        if not staging:
            return
        print(f"\n  🔄 Consolidation [{batch_label}]: {len(staging)} chapters...")
        try:
            from littrans.utils.data_versioning import backup, prune_old_backups
            for db_file in self._store._db_dir.glob("*.json"):
                if db_file.name != "index.json":
                    backup(db_file)
                    prune_old_backups(db_file, keep=3)
            wb_path = self._store._dir / "worldbuilding.json"
            if wb_path.exists():
                backup(wb_path)
                prune_old_backups(wb_path, keep=3)
        except Exception as e:
            logging.warning(f"[BibleScanner] Backup lỗi: {e}")

        # ── Enrichment pass: enrich entities đã biết TRƯỚC khi consolidate ──
        try:
            from littrans.context.bible_enricher import BibleEnricher
            enrich_result = BibleEnricher(self._store).run(staging)
            if enrich_result.entities_enriched:
                print(
                    f"  🔮 Enriched: {enrich_result.entities_enriched} entities · "
                    f"skipped: {enrich_result.entities_skipped}"
                )
        except Exception as e:
            logging.warning(f"[BibleScanner] Enrichment lỗi (bỏ qua): {e}")
            print(f"  ⚠️  Enrichment lỗi (bỏ qua): {e}")

        try:
            from littrans.context.bible_consolidator import BibleConsolidator
            result = BibleConsolidator(self._store).run(staging)
            print(
                f"  ✅ Consolidated: +{result.chars_added} nhân vật · "
                f"+{result.entities_added} entities · "
                f"+{result.lore_chapters} lore entries"
            )
            if result.errors:
                print(f"  ⚠️  {len(result.errors)} lỗi:")
                for err in result.errors[:5]:
                    print(f"     {err}")
            failed_chapters = {err.split(":")[0].strip() for err in result.errors if err}
            successful = [
                s.source_chapter for s in staging
                if s.source_chapter not in failed_chapters
            ]
            if successful:
                self._store.clear_staging(successful)
        except Exception as e:
            logging.error(f"[BibleScanner] Consolidation lỗi: {e}")
            print(f"  ⚠️  Consolidation lỗi: {e} → staging giữ nguyên")

    def _run_cross_reference(self) -> None:
        print(f"\n  🔎 Cross-reference đang chạy...")
        try:
            from littrans.context.cross_reference import CrossReferenceEngine
            report = CrossReferenceEngine(self._store).run()
            print(
                f"  📊 Cross-reference xong: health={report.health_score:.0%} · "
                f"{report.total_issues} issues "
                f"({len(report.errors)} errors, {len(report.warnings)} warnings)"
            )
        except Exception as e:
            logging.error(f"[BibleScanner] Cross-reference lỗi: {e}")
            print(f"  ⚠️  Cross-reference lỗi: {e}")

    def _verification_call(self, output: ScanOutput, chapter_text: str, filename: str) -> ScanOutput:
        if len(output.database_candidates) < 2:
            return output
        verify_system = (
            'Bạn là AI kiểm tra chất lượng dữ liệu. Đọc danh sách entities. '
            'Tìm entity nào CÓ VẺ cùng một nhân vật/địa điểm/vật phẩm được gọi khác tên. '
            'Trả về JSON: {"duplicates": [{"idx_a": 0, "idx_b": 1, "reason": "..."}]}'
        )
        cand_summary = "\n".join(
            f"{i}. [{c.entity_type}] {c.en_name} → {c.canonical_name}: {c.description}"
            for i, c in enumerate(output.database_candidates[:30])
        )
        try:
            result = _call_json(verify_system, f"Entities từ {filename}:\n\n{cand_summary}")
            if not isinstance(result, dict):
                return output
            skip_idxs = {
                d["idx_b"] for d in result.get("duplicates", [])
                if isinstance(d, dict)
            }
            output.database_candidates = [
                c for i, c in enumerate(output.database_candidates)
                if i not in skip_idxs
            ]
            if skip_idxs:
                print(f"    🔧 Verification: bỏ {len(skip_idxs)} duplicates")
        except Exception as e:
            logging.warning(f"[BibleScanner] Verification call lỗi: {e}")
        return output

    def _sorted_inputs(self, input_dir: Path) -> list[str]:
        if not input_dir.exists():
            return []
        files = [f.name for f in input_dir.iterdir() if f.suffix in (".txt", ".md")]
        return sorted(
            files,
            key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)],
        )

    def _current_model(self) -> str:
        try:
            return _get_settings().gemini_model
        except Exception:
            return "unknown"

    def _print_final_stats(self, stats: dict[str, int], total: int) -> None:
        print(f"\n{'═'*62}\n  📖 BIBLE SCAN — Hoàn tất")
        print(
            f"  Tổng: {total} · Scanned: {stats['scanned']} · "
            f"Skipped: {stats['skipped']} · Failed: {stats['failed']}"
        )
        by_type = self._store.get_stats().get("by_type", {})
        if by_type:
            print(f"  Database: {' · '.join(f'{k}:{v}' for k, v in sorted(by_type.items()))}")
        print(f"{'═'*62}\n")