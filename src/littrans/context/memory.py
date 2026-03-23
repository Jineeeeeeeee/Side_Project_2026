"""
src/littrans/managers/memory.py — Arc Memory: bộ nhớ arc dài hạn.

  Context_Notes  → Ngắn hạn. Scout xóa & tạo lại mỗi SCOUT_REFRESH_EVERY chương.
  Arc_Memory     → Dài hạn. CHỈ APPEND. Không bao giờ xóa.

Chống trùng lặp:
  - Trích xuất dữ liệu đã có → truyền vào prompt AI ("đã biết — KHÔNG ghi lại")
  - Post-process entry mới → loại dòng trùng
  - Chỉnh sửa thủ công của người dùng được bảo toàn
"""
from __future__ import annotations

import re
import logging
from datetime import datetime

from littrans.config.settings import settings
from littrans.utils.io_utils import load_text, atomic_write

_ARC_SYSTEM_TEMPLATE = """Bạn là AI chuyên tạo BỘ NHỚ ARC để hỗ trợ pipeline dịch truyện dài kỳ.

Đọc các chương được cung cấp và sinh 1 bản TÓM TẮT ARC ngắn gọn bằng tiếng Việt.
Tập trung vào thông tin SẼ CÒN QUAN TRỌNG ở các chương sau.
KHÔNG thêm lời mở đầu hay kết luận. Trả về ĐÚNG cấu trúc Markdown sau:

### Sự kiện lớn
3–6 sự kiện quan trọng nhất + kết quả.
{already_known_events}

### Thay đổi thế giới
Tổ chức mới/tan rã, địa điểm quan trọng, quy tắc thay đổi.
Nếu không có → "Không đáng kể."

### Danh tính active
Nhân vật đang dùng alias/danh tính nào ở CUỐI window.
{already_known_identities}

### Xưng hô đã chốt
Các cặp xưng hô ĐÃ ĐƯỢC THIẾT LẬP RÕ RÀNG trong arc này.
Chỉ ghi cặp CHẮC CHẮN và CHƯA có trong danh sách đã biết.
{already_known_pronouns}"""


# ── Extract existing data ─────────────────────────────────────────

