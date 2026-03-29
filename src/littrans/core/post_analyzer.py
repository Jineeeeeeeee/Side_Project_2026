"""
src/littrans/core/post_analyzer.py — Post-call: review + extract metadata.

[FIX v2] Auto-escalate warn → retry_required for critical issues that small models
         tend to mislabel (truncated content, missing paragraphs, name leaks).
         Also fixes 'passed' logic: if any retry_required issue exists → passed=False.
         Improves _POST_SYSTEM prompt clarity for smaller models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from littrans.utils.io_utils import safe_list


# ── Output schema ─────────────────────────────────────────────────

@dataclass
class QualityIssue:
    type      : str   # format | structure | name_leak | pronoun | style | missing
    severity  : str   # warn | retry_required
    location  : str   # trích đoạn ngắn nơi xảy ra lỗi
    detail    : str   # mô tả lỗi


@dataclass
class PostResult:
    # Bản dịch cuối cùng
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
    ok                  : bool = True

    def has_retry_required(self) -> bool:
        return any(i.severity == "retry_required" for i in self.issues)


# ── Severity escalation rules ─────────────────────────────────────

# Các issue type mà nếu có keyword nghiêm trọng → bắt buộc retry
_ESCALATE_TYPES = frozenset({"format", "missing", "structure", "name_leak", "pronoun"})

# Keywords trong `detail` cho thấy lỗi thực sự nghiêm trọng
# (small models hay mislabel những lỗi này là "warn")
_CRITICAL_KEYWORDS = frozenset({
    # Truncation / missing content
    "cắt cụt", "bị cắt", "missing content", "bị mất", "thiếu nội dung",
    "mất đoạn", "mất nội dung", "thiếu đoạn", "bỏ sót đoạn",
    "truncat", "incomplete", "cut off",
    # Name / skill errors
    "tên gốc", "name lock", "còn sót", "dùng sai tên", "sai tên",
    "không dịch tên", "giữ nguyên tên tiếng anh",
    # Pronoun errors
    "sai xưng hô", "xưng hô không đúng", "pronoun sai",
    # Missing translation
    "không dịch", "bỏ qua đoạn", "đoạn chưa dịch",
})


def _escalate_severity(issues: list[QualityIssue]) -> list[QualityIssue]:
    """
    Auto-escalate warn → retry_required for clearly critical issues.

    Small models (flash-lite, haiku) regularly mislabel serious issues as 'warn':
    - Truncated chapters detected by post-call
    - Name lock violations
    - Missing paragraphs

    This function catches those cases deterministically in Python,
    independent of what the AI model decided.
    """
    result = []
    for issue in issues:
        if issue.severity == "warn":
            detail_lower = issue.detail.lower()
            is_escalatable_type = issue.type in _ESCALATE_TYPES
            has_critical_kw = any(kw in detail_lower for kw in _CRITICAL_KEYWORDS)

            if is_escalatable_type and has_critical_kw:
                logging.warning(
                    f"[PostAnalyzer] Auto-escalate warn→retry_required: "
                    f"[{issue.type}] {issue.detail[:100]}"
                )
                issue = QualityIssue(
                    type     = issue.type,
                    severity = "retry_required",
                    location = issue.location,
                    detail   = issue.detail + "  ⬆ [auto-escalated]",
                )
        result.append(issue)
    return result


# ── System prompt ─────────────────────────────────────────────────

_POST_SYSTEM = """Bạn là AI editor chuyên review bản dịch LitRPG / Tu Tiên.

Bạn nhận được:
  1. Bản gốc tiếng Anh
  2. Bản dịch tiếng Việt (đã qua code cleanup cơ bản)
  3. Chapter Map (tên/skill/pronoun đã lock cho chapter này)

═══════════════════════════════════════════════════════════════
NHIỆM VỤ 1 — ĐÁNH GIÁ CHẤT LƯỢNG
═══════════════════════════════════════════════════════════════
Lưu ý: Bản dịch đã qua code cleanup (dấu câu, dòng trống, code block wrapper).

NGUYÊN TẮC PHÂN LOẠI SEVERITY:
  retry_required = Trans-call PHẢI chạy lại, người đọc thấy lỗi rõ ràng
  warn           = Chỉ ghi log, không cần chạy lại

retry_required — CÁC TRƯỜNG HỢP SAU BẮT BUỘC DÙNG retry_required:
  ✗ Tên nhân vật / địa danh sai (dùng tên EN khi đã có tên VN trong Chapter Map)
  ✗ Tên kỹ năng sai so với danh sách đã lock trong Chapter Map
  ✗ Pronoun sai (dùng sai cặp xưng hô đã chốt, VD: "Anh/Em" thay vì "Ta/Ngươi")
  ✗ Đoạn văn bị cắt cụt, mất nội dung, thiếu đoạn so với bản gốc
  ✗ Câu bị bỏ qua hoàn toàn, không có trong bản dịch
  ✗ Ý nghĩa bị dịch ngược hoặc sai hoàn toàn

