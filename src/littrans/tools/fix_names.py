"""
src/littrans/tools/fix_names.py — Sửa tên vi phạm Name Lock.

Đọc data/name_fixes.json → thay tên sai bằng tên đúng trong outputs/.
"""
from __future__ import annotations

import re
from pathlib import Path

from littrans.config.settings import settings
from littrans.utils.io_utils import load_json, save_json, atomic_write


# ── I/O ───────────────────────────────────────────────────────────

def load_fixes(fixes_path: Path) -> dict:
    return load_json(fixes_path) or {"fixes": {}}


def save_fixes(data: dict, fixes_path: Path) -> None:
    save_json(fixes_path, data)


# ── Core logic ────────────────────────────────────────────────────

def apply_fixes_to_text(text: str, fixes: dict) -> tuple[str, list[str]]:
    changes: list[str] = []
    sorted_fixes = sorted(fixes.items(), key=lambda x: len(x[0]), reverse=True)
    for wrong, entry in sorted_fixes:
        if entry.get("fixed") and not entry.get("chapters"):
            continue
        correct = entry.get("correct", "")
        if not wrong or not correct or wrong == correct:
            continue
        try:
            pattern = rf"\b{re.escape(wrong)}\b"
            count   = len(re.findall(pattern, text, flags=re.IGNORECASE))
            if count > 0:
                text = re.sub(pattern, correct, text, flags=re.IGNORECASE)
                changes.append(f"'{wrong}' → '{correct}' ({count} chỗ)")
        except re.error:
            if wrong in text:
                count = text.count(wrong)
                text  = text.replace(wrong, correct)
                changes.append(f"'{wrong}' → '{correct}' ({count} chỗ, plain)")
    return text, changes


def get_target_files(fixes: dict, all_chapters: bool) -> list[str]:
    if not settings.output_dir.exists():
        return []
    all_files = [f for f in settings.output_dir.iterdir()
                 if f.suffix in (".txt", ".md")]
    all_names = [f.name for f in all_files]

    if all_chapters:
        return sorted(all_names)

    affected: set[str] = set()
    for entry in fixes.values():
        if entry.get("fixed"):
            continue
        for ch in entry.get("chapters", []):
            base, _ = ch.rsplit(".", 1) if "." in ch else (ch, "")
            vn_name = f"{base}_VN.txt"
            if vn_name in all_names:
                affected.add(vn_name)
    return sorted(affected)


# ── Commands ──────────────────────────────────────────────────────

def cmd_list(data: dict) -> None:
    fixes   = data.get("fixes", {})
    pending = {k: v for k, v in fixes.items() if not v.get("fixed")}
    done    = {k: v for k, v in fixes.items() if v.get("fixed")}

    print(f"\n{'─'*62}")
    print(f"  NAME FIXES — {len(pending)} chờ sửa, {len(done)} đã sửa")
    print(f"{'─'*62}")

    if not fixes:
        print("  ✅ Không có vi phạm nào."); return

    if pending:
        print(f"\n  {'TÊN SAI':<35} TÊN ĐÚNG")
        print(f"  {'─'*60}")
        for wrong, entry in sorted(pending.items()):
            correct  = entry.get("correct", "?")
            chapters = entry.get("chapters", [])
            ch_str   = f"  ({len(chapters)} chương)" if chapters else ""
            print(f"  {wrong:<35} {correct}{ch_str}")
            for ch in chapters[:3]: print(f"    └ {ch}")
            if len(chapters) > 3: print(f"    └ ... và {len(chapters)-3} chương khác")
    if done:
        print(f"\n  Đã sửa ({len(done)}): {', '.join(sorted(done.keys()))}")
    print()


def cmd_fix(data: dict, fixes_path: Path, all_chapters: bool = False, dry_run: bool = False) -> None:
    fixes   = data.get("fixes", {})
    pending = {k: v for k, v in fixes.items() if not v.get("fixed")}

    if not pending:
        print("✅ Không có vi phạm nào cần sửa."); return

    target_files = get_target_files(pending, all_chapters)
    if not target_files:
        print(f"⚠️  Không tìm thấy file nào trong '{settings.output_dir}'."); return

    mode  = "DRY RUN — " if dry_run else ""
    scope = "toàn bộ chương" if all_chapters else f"{len(target_files)} chương bị vi phạm"
    print(f"\n{'═'*62}")
    print(f"  {mode}Sửa tên — {len(pending)} vi phạm · {scope}")
    print(f"{'═'*62}\n")

    total_files   = 0
    total_changes = 0

    for fn in target_files:
        filepath = settings.output_dir / fn
        try:
            original = filepath.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  ⚠️  Không đọc được {fn}: {e}"); continue

        new_text, changes = apply_fixes_to_text(original, pending)
        if not changes:
            continue

        total_files   += 1
        total_changes += sum(
            int(m.group(1)) for c in changes
            if (m := re.search(r"\((\d+)", c))
        )
        print(f"  {'[DRY]' if dry_run else '✏️ '} {fn}")
        for c in changes: print(f"       {c}")
        if not dry_run:
            atomic_write(filepath, new_text)

    if not dry_run and total_files > 0:
        for wrong in pending:
            fixes[wrong]["fixed"]    = True
            fixes[wrong]["chapters"] = []
        save_fixes(data, fixes_path)
        print(f"\n✅ Đã sửa {total_changes} chỗ trong {total_files} file.")
    elif dry_run:
        print(f"\n[DRY RUN] Sẽ sửa {total_changes} chỗ trong {total_files} file.")
    else:
        print("\n✅ Không có thay đổi nào.")
