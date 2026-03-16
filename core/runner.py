"""
core/runner.py — Điều phối pipeline dịch tuần tự v3.

LUỒNG TỔNG QUAN:
┌────────────────────────────────────────────────────────────────┐
│  process_chapters()                                             │
│                                                                 │
│  ① Nạp tài liệu, lọc chương chưa dịch                          │
│                                                                 │
│  ② Vòng lặp tuần tự (mỗi chương):                              │
│     a. Scout refresh (nếu đến kỳ):                             │
│        • Xóa Context_Notes cũ → sinh mới                       │
│        • Append Arc_Memory (tóm tắt window vừa xong)           │
│        • Rotate nhân vật lâu không xuất hiện → Archive         │
│     b. Dịch chương:                                            │
│        • Build context (glossary + characters + memory)         │
│        • Build system prompt 7 phần                            │
│        • Gọi Gemini API (retry nếu lỗi)                        │
│        • Ghi file dịch (atomic write)                          │
│        • Cập nhật Glossary + Characters                         │
│        • touch_seen() → cập nhật last_seen cho rotation        │
│     c. Sync staging → Active (nếu IMMEDIATE_MERGE=true)        │
│                                                                 │
│  ③ Retry pass (RETRY_FAILED_PASSES vòng)                       │
│  ④ Final sync + Auto-merge + Tổng kết                          │
└────────────────────────────────────────────────────────────────┘

SCOUT TRIGGER: chapters_done % SCOUT_REFRESH_EVERY == 0
  → Trước chương 1 (chapters_done=0)
  → Sau mỗi SCOUT_REFRESH_EVERY chương thành công
"""
import os, re, time, tempfile, logging

from .config import (
    RAW_DIR, TRANS_DIR, INSTRUCTIONS_FILE, CHAR_INSTRUCTIONS_FILE,
    MAX_RETRIES, SUCCESS_SLEEP, RATE_LIMIT_SLEEP,
    MIN_CHARS_PER_CHAPTER, IMMEDIATE_MERGE,
    AUTO_MERGE_GLOSSARY, AUTO_MERGE_CHARACTERS, RETRY_FAILED_PASSES,
    GEMINI_MODEL, SCOUT_REFRESH_EVERY,
)
from .io_utils      import load_text
from .glossary      import filter_glossary, add_new_terms, has_pending_terms, count_pending_terms
from .characters    import (filter_characters, update_from_response,
                             sync_staging_to_active, has_staging_chars,
                             rotate_to_archive, touch_seen, character_stats)
from .ai_client     import call_gemini, is_rate_limit
from . import scout
from .arc_memory    import load_recent as load_arc_memory
from .prompt        import build as build_prompt
from .name_lock     import build_name_lock_table, validate_translation, lock_stats
from .skills        import load_skills_for_chapter, add_skill_updates, skills_stats

# ── Ngưỡng kiểm tra chất lượng bản dịch ─────────────────────────
MIN_TRANSLATION_LINES  = 10    # Số dòng không rỗng tối thiểu (tuyệt đối)
MAX_LINE_LENGTH        = 1000  # Ký tự/dòng tối đa — vượt ngưỡng = dính dòng
MAX_MERGED_LINE_RATIO  = 0.75  # Nếu hơn 75% số dòng bị mất so với bản gốc → dính nhiều dòng
MIN_BLANK_LINE_RATIO   = 0.20  # Dòng trống phải chiếm ít nhất 20% tổng số dòng


# ═══════════════════════════════════════════════════════════════════
# KIỂM TRA CHẤT LƯỢNG BẢN DỊCH
# ═══════════════════════════════════════════════════════════════════

