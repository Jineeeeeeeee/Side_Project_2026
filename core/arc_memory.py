"""
core/arc_memory.py — Bộ nhớ arc dài hạn (chỉ APPEND, không xóa).

KHÁC CONTEXT_NOTES:
  Context_Notes  → Ngắn hạn. Xóa & tạo lại mỗi SCOUT_REFRESH_EVERY chương.
  Arc_Memory     → Dài hạn. Chỉ APPEND. Không bao giờ xóa.

CHỐNG TRÙNG LẶP:
  Trước khi append entry mới, hệ thống:
    1. Trích xuất toàn bộ xưng hô, danh tính, sự kiện ĐÃ CÓ trong file
    2. Truyền vào prompt AI dưới dạng "đã biết — KHÔNG ghi lại"
       → AI chỉ viết thông tin MỚI, không lặp lại cũ
    3. Post-process entry mới: loại bỏ dòng trùng hoàn toàn với nội dung cũ

  Ý nghĩa với người dùng:
    - Có thể chỉnh sửa thủ công Arc_Memory.md (VD: sửa xưng hô, thêm ghi chú)
    - Chỉnh sửa đó sẽ được GIỮ NGUYÊN — không bị ghi đè bởi entry mới
    - Thông tin đã có không bị lặp lại vô ích, file không phình to vô nghĩa
"""
import re, logging
from datetime import datetime
from google.genai import types
from .config import (
    RAW_DIR, TRANS_DIR, ARC_MEMORY_FILE, ARC_MEMORY_WINDOW,
    GEMINI_MODEL, gemini_client,
)
from .io_utils import load_text, save_text_atomic

_ARC_SYSTEM_TEMPLATE = """Bạn là AI chuyên tạo BỘ NHỚ ARC để hỗ trợ pipeline dịch truyện dài kỳ.

Đọc các chương được cung cấp và sinh ra 1 bản TÓM TẮT ARC ngắn gọn bằng tiếng Việt.
Tập trung vào thông tin SẼ CÒN QUAN TRỌNG ở các chương sau.
KHÔNG thêm lời mở đầu hay kết luận. Trả về ĐÚNG cấu trúc Markdown sau:

### Sự kiện lớn
3–6 sự kiện quan trọng nhất + kết quả. Ưu tiên thay đổi không thể đảo ngược.
Mỗi điểm 1 dòng.
{already_known_events}

### Thay đổi thế giới
Tổ chức mới/tan rã, địa điểm quan trọng, quy tắc/luật lệ thay đổi.
Nếu không có → "Không đáng kể."

### Danh tính active
Liệt kê nhân vật đang dùng alias/danh tính nào ở CUỐI window.
VD: Klein → đang hoạt động với danh tính "Thám tử Moriarty" tại Backlund.
{already_known_identities}

### Xưng hô đã chốt
Các cặp xưng hô ĐÃ ĐƯỢC THIẾT LẬP RÕ RÀNG trong arc này.
VD: Klein ↔ Audrey: Tôi–Cô (trang trọng, nơi công cộng).
Chỉ ghi những cặp CHẮC CHẮN và CHƯA có trong danh sách đã biết dưới đây.
{already_known_pronouns}"""


# ═══════════════════════════════════════════════════════════════════
# TRÍCH XUẤT DỮ LIỆU ĐÃ CÓ
# ═══════════════════════════════════════════════════════════════════

