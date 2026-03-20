"""
src/littrans/engine/post_analyzer.py — Post-call: review + extract metadata.

Chạy SAU Translation call. Làm 2 việc:
  1. Đánh giá chất lượng bản dịch:
       - Lỗi trình bày/cấu trúc → tự sửa (auto_fix)
       - Lỗi dịch thuật (tên, kỹ năng, pronoun) → yêu cầu retry Trans-call
  2. Extract metadata đầy đủ:
       new_terms, new_characters (full profile), relationship_updates, skill_updates

Severity:
  auto_fix       → Post-call tự sửa trong auto_fixed_translation
  retry_required → Trans-call cần chạy lại với retry_instruction

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


# ── System prompt ─────────────────────────────────────────────────

_POST_SYSTEM = """Bạn là AI editor chuyên review bản dịch LitRPG / Tu Tiên.

Bạn nhận được:
  1. Bản gốc tiếng Anh
  2. Bản dịch tiếng Việt
  3. Chapter Map (tên/skill/pronoun đã lock cho chapter này)

═══════════════════════════════════════════════════════════
NHIỆM VỤ 1 — ĐÁNH GIÁ CHẤT LƯỢNG
═══════════════════════════════════════════════════════════
Phân loại lỗi theo severity:

auto_fix (tự sửa trong auto_fixed_translation):
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

QUAN TRỌNG khi viết auto_fixed_translation:
  - Chỉ sửa đúng những gì bị đánh dấu auto_fix
  - Giữ nguyên toàn bộ nội dung còn lại
  - Nếu không có lỗi auto_fix → để auto_fixed_translation = ""

Trả về JSON. KHÔNG thêm bất cứ thứ gì ngoài JSON:
{
  "quality": {
    "passed": true,
    "auto_fixed_translation": "",
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


# ── Public API ────────────────────────────────────────────────────

def run(
    source_text     : str,
    translation     : str,
    chapter_map     = None,  # ChapterMap | None
    source_filename : str = "",
) -> PostResult:
    """
    Chạy Post-call. Trả về PostResult.
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
        return _parse(data, translation, source_filename)
    except Exception as e:
        logging.error(f"[PostAnalyzer] {source_filename} | {e}")
        print(f"  ⚠️  Post-call lỗi: {e} → dùng bản dịch gốc, bỏ qua metadata")
        return PostResult(
            final_translation = translation,
            passed            = True,   # không block pipeline
            ok                = False,
        )


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

    passed  = bool(quality.get("passed", True))
    auto_tx = quality.get("auto_fixed_translation", "").strip()
    retry   = quality.get("retry_instruction", "").strip()

    has_auto_fix_issues = any(i.severity == "auto_fix" for i in issues)
    if has_auto_fix_issues and auto_tx:
        final_translation = auto_tx
        auto_fixed        = True
        _log_fixes(issues, filename)
    else:
        final_translation = original_translation
        auto_fixed        = False

    retry_issues = [i for i in issues if i.severity == "retry_required"]
    if retry_issues:
        for issue in retry_issues:
            logging.warning(
                f"[PostAnalyzer] {filename} | {issue.type} | {issue.detail} | at: {issue.location}"
            )

    return PostResult(
        final_translation    = final_translation,
        passed               = passed,
        issues               = issues,
        retry_instruction    = retry,
        new_terms            = _safe_list(metadata.get("new_terms")),
        new_characters       = _safe_list(metadata.get("new_characters")),
        relationship_updates = _safe_list(metadata.get("relationship_updates")),
        skill_updates        = _safe_list(metadata.get("skill_updates")),
        ok                   = True,
        auto_fixed           = auto_fixed,
    )


def _log_fixes(issues: list[QualityIssue], filename: str) -> None:
    fix_issues = [i for i in issues if i.severity == "auto_fix"]
    if fix_issues:
        logging.info(
            f"[PostAnalyzer] {filename} | auto_fix {len(fix_issues)} lỗi: "
            + "; ".join(i.type for i in fix_issues)
        )


def _safe_list(v: Any) -> list:
    return v if isinstance(v, list) else []