def _check_translation_quality(translation: str, source_text: str = "") -> tuple[bool, str]:
    """
    Kiểm tra bản dịch có bị lỗi dính dòng / thiếu dòng trống không.

    Trả về (True, "") nếu ổn.
    Trả về (False, mô_tả_lỗi) nếu phát hiện vấn đề.

    Bốn tiêu chí (theo mức độ nghiêm trọng giảm dần):
      1. Có dòng dài hơn MAX_LINE_LENGTH ký tự
         → Dính dòng cực nghiêm trọng (toàn bộ gộp vào 1–2 dòng)
      2. Số dòng không rỗng < MIN_TRANSLATION_LINES
         → Quá ít dòng tuyệt đối
      3. Tỉ lệ dòng mất so với bản gốc > MAX_MERGED_LINE_RATIO (75%)
         → Dính nhiều dòng một phần
      4. Tỉ lệ dòng trống / tổng số dòng < MIN_BLANK_LINE_RATIO (20%)
         → Thiếu dòng trống ngăn cách giữa các đoạn văn
    """
    if not translation or not translation.strip():
        return False, "Bản dịch rỗng."

    all_lines       = translation.splitlines()
    non_empty_lines = [l for l in all_lines if l.strip()]
    blank_lines     = [l for l in all_lines if not l.strip()]
    line_count      = len(non_empty_lines)
    total_lines     = len(all_lines)

    # ── Tiêu chí 1: dòng quá dài ────────────────────────────────────
    long_lines = [l for l in non_empty_lines if len(l) > MAX_LINE_LENGTH]
    if long_lines:
        longest = max(len(l) for l in long_lines)
        return False, (
            f"DÍNH DÒNG NGHIÊM TRỌNG: {len(long_lines)} dòng vượt {MAX_LINE_LENGTH} ký tự "
            f"(dòng dài nhất: {longest} ký tự). "
            f"Toàn bộ nội dung bị gộp vào một số dòng duy nhất."
        )

    # ── Tiêu chí 2: quá ít dòng tuyệt đối ─────────────────────────
    if line_count < MIN_TRANSLATION_LINES:
        return False, (
            f"DÍNH DÒNG: Bản dịch chỉ có {line_count} dòng "
            f"(tối thiểu: {MIN_TRANSLATION_LINES}). "
            f"Nhiều đoạn văn bị gộp thành một dòng."
        )

    # ── Tiêu chí 3: so sánh tỉ lệ dòng với bản gốc ─────────────────
    if source_text and source_text.strip():
        src_lines = len([l for l in source_text.splitlines() if l.strip()])
        if src_lines >= MIN_TRANSLATION_LINES:
            lost_ratio = (src_lines - line_count) / src_lines
            if lost_ratio > MAX_MERGED_LINE_RATIO:
                lost_pct = int(lost_ratio * 100)
                return False, (
                    f"DÍNH DÒNG NHIỀU CHỖ: Bản gốc có {src_lines} dòng, "
                    f"bản dịch chỉ còn {line_count} dòng "
                    f"(mất {lost_pct}% số dòng, ngưỡng: {int(MAX_MERGED_LINE_RATIO*100)}%). "
                    f"Nhiều đoạn văn bị gộp lại — cần xuống dòng đúng như bản gốc."
                )

    # ── Tiêu chí 4: thiếu dòng trống ngăn cách đoạn văn ────────────
    # Chỉ kiểm tra khi đủ dòng để có nghĩa (tránh false positive chương rất ngắn)
    if total_lines >= MIN_TRANSLATION_LINES:
        blank_ratio = len(blank_lines) / total_lines if total_lines > 0 else 0
        if blank_ratio < MIN_BLANK_LINE_RATIO:
            blank_pct  = int(blank_ratio * 100)
            return False, (
                f"THIẾU DÒNG TRỐNG: Chỉ {len(blank_lines)}/{total_lines} dòng là dòng trống "
                f"({blank_pct}%, ngưỡng tối thiểu: {int(MIN_BLANK_LINE_RATIO*100)}%). "
                f"Các đoạn văn CHƯA được cách nhau bằng dòng trống — "
                f"mỗi đoạn văn phải cách nhau đúng 1 dòng trống."
            )

    return True, ""