def _extract_existing_data(content: str) -> dict[str, set[str]]:
    """
    Đọc toàn bộ Arc_Memory.md và trích xuất:
      - pronouns  : set cặp xưng hô đã chốt (mỗi dòng là 1 entry)
      - identities: set danh tính active đã ghi
      - events    : set sự kiện lớn đã ghi (dòng bullet)

    Dùng để:
      1. Truyền vào prompt AI → AI không ghi lại thông tin cũ
      2. Post-process → loại dòng trùng khỏi entry mới
    """
    result: dict[str, set[str]] = {
        "pronouns"  : set(),
        "identities": set(),
        "events"    : set(),
    }
    if not content.strip():
        return result

    current_section = None
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Xác định section đang ở
        low = stripped.lower()
        if "xưng hô" in low and stripped.startswith("###"):
            current_section = "pronouns"
        elif "danh tính" in low and stripped.startswith("###"):
            current_section = "identities"
        elif "sự kiện" in low and stripped.startswith("###"):
            current_section = "events"
        elif stripped.startswith("###"):
            current_section = None
        elif stripped.startswith("##"):
            current_section = None  # header entry mới
        elif current_section and stripped.startswith(("-", "•", "*", "+")):
            # Dòng bullet — chuẩn hóa để so sánh
            normalized = re.sub(r"^[-•*+]\s*", "", stripped).strip().lower()
            if normalized:
                result[current_section].add(normalized)
        elif current_section == "pronouns" and "↔" in stripped:
            # Xưng hô dạng "A ↔ B: ..." không có bullet
            result["pronouns"].add(stripped.lower())
        elif current_section == "identities" and "→" in stripped:
            result["identities"].add(stripped.lower())

    return result


def _build_known_hints(existing: dict[str, set[str]]) -> dict[str, str]:
    """
    Tạo đoạn text "đã biết" để chèn vào prompt.
    Nếu không có gì → trả về chuỗi rỗng (không chèn gì).
    """
    hints = {"already_known_events": "", "already_known_identities": "", "already_known_pronouns": ""}

    if existing["pronouns"]:
        lines = "\n".join(f"  - {p}" for p in sorted(existing["pronouns"]))
        hints["already_known_pronouns"] = (
            f"\n⚠️  CÁC CẶP XƯNG HÔ SAU ĐÃ CÓ TRONG ARC MEMORY — KHÔNG GHI LẠI:\n{lines}\n"
            f"Chỉ ghi cặp HOÀN TOÀN MỚI chưa có trong danh sách trên."
        )

    if existing["identities"]:
        lines = "\n".join(f"  - {i}" for i in sorted(existing["identities"]))
        hints["already_known_identities"] = (
            f"\n⚠️  DANH TÍNH SAU ĐÃ ĐƯỢC GHI — CHỈ CẬP NHẬT NẾU ĐÃ THAY ĐỔI:\n{lines}"
        )

    if existing["events"]:
        lines = "\n".join(f"  - {e}" for e in sorted(existing["events"]))
        hints["already_known_events"] = (
            f"\n⚠️  CÁC SỰ KIỆN SAU ĐÃ CÓ — KHÔNG GHI LẠI:\n{lines}"
        )

    return hints


# ═══════════════════════════════════════════════════════════════════
# POST-PROCESS: LOẠI DÒNG TRÙNG
# ═══════════════════════════════════════════════════════════════════

def _deduplicate_entry(new_body: str, existing: dict[str, set[str]]) -> tuple[str, int]:
    """
    Loại bỏ các dòng trong new_body trùng với nội dung đã có.
    Trả về (body_đã_lọc, số_dòng_bị_loại).

    Tiêu chí so sánh: chuẩn hóa về lowercase, bỏ bullet,
    rồi kiểm tra xem có trong existing không.
    """
    all_existing = existing["pronouns"] | existing["identities"] | existing["events"]
    if not all_existing:
        return new_body, 0

    output_lines = []
    removed = 0

    for line in new_body.splitlines():
        stripped = line.strip()
        if not stripped:
            output_lines.append(line)
            continue

        # Chuẩn hóa để so sánh
        normalized = re.sub(r"^[-•*+]\s*", "", stripped).strip().lower()

        # Kiểm tra trùng — so sánh chính xác hoặc bao hàm (substring ≥ 80% độ dài)
        is_dup = False
        if normalized in all_existing:
            is_dup = True
        else:
            # Kiểm tra gần giống: dòng mới là subset của dòng cũ hoặc ngược lại
            for ex in all_existing:
                if len(normalized) >= 8 and len(ex) >= 8:
                    shorter, longer = sorted([normalized, ex], key=len)
                    if shorter in longer and len(shorter) / len(longer) >= 0.75:
                        is_dup = True
                        break

        if is_dup:
            removed += 1
            # Thêm dòng comment để người dùng biết dòng đó bị bỏ (không mất trace)
            output_lines.append(f"<!-- trùng, đã bỏ: {stripped} -->")
        else:
            output_lines.append(line)

    return "\n".join(output_lines), removed


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════

