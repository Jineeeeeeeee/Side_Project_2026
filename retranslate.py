"""
retranslate.py — Dịch lại MỘT chương cụ thể theo yêu cầu.

CÁCH DÙNG:
    python retranslate.py                        # Chọn từ danh sách
    python retranslate.py 0005                   # Tìm file chứa "0005"
    python retranslate.py "Chapter 5"            # Tìm file chứa "Chapter 5"
    python retranslate.py --list                 # Liệt kê tất cả chương

Chương sẽ bị ghi đè bản dịch cũ (nếu có).
Glossary, Characters, Skills KHÔNG bị cập nhật lại từ chương này
(vì đã được cập nhật lần đầu — dùng để sửa bản dịch, không phải thêm data mới).
Dùng flag --update-data để cập nhật lại Glossary/Characters/Skills.
"""
import sys, os, re, argparse
sys.stdout.reconfigure(encoding="utf-8")


def find_chapter(keyword: str, all_files: list[str]) -> list[str]:
    """Tìm file theo keyword (không phân biệt hoa thường)."""
    kw = keyword.lower()
    return [f for f in all_files if kw in f.lower()]


def list_chapters(all_files: list[str], trans_dir: str) -> None:
    print(f"\n{'─'*62}")
    print(f"  {'#':<5} {'TRẠNG THÁI':<12} TÊN FILE")
    print(f"{'─'*62}")
    for i, fn in enumerate(all_files, 1):
        base, _ = os.path.splitext(fn)
        out = os.path.join(trans_dir, f"{base}_VN.txt")
        status = "✅ Đã dịch" if os.path.exists(out) else "⬜ Chưa dịch"
        print(f"  {i:<5} {status:<12} {fn}")
    print(f"{'─'*62}\n")


def pick_chapter_interactive(all_files: list[str], trans_dir: str) -> str | None:
    """Hiển thị danh sách và để người dùng chọn."""
    list_chapters(all_files, trans_dir)
    choice = input("Nhập số thứ tự hoặc một phần tên file: ").strip()
    if not choice:
        return None
    # Thử số thứ tự
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(all_files):
            return all_files[idx]
        print(f"❌ Số thứ tự {choice} không hợp lệ.")
        return None
    # Thử keyword
    found = find_chapter(choice, all_files)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        print(f"\n⚠️  Tìm thấy {len(found)} file khớp:")
        for i, f in enumerate(found, 1):
            print(f"  {i}. {f}")
        sub = input("Chọn số thứ tự: ").strip()
        if sub.isdigit() and 1 <= int(sub) <= len(found):
            return found[int(sub) - 1]
    print(f"❌ Không tìm thấy file khớp với '{choice}'.")
    return None


def retranslate(filename: str, update_data: bool = False) -> None:
    from core.config import RAW_DIR, TRANS_DIR
    from core.runner import (
        process_single_chapter, _sorted_files,
        _ensure_data_dirs, sync_staging_to_active,
    )
    from core.io_utils import load_text

    _ensure_data_dirs()

    all_files = _sorted_files(RAW_DIR)
    if filename not in all_files:
        print(f"❌ Không tìm thấy '{filename}' trong '{RAW_DIR}'.")
        return

    chapter_index = all_files.index(filename)
    filepath      = os.path.join(RAW_DIR, filename)
    base, _       = os.path.splitext(filename)
    out_filepath  = os.path.join(TRANS_DIR, f"{base}_VN.txt")
    os.makedirs(TRANS_DIR, exist_ok=True)

    # Xoá bản dịch cũ để process_single_chapter không bỏ qua
    if os.path.exists(out_filepath):
        os.remove(out_filepath)
        print(f"🗑️  Đã xoá bản dịch cũ: {os.path.basename(out_filepath)}")

    instructions_text = load_text("translateAGENT_INSTRUCTIONS.md")
    char_instructions = load_text("CHARACTER_PROFILING_INSTRUCTIONS.md")

    print(f"\n{'═'*62}")
    print(f"  Retranslate — chương {chapter_index + 1}/{len(all_files)}")
    print(f"  File: {filename}")
    print(f"  Cập nhật Glossary/Characters/Skills: {'✅ Có' if update_data else '❌ Không'}")
    print(f"{'═'*62}\n")

    if update_data:
        # Dịch bình thường — sẽ cập nhật data
        ok = process_single_chapter(
            filename, filepath, out_filepath,
            instructions_text, char_instructions,
            chapter_index,
        )
    else:
        # Dịch nhưng KHÔNG cập nhật Glossary/Characters/Skills
        ok = _retranslate_no_update(
            filename, filepath, out_filepath,
            instructions_text, char_instructions,
            chapter_index,
        )

    if ok:
        print(f"\n✅ Retranslate xong: {filename}")
        if update_data:
            sync_staging_to_active()
    else:
        print(f"\n❌ Retranslate thất bại: {filename}")