# ═══════════════════════════════════════════════════════════════════
# DỊCH MỘT CHƯƠNG
# ═══════════════════════════════════════════════════════════════════

def process_single_chapter(
    filename         : str,
    filepath         : str,
    out_filepath     : str,
    instructions_text: str,
    char_instructions: str,
    chapter_index    : int,
) -> bool:
    """
    Dịch 1 chương. Trả về True nếu thành công.

    ⚠️  TUẦN TỰ TUYỆT ĐỐI: hàm này KHÔNG được gọi đồng thời từ nhiều thread.
    Pipeline đảm bảo điều đó bằng vòng lặp for đơn trong process_chapters().

    Quy trình:
      1. Đọc file gốc & kiểm tra độ dài
      2. Lọc Glossary (phân category) + Characters (có cả Archive)
      3. Nạp Arc_Memory (N entry gần nhất) + Context_Notes
      4. Build Name Lock Table (bảng tên đã chốt xuyên suốt toàn bộ truyện)
      5. Build system prompt 8 phần
      6. Gọi Gemini API (retry với backoff):
         a. Nếu retry do lỗi chất lượng → đính kèm cảnh báo vào input
         b. Kiểm tra chất lượng (dính dòng) TRƯỚC khi cập nhật Glossary/Characters
         c. Cảnh báo chất lượng chỉ tồn tại trong retry loop của chương này,
            sang chương mới là xoá hoàn toàn.
      7. Validate Name Lock vi phạm
      8. Atomic write file dịch
      9. Cập nhật Glossary + Characters + touch_seen
    """
    text = load_text(filepath)
    if not text.strip():
        print(f"  ⚠️  File rỗng, bỏ qua: {filename}"); return False
    if MIN_CHARS_PER_CHAPTER > 0 and len(text) < MIN_CHARS_PER_CHAPTER:
        print(f"  ⚠️  Chương ngắn: {len(text)} ký tự (ngưỡng {MIN_CHARS_PER_CHAPTER})")

    print(f"\n▶  [{chapter_index+1}] Dịch: {filename}")

    # Build context
    glossary_ctx  = filter_glossary(text)
    char_profiles = filter_characters(text)
    arc_mem       = load_arc_memory()
    ctx_notes     = scout.load_context_notes()

    # Build Name Lock Table — snapshot tại thời điểm này
    name_lock    = build_name_lock_table()
    # Skills đã biết xuất hiện trong chương — cho system box context
    known_skills = load_skills_for_chapter(text)

    total_terms = sum(len(v) for v in glossary_ctx.values())
    print(f"     Glossary: {total_terms} terms · Characters: {len(char_profiles)} · "
          f"Name Lock: {len(name_lock)} tên · Skills: {len(known_skills)} · "
          f"Arc entries: {'có' if arc_mem else 'chưa có'}")

    system_prompt = build_prompt(
        instructions     = instructions_text,
        glossary_ctx     = glossary_ctx,
        char_profiles    = char_profiles,
        char_instructions= char_instructions,
        arc_memory_text  = arc_mem,
        context_notes    = ctx_notes,
        name_lock_table  = name_lock,
        known_skills     = known_skills,
    )

    # quality_warning: chỉ sống trong retry loop của chương này.
    # Khi hàm kết thúc (thành công hay thất bại), biến này bị huỷ.
    # Sang chương mới → gọi hàm mới → quality_warning = "" từ đầu.
    quality_warning = ""

    # Gọi API với retry
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"  ⚙️  API call {attempt}/{MAX_RETRIES} | {GEMINI_MODEL}")

            # Nếu đang retry do lỗi chất lượng → đính kèm cảnh báo vào đầu input.
            # AI sẽ thấy lỗi cụ thể và biết cần sửa gì.
            if quality_warning:
                input_text = (
                    f"⚠️ CẢNH BÁO: Bản dịch lần trước bị lỗi — {quality_warning}\n"
                    f"Hãy dịch lại TOÀN BỘ chương dưới đây, đảm bảo:\n"
                    f"  • GIỮ NGUYÊN cấu trúc đoạn văn của bản gốc\n"
                    f"  • MỖI đoạn văn gốc = MỘT đoạn văn trong bản dịch\n"
                    f"  • KHÔNG gộp nhiều đoạn thành một dòng\n"
                    f"  • Xuống dòng đúng như bản gốc\n\n"
                    f"--- NỘI DUNG GỐC ---\n\n{text}"
                )
            else:
                input_text = text

            result = call_gemini(system_prompt, input_text)

            # ── Kiểm tra chất lượng TRƯỚC khi cập nhật Glossary/Characters ──
            quality_ok, quality_msg = _check_translation_quality(result.translation, text)
            if not quality_ok:
                logging.warning(f"{filename} | attempt {attempt} | Quality: {quality_msg}")
                print(f"  ⚠️  Lỗi chất lượng (attempt {attempt}/{MAX_RETRIES}): {quality_msg}")
                if attempt < MAX_RETRIES:
                    quality_warning = quality_msg   # lưu để đính kèm vào lần retry tiếp
                    print(f"  🔄 Yêu cầu AI dịch lại...")
                    _wait_quality(attempt)
                    continue                         # KHÔNG cập nhật gì, retry ngay
                else:
                    # Hết lượt retry — ghi file kèm cảnh báo để người dùng kiểm tra
                    print(f"  ⚠️  Vẫn còn lỗi chất lượng sau {MAX_RETRIES} lần. Ghi file để kiểm tra thủ công.")

            # ── Validate Name Lock ────────────────────────────────────────────
            lock_violations = validate_translation(result.translation, name_lock)
            if lock_violations:
                print(f"  🔒 Name Lock — {len(lock_violations)} vi phạm:")
                for w in lock_violations:
                    print(f"     {w}")
                logging.warning(
                    f"{filename} | Name Lock violations:\n" +
                    "\n".join(lock_violations)
                )
                # Ghi tên sai → tên đúng vào file để fix_names.py xử lý sau
                _record_name_violations(lock_violations, name_lock, filename)
                print(f"  ⚠️  Đã ghi vi phạm vào name_fixes.json — chạy fix_names.py để sửa.")

            # ── Ghi file ──────────────────────────────────────────────────────
            _atomic_write(out_filepath, result.translation)
            print(f"  ✅ Dịch xong: {filename}")

            # ── Cập nhật Glossary ─────────────────────────────────────────────
            n_terms = add_new_terms(result.new_terms, filename)
            if n_terms: print(f"  📝 Thuật ngữ mới: {n_terms}")

            # ── Cập nhật Skills ───────────────────────────────────────────────
            n_skills = add_skill_updates(result.skill_updates, filename)
            if n_skills: print(f"  ⚔️  Kỹ năng mới/tiến hóa: {n_skills}")

            # ── Cập nhật Characters ───────────────────────────────────────────
            n_chars, n_rels = update_from_response(
                result.new_characters, result.relationship_updates,
                filename, chapter_index,
            )
            if n_chars:
                dest = "Active" if IMMEDIATE_MERGE else "Staging"
                print(f"  👤 Nhân vật mới: {n_chars} → {dest}")
            if n_rels: print(f"  🔗 Quan hệ cập nhật: {n_rels}")

            # ── Cập nhật last_seen để rotation chính xác ─────────────────────
            touch_seen(list(char_profiles.keys()), chapter_index)

            time.sleep(SUCCESS_SLEEP)
            return True

        except Exception as e:
            logging.error(f"{filename} | attempt {attempt} | {e}")
            print(f"  ❌ Lỗi {attempt}/{MAX_RETRIES}: {e}")
            if attempt >= MAX_RETRIES:
                print(f"  🛑 Bỏ qua sau {MAX_RETRIES} lần thử."); return False
            _wait(e, attempt)

    return False


