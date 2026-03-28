"""
src/littrans/tools/epub_processor.py — EPUB → inputs/{epub_name}/ pipeline.

Flow:
  epub/{name}.epub
    → Phase 0: AI phân tích cấu trúc, xác định ranh giới chương
    → Phase 1: Cắt doc EPUB thành file .txt thô (Temp_Raw_TXT/{name}/)
    → Phase 1.5: AI học pattern rác từ 3 mẫu → ruleset code-only
    → Phase 2: Làm sạch lai (code + AI khi cần)
    → inputs/{name}/chapter_0001.txt
    → inputs/{name}/chapter_0002.txt
    → ...

Tích hợp LiTTrans:
  - Dùng key_pool (llm.client) — rotate key, retry 429 tự động
  - Dùng settings cho tất cả paths
  - Output vào inputs/{name}/ sẵn sàng cho: translate --book {name}

Yêu cầu thêm: pip install ebooklib beautifulsoup4

[FIX] Xoá import _call_with_timeout (đã bị xoá khỏi client.py).
      Thay _call_with_timeout(_do, API_TIMEOUT) → _do() trực tiếp.
      Timeout được xử lý bởi http_options={'timeout': API_TIMEOUT} trong genai.Client.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import time
import random
from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm


# ═══════════════════════════════════════════════════════════════════
# DEPENDENCY HELPERS
# ═══════════════════════════════════════════════════════════════════

def _require_epub_deps():
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
        return ebooklib, epub, BeautifulSoup
    except ImportError:
        raise ImportError(
            "❌ Cần cài thêm thư viện để xử lý EPUB:\n"
            "   pip install ebooklib beautifulsoup4"
        )


def _get_settings():
    from littrans.config.settings import settings
    return settings


# ═══════════════════════════════════════════════════════════════════
# LLM CALL WRAPPERS  (dùng key_pool của LiTTrans)
# ═══════════════════════════════════════════════════════════════════

CHUNK_MAX_CHARS = 30_000
_DELAY_MIN      = 3
_DELAY_MAX      = 8


def _parse_retry_delay(error: Exception, default: float = 30.0) -> float:
    for pattern in [r'retry_delay\s*\{\s*seconds:\s*(\d+)', r'retry in\s*([\d.]+)s']:
        m = re.search(pattern, str(error))
        if m:
            return float(m.group(1)) + 2
    return default


def _epub_call_text(system: str, user: str) -> str:
    """Gọi Gemini → plain text. Dùng cho clean agent."""
    from google.genai import types
    # [FIX] Bỏ _call_with_timeout — timeout được xử lý bởi http_options trong genai.Client
    from littrans.llm.client import key_pool, is_rate_limit, handle_api_error
    settings = _get_settings()

    while True:
        def _do():
            return key_pool.current_client.models.generate_content(
                model=settings.gemini_model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.1,
                ),
            )
        try:
            resp = _do()  # [FIX] trực tiếp thay vì _call_with_timeout(_do, API_TIMEOUT)
            if not resp.parts:
                tqdm.write("    [!] AI trả về rỗng — giữ nguyên text.")
                return user
            key_pool.on_success()
            return resp.text or ""
        except Exception as e:
            if is_rate_limit(e):
                wait = _parse_retry_delay(e)
                tqdm.write(f"\n    [~] Rate limit. Chờ {wait:.0f}s...")
                time.sleep(wait)
                handle_api_error(e)
                continue
            handle_api_error(e)
            raise


def _epub_call_json(system: str, user: str) -> dict | list:
    """
    Gọi Gemini → JSON. Giữ nguyên list nếu structure analyst trả về list.
    """
    from google.genai import types
    # [FIX] Bỏ _call_with_timeout — timeout được xử lý bởi http_options trong genai.Client
    from littrans.llm.client import key_pool, is_rate_limit, handle_api_error
    settings = _get_settings()

    while True:
        def _do():
            return key_pool.current_client.models.generate_content(
                model=settings.gemini_model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
        try:
            resp = _do()  # [FIX] trực tiếp thay vì _call_with_timeout(_do, API_TIMEOUT)
            key_pool.on_success()
            raw   = resp.text or "{}"
            clean = re.sub(r"^```json\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)
            return json.loads(clean)
        except json.JSONDecodeError as e:
            logging.error(f"[EpubProcessor] JSON parse lỗi: {e}")
            return {}
        except Exception as e:
            if is_rate_limit(e):
                wait = _parse_retry_delay(e)
                tqdm.write(f"\n    [~] Rate limit. Chờ {wait:.0f}s...")
                time.sleep(wait)
                handle_api_error(e)
                continue
            handle_api_error(e)
            raise


# ═══════════════════════════════════════════════════════════════════
# TEXT UTILITIES
# ═══════════════════════════════════════════════════════════════════

def _split_into_chunks(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """Chia văn bản dài tại ranh giới đoạn — tránh cắt giữa câu."""
    if len(text) <= max_chars:
        return [text]
    chunks, buf, buf_len = [], [], 0
    for para in text.split('\n\n'):
        plen = len(para) + 2
        if buf_len + plen > max_chars and buf:
            chunks.append('\n\n'.join(buf))
            buf, buf_len = [], 0
        buf.append(para)
        buf_len += plen
    if buf:
        chunks.append('\n\n'.join(buf))
    return chunks


def _extract_paragraphs(soup) -> str:
    """Ưu tiên <p> để giữ cấu trúc. Fallback về get_text()."""
    paras = soup.find_all('p')
    if paras:
        return "\n\n".join(
            p.get_text(separator=' ').strip()
            for p in paras if p.get_text().strip()
        )
    return soup.get_text(separator='\n').strip()


def _load_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        logging.error(f"[EpubProcessor] Không tìm thấy prompt: {path}")
        return ""


# ═══════════════════════════════════════════════════════════════════
# PHASE 0 — PHÂN TÍCH CẤU TRÚC EPUB
# ═══════════════════════════════════════════════════════════════════

def _build_epub_structure(book) -> tuple[list[dict], dict]:
    """Quét spine + TOC → bản đồ cấu trúc."""
    ebooklib, epub_lib, BeautifulSoup = _require_epub_deps()

    toc_map: dict[str, str] = {}

    def _parse_toc(items):
        for item in items:
            if isinstance(item, epub_lib.Link):
                key = item.href.split('#')[0].split('/')[-1]
                toc_map[key] = item.title
            elif isinstance(item, tuple):
                sec, children = item
                if hasattr(sec, 'href') and sec.href:
                    key = sec.href.split('#')[0].split('/')[-1]
                    toc_map[key] = sec.title
                _parse_toc(children)

    _parse_toc(book.toc)

    structure = []
    for item_id in [s[0] for s in book.spine]:
        item = book.get_item_with_id(item_id)
        if not (item and item.get_type() == ebooklib.ITEM_DOCUMENT):
            continue

        soup  = BeautifulSoup(item.get_content(), 'html.parser')
        h_tag = soup.find(['h1', 'h2', 'h3'])
        imgs  = [
            os.path.basename(img.get('src', img.get('xlink:href', '')))
            for img in soup.find_all(['img', 'image'])
            if img.get('src') or img.get('xlink:href')
        ]
        for tag in soup.find_all(['img', 'image', 'svg']):
            tag.decompose()
        raw_text  = _extract_paragraphs(soup)
        item_href = os.path.basename(item.get_name())

        structure.append({
            "doc_id"   : item_id,
            "text_len" : len(raw_text),
            "heading"  : f"{h_tag.name} → \"{h_tag.get_text().strip()}\"" if h_tag else None,
            "images"   : imgs,
            "toc_title": toc_map.get(item_href),
            "preview"  : raw_text[:200].replace('\n', ' ').strip(),
            "raw_text" : raw_text,
        })

    return structure, toc_map


def _format_for_ai(structure: list[dict]) -> str:
    lines = []
    for doc in structure:
        lines += [
            f"[DOC_ID: {doc['doc_id']}]",
            f"  text_len   : {doc['text_len']}",
            f"  has_heading: {doc['heading'] or 'không'}",
            f"  has_images : {', '.join(doc['images']) if doc['images'] else 'không'}",
            f"  toc_title  : {doc['toc_title'] or 'không'}",
            f"  preview    : \"{doc['preview']}\"",
            "",
        ]
    return "\n".join(lines)


def _analyze_structure(structure: list[dict], prompt: str) -> list[dict] | None:
    """Phase 0: hỏi AI → list[{doc_id, is_chapter_start, title}]."""
    try:
        result = _epub_call_json(prompt, _format_for_ai(structure))
        if isinstance(result, list):
            n = sum(1 for r in result if r.get('is_chapter_start'))
            print(f"  [+] AI xác định {n} chương.")
            return result
        print("  [-] AI trả về định dạng lạ → fallback.")
        return None
    except Exception as e:
        logging.error(f"[EpubProcessor] Structure analysis: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# PHASE 1.5 — HỌC PATTERN RÁC
# ═══════════════════════════════════════════════════════════════════

def _learn_patterns(raw_files: list[str], prompt: str) -> dict | None:
    """Gửi 3 mẫu (đầu/giữa/cuối) → ruleset code-only."""
    n  = len(raw_files)
    idxs = [0, n // 2, n - 1] if n >= 3 else list(range(n))

    samples = ""
    for i, idx in enumerate(idxs, 1):
        body = Path(raw_files[idx]).read_text(encoding='utf-8').split('\n', 1)
        body = body[1].strip() if len(body) > 1 else ""
        if body:
            samples += f"=== SAMPLE {i} ===\n{body[:3_000]}\n\n"

    if not samples.strip():
        print("  [-] Mẫu rỗng, không học được pattern.")
        return None

    try:
        ruleset = _epub_call_json(prompt, samples)
        if not isinstance(ruleset, dict):
            return None

        ruleset.setdefault("remove_lines_exact", [])
        ruleset.setdefault("remove_lines_regex", [])
        ruleset.setdefault("remove_short_lines_below", 0)

        compiled, skipped = [], []
        for p in ruleset["remove_lines_regex"]:
            try:
                compiled.append(re.compile(p))
            except re.error as e:
                skipped.append(p)
                print(f"  [!] Bỏ qua regex không hợp lệ '{p}': {e}")
        ruleset["_compiled_regex"] = compiled
        ruleset["remove_lines_regex"] = [
            p for p in ruleset["remove_lines_regex"] if p not in skipped
        ]

        print(
            f"  [+] Ruleset: {len(ruleset['remove_lines_exact'])} exact, "
            f"{len(compiled)} regex, min_len={ruleset['remove_short_lines_below']}"
        )
        if ruleset.get("book_title"):
            print(f"      Tên sách: {ruleset['book_title']}")
        return ruleset

    except Exception as e:
        print(f"  [-] Lỗi học pattern: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — LÀM SẠCH
# ═══════════════════════════════════════════════════════════════════

def _apply_ruleset(text: str, ruleset: dict) -> str:
    """Áp ruleset bằng code thuần — không gọi AI."""
    exact_set   = set(ruleset.get("remove_lines_exact", []))
    compiled_rx = ruleset.get("_compiled_regex", [])
    min_len     = ruleset.get("remove_short_lines_below", 0)

    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            out.append("")
            continue
        if s in exact_set:
            continue
        if any(rx.search(s) for rx in compiled_rx):
            continue
        if min_len > 0 and len(s) < min_len:
            continue
        out.append(line)

    return re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()


def _needs_ai_review(text: str) -> bool:
    """Heuristic: > 5% dòng đáng ngờ VÀ >= 3 dòng → cần AI."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return False
    suspicious = sum(
        1 for l in lines
        if (len(l) < 20 and not l[-1:] in '.!?…"\':-—')
        or (l.isupper() and len(l) > 5)
    )
    if suspicious >= 3 and suspicious / len(lines) > 0.05:
        tqdm.write(f"    [~] {suspicious}/{len(lines)} dòng nghi ngờ → gọi AI.")
        return True
    return False


