"""
src/littrans/engine/scout.py — Scout AI.

Mỗi SCOUT_REFRESH_EVERY chương:
  1. Xóa Context_Notes cũ → sinh mới (4 mục)
  2. Append Arc_Memory (tóm tắt window)
  3. [v4] Cập nhật emotional_state nhân vật

Không raise — pipeline tiếp tục nếu Scout thất bại.

[v4.2] Validate emotional_states là list + giá trị hợp lệ trước khi ghi DB.
[v4.3 FIX] Xoá dead import `from google.genai import types` — không dùng trực tiếp ở đây;
           mọi API call đã được đóng gói trong littrans.llm.client.
"""
from __future__ import annotations

import os
import re
import json
import logging

from littrans.config.settings import settings
from littrans.utils.io_utils import load_text, atomic_write, load_json, save_json

_SCOUT_SYSTEM = """Bạn là Scout AI — đọc trước các chương truyện để sinh ghi chú hỗ trợ AI dịch.

Đọc các chương tiếng Anh, trả về ghi chú ngắn gọn bằng tiếng Việt
theo ĐÚNG 4 mục dưới đây. KHÔNG thêm lời mở đầu hay kết luận.

## 1. MẠCH TRUYỆN ĐẶC BIỆT
Có flashback / hồi ký / giấc mơ / thư từ / cảnh quá khứ không?
Nếu không → "Không có."

## 2. KHOÁ XƯNG HÔ ĐANG ACTIVE
Từng cặp nhân vật + xưng hô hiện tại. Ghi rõ nếu khác theo ngữ cảnh.
VD:
- Arthur ↔ Lyra: hiện tại = Anh–Em | trong hồi ký = Tao–Mày
- System ↔ MC: luôn = Hệ thống–Ký chủ

## 3. DIỄN BIẾN GẦN NHẤT
3–5 sự kiện / thay đổi trạng thái quan trọng nhất.

## 4. CẢNH BÁO CHO AI DỊCH
Những điểm CỤ THỂ dễ sai nếu không có ngữ cảnh.
Nếu không có → "Không có cảnh báo đặc biệt."
VD:
- ⚠️ Chương tiếp theo có thể tiếp tục hồi ký → GIỮ xưng hô Tao–Mày."""

_EMOTION_SYSTEM = """Bạn là AI phân tích cảm xúc nhân vật trong truyện.

Đọc các chương, xác định trạng thái cảm xúc CUỐI CÙNG của từng nhân vật CHÍNH.
Trả về JSON. KHÔNG thêm gì ngoài JSON:
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
- "normal"  : bình thường
- "angry"   : tức giận, bực bội — ảnh hưởng lời thoại
- "hurt"    : tổn thương, buồn — ảnh hưởng lời thoại
- "changed" : vừa trải qua sự kiện lớn thay đổi nhận thức/mục tiêu
- Chỉ nhân vật có tên rõ ràng và xuất hiện đáng kể. Tối đa 8 nhân vật."""

_VALID_STATES      = {"normal", "angry", "hurt", "changed"}
_VALID_INTENSITIES = {"low", "medium", "high"}


# ── Public API ────────────────────────────────────────────────────

def run(all_files: list[str], current_index: int) -> None:
    """Chạy toàn bộ Scout: notes + arc memory + emotion. Không raise."""
    _refresh_context_notes(all_files, current_index)

    start  = max(0, current_index - settings.scout_lookback)
    window = all_files[start:current_index]
    if window:
        range_label = f"{window[0]} → {window[-1]}"
        try:
            from littrans.managers.memory import append_arc_summary
            append_arc_summary(all_files, current_index, range_label)
        except Exception as e:
            logging.error(f"Arc Memory: {e}")
            print(f"  ⚠️  Arc Memory lỗi: {e}")

    try:
        _update_emotional_states(all_files, current_index)
    except Exception as e:
        logging.error(f"Emotion Tracker: {e}")
        print(f"  ⚠️  Emotion Tracker lỗi: {e}")


def should_refresh(chapters_done: int) -> bool:
    return chapters_done % settings.scout_refresh_every == 0


def load_context_notes() -> str:
    return load_text(settings.context_notes_file)


# ── Context Notes ─────────────────────────────────────────────────

