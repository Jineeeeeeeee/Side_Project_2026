"""
src/littrans/engine/post_analyzer.py — Post-call: review + extract metadata.

Chạy SAU Translation call. Làm 2 việc:
  1. Đánh giá chất lượng bản dịch:
       - Lỗi trình bày/cấu trúc → gọi _auto_fix_call() riêng (plain text)
       - Lỗi dịch thuật (tên, kỹ năng, pronoun) → yêu cầu retry Trans-call
  2. Extract metadata đầy đủ:
       new_terms, new_characters (full profile), relationship_updates, skill_updates

Severity:
  auto_fix       → gọi plain-text call để sửa → không nhồi text khổng lồ vào JSON
  retry_required → Trans-call cần chạy lại với retry_instruction

[v4.3 FIX] auto_fixed_translation KHÔNG còn nằm trong JSON response.
  Lý do: JSON output token bị giới hạn → text dài dễ bị truncate → json.loads fail
  hoặc LLM trả về chuỗi tóm tắt thay vì full text → ghi đè mất bản dịch.
  Giải pháp: Nếu có auto_fix issues → gọi thêm 1 plain-text call nhỏ để sửa.

Không raise — nếu lỗi hoàn toàn, trả về PostResult với translation gốc + metadata rỗng.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from littrans.config.settings import settings


# ── Output schema ─────────────────────────────────────────────────

@dataclass
class QualityIssue:
    type      : str   # format | structure | name_leak | pronoun | style | missing
    severity  : str   # auto_fix | retry_required
    location  : str   # trích đoạn ngắn nơi xảy ra lỗi
    detail    : str   # mô tả lỗi


@dataclass
class PostResult:
    # Bản dịch cuối cùng — có thể đã được auto_fix
    final_translation   : str

    # Chất lượng
    passed              : bool
    issues              : list[QualityIssue] = field(default_factory=list)
    retry_instruction   : str               = ""

    # Metadata để update Master State
    new_terms           : list[dict]        = field(default_factory=list)
    new_characters      : list[dict]        = field(default_factory=list)
    relationship_updates: list[dict]        = field(default_factory=list)
    skill_updates       : list[dict]        = field(default_factory=list)

    # Meta
    ok                  : bool = True   # False nếu post-call lỗi hoàn toàn
    auto_fixed          : bool = False  # True nếu có auto_fix được áp dụng

    def has_retry_required(self) -> bool:
        return any(i.severity == "retry_required" for i in self.issues)

    def has_auto_fix(self) -> bool:
        return any(i.severity == "auto_fix" for i in self.issues)


# ── System prompts ────────────────────────────────────────────────

# [v4.3] JSON call chỉ trả về issues + metadata — KHÔNG có auto_fixed_translation.
# Tách riêng để tránh truncate JSON khi chương dài.
_POST_SYSTEM = """Bạn là AI editor chuyên review bản dịch LitRPG / Tu Tiên.

Bạn nhận được:
  1. Bản gốc tiếng Anh
  2. Bản dịch tiếng Việt
  3. Chapter Map (tên/skill/pronoun đã lock cho chapter này)

═══════════════════════════════════════════════════════════
NHIỆM VỤ 1 — ĐÁNH GIÁ CHẤT LƯỢNG
═══════════════════════════════════════════════════════════
Phân loại lỗi theo severity:

auto_fix (sẽ được sửa bằng call riêng — chỉ cần MÔ TẢ lỗi, không cần sửa ở đây):
  - Thiếu dòng trống giữa các đoạn văn thường
  - Thoại bị dính dòng (2 người nói cùng dòng)
  - System box / bảng hệ thống có dòng trống thừa GIỮA các dòng trong box
    (Quy tắc: nội dung system box phải liền nhau, KHÔNG có dòng trống ở giữa)
  - Thừa/thiếu dấu cách, markdown lỗi lẻ tẻ

retry_required (Trans-call phải chạy lại):
  - Tên nhân vật / địa danh sai hoặc lọt qua Name Lock
  - Tên kỹ năng sai so với danh sách đã lock
  - Pronoun sai (dùng sai cặp xưng hô đã chốt)
  - Đoạn văn bị mất hoặc ý nghĩa lệch nghiêm trọng
  - Câu bị cắt cụt, thiếu nội dung

═══════════════════════════════════════════════════════════
NHIỆM VỤ 2 — EXTRACT METADATA ĐẦY ĐỦ
═══════════════════════════════════════════════════════════
Đọc bản gốc + bản dịch, extract chính xác.

── new_characters ──────────────────────────────────────────
Nhân vật có tên xuất hiện LẦN ĐẦU → điền FULL profile.