# ═══════════════════════════════════════════════════════════════════
# PIPELINE CHÍNH
# ═══════════════════════════════════════════════════════════════════

def process_chapters() -> None:
    """
    Pipeline chính. Dịch tuần tự từng chương — KHÔNG song song.

    Lý do tuần tự:
      - Chương N+1 cần đọc kết quả Glossary/Characters/Arc Memory của chương N.
      - Nếu song song → context bị lộn xộn, tên/xưng hô mất nhất quán.
      - Không yêu cầu tốc độ, chỉ yêu cầu CHẤT LƯỢNG và NHẤT QUÁN.
    """
    if not os.path.exists(RAW_DIR):
        print(f"❌ Không tìm thấy '{RAW_DIR}'."); return

    os.makedirs(TRANS_DIR, exist_ok=True)
    _ensure_data_dirs()

    instructions_text = load_text(INSTRUCTIONS_FILE)
    char_instructions = load_text(CHAR_INSTRUCTIONS_FILE)
    if not char_instructions:
        print("⚠️  Không tìm thấy CHARACTER_PROFILING_INSTRUCTIONS.md")

    all_files = _sorted_files(RAW_DIR)
    if not all_files:
        print(f"❌ Không có file nào trong '{RAW_DIR}'."); return

    pending = _get_pending(all_files)
    _print_banner(all_files, pending)

    if not pending:
        print("✅ Tất cả chương đã được dịch.")
        _final_merge(); return

    # ── Vòng lặp chính ────────────────────────────────────────────
    total_ok = total_fail = 0
    failed   = []
    chapters_done = 0  # Số chương dịch thành công trong session

    for file_index, fn, fp, op in pending:

        # a. Scout refresh
        if scout.should_refresh(chapters_done):
            reason = "khởi động" if chapters_done == 0 else f"sau {chapters_done} chương"
            print(f"\n🔭 Scout AI ({reason})...")
            try:
                scout.run(all_files, file_index)
            except Exception as e:
                logging.error(f"Scout thất bại: {e}")
                print(f"  ⚠️  Scout gặp lỗi: {e} — tiếp tục không có ghi chú.")

            # Rotate nhân vật lâu không xuất hiện → Archive
            n_archived = rotate_to_archive(file_index)
            if n_archived:
                print(f"  📦 Archived {n_archived} nhân vật ít xuất hiện.")

        # b. Dịch chương
        ok = process_single_chapter(
            fn, fp, op, instructions_text, char_instructions, file_index
        )

        if ok:
            total_ok      += 1
            chapters_done += 1
            # c. Sync staging → Active
            if IMMEDIATE_MERGE:
                n, _ = sync_staging_to_active()
                if n: print(f"  🔄 Merged {n} nhân vật → Active")
        else:
            total_fail += 1
            failed.append((file_index, fn, fp, op))

    # ── Retry pass ────────────────────────────────────────────────
    failed = _retry_passes(failed, instructions_text, char_instructions)

    # ── Kết thúc ──────────────────────────────────────────────────
    if IMMEDIATE_MERGE:
        n, _ = sync_staging_to_active()
        if n: print(f"\n🔄 Final sync: {n} nhân vật → Active")

    _final_merge()
    _print_summary(total_ok, total_fail, failed)