warn — CHỈ dùng warn khi:
  ~ Văn phong chưa tự nhiên nhưng ý đúng
  ~ Thuật ngữ dịch chưa hay nhưng không sai
  ~ Lỗi format nhỏ không ảnh hưởng nội dung

LƯU Ý QUAN TRỌNG — CẮT CỤT:
  Nếu bạn không thể xem toàn bộ bản gốc/bản dịch do giới hạn ký tự,
  hãy ghi issue với severity: "retry_required" và type: "format",
  không phải "warn" hay "style". Đây là lỗi nghiêm trọng cần kiểm tra.

KHÔNG báo cáo:
  - Dấu câu, dòng trống, code block — đã được xử lý tự động
  - Lỗi spacing thông thường

═══════════════════════════════════════════════════════════════
NHIỆM VỤ 2 — EXTRACT METADATA ĐẦY ĐỦ
═══════════════════════════════════════════════════════════════
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

Quy tắc relationships.dynamic:
  - Cặp đại từ 2 chiều: VD "Tao/Mày", "Ta/Ngươi", "Anh/Em"
  - pronoun_status: "weak" nếu chưa chắc, "strong" nếu đã xác nhận rõ ràng

Quy tắc relationships.intimacy_level:
  1 = FORMAL (lạnh lùng, trang trọng)
  2 = NEUTRAL (mặc định)
  3 = FRIENDLY (thân thiện, thoải mái)
  4 = CLOSE (rất thân, nickname, bỏ kính ngữ)
  5 = INTIMATE (yêu/gia đình gần gũi, ngôn ngữ đặc biệt)

═══════════════════════════════════════════════════════════════

Trả về JSON. KHÔNG thêm bất cứ thứ gì ngoài JSON:
{
  "quality": {
    "passed": true,
    "issues": [
      {
        "type": "format|structure|name_leak|pronoun|style|missing",
        "severity": "warn|retry_required",
        "location": "trích đoạn ngắn dưới 50 ký tự",
        "detail": "mô tả lỗi cụ thể"
      }
    ],
    "retry_instruction": "hướng dẫn cụ thể để Trans-call sửa (chỉ điền khi có retry_required)"
  },
  "metadata": {
    "new_terms": [],
    "new_characters": [],
    "relationship_updates": [],
    "skill_updates": []
  }
}"""


# ── Public API ────────────────────────────────────────────────────

def run(
    source_text     : str,
    translation     : str,
    chapter_map     = None,
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
            passed            = True,
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
        src_preview += (
            f"\n[... BỊ CẮT — bản gốc còn {len(source_text) - MAX_CHARS:,} ký tự phía sau ...]"
        )
    tl_preview = translation[:MAX_CHARS]
    if len(translation) > MAX_CHARS:
        tl_preview += (
            f"\n[... BỊ CẮT — bản dịch còn {len(translation) - MAX_CHARS:,} ký tự phía sau ...]"
        )

    parts.append(f"## BẢN GỐC (EN)\n{src_preview}")
    parts.append(f"## BẢN DỊCH (VN)\n{tl_preview}")

    return "\n\n---\n\n".join(parts)


def _parse(data: dict, original_translation: str, filename: str) -> PostResult:
    quality  = data.get("quality", {})
    metadata = data.get("metadata", {})

    # ── Parse raw issues ──────────────────────────────────────────
    issues = []
    for raw in quality.get("issues", []):
        if not isinstance(raw, dict):
            continue
        severity = raw.get("severity", "warn")
        # Map legacy "auto_fix" → "warn" (post_processor đã xử lý)
        if severity == "auto_fix":
            severity = "warn"
        issues.append(QualityIssue(
            type     = raw.get("type", "unknown"),
            severity = severity,
            location = raw.get("location", ""),
            detail   = raw.get("detail", ""),
        ))

    # ── [FIX] Auto-escalate critical mislabeled issues ────────────
    issues = _escalate_severity(issues)

    # ── [FIX] passed must be False if any retry_required exists ───
    # AI sometimes returns passed=true even with retry_required issues
    has_critical = any(i.severity == "retry_required" for i in issues)
    ai_passed    = bool(quality.get("passed", True))
    passed       = ai_passed and not has_critical

    retry = quality.get("retry_instruction", "").strip()

    # ── [FIX] Auto-generate retry_instruction if missing ─────────
    if has_critical and not retry:
        retry_details = [
            f"[{i.type}] {i.detail}"
            for i in issues if i.severity == "retry_required"
        ]
        retry = "Sửa các lỗi sau: " + " | ".join(retry_details)

    # ── Log retry_required issues ─────────────────────────────────
    retry_issues = [i for i in issues if i.severity == "retry_required"]
    for issue in retry_issues:
        logging.warning(
            f"[PostAnalyzer] {filename} | {issue.type} | {issue.detail} | at: {issue.location}"
        )

    return PostResult(
        final_translation    = original_translation,
        passed               = passed,
        issues               = issues,
        retry_instruction    = retry,
        new_terms            = safe_list(metadata.get("new_terms")),
        new_characters       = safe_list(metadata.get("new_characters")),
        relationship_updates = safe_list(metadata.get("relationship_updates")),
        skill_updates        = safe_list(metadata.get("skill_updates")),
        ok                   = True,
    )


# ── Auto-fix prompt ───────────────────────────────────────────────

_AUTO_FIX_SYSTEM = """Bạn là AI editor chuyên vá lỗi bản dịch LitRPG/Tu Tiên.
Nhận bản dịch tiếng Việt + danh sách lỗi cụ thể cần sửa.