def _refresh_context_notes(all_files: list[str], current_index: int) -> None:
    if os.path.exists(str(settings.context_notes_file)):
        print("  🗑️  Context_Notes.md cũ đã xóa.")

    start  = max(0, current_index - settings.scout_lookback)
    window = all_files[start:current_index]
    if not window:
        _write_empty_note("Chưa có chương nào để phân tích.")
        return

    texts = [
        (fn, load_text(str(settings.input_dir / fn))[:6000])
        for fn in window
        if load_text(str(settings.input_dir / fn)).strip()
    ]
    if not texts:
        _write_empty_note("Không đọc được nội dung chương.")
        return

    range_label = f"{window[0]} → {window[-1]}"
    print(f"  🔭 Scout đọc {len(texts)} chương ({range_label})...")
    user_msg = "\n\n---\n\n".join(f"### {fn}\n\n{text}" for fn, text in texts)

    try:
        from littrans.llm.client import call_gemini_text
        body = call_gemini_text(_SCOUT_SYSTEM, user_msg)
    except Exception as e:
        logging.error(f"Scout AI: {e}")
        body = f"⚠️ Scout AI lỗi: {e}"

    note = (
        f"# Context Notes\n"
        f"_Sinh bởi Scout AI · {range_label}_\n\n"
        f"{body.strip()}\n"
    )
    atomic_write(settings.context_notes_file, note)
    print(f"  ✅ Context_Notes.md ({len(note)} ký tự).")


def _write_empty_note(reason: str) -> None:
    note = (
        f"# Context Notes\n_Không có dữ liệu: {reason}_\n\n"
        "## 1. MẠCH TRUYỆN ĐẶC BIỆT\nKhông có.\n\n"
        "## 2. KHOÁ XƯNG HÔ ĐANG ACTIVE\nChưa xác định.\n\n"
        "## 3. DIỄN BIẾN GẦN NHẤT\nKhông có.\n\n"
        "## 4. CẢNH BÁO CHO AI DỊCH\nKhông có cảnh báo đặc biệt.\n"
    )
    atomic_write(settings.context_notes_file, note)


# ── Emotion Tracker ───────────────────────────────────────────────

def _update_emotional_states(all_files: list[str], current_index: int) -> None:
    start  = max(0, current_index - settings.scout_lookback)
    window = all_files[start:current_index]
    if not window:
        return

    texts = []
    for fn in window[-5:]:
        base, _ = os.path.splitext(fn)
        vn_path = str(settings.output_dir / f"{base}_VN.txt")
        en_path = str(settings.input_dir  / fn)
        for path in [vn_path, en_path]:
            text = load_text(path)
            if text.strip():
                texts.append((fn, text[:3000]))
                break

    if not texts:
        return

    user_msg = "\n\n---\n\n".join(f"### {fn}\n\n{t}" for fn, t in texts)

    try:
        from littrans.llm.client import call_gemini_json
        data = call_gemini_json(_EMOTION_SYSTEM, user_msg)
    except Exception as e:
        logging.error(f"Emotion extract: {e}")
        return

    if not isinstance(data, dict):
        logging.warning(f"[Emotion] Response không phải dict: {type(data)}")
        return

    states = data.get("emotional_states", [])

    if not isinstance(states, list):
        logging.warning(
            f"[Emotion] 'emotional_states' không phải list "
            f"(got {type(states).__name__}: {str(states)[:80]}) — bỏ qua."
        )
        return

    if not states:
        return

    char_data = load_json(settings.characters_active_file) or {}
    chars     = char_data.get("characters", {})
    updated   = 0

    for name, profile in chars.items():
        em      = profile.get("emotional_state", {})
        last_ch = em.get("last_chapter_index", 0)
        if (current_index - last_ch) >= settings.emotion_reset_chapters:
            if em.get("current", "normal") != "normal":
                profile.setdefault("emotional_state", {})["current"] = "normal"
                profile["emotional_state"]["reset_at"] = current_index
                updated += 1

    for entry in states:
        if not isinstance(entry, dict):
            continue

        char_name = entry.get("character", "")
        if not isinstance(char_name, str) or not char_name.strip():
            continue
        char_name = char_name.strip()

        state     = entry.get("state", "normal")
        intensity = entry.get("intensity", "medium")
        reason    = entry.get("reason", "")

        if state not in _VALID_STATES:
            logging.warning(f"[Emotion] '{char_name}' state='{state}' không hợp lệ → 'normal'")
            state = "normal"
        if intensity not in _VALID_INTENSITIES:
            intensity = "medium"

        matched = next((n for n in chars if n.lower() == char_name.lower()), None)
        if not matched:
            continue

        chars[matched]["emotional_state"] = {
            "current"            : state,
            "intensity"          : intensity,
            "reason"             : reason if isinstance(reason, str) else "",
            "last_chapter_index" : current_index,
        }
        updated += 1

    if updated:
        save_json(settings.characters_active_file, char_data)
        non_normal = [
            f"{n}={p['emotional_state']['current']}"
            for n, p in chars.items()
            if p.get("emotional_state", {}).get("current", "normal") != "normal"
        ]
        print(f"  💭 Emotion Tracker: {updated} cập nhật"
              + (f" | Active: {', '.join(non_normal[:5])}" if non_normal else " | Tất cả normal"))