Quy tắc tên:
  - "name" = tên gốc tiếng Anh (dùng làm key trong database)
  - "canonical_name" = tên VN chuẩn sẽ dùng xuyên suốt truyện
  - Tên Hán (Zhang Wei, Xiao Yan) → dịch Hán Việt làm canonical_name
  - Tên phương Tây (Arthur, Klein) → canonical_name = giữ nguyên EN

Quy tắc archetype (chọn đúng 1):
  MC_GREMLIN    → cợt nhả, ảo thật, tự xưng Tao/Tôi
  SYSTEM_AI     → vô cảm, châm biếm ngầm, Hệ thống/Ký chủ
  EDGELORD      → tỏ vẻ nguy hiểm, ngầu lòi, Ta/bọn kiến rệp
  ARROGANT_NOBLE → khinh khỉnh, thượng đẳng, Bản thiếu gia/Ngươi
  BRO_COMPANION → sảng khoái, nhiệt huyết, Tớ/Cậu
  ANCIENT_MAGE  → cổ trang, uyên bác, Lão phu/Tiểu tử
  UNKNOWN       → chưa xác định

Quy tắc personality_traits:
  - 4-6 câu, MỖI câu phải đủ ngữ cảnh để dùng ngay khi dịch
  - KHÔNG dùng keyword ngắn một mình ("lạnh lùng", "mạnh mẽ")
  - ĐÚNG: "Bề ngoài lạnh lùng với người lạ nhưng quan sát — tin rồi thì trung thành tuyệt đối"
  - SAI: "Lạnh lùng, mạnh mẽ, bí ẩn"

Quy tắc pronoun_self:
  Tao / Ta / Tôi / Tớ / Mình / Bổn tọa / Lão phu / Hệ thống...

Quy tắc how_refers_to_others:
  - target: tên nhân vật CỤ THỂ hoặc "default_ally" / "default_enemy" / "default_elder"
  - style: đại từ + ngữ cảnh. VD: "Mày (thân thiết)", "Ngươi (khinh thường)"

Quy tắc relationships.dynamic:
  - Cặp đại từ 2 chiều: VD "Tao/Mày", "Ta/Ngươi", "Anh/Em"
  - Đây là nguồn ƯU TIÊN CAO NHẤT khi dịch hội thoại
  - pronoun_status: "weak" nếu chưa chắc, "strong" nếu đã xác nhận rõ ràng

═══════════════════════════════════════════════════════════

