"""
core/scout.py — Scout AI: sinh Context_Notes + cập nhật Arc_Memory + Emotion Tracker.

MỖI LẦN CHẠY (trigger: chapters_done % SCOUT_REFRESH_EVERY == 0):
  1. Xóa Context_Notes.md cũ
  2. Đọc SCOUT_LOOKBACK chương gốc tiếng Anh gần nhất
  3. Gọi Gemini → sinh Context_Notes.md mới (ngắn hạn)
  4. Gọi arc_memory.append_arc_summary() → APPEND vào Arc_Memory.md (dài hạn)
  5. [v4] Gọi _update_emotional_states() → cập nhật trạng thái cảm xúc vào Characters_Active.json

Context_Notes.md gồm 4 mục:
  1. Mạch truyện đặc biệt (flashback, hồi ký, giấc mơ...)
  2. Khoá xưng hô đang active (cặp nhân vật + đại từ hiện tại)
  3. Diễn biến gần nhất (3-5 điểm)
  4. Cảnh báo cụ thể cho AI dịch

[v4] Emotion Tracker:
  Scout đọc các chương → infer trạng thái cảm xúc cuối window cho từng nhân vật chính
  → ghi vào Characters_Active.json → prompt P3 hiển thị cảnh báo tông cảm xúc

Pipeline tiếp tục dù Scout gặp lỗi — chỉ log, không raise.
"""
import os, logging
from google.genai import types
from .config import (
    RAW_DIR, CONTEXT_NOTES_FILE,
    SCOUT_LOOKBACK, SCOUT_REFRESH_EVERY,
    GEMINI_MODEL, gemini_client,
    EMOTION_RESET_CHAPTERS,
)
from .io_utils import load_text, save_text_atomic
from . import arc_memory

_SCOUT_SYSTEM = """Bạn là Scout AI — đọc trước các chương truyện để sinh ghi chú hỗ trợ AI dịch.

Đọc các chương tiếng Anh được cung cấp, trả về ghi chú ngắn gọn bằng tiếng Việt
theo ĐÚNG 4 mục dưới đây. KHÔNG thêm lời mở đầu hay kết luận.

## 1. MẠCH TRUYỆN ĐẶC BIỆT
Có flashback / hồi ký / giấc mơ / thư từ / cảnh quá khứ không?
Nếu không → "Không có."
Nếu có → mô tả cụ thể phạm vi và nội dung.

## 2. KHOÁ XƯNG HÔ ĐANG ACTIVE
Liệt kê từng cặp nhân vật và xưng hô hiện tại.
Ghi rõ nếu khác theo ngữ cảnh (hiện tại vs hồi ký / bình thường vs chiến đấu).
Nếu chưa rõ → "Chưa xác định."
VD:
- Arthur ↔ Lyra: hiện tại = Anh–Em | trong hồi ký ch.7–8 = Tao–Mày
- System ↔ MC: luôn = Hệ thống–Ký chủ

## 3. DIỄN BIẾN GẦN NHẤT
3–5 sự kiện / thay đổi trạng thái quan trọng nhất. Mỗi điểm 1 dòng.

## 4. CẢNH BÁO CHO AI DỊCH
Những điểm CỤ THỂ dễ sai nếu không có ngữ cảnh.
Nếu không có → "Không có cảnh báo đặc biệt."
VD:
- ⚠️ Chương tiếp theo có thể tiếp tục hồi ký → GIỮ xưng hô Tao–Mày, không đổi sang Anh–Em.
- ⚠️ Arthur vừa đổi phe → xưng hô với nhóm cũ có thể thay đổi."""