# ═══════════════════════════════════════════════════════════════════
# RETRY PASSES
# ═══════════════════════════════════════════════════════════════════

def _retry_passes(failed, instructions_text, char_instructions):
    for retry_num in range(1, RETRY_FAILED_PASSES + 1):
        still = [(fi,fn,fp,op) for fi,fn,fp,op in failed if not os.path.exists(op)]
        if not still:
            print(f"\n✅ Không còn chương thất bại (trước retry {retry_num})."); break
        print(f"\n{'─'*55}")
        print(f"🔄 Retry {retry_num}/{RETRY_FAILED_PASSES} — {len(still)} chương")
        print(f"   Chờ {RATE_LIMIT_SLEEP}s..."); time.sleep(RATE_LIMIT_SLEEP)
        new_failed = []
        for fi, fn, fp, op in still:
            ok = process_single_chapter(fn, fp, op, instructions_text, char_instructions, fi)
            if ok:
                if IMMEDIATE_MERGE: sync_staging_to_active()
            else:
                new_failed.append((fi,fn,fp,op))
        failed = new_failed
    return failed


# ═══════════════════════════════════════════════════════════════════
# AUTO-MERGE
# ═══════════════════════════════════════════════════════════════════

def _final_merge():
    _maybe_merge_glossary()
    _maybe_merge_characters()