Trả về JSON. KHÔNG thêm bất cứ thứ gì ngoài JSON:
{
  "quality": {
    "passed": true,
    "issues": [
      {
        "type": "format|structure|name_leak|pronoun|style|missing",
        "severity": "auto_fix|retry_required",
        "location": "trích đoạn ngắn dưới 50 ký tự",
        "detail": "mô tả lỗi cụ thể"
      }
    ],
    "retry_instruction": ""
  },
  "metadata": {
    "new_terms": [
      {
        "english": "tên/thuật ngữ EN",
        "vietnamese": "bản dịch VN",
        "category": "general|items|locations|organizations|pathways"
      }
    ],
    "new_characters": [
      {
        "name": "tên gốc EN — dùng làm key",
        "canonical_name": "tên VN chuẩn",
        "alias_canonical_map": { "alias_EN": "alias_VN" },
        "full_name": "tên đầy đủ nếu có, chuỗi rỗng nếu không",
        "aliases": [],
        "active_identity": "danh tính đang dùng nếu khác tên chính, chuỗi rỗng nếu không",
        "identity_context": "ngữ cảnh danh tính, chuỗi rỗng nếu không",
        "current_title": "danh hiệu hiện tại, chuỗi rỗng nếu không",
        "faction": "phe/môn phái, chuỗi rỗng nếu không",
        "cultivation_path": "hệ thống tu luyện, chuỗi rỗng nếu không",
        "current_level": "cấp độ hiện tại, chuỗi rỗng nếu không",
        "signature_skills": [],
        "combat_style": "phong cách chiến đấu, chuỗi rỗng nếu không",
        "role": "MC|Party Member|Enemy|NPC|Mentor|Rival|Love Interest|Antagonist|Unknown",
        "archetype": "MC_GREMLIN|SYSTEM_AI|EDGELORD|ARROGANT_NOBLE|BRO_COMPANION|ANCIENT_MAGE|UNKNOWN",
        "personality_traits": [
          "trait 1 — câu đủ ngữ cảnh, không phải keyword ngắn",
          "trait 2 — câu đủ ngữ cảnh"
        ],
        "pronoun_self": "Tao|Ta|Tôi|...",
        "formality_level": "low|medium-low|medium|medium-high|high",
        "formality_note": "ghi chú formality, chuỗi rỗng nếu không",
        "how_refers_to_others": [
          { "target": "tên cụ thể hoặc default_ally/default_enemy", "style": "đại từ + ngữ cảnh" }
        ],
        "speech_quirks": [],
        "relationships": [
          {
            "with_character": "tên nhân vật kia",
            "rel_type": "ally|enemy|neutral|romantic|family|mentor|rival",
            "feeling": "cảm xúc hiện tại",
            "dynamic": "cặp xưng hô 2 chiều VD: Tao/Mày",
            "pronoun_status": "weak|strong",
            "current_status": "mô tả trạng thái quan hệ hiện tại",
            "tension_points": [],
            "history": []
          }
        ],
        "relationship_to_mc": "mô tả quan hệ với MC, chuỗi rỗng nếu không liên quan",
        "current_goal": "mục tiêu hiện tại, chuỗi rỗng nếu chưa rõ",
        "hidden_goal": "mục tiêu ẩn nếu có dấu hiệu, chuỗi rỗng nếu không",
        "current_conflict": "xung đột nội tâm hiện tại, chuỗi rỗng nếu không"
      }
    ],
    "relationship_updates": [
      {
        "character_a": "tên nhân vật A",
        "character_b": "tên nhân vật B",
        "event": "mô tả sự kiện thay đổi quan hệ",
        "new_type": "loại quan hệ mới nếu thay đổi, chuỗi rỗng nếu không",
        "new_feeling": "cảm xúc mới nếu thay đổi, chuỗi rỗng nếu không",
        "new_status": "trạng thái mới",
        "new_dynamic": "cặp xưng hô mới nếu thay đổi, chuỗi rỗng nếu không",
        "new_tension": "điểm căng thẳng mới nếu có, chuỗi rỗng nếu không",
        "promote_to_strong": false
      }
    ],
    "skill_updates": [
      {
        "english": "tên kỹ năng EN",
        "vietnamese": "[Tên Kỹ Năng VN]",
        "owner": "tên nhân vật sở hữu",
        "skill_type": "active|passive|ultimate|evolution|system",
        "evolved_from": "tên kỹ năng gốc nếu là tiến hóa, chuỗi rỗng nếu không",
        "description": "mô tả ngắn kỹ năng"
      }
    ]
  }
}"""


# [v4.3] Prompt cho plain-text auto-fix call riêng biệt.
# Chỉ chạy khi có auto_fix issues — input nhỏ, output là plain text → không lo truncate.
_AUTO_FIX_SYSTEM = """Bạn là AI editor chỉnh sửa trình bày bản dịch tiếng Việt.