def _retranslate_no_update(
    filename, filepath, out_filepath,
    instructions_text, char_instructions, chapter_index,
) -> bool:
    """
    Dịch lại 1 chương mà KHÔNG cập nhật Glossary / Characters / Skills.
    Dùng khi chỉ muốn cải thiện bản dịch, không thêm data mới.
    """
    import time, logging
    from core.config import MAX_RETRIES, SUCCESS_SLEEP, GEMINI_MODEL
    from core.io_utils import load_text as _load
    from core.glossary import filter_glossary
    from core.characters import filter_characters, touch_seen
    from core.arc_memory import load_recent as load_arc_memory
    from core import scout
    from core.prompt import build as build_prompt
    from core.name_lock import build_name_lock_table, validate_translation
    from core.skills import load_skills_for_chapter
    from core.ai_client import call_gemini, is_rate_limit
    from core.runner import (
        _check_translation_quality, _atomic_write, _wait, _wait_quality,
    )

    text = _load(filepath)
    if not text.strip():
        print(f"  ⚠️  File rỗng."); return False

    print(f"\n▶  [retranslate] {filename}")

    glossary_ctx  = filter_glossary(text)
    char_profiles = filter_characters(text)
    arc_mem       = load_arc_memory()
    ctx_notes     = scout.load_context_notes()
    name_lock     = build_name_lock_table()
    known_skills  = load_skills_for_chapter(text)

    total_terms = sum(len(v) for v in glossary_ctx.values())
    print(f"     Glossary: {total_terms} terms · Characters: {len(char_profiles)} · "
          f"Name Lock: {len(name_lock)} tên · Skills: {len(known_skills)}")

    system_prompt = build_prompt(
        instructions      = instructions_text,
        glossary_ctx      = glossary_ctx,
        char_profiles     = char_profiles,
        char_instructions = char_instructions,
        arc_memory_text   = arc_mem,
        context_notes     = ctx_notes,
        name_lock_table   = name_lock,
        known_skills      = known_skills,
    )

    quality_warning = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"  ⚙️  API call {attempt}/{MAX_RETRIES} | {GEMINI_MODEL}")
            input_text = text
            if quality_warning:
                input_text = (
                    f"⚠️ CẢNH BÁO: Bản dịch lần trước bị lỗi — {quality_warning}\n"
                    f"Hãy dịch lại TOÀN BỘ chương dưới đây, đảm bảo:\n"
                    f"  • GIỮ NGUYÊN cấu trúc đoạn văn của bản gốc\n"
                    f"  • MỖI đoạn văn gốc = MỘT đoạn văn trong bản dịch\n"
                    f"  • KHÔNG gộp nhiều đoạn thành một dòng\n"
                    f"  • Xuống dòng và dòng trống đúng như bản gốc\n\n"
                    f"--- NỘI DUNG GỐC ---\n\n{text}"
                )

            result = call_gemini(system_prompt, input_text)

            quality_ok, quality_msg = _check_translation_quality(result.translation, text)
            if not quality_ok:
                logging.warning(f"{filename} | retranslate attempt {attempt} | Quality: {quality_msg}")
                print(f"  ⚠️  Lỗi chất lượng (attempt {attempt}/{MAX_RETRIES}): {quality_msg}")
                if attempt < MAX_RETRIES:
                    quality_warning = quality_msg
                    print(f"  🔄 Yêu cầu dịch lại...")
                    _wait_quality(attempt)
                    continue
                else:
                    print(f"  ⚠️  Vẫn còn lỗi chất lượng sau {MAX_RETRIES} lần. Ghi file để kiểm tra.")

            lock_violations = validate_translation(result.translation, name_lock)
            if lock_violations:
                print(f"  🔒 Name Lock — {len(lock_violations)} vi phạm:")
                for w in lock_violations:
                    print(f"     {w}")

            _atomic_write(out_filepath, result.translation)
            print(f"  ✅ Dịch xong (data không được cập nhật)")

            # Vẫn touch_seen để rotation không bị lệch
            touch_seen(list(char_profiles.keys()), chapter_index)

            time.sleep(SUCCESS_SLEEP)
            return True

        except Exception as e:
            logging.error(f"{filename} | retranslate attempt {attempt} | {e}")
            print(f"  ❌ Lỗi {attempt}/{MAX_RETRIES}: {e}")
            if attempt >= MAX_RETRIES:
                print(f"  🛑 Bỏ qua sau {MAX_RETRIES} lần thử."); return False
            sleep = 60 if "429" in str(e) or "rate" in str(e).lower() else min(10*(2**(attempt-1)), 120)
            print(f"  ⏳ Chờ {sleep}s..."); time.sleep(sleep)

    return False


