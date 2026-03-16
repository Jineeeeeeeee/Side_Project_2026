"""
fix_names.py — Sửa tên sai trong các bản dịch đã có.

Đọc data/name_fixes.json (được ghi tự động khi pipeline phát hiện vi phạm
Name Lock), sau đó thay tất cả tên sai bằng tên đúng trong các file
Translated_VN/.

CÁCH DÙNG:
    python fix_names.py                  # Sửa tất cả vi phạm đã ghi
    python fix_names.py --list           # Xem danh sách vi phạm chưa sửa
    python fix_names.py --all-chapters   # Sửa toàn bộ chương (không chỉ chương bị vi phạm)
    python fix_names.py --dry-run        # Xem trước thay đổi, không ghi file
    python fix_names.py --clear          # Xóa name_fixes.json sau khi đã sửa xong

Sau khi sửa, mỗi entry trong name_fixes.json sẽ được đánh dấu "fixed": true.
"""
import sys, os, re, json, argparse, tempfile
sys.stdout.reconfigure(encoding="utf-8")

FIXES_PATH = os.path.join("data", "name_fixes.json")
TRANS_DIR  = "Translated_VN"


# ═══════════════════════════════════════════════════════════════════
# ĐỌC / GHI FILE
# ═══════════════════════════════════════════════════════════════════