Nhận vào: bản dịch + danh sách lỗi trình bày cụ thể.
Yêu cầu:
  • Sửa ĐÚNG các lỗi được liệt kê, không thêm không bớt.
  • KHÔNG thay đổi bất kỳ nội dung, từ ngữ, tên, hay ý nghĩa nào khác.
  • Trả về bản dịch đã sửa — plain text, KHÔNG JSON, KHÔNG code block, KHÔNG lời giải thích."""


# ── Public API ────────────────────────────────────────────────────

def run(
    source_text     : str,
    translation     : str,
    chapter_map     = None,  # ChapterMap | None
    source_filename : str = "",
) -> PostResult:
    """
    Chạy Post-call. Trả về PostResult.

    Flow:
      1. call_gemini_json → quality issues + metadata (JSON nhỏ, không có full text)
      2. Nếu có auto_fix issues → gọi thêm plain-text call để sửa trình bày
      3. Trả về PostResult với final_translation đã sửa (nếu cần)

    Không raise — lỗi trả về PostResult với translation gốc + metadata rỗng.
    """
    if not translation.strip():
        return PostResult(
            final_translation = translation,
            passed            = False,
            ok                = False,
            retry_instruction = "Bản dịch rỗng.",
        )

    user_msg = _build_user_message(source_text, translation, chapter_map)

    try:
        from littrans.llm.client import call_gemini_json
        data = call_gemini_json(_POST_SYSTEM, user_msg)
        result = _parse(data, translation, source_filename)
    except Exception as e:
        logging.error(f"[PostAnalyzer] {source_filename} | {e}")
        print(f"  ⚠️  Post-call lỗi: {e} → dùng bản dịch gốc, bỏ qua metadata")
        return PostResult(
            final_translation = translation,
            passed            = True,   # không block pipeline
            ok                = False,
        )

    # ── Bước 2: Auto-fix bằng plain-text call riêng ───────────────
    # [v4.3] Tách khỏi JSON để tránh truncation và ghi đè nhầm.
    if result.has_auto_fix():
        auto_fix_issues = [i for i in result.issues if i.severity == "auto_fix"]
        fixed = _auto_fix_call(translation, auto_fix_issues, source_filename)
        if fixed:
            result.final_translation = fixed
            result.auto_fixed        = True

    return result


# ── Auto-fix plain-text call ──────────────────────────────────────

def _auto_fix_call(
    translation : str,
    issues      : list[QualityIssue],
    filename    : str = "",
) -> str:
    """
    Gọi LLM với plain-text output để sửa lỗi trình bày.
    Trả về bản dịch đã sửa, hoặc chuỗi rỗng nếu lỗi / kết quả không hợp lệ.
    """
    issue_lines = "\n".join(
        f"  - [{i.type}] {i.detail}"
        + (f" | vị trí: «{i.location}»" if i.location else "")
        for i in issues
    )
    user_msg = (
        f"## LỖI TRÌNH BÀY CẦN SỬA\n{issue_lines}\n\n"
        f"## BẢN DỊCH\n{translation}"
    )

    try:
        from littrans.llm.client import call_gemini_text
        fixed = call_gemini_text(_AUTO_FIX_SYSTEM, user_msg).strip()
    except Exception as e:
        logging.error(f"[PostAnalyzer.AutoFix] {filename} | {e}")
        print(f"  ⚠️  Auto-fix call lỗi: {e} → giữ nguyên bản dịch")
        return ""

    # Sanity check: bản sửa phải đủ dài (≥ 50% độ dài gốc) để không ghi đè nhầm
    MIN_RATIO = 0.50
    if not fixed or len(fixed) < len(translation) * MIN_RATIO:
        logging.warning(
            f"[PostAnalyzer.AutoFix] {filename} | Kết quả quá ngắn "
            f"({len(fixed)} / {len(translation)} ký tự) → bỏ qua"
        )
        print(f"  ⚠️  Auto-fix trả về văn bản quá ngắn → giữ nguyên bản dịch gốc")
        return ""

    return fixed


# ── Helpers ───────────────────────────────────────────────────────

def _build_user_message(
    source_text : str,
    translation : str,
    chapter_map,
) -> str:
    parts = []

    if chapter_map and not chapter_map.is_empty():
        parts.append(f"## CHAPTER MAP\n{chapter_map.to_prompt_block()}")

    MAX_CHARS = 15_000
    src_preview = source_text[:MAX_CHARS]
    if len(source_text) > MAX_CHARS:
        src_preview += "\n[... bị cắt bớt ...]"
    tl_preview = translation[:MAX_CHARS]
    if len(translation) > MAX_CHARS:
        tl_preview += "\n[... bị cắt bớt ...]"

    parts.append(f"## BẢN GỐC (EN)\n{src_preview}")
    parts.append(f"## BẢN DỊCH (VN)\n{tl_preview}")

    return "\n\n---\n\n".join(parts)


def _parse(data: dict, original_translation: str, filename: str) -> PostResult:
    quality  = data.get("quality", {})
    metadata = data.get("metadata", {})

    issues = []
    for raw in quality.get("issues", []):
        if not isinstance(raw, dict):
            continue
        issues.append(QualityIssue(
            type     = raw.get("type", "unknown"),
            severity = raw.get("severity", "auto_fix"),
            location = raw.get("location", ""),
            detail   = raw.get("detail", ""),
        ))

    passed = bool(quality.get("passed", True))
    retry  = quality.get("retry_instruction", "").strip()

    retry_issues = [i for i in issues if i.severity == "retry_required"]
    if retry_issues:
        for issue in retry_issues:
            logging.warning(
                f"[PostAnalyzer] {filename} | {issue.type} | {issue.detail} | at: {issue.location}"
            )

    if [i for i in issues if i.severity == "auto_fix"]:
        count = sum(1 for i in issues if i.severity == "auto_fix")
        logging.info(f"[PostAnalyzer] {filename} | auto_fix {count} lỗi: "
                     + "; ".join(i.type for i in issues if i.severity == "auto_fix"))

    return PostResult(
        final_translation    = original_translation,  # auto_fix sẽ cập nhật sau nếu cần
        passed               = passed,
        issues               = issues,
        retry_instruction    = retry,
        new_terms            = _safe_list(metadata.get("new_terms")),
        new_characters       = _safe_list(metadata.get("new_characters")),
        relationship_updates = _safe_list(metadata.get("relationship_updates")),
        skill_updates        = _safe_list(metadata.get("skill_updates")),
        ok                   = True,
        auto_fixed           = False,  # sẽ được set True bởi _auto_fix_call nếu thành công
    )


def _safe_list(v: Any) -> list:
    return v if isinstance(v, list) else []