# ── [v4] System prompt cho Emotion Tracker ───────────────────────
_EMOTION_SYSTEM = """Bạn là AI phân tích cảm xúc nhân vật trong truyện.

Đọc các chương được cung cấp. Xác định trạng thái cảm xúc CUỐI CÙNG của từng nhân vật CHÍNH.

Trả về JSON theo định dạng sau. KHÔNG thêm gì khác ngoài JSON:
{
  "emotional_states": [
    {
      "character": "Tên nhân vật",
      "state": "normal|angry|hurt|changed",
      "reason": "Lý do ngắn gọn (1 câu)",
      "intensity": "low|medium|high"
    }
  ]
}

Quy tắc:
- "normal": bình thường, không có gì đặc biệt
- "angry": tức giận, bực bội, oán hận — ảnh hưởng đến cách nói chuyện
- "hurt": tổn thương, buồn, mất mát, phản bội — ảnh hưởng đến cách nói chuyện
- "changed": vừa trải qua sự kiện lớn thay đổi nhận thức/mục tiêu — quan trọng cho context
- Chỉ liệt kê nhân vật có TÊN RÕ RÀNG và xuất hiện ĐÁN KỂ trong window này
- Nếu không rõ → dùng "normal"
- Tối đa 8 nhân vật. Ưu tiên nhân vật chính và nhân vật sẽ xuất hiện trong chương tiếp theo."""


def run(all_files: list[str], current_index: int) -> None:
    """
    Chạy Scout: tạo Context_Notes mới + append Arc_Memory + update Emotion.
    Không raise — pipeline tiếp tục nếu Scout thất bại.
    """
    _refresh_context_notes(all_files, current_index)

    # Append arc summary (dài hạn)
    start = max(0, current_index - SCOUT_LOOKBACK)
    files_in_window = all_files[start:current_index]
    if files_in_window:
        range_label = f"{files_in_window[0]} → {files_in_window[-1]}"
        try:
            arc_memory.append_arc_summary(all_files, current_index, range_label)
        except Exception as e:
            logging.error(f"Arc Memory thất bại: {e}")
            print(f"  ⚠️  Arc Memory gặp lỗi: {e}")

    # [v4] Update emotional states
    try:
        _update_emotional_states(all_files, current_index)
    except Exception as e:
        logging.error(f"Emotion Tracker thất bại: {e}")
        print(f"  ⚠️  Emotion Tracker gặp lỗi: {e}")


def _refresh_context_notes(all_files: list[str], current_index: int) -> None:
    # Xóa note cũ — dùng atomic write bên dưới nên không cần xóa thủ công
    # (os.replace() sẽ overwrite), nhưng giữ print log để người dùng biết
    if os.path.exists(str(CONTEXT_NOTES_FILE)):
        print("  🗑️  Đã xóa Context_Notes.md cũ.")

    start  = max(0, current_index - SCOUT_LOOKBACK)
    window = all_files[start:current_index]

    if not window:
        _write_empty_note("Chưa có chương nào để phân tích.")
        return

    texts = []
    for fn in window:
        text = load_text(os.path.join(RAW_DIR, fn))
        if text.strip():
            texts.append((fn, text[:6000]))

    if not texts:
        _write_empty_note("Không đọc được nội dung chương.")
        return

    range_label = f"{window[0]} → {window[-1]}"
    print(f"  🔭 Scout AI đọc {len(texts)} chương ({range_label})...")

    user_msg = "\n\n---\n\n".join(f"### {fn}\n\n{text}" for fn, text in texts)

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=_SCOUT_SYSTEM,
                temperature=0.2,
            ),
        )
        body = response.text or "_(Scout AI không trả về nội dung)_"
    except Exception as e:
        logging.error(f"Scout AI thất bại: {e}")
        body = f"⚠️ Scout AI gặp lỗi: {e}"

    note = (f"# Context Notes\n"
            f"_Sinh bởi Scout AI · {range_label}_\n\n"
            f"{body.strip()}\n")
    save_text_atomic(str(CONTEXT_NOTES_FILE), note)
    print(f"  ✅ Context_Notes.md ({len(note)} ký tự).")


# ── [v4] Emotion Tracker ─────────────────────────────────────────