def main():
    parser = argparse.ArgumentParser(
        description="Dịch lại một chương cụ thể.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ví dụ:\n"
            "  python retranslate.py                  # chọn từ danh sách\n"
            "  python retranslate.py 0005             # tìm file chứa '0005'\n"
            "  python retranslate.py --list           # liệt kê tất cả chương\n"
            "  python retranslate.py 0005 --update-data  # dịch lại + cập nhật data\n"
        )
    )
    parser.add_argument("keyword",  nargs="?", default="",
                        help="Từ khoá tìm tên file (số thứ tự hoặc một phần tên)")
    parser.add_argument("--list",   action="store_true",
                        help="Liệt kê tất cả chương và trạng thái dịch")
    parser.add_argument("--update-data", action="store_true",
                        help="Cập nhật lại Glossary / Characters / Skills sau khi dịch")
    args = parser.parse_args()

    from core.config import RAW_DIR, TRANS_DIR
    from core.runner import _sorted_files

    if not os.path.exists(RAW_DIR):
        print(f"❌ Không tìm thấy thư mục '{RAW_DIR}'."); return

    all_files = _sorted_files(RAW_DIR)
    if not all_files:
        print(f"❌ Không có file nào trong '{RAW_DIR}'."); return

    if args.list:
        list_chapters(all_files, TRANS_DIR); return

    # Xác định file cần dịch
    target = None
    if args.keyword:
        found = find_chapter(args.keyword, all_files)
        if len(found) == 0:
            print(f"❌ Không tìm thấy file nào khớp với '{args.keyword}'.")
            list_chapters(all_files, TRANS_DIR); return
        elif len(found) == 1:
            target = found[0]
            print(f"✅ Tìm thấy: {target}")
        else:
            print(f"\n⚠️  Tìm thấy {len(found)} file khớp với '{args.keyword}':")
            for i, f in enumerate(found, 1):
                print(f"  {i}. {f}")
            sub = input("Chọn số thứ tự: ").strip()
            if sub.isdigit() and 1 <= int(sub) <= len(found):
                target = found[int(sub) - 1]
            else:
                print("❌ Lựa chọn không hợp lệ."); return
    else:
        target = pick_chapter_interactive(all_files, TRANS_DIR)

    if not target:
        return

    # Xác nhận
    base, _ = os.path.splitext(target)
    out = os.path.join(TRANS_DIR, f"{base}_VN.txt")
    already = os.path.exists(out)
    print(f"\n  File   : {target}")
    print(f"  Trạng thái: {'✅ Đã có bản dịch (sẽ bị GHI ĐÈ)' if already else '⬜ Chưa dịch'}")
    print(f"  Cập nhật data: {'✅ Có' if args.update_data else '❌ Không (chỉ cải thiện bản dịch)'}")
    confirm = input("\nXác nhận dịch lại? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Huỷ."); return

    retranslate(target, update_data=args.update_data)


if __name__ == "__main__":
    main()