def _extract_existing(content: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {"pronouns": set(), "identities": set(), "events": set()}
    section = None
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if s.startswith("###"):
            if "xưng hô"  in low: section = "pronouns"
            elif "danh tính" in low: section = "identities"
            elif "sự kiện"  in low: section = "events"
            else: section = None
        elif s.startswith("##"):
            section = None
        elif section and s.startswith(("-", "•", "*", "+")):
            norm = re.sub(r"^[-•*+]\s*", "", s).strip().lower()
            if norm:
                result[section].add(norm)
        elif section == "pronouns" and "↔" in s:
            result["pronouns"].add(s.lower())
        elif section == "identities" and "→" in s:
            result["identities"].add(s.lower())
    return result


def _build_hints(existing: dict[str, set[str]]) -> dict[str, str]:
    hints = {"already_known_events": "", "already_known_identities": "", "already_known_pronouns": ""}
    if existing["pronouns"]:
        lines = "\n".join(f"  - {p}" for p in sorted(existing["pronouns"]))
        hints["already_known_pronouns"] = (
            f"\n⚠️  ĐÃ CÓ — KHÔNG GHI LẠI:\n{lines}\n"
            "Chỉ ghi cặp HOÀN TOÀN MỚI."
        )
    if existing["identities"]:
        lines = "\n".join(f"  - {i}" for i in sorted(existing["identities"]))
        hints["already_known_identities"] = f"\n⚠️  ĐÃ CÓ — CHỈ CẬP NHẬT NẾU THAY ĐỔI:\n{lines}"
    if existing["events"]:
        lines = "\n".join(f"  - {e}" for e in sorted(existing["events"]))
        hints["already_known_events"] = f"\n⚠️  ĐÃ CÓ — KHÔNG GHI LẠI:\n{lines}"
    return hints


def _deduplicate(body: str, existing: dict[str, set[str]]) -> tuple[str, int]:
    all_ex = existing["pronouns"] | existing["identities"] | existing["events"]
    if not all_ex:
        return body, 0
    output = []
    removed = 0
    for line in body.splitlines():
        s    = line.strip()
        norm = re.sub(r"^[-•*+]\s*", "", s).strip().lower()
        dup  = False
        if norm in all_ex:
            dup = True
        else:
            for ex in all_ex:
                if len(norm) >= 8 and len(ex) >= 8:
                    shorter, longer = sorted([norm, ex], key=len)
                    if shorter in longer and len(shorter) / len(longer) >= 0.75:
                        dup = True
                        break
        if dup:
            removed += 1
            output.append(f"<!-- trùng, đã bỏ: {s} -->")
        else:
            output.append(line)
    return "\n".join(output), removed


# ── Public API ────────────────────────────────────────────────────

def append_arc_summary(all_files: list[str], current_index: int, range_label: str) -> None:
    """Sinh tóm tắt arc và APPEND vào Arc_Memory.md."""
    from littrans.config.settings import settings as cfg

    start  = max(0, current_index - cfg.scout_lookback)
    window = all_files[start:current_index]
    if not window:
        return

    texts = _load_window(window)
    if not texts:
        return

    existing_content = load_text(cfg.arc_memory_file)
    existing_data    = _extract_existing(existing_content)
    hints            = _build_hints(existing_data)
    system_prompt    = _ARC_SYSTEM_TEMPLATE.format(**hints)

    print(f"  📖 Arc Memory: tóm tắt {len(texts)} chương ({range_label})...")
    n_known = sum(len(v) for v in existing_data.values())
    if n_known:
        print(f"     Đã có: {len(existing_data['pronouns'])} xưng hô · "
              f"{len(existing_data['identities'])} danh tính · "
              f"{len(existing_data['events'])} sự kiện → bỏ qua khi sinh mới")

    try:
        from littrans.llm.client import call_gemini_text
        body = call_gemini_text(
            system_prompt,
            "\n\n---\n\n".join(f"### {label}\n\n{text}" for label, text in texts),
        )
    except Exception as e:
        logging.error(f"Arc Memory: {e}")
        body = f"_(Lỗi: {e})_"

    body_deduped, n_removed = _deduplicate(body.strip(), existing_data)
    if n_removed:
        print(f"     Đã loại {n_removed} dòng trùng.")

    entry = (
        f"\n\n---\n"
        f"## Arc: {range_label}  _{datetime.now().strftime('%Y-%m-%d')}_\n\n"
        f"{body_deduped.strip()}\n"
    )
    if not existing_content.strip():
        content = "# Arc Memory\n_Bộ nhớ arc tích lũy — không bao giờ xóa_\n" + entry
    else:
        content = existing_content.rstrip("\n") + entry

    atomic_write(cfg.arc_memory_file, content)
    n = content.count("## Arc:")
    print(f"  ✅ Arc Memory cập nhật ({n} entry tổng cộng).")


def load_recent(n: int | None = None) -> str:
    """Trả về N entry gần nhất để đưa vào prompt."""
    n       = n or settings.arc_memory_window
    content = load_text(settings.arc_memory_file)
    if not content.strip():
        return ""
    entries = [e for e in re.split(r"\n---\n", content) if e.strip().startswith("## Arc:")]
    if not entries:
        return ""
    recent = entries[-n:]
    total  = len(entries)
    return (f"_({total} arc entry, hiển thị {len(recent)} gần nhất)_\n\n"
            + "\n\n---\n".join(recent))


def load_context_notes() -> str:
    return load_text(settings.context_notes_file)


# ── Helpers ───────────────────────────────────────────────────────

def _load_window(window_files: list[str]) -> list[tuple[str, str]]:
    import os
    MAX    = 4000
    result = []
    for fn in window_files:
        base, _ = os.path.splitext(fn)
        vn_path = str(settings.active_output_dir / f"{base}_VN.txt")
        en_path = str(settings.active_input_dir  / fn)
        for path, label_suffix in [(vn_path, "[VN]"), (en_path, "[EN]")]:
            text = load_text(path)
            if text.strip():
                result.append((f"{fn} {label_suffix}", text[:MAX]))
                break
    return result