def load_fixes() -> dict:
    if not os.path.exists(FIXES_PATH):
        return {"fixes": {}}
    with open(FIXES_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            print(f"❌ Không đọc được {FIXES_PATH} — file có thể bị hỏng.")
            return {"fixes": {}}


def save_fixes(data: dict) -> None:
    os.makedirs(os.path.dirname(FIXES_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(FIXES_PATH) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, FIXES_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def atomic_write(filepath: str, content: str) -> None:
    out_dir = os.path.dirname(filepath) or "."
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, filepath)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ═══════════════════════════════════════════════════════════════════
# LOGIC SỬA TÊN
# ═══════════════════════════════════════════════════════════════════

def apply_fixes_to_text(text: str, fixes: dict) -> tuple[str, list[str]]:
    """
    Áp dụng tất cả fix vào text.
    Trả về (text_mới, danh_sách_thay_đổi_đã_thực_hiện).

    Thay theo word boundary để tránh thay nhầm (VD: "Moon" không nhầm với "Moonlight").
    Xử lý từ dài nhất trước để tránh thay một phần của tên dài hơn.
    """
    changes = []
    # Sắp xếp theo độ dài giảm dần để tránh conflict
    sorted_fixes = sorted(fixes.items(), key=lambda x: len(x[0]), reverse=True)

    for wrong, entry in sorted_fixes:
        if entry.get("fixed") and not entry.get("chapters"):
            continue  # đã fix và không còn chapter nào
        correct = entry.get("correct", "")
        if not wrong or not correct or wrong == correct:
            continue
        try:
            pattern = rf"\b{re.escape(wrong)}\b"
            count   = len(re.findall(pattern, text, flags=re.IGNORECASE))
            if count > 0:
                # Thay thế giữ nguyên case của chữ cái đầu nếu cần
                text = re.sub(pattern, correct, text, flags=re.IGNORECASE)
                changes.append(f"'{wrong}' → '{correct}' ({count} chỗ)")
        except re.error:
            # Fallback plain replace nếu regex lỗi
            if wrong in text:
                count = text.count(wrong)
                text  = text.replace(wrong, correct)
                changes.append(f"'{wrong}' → '{correct}' ({count} chỗ, plain)")

    return text, changes


def get_target_files(fixes: dict, all_chapters: bool) -> list[str]:
    """
    Trả về danh sách file cần sửa trong TRANS_DIR.

    all_chapters=False: chỉ sửa các chương được ghi trong 'chapters' của từng fix.
    all_chapters=True:  sửa toàn bộ file trong TRANS_DIR.
    """
    if not os.path.exists(TRANS_DIR):
        return []

    all_files = [
        f for f in os.listdir(TRANS_DIR)
        if f.endswith((".txt", ".md"))
    ]

    if all_chapters:
        return sorted(all_files)

    # Gộp tất cả chapter có vi phạm
    affected = set()
    for entry in fixes.values():
        if entry.get("fixed"):
            continue
        for ch in entry.get("chapters", []):
            # ch là tên file gốc (Raw_English), chuyển sang tên VN
            base, _ = os.path.splitext(ch)
            vn_name = f"{base}_VN.txt"
            if vn_name in all_files:
                affected.add(vn_name)

    return sorted(affected)


# ═══════════════════════════════════════════════════════════════════
# LỆNH: LIST
# ═══════════════════════════════════════════════════════════════════

def cmd_list(data: dict) -> None:
    fixes = data.get("fixes", {})
    if not fixes:
        print("✅ Không có vi phạm nào trong name_fixes.json.")
        return

    pending = {k: v for k, v in fixes.items() if not v.get("fixed")}
    done    = {k: v for k, v in fixes.items() if v.get("fixed")}

    print(f"\n{'─'*62}")
    print(f"  NAME FIXES — {len(pending)} chờ sửa, {len(done)} đã sửa")
    print(f"{'─'*62}")

    if pending:
        print(f"\n  {'TÊN SAI':<35} TÊN ĐÚNG")
        print(f"  {'─'*60}")
        for wrong, entry in sorted(pending.items()):
            correct  = entry.get("correct", "?")
            chapters = entry.get("chapters", [])
            ch_str   = f"  ({len(chapters)} chương)" if chapters else ""
            print(f"  {wrong:<35} {correct}{ch_str}")
            for ch in chapters[:3]:
                print(f"    └ {ch}")
            if len(chapters) > 3:
                print(f"    └ ... và {len(chapters)-3} chương khác")

    if done:
        print(f"\n  Đã sửa ({len(done)}):", ", ".join(sorted(done.keys())))

    print(f"\n  Chạy: python fix_names.py  để sửa tất cả\n")


# ═══════════════════════════════════════════════════════════════════
# LỆNH: FIX
# ═══════════════════════════════════════════════════════════════════

def cmd_fix(data: dict, all_chapters: bool, dry_run: bool) -> None:
    fixes = data.get("fixes", {})
    pending = {k: v for k, v in fixes.items() if not v.get("fixed")}

    if not pending:
        print("✅ Không có vi phạm nào cần sửa.")
        return

    target_files = get_target_files(pending, all_chapters)
    if not target_files:
        print(f"⚠️  Không tìm thấy file nào trong '{TRANS_DIR}'.")
        return

    mode = "DRY RUN — " if dry_run else ""
    scope = "toàn bộ chương" if all_chapters else f"{len(target_files)} chương bị vi phạm"
    print(f"\n{'═'*62}")
    print(f"  {mode}Sửa tên — {len(pending)} vi phạm · {scope}")
    print(f"{'═'*62}\n")

    total_files_changed = 0
    total_replacements  = 0

    for fn in target_files:
        filepath = os.path.join(TRANS_DIR, fn)
        try:
            with open(filepath, encoding="utf-8") as f:
                original = f.read()
        except Exception as e:
            print(f"  ⚠️  Không đọc được {fn}: {e}")
            continue

        new_text, changes = apply_fixes_to_text(original, pending)

        if not changes:
            continue

        total_files_changed += 1
        total_replacements  += sum(
            int(re.search(r'\((\d+)', c).group(1)) for c in changes if re.search(r'\((\d+)', c)
        )

        print(f"  {'[DRY]' if dry_run else '✏️ '} {fn}")
        for c in changes:
            print(f"       {c}")

        if not dry_run:
            atomic_write(filepath, new_text)

    # Đánh dấu đã fix
    if not dry_run and total_files_changed > 0:
        for wrong in pending:
            fixes[wrong]["fixed"]    = True
            fixes[wrong]["chapters"] = []  # xóa danh sách chapter vì đã fix xong
        save_fixes(data)
        print(f"\n✅ Đã sửa {total_replacements} chỗ trong {total_files_changed} file.")
        print(f"   name_fixes.json đã được cập nhật (đánh dấu fixed=true).")
    elif dry_run:
        print(f"\n[DRY RUN] Sẽ sửa {total_replacements} chỗ trong {total_files_changed} file.")
        print("   Chạy lại không có --dry-run để áp dụng thực sự.")
    else:
        print("\n✅ Không có thay đổi nào cần thực hiện.")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Sửa tên sai trong các bản dịch theo name_fixes.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ví dụ:\n"
            "  python fix_names.py                  # Sửa tất cả vi phạm\n"
            "  python fix_names.py --list           # Xem danh sách vi phạm\n"
            "  python fix_names.py --dry-run        # Xem trước, không ghi file\n"
            "  python fix_names.py --all-chapters   # Sửa toàn bộ chương (không chỉ chương bị vi phạm)\n"
            "  python fix_names.py --clear          # Xóa name_fixes.json\n"
        )
    )
    parser.add_argument("--list",         action="store_true", help="Liệt kê vi phạm")
    parser.add_argument("--dry-run",      action="store_true", help="Xem trước, không ghi file")
    parser.add_argument("--all-chapters", action="store_true", help="Sửa toàn bộ chương")
    parser.add_argument("--clear",        action="store_true", help="Xóa name_fixes.json")
    args = parser.parse_args()

    if args.clear:
        if os.path.exists(FIXES_PATH):
            os.remove(FIXES_PATH)
            print(f"🗑️  Đã xóa {FIXES_PATH}.")
        else:
            print(f"⚠️  {FIXES_PATH} không tồn tại.")
        return

    data = load_fixes()

    if args.list:
        cmd_list(data)
        return

    cmd_fix(data, all_chapters=args.all_chapters, dry_run=args.dry_run)


if __name__ == "__main__":
    main()