def _maybe_merge_glossary():
    if not has_pending_terms(): return
    n = count_pending_terms()
    if AUTO_MERGE_GLOSSARY:
        print(f"\n📚 Auto-merge ~{n} thuật ngữ...")
        ok = _run_script("clean_glossary.py", "clean_glossary")
        print("   ✅ Xong." if ok else "   → Chạy thủ công: python clean_glossary.py")
    else:
        print(f"\n💡 Có ~{n} thuật ngữ mới trong Staging_Terms.md.")
        print("   Chạy: python clean_glossary.py (hoặc AUTO_MERGE_GLOSSARY=true)")

def _maybe_merge_characters():
    n = has_staging_chars()
    if not n: return
    if AUTO_MERGE_CHARACTERS:
        print(f"\n👤 Auto-merge {n} nhân vật...")
        ok = _run_script("clean_characters.py", "action_merge")
        print("   ✅ Xong." if ok else "   → Chạy thủ công: python clean_characters.py --action merge")
    else:
        print(f"\n💡 Có {n} nhân vật mới trong Staging_Characters.json.")
        print("   Chạy: python clean_characters.py --action merge")


# ═══════════════════════════════════════════════════════════════════
# HELPER PRIVATE
# ═══════════════════════════════════════════════════════════════════

def _sorted_files(directory: str) -> list[str]:
    files = [f for f in os.listdir(directory) if f.endswith((".txt", ".md"))]
    return sorted(files, key=lambda s: [
        int(t) if t.isdigit() else t.lower()
        for t in re.split(r"(\d+)", s)
    ])

def _get_pending(all_files: list[str]) -> list[tuple]:
    pending = []
    for i, fn in enumerate(all_files):
        base, _ = os.path.splitext(fn)
        out = os.path.join(TRANS_DIR, f"{base}_VN.txt")
        if os.path.exists(out):
            print(f"⏭️  Bỏ qua (đã dịch): {fn}")
        else:
            pending.append((i, fn, os.path.join(RAW_DIR, fn), out))
    return pending

def _atomic_write(filepath: str, content: str) -> None:
    out_dir = os.path.dirname(filepath) or "."
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(content)
        os.replace(tmp, filepath)
    except Exception:
        os.path.exists(tmp) and os.remove(tmp); raise

def _record_name_violations(violations: list[str], name_lock: dict[str, str], filename: str) -> None:
    """
    Ghi tên sai → tên đúng vào data/name_fixes.json để fix_names.py xử lý sau.

    Format file:
    {
      "fixes": {
        "Dawn Association": {            ← tên tiếng Anh (tên sai còn sót trong bản dịch)
          "correct": "Hội Bình Minh",   ← tên đúng theo Name Lock
          "chapters": ["ch01.md", ...]  ← chương nào bị vi phạm
        }
      }
    }
    """
    import re
    from pathlib import Path
    fixes_path = Path("data") / "name_fixes.json"
    fixes_path.parent.mkdir(parents=True, exist_ok=True)

    data = load_json(str(fixes_path)) or {"fixes": {}}
    fixes = data.setdefault("fixes", {})

    # Parse từng violation: "  ⚠️  Tên gốc 'X' còn sót → phải dùng 'Y'"
    for v in violations:
        m = re.search(r"Tên gốc '(.+?)' còn sót → phải dùng '(.+?)'", v)
        if not m:
            continue
        wrong   = m.group(1).strip()
        correct = m.group(2).strip()
        if wrong not in fixes:
            fixes[wrong] = {"correct": correct, "chapters": []}
        entry = fixes[wrong]
        # Cập nhật correct nếu khác (Name Lock có thể đã thay đổi)
        if entry.get("correct") != correct:
            entry["correct"] = correct
        if filename not in entry.get("chapters", []):
            entry.setdefault("chapters", []).append(filename)

    from .io_utils import save_json
    save_json(str(fixes_path), data)