def _update_emotional_states(all_files: list[str], current_index: int) -> None:
    """
    Scout đọc window chương → infer emotional_state của nhân vật chính
    → ghi vào Characters_Active.json.

    Reset về "normal" cho nhân vật không được update trong EMOTION_RESET_CHAPTERS.
    """
    import json
    from .config import CHARACTERS_ACTIVE_FILE

    start  = max(0, current_index - SCOUT_LOOKBACK)
    window = all_files[start:current_index]
    if not window:
        return

    # Đọc các chương (ưu tiên bản VN đã dịch, fallback EN)
    from .config import TRANS_DIR
    texts = []
    for fn in window[-5:]:   # chỉ cần 5 chương gần nhất cho emotion
        base, _ = os.path.splitext(fn)
        vn_path = os.path.join(TRANS_DIR, f"{base}_VN.txt")
        en_path = os.path.join(RAW_DIR, fn)
        for path in [vn_path, en_path]:
            text = load_text(path)
            if text.strip():
                texts.append((fn, text[:3000]))
                break

    if not texts:
        return

    user_msg = "\n\n---\n\n".join(f"### {fn}\n\n{t}" for fn, t in texts)

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=_EMOTION_SYSTEM,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        raw = response.text or "{}"
        import re
        clean = re.sub(r"^```json\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)
        data  = json.loads(clean)
        states = data.get("emotional_states", [])
    except Exception as e:
        logging.error(f"Emotion extract: {e}")
        return

    if not states:
        return

    # Ghi vào Characters_Active.json
    from .io_utils import load_json, save_json
    char_data = load_json(str(CHARACTERS_ACTIVE_FILE)) or {}
    chars     = char_data.get("characters", {})
    updated   = 0

    # Reset nhân vật lâu không update
    for name, profile in chars.items():
        em = profile.get("emotional_state", {})
        last_ch = em.get("last_chapter_index", 0)
        if (current_index - last_ch) >= EMOTION_RESET_CHAPTERS:
            if em.get("current", "normal") != "normal":
                profile.setdefault("emotional_state", {})["current"] = "normal"
                profile["emotional_state"]["reset_at"] = current_index
                updated += 1

    # Cập nhật từ kết quả scout
    for entry in states:
        char_name = entry.get("character", "").strip()
        state     = entry.get("state", "normal").strip()
        reason    = entry.get("reason", "").strip()
        intensity = entry.get("intensity", "medium").strip()

        if not char_name:
            continue
        # Tìm match (không phân biệt hoa thường)
        matched = next(
            (n for n in chars if n.lower() == char_name.lower()),
            None
        )
        if not matched:
            continue

        chars[matched]["emotional_state"] = {
            "current"            : state,
            "intensity"          : intensity,
            "reason"             : reason,
            "last_chapter_index" : current_index,
        }
        updated += 1

    if updated:
        save_json(str(CHARACTERS_ACTIVE_FILE), char_data)
        non_normal = [
            f"{n}={p['emotional_state']['current']}"
            for n, p in chars.items()
            if p.get("emotional_state", {}).get("current", "normal") != "normal"
        ]
        print(f"  💭 Emotion Tracker: {updated} nhân vật cập nhật"
              + (f" | Active: {', '.join(non_normal[:5])}" if non_normal else " | Tất cả normal"))


def _write_empty_note(reason: str) -> None:
    note = (f"# Context Notes\n_Không có dữ liệu: {reason}_\n\n"
            "## 1. MẠCH TRUYỆN ĐẶC BIỆT\nKhông có.\n\n"
            "## 2. KHOÁ XƯNG HÔ ĐANG ACTIVE\nChưa xác định.\n\n"
            "## 3. DIỄN BIẾN GẦN NHẤT\nKhông có.\n\n"
            "## 4. CẢNH BÁO CHO AI DỊCH\nKhông có cảnh báo đặc biệt.\n")
    save_text_atomic(str(CONTEXT_NOTES_FILE), note)

def load_context_notes() -> str:
    return load_text(str(CONTEXT_NOTES_FILE))

def should_refresh(chapters_done: int) -> bool:
    """True khi chapters_done % SCOUT_REFRESH_EVERY == 0 (trước ch.1, sau mỗi N chương)."""
    return chapters_done % SCOUT_REFRESH_EVERY == 0