QUY TẮC CỨNG:
1. Chỉ sửa đúng các lỗi được liệt kê — KHÔNG thay đổi phần không liên quan.
2. Giữ nguyên toàn bộ format: dòng trống, *nghiêng*, **đậm**, [Kỹ năng], system box.
3. Nếu có NAME LOCK → bắt buộc dùng bản chuẩn đã cho, không ngoại lệ.
4. KHÔNG thêm lời mở đầu, kết luận, chú thích.

Trả về BẢN DỊCH ĐÃ SỬA — plain text, không JSON, không markdown fences."""


# ── Public ────────────────────────────────────────────────────────

def auto_fix_translation(
    translation     : str,
    issues          : list[QualityIssue],
    name_lock_table : dict[str, str] | None = None,
    source_filename : str = "",
) -> tuple[str, list[str]]:
    """
    Targeted AI fix thay vì full Trans-call retry.
    Gửi bản dịch + danh sách lỗi → AI sửa chính xác → trả về bản đã vá.

    Chi phí: ~1 Gemini call (nhẹ) thay vì 1 Trans-call đầy đủ.

    Returns:
        (fixed_translation, fix_descriptions)
        (original_translation, []) nếu thất bại hoặc không có lỗi cần sửa.
    """
    retry_issues = [i for i in issues if i.severity == "retry_required"]
    if not retry_issues:
        return translation, []

    # ── Build issue block ─────────────────────────────────────────
    issues_block = "\n".join(
        f"  {idx + 1}. [{i.type}] tại «{i.location[:60]}» — {i.detail}"
        for idx, i in enumerate(retry_issues)
    )

    # ── Relevant Name Lock only (giảm token) ─────────────────────
    nl_block = ""
    if name_lock_table:
        relevant = {
            k: v for k, v in name_lock_table.items()
            if k.lower() in translation.lower()
        }
        if relevant:
            nl_block = (
                "\n\nNAME LOCK BẮT BUỘC:\n"
                + "\n".join(f"  {eng} → {vn}" for eng, vn in relevant.items())
            )

    # ── Truncate translation nếu quá dài ─────────────────────────
    MAX_CHARS    = 12_000
    is_truncated = len(translation) > MAX_CHARS
    tl_content   = translation[:MAX_CHARS]
    if is_truncated:
        tl_content += "\n\n[... phần còn lại không gửi — giữ nguyên khi ghép lại ...]"

    user_msg = (
        f"SỬA {len(retry_issues)} LỖI SAU:\n"
        f"{issues_block}"
        f"{nl_block}\n\n"
        f"BẢN DỊCH CẦN SỬA:\n"
        f"{tl_content}"
    )

    try:
        from littrans.llm.client import call_gemini_text
        fixed = call_gemini_text(_AUTO_FIX_SYSTEM, user_msg)

        if not fixed or not fixed.strip():
            logging.warning(f"[AutoFix] {source_filename}: AI trả về rỗng")
            return translation, []

        # Sanity check: không để AI bị mất nội dung
        min_acceptable = len(translation) * 0.75
        if len(fixed) < min_acceptable:
            logging.warning(
                f"[AutoFix] {source_filename}: kết quả quá ngắn "
                f"({len(fixed)} < {min_acceptable:.0f} chars) → từ chối"
            )
            return translation, []

        # Ghép lại phần bị truncate (nếu có)
        if is_truncated:
            fixed = fixed.rstrip("\n") + "\n\n" + translation[MAX_CHARS:].lstrip("\n")

        fix_summaries = [f"[{i.type}] {i.detail}" for i in retry_issues]
        logging.info(
            f"[AutoFix] {source_filename}: patched {len(retry_issues)} issues "
            f"({len(translation)} → {len(fixed)} chars)"
        )
        return fixed, fix_summaries

    except Exception as e:
        logging.warning(f"[AutoFix] {source_filename}: {e}")
        return translation, []