def append_arc_summary(all_files: list[str], current_index: int, range_label: str) -> None:
    """
    Sinh tóm tắt arc cho cửa sổ [current_index - lookback : current_index]
    và APPEND vào Arc_Memory.md.
    Gọi từ scout.run() sau khi Context_Notes đã được tạo.

    Chống trùng lặp:
      - Trích xuất dữ liệu đã có → truyền vào prompt AI
      - Post-process entry mới → loại dòng trùng
      - Chỉnh sửa thủ công của người dùng được bảo toàn hoàn toàn
    """
    from .config import SCOUT_LOOKBACK
    start  = max(0, current_index - SCOUT_LOOKBACK)
    window = all_files[start:current_index]
    if not window:
        return

    texts = _load_window(window)
    if not texts:
        return

    # Đọc nội dung hiện có + trích xuất dữ liệu đã biết
    existing_content = load_text(str(ARC_MEMORY_FILE))
    existing_data    = _extract_existing_data(existing_content)
    known_hints      = _build_known_hints(existing_data)

    # Build system prompt có nhúng thông tin đã biết
    system_prompt = _ARC_SYSTEM_TEMPLATE.format(**known_hints)

    print(f"  📖 Arc Memory: tóm tắt {len(texts)} chương ({range_label})...")
    n_known = sum(len(v) for v in existing_data.values())
    if n_known:
        print(f"     Đã có: {len(existing_data['pronouns'])} xưng hô · "
              f"{len(existing_data['identities'])} danh tính · "
              f"{len(existing_data['events'])} sự kiện → sẽ bỏ qua khi sinh mới")

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents="\n\n---\n\n".join(f"### {label}\n\n{text}" for label, text in texts),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
            ),
        )
        body = response.text or "_(Không tạo được tóm tắt)_"
    except Exception as e:
        logging.error(f"Arc Memory: {e}")
        body = f"_(Lỗi: {e})_"

    # Post-process: loại dòng trùng
    body_deduped, n_removed = _deduplicate_entry(body.strip(), existing_data)
    if n_removed:
        print(f"     Đã loại {n_removed} dòng trùng với nội dung đã chỉnh sửa thủ công.")

    entry = (
        f"\n\n---\n"
        f"## Arc: {range_label}  _{datetime.now().strftime('%Y-%m-%d')}_\n\n"
        f"{body_deduped.strip()}\n"
    )

    if not existing_content.strip():
        content = "# Arc Memory\n_Bộ nhớ arc tích lũy — không bao giờ xóa_\n" + entry
    else:
        content = existing_content.rstrip("\n") + entry

    save_text_atomic(str(ARC_MEMORY_FILE), content)
    n = content.count("## Arc:")
    print(f"  ✅ Arc Memory cập nhật ({n} entry tổng cộng).")


def load_recent(n: int = None) -> str:
    """Trả về N entry gần nhất để đưa vào prompt."""
    n = n or ARC_MEMORY_WINDOW
    content = load_text(str(ARC_MEMORY_FILE))
    if not content.strip():
        return ""
    entries = [e for e in re.split(r"\n---\n", content) if e.strip().startswith("## Arc:")]
    if not entries:
        return ""
    recent = entries[-n:]
    total  = len(entries)
    return (f"_({total} arc entry tổng cộng, hiển thị {len(recent)} gần nhất)_\n\n"
            + "\n\n---\n".join(recent))


def _load_window(window_files: list[str]) -> list[tuple[str, str]]:
    """Ưu tiên đọc bản VN đã dịch, fallback về bản EN gốc. Giới hạn 4000 ký tự/chương."""
    import os
    MAX = 4000
    result = []
    for fn in window_files:
        base, _ = os.path.splitext(fn)
        vn = os.path.join(TRANS_DIR, f"{base}_VN.txt")
        en = os.path.join(RAW_DIR, fn)
        if os.path.exists(vn):
            text, label = load_text(vn), f"{fn} [VN]"
        elif os.path.exists(en):
            text, label = load_text(en), f"{fn} [EN]"
        else:
            continue
        if text.strip():
            result.append((label, text[:MAX]))
    return result