def _wait(exc: Exception, attempt: int) -> None:
    if is_rate_limit(exc):
        print(f"  ⚠️  Rate limit → chờ {RATE_LIMIT_SLEEP}s...")
        time.sleep(RATE_LIMIT_SLEEP)
    else:
        delay = min(10 * (2 ** (attempt - 1)), 120)
        print(f"  ⏳ Backoff {delay}s..."); time.sleep(delay)

def _wait_quality(attempt: int) -> None:
    """Chờ ngắn trước khi retry do lỗi chất lượng (không phải lỗi API)."""
    delay = min(5 * attempt, 30)
    print(f"  ⏳ Chờ {delay}s trước khi retry...")
    time.sleep(delay)

def _run_script(script_name: str, fn_name: str) -> bool:
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parent.parent / script_name
    if not path.exists(): return False
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        getattr(mod, fn_name)(); return True
    except Exception as e:
        logging.error(f"_run_script({script_name}): {e}"); return False

def _ensure_data_dirs():
    from .config import GLOSSARY_DIR, CHAR_DIR, MEM_DIR, SKILLS_FILE
    for d in [GLOSSARY_DIR, CHAR_DIR, MEM_DIR, SKILLS_FILE.parent]:
        d.mkdir(parents=True, exist_ok=True)

def _print_banner(all_files, pending):
    stats = character_stats()
    nl    = lock_stats()
    sk    = skills_stats()
    print(f"\n{'═'*62}")
    print(f"  Pipeline Dịch Truyện v3 — {GEMINI_MODEL}")
    print(f"{'─'*62}")
    print(f"  Tổng chương      : {len(all_files)}")
    print(f"  Cần dịch         : {len(pending)}")
    print(f"  Nhân vật Active  : {stats['active']}")
    print(f"  Nhân vật Archive : {stats['archive']}")
    print(f"  Name Lock        : {nl['total_locked']} tên đã chốt")
    print(f"  Kỹ năng đã biết  : {sk['total']} ({sk['evolution']} tiến hóa)")
    print(f"  Scout lookback   : {SCOUT_REFRESH_EVERY} chương/lần, đọc {__import__('core.config',fromlist=['SCOUT_LOOKBACK']).SCOUT_LOOKBACK} chương")
    print(f"  Arc Memory window: {__import__('core.config',fromlist=['ARC_MEMORY_WINDOW']).ARC_MEMORY_WINDOW} entry")
    print(f"  Dịch tuần tự     : ✅ (từng chương, không song song)")
    print(f"  Merge mode       : {'Ngay sau mỗi chương' if IMMEDIATE_MERGE else 'Cuối pipeline'}")
    print(f"  Retry passes     : {RETRY_FAILED_PASSES}")
    print(f"{'═'*62}\n")

def _print_summary(total_ok, total_fail, failed):
    remaining = [fn for _,fn,_,op in failed if not os.path.exists(op)]
    print(f"\n{'═'*62}")
    print(f"  ✅ Thành công : {total_ok} chương")
    print(f"  ❌ Thất bại   : {len(remaining)} chương")
    if remaining:
        for fn in remaining: print(f"     • {fn}")
        print(f"  → Chi tiết: logs/translation_errors.log")
    print(f"{'═'*62}")