def _clean_with_ai(text: str, prompt: str) -> str:
    """Làm sạch bằng AI. Tự chia chunk nếu quá dài."""
    chunks  = _split_into_chunks(text)
    if len(chunks) > 1:
        tqdm.write(f"    [~] Chương dài ({len(text):,} ký tự) → {len(chunks)} chunks.")
    results = []
    for chunk in chunks:
        results.append(_epub_call_text(prompt, chunk))
        if len(chunks) > 1:
            time.sleep(2)
    return "\n\n".join(results)


# ═══════════════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EpubResult:
    epub_name      : str       = ""
    chapters_written: int      = 0
    chapters_skipped: int      = 0
    ai_chapters    : int       = 0
    code_chapters  : int       = 0
    output_dir     : str       = ""   # inputs/{epub_name}/
    errors         : list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def process_epub(
    epub_path   : str | Path,
    log_queue   = None,
) -> EpubResult:
    """
    Xử lý một file EPUB.

    Input  : epub/{name}.epub
    Output : inputs/{name}/chapter_0001.txt, chapter_0002.txt, ...

    log_queue: nếu có, stdout được đưa vào queue để UI stream.
    """
    _require_epub_deps()
    ebooklib, epub_lib, _ = _require_epub_deps()

    settings  = _get_settings()
    epub_path = Path(epub_path)
    epub_name = epub_path.stem

    # ── Paths ──────────────────────────────────────────────────────
    # inputs/{epub_name}/  — output cuối cùng
    chapter_dir = settings.input_dir / epub_name
    # Temp_Raw_TXT/{epub_name}/  — file tạm
    temp_dir    = settings.epub_temp_dir / epub_name
    # Images/{epub_name}/
    images_dir  = settings.epub_images_dir / epub_name

    chapter_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    result           = EpubResult(epub_name=epub_name, output_dir=str(chapter_dir))
    ai_count         = 0
    code_count       = 0

    def _log(msg: str):
        if log_queue:
            log_queue.put(msg)
        else:
            print(msg)

    _log(f"\n{'='*55}")
    _log(f"  ĐANG XỬ LÝ: {epub_name}")
    _log(f"  Output: inputs/{epub_name}/")
    _log(f"{'='*55}")

    # ── Tải prompts ────────────────────────────────────────────────
    clean_prompt     = _load_prompt(settings.epub_cut_agent_file)
    structure_prompt = _load_prompt(settings.epub_structure_analyst_file)
    learner_prompt   = _load_prompt(settings.epub_pattern_learner_file)

    if not clean_prompt or not structure_prompt or not learner_prompt:
        result.errors.append("Thiếu prompt file — kiểm tra prompts/epub_*.md")
        return result

    # ── RESUME check ───────────────────────────────────────────────
    existing_raw = sorted(glob.glob(str(temp_dir / "*.txt")))
    is_resuming  = len(existing_raw) > 0

    if is_resuming:
        _log(f"\n  ⏩ Resume: {len(existing_raw)} chương thô từ lần trước.")
        raw_files = existing_raw
    else:
        # ── Phase 0: Đọc EPUB ──────────────────────────────────────
        try:
            book = epub_lib.read_epub(str(epub_path))
        except Exception as e:
            result.errors.append(f"Lỗi đọc EPUB: {e}")
            return result

        # Lưu ảnh
        img_count = 0
        for item in book.get_items():
            if item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER):
                img_name = os.path.basename(item.get_name())
                (images_dir / img_name).write_bytes(item.get_content())
                img_count += 1
        _log(f"  Lưu {img_count} ảnh → Images/{epub_name}/")

        _log("\n[Phase 0] Phân tích cấu trúc EPUB...")
        structure, _ = _build_epub_structure(book)
        _log(f"  Tìm thấy {len(structure)} documents trong spine")

        ai_decisions = _analyze_structure(structure, structure_prompt)

        if ai_decisions is None:
            _log("  [!] Fallback: dùng h-tag để xác định chương.")
            ai_decisions = [
                {
                    "doc_id"          : doc["doc_id"],
                    "is_chapter_start": doc["heading"] is not None,
                    "title"           : (
                        doc["heading"].split('→')[-1].strip().strip('"')
                        if doc["heading"] else None
                    ),
                }
                for doc in structure
            ]
            if ai_decisions:
                ai_decisions[0]["is_chapter_start"] = True

        decision_map = {d["doc_id"]: d for d in ai_decisions}

        # ── Phase 1: Cắt chương thành file .txt tạm ────────────────
        _log("\n[Phase 1] Cắt chương...")
        ch_count   = 0
        cur_file   = None

        for doc in structure:
            raw_text = doc["raw_text"]
            if len(raw_text) < 150:
                continue

            decision = decision_map.get(doc["doc_id"], {})
            is_new   = decision.get("is_chapter_start", False)
            title    = decision.get("title") or ""

            if cur_file is None:
                is_new = True

            if is_new:
                ch_count += 1
                if not title:
                    title = f"Chương {ch_count}"
                title    = re.sub(r'[\n\r\t]', " ", title).strip()
                cur_file = str(temp_dir / f"{ch_count:04d}.txt")
                with open(cur_file, 'w', encoding='utf-8') as f:
                    f.write(f"---TITLE:{title}---\n{raw_text}\n")
            else:
                with open(cur_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n\n{raw_text}\n")

        _log(f"  Cắt xong: {ch_count} chương → {temp_dir}/")
        raw_files = sorted(glob.glob(str(temp_dir / "*.txt")))

    if not raw_files:
        _log("  [!] Không có file thô nào.")
        return result

    # ── Phase 1.5: Học pattern ─────────────────────────────────────
    _log("\n[Phase 1.5] AI học pattern rác...")
    ruleset = _learn_patterns(raw_files, learner_prompt)

    # ── Phase 2: Làm sạch & ghi chapters vào inputs/{name}/ ────────
    _log(f"\n[Phase 2] Làm sạch → inputs/{epub_name}/")

    for file_path in tqdm(raw_files, desc="  Làm sạch", unit="chương"):
        content = Path(file_path).read_text(encoding='utf-8')
        parts   = content.split('\n', 1)
        title   = parts[0].replace("---TITLE:", "").replace("---", "").strip()
        body    = parts[1] if len(parts) > 1 else ""

        # Tính số thứ tự từ tên file (0001.txt → 1)
        ch_num = int(Path(file_path).stem)

        # ── Luồng lai ──────────────────────────────────────────────
        used_ai = False
        if ruleset is not None:
            pre = _apply_ruleset(body, ruleset)
            if _needs_ai_review(pre):
                tqdm.write(f"    → {title} [code + AI]")
                cleaned = _clean_with_ai(pre, clean_prompt)
                ai_count += 1
                used_ai   = True
            else:
                tqdm.write(f"    → {title} [code only ✓]")
                cleaned    = pre
                code_count += 1
        else:
            tqdm.write(f"    → {title} [AI]")
            cleaned = _clean_with_ai(body, clean_prompt)
            ai_count += 1
            used_ai  = True
        # ──────────────────────────────────────────────────────────

        if not cleaned.strip() or "---EMPTY---" in cleaned:
            tqdm.write("       Bỏ qua (không có nội dung).")
            try:
                os.remove(file_path)
            except Exception:
                pass
            result.chapters_skipped += 1
            continue

        # Ghi ra inputs/{epub_name}/chapter_NNNN.txt
        out_file = chapter_dir / f"chapter_{ch_num:04d}.txt"
        out_file.write_text(
            f"# {title}\n\n{cleaned.strip()}\n",
            encoding='utf-8',
        )

        # Xóa file tạm SAU KHI ghi thành công
        try:
            os.remove(file_path)
        except Exception as e:
            tqdm.write(f"       [!] Không xóa được file tạm: {e}")

        result.chapters_written += 1
        if used_ai:
            time.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))

    # Dọn thư mục tạm nếu rỗng
    try:
        if not list(temp_dir.iterdir()):
            temp_dir.rmdir()
    except Exception:
        pass

    result.ai_chapters   = ai_count
    result.code_chapters = code_count

    total = ai_count + code_count
    _log(
        f"\n  📊 {code_count}/{total} code-only | {ai_count}/{total} AI-assisted"
    )
    _log(
        f"  ✅ {result.chapters_written} chapters → inputs/{epub_name}/\n"
        f"     Dịch: python scripts/main.py translate --book {epub_name}"
    )
    return result


def process_all_epubs(log_queue=None) -> list[EpubResult]:
    """Xử lý tất cả .epub trong epub/ folder."""
    settings  = _get_settings()
    epub_dir  = settings.epub_dir
    epub_dir.mkdir(parents=True, exist_ok=True)

    epub_files = sorted(epub_dir.glob("*.epub"))
    if not epub_files:
        msg = f"[-] Không có file .epub nào trong {epub_dir}/"
        if log_queue:
            log_queue.put(msg)
        else:
            print(msg)
        return []

    results = []
    for ep in epub_files:
        r = process_epub(ep, log_queue=log_queue)
        results.append(r)

    if log_queue:
        log_queue.put("__DONE__")
    return results