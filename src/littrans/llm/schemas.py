"""
src/littrans/llm/schemas.py — Pydantic schemas cho toàn bộ pipeline.

[FIX] Xoá GEMINI_SCHEMA — không còn caller nào dùng (pipeline dùng plain text output).
     _strip() giữ lại vì vẫn cần nếu ai dùng structured output trong tương lai.

[v5.0] EPS (Emotional Proximity Signal):
  RelationshipDetail.intimacy_level (int 1–5)
  RelationshipDetail.eps_signals    (list[str])
  RelationshipUpdate.new_intimacy_level
  RelationshipUpdate.new_eps_signals
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── Glossary ──────────────────────────────────────────────────────

class TermDetail(BaseModel):
    english    : str = Field(description="Thuật ngữ tiếng Anh gốc")
    vietnamese : str = Field(description="Bản dịch tiếng Việt")
    category   : str = Field(
        default="general",
        description="pathways|organizations|items|locations|general",
    )


# ── Skills ────────────────────────────────────────────────────────

class SkillUpdate(BaseModel):
    """Kỹ năng mới hoặc kỹ năng tiến hóa — lưu vào Skills.json."""
    english      : str = Field(description="Tên kỹ năng tiếng Anh gốc")
    vietnamese   : str = Field(description="Tên kỹ năng tiếng Việt (dùng ngoặc vuông: [Tên])")
    owner        : str = Field(default="")
    skill_type   : str = Field(default="active", description="active|passive|ultimate|evolution|system")
    evolved_from : str = Field(default="", description="Tên kỹ năng gốc nếu là kỹ năng tiến hóa")
    description  : str = Field(default="")
    first_seen   : str = Field(default="")


# ── Characters ───────────────────────────────────────────────────

class HabitualBehavior(BaseModel):
    behavior          : str
    trigger           : str
    intensity         : str   = Field(description="subtle|medium|strong")
    narrative_effect  : str
    evidence_chapters : list[str] = Field(default_factory=list)
    confidence        : float     = Field(default=0.7)


class RelationshipEvent(BaseModel):
    chapter : str
    event   : str


class PronounEntry(BaseModel):
    target : str = Field(description="Tên nhân vật HOẶC default_ally/default_enemy/default_elder")
    style  : str = Field(description="Đại từ + ngữ cảnh. VD: 'Cậu (thân thiết)'")


class RelationshipDetail(BaseModel):
    with_character  : str
    rel_type        : str
    feeling         : str
    dynamic         : str   = Field(
        description="Cặp đại từ 2 chiều: VD 'Tao/Mày'. "
                    "ĐÂY LÀ NGUỒN ƯU TIÊN CAO NHẤT khi dịch hội thoại."
    )
    pronoun_status  : str   = Field(
        default="weak",
        description="weak = chưa chốt | strong = đã xác nhận, KHÔNG thay đổi",
    )

    # ── EPS fields (v5.0) ─────────────────────────────────────────
    intimacy_level  : int   = Field(
        default=2,
        description=(
            "Mức độ thân mật 1–5: "
            "1=FORMAL(lạnh/trang trọng) | 2=NEUTRAL | 3=FRIENDLY(thân thiện) "
            "| 4=CLOSE(rất thân, nickname) | 5=INTIMATE(yêu/gia đình gần gũi)"
        ),
    )
    eps_signals     : list[str] = Field(
        default_factory=list,
        description=(
            "Dấu hiệu cụ thể về mức độ thân mật: "
            "kính ngữ có dùng không, nickname, độ dài câu, chia sẻ cảm xúc..."
        ),
    )

    current_status  : str
    tension_points  : list[str]               = Field(default_factory=list)
    history         : list[RelationshipEvent] = Field(default_factory=list)


class CharacterDetail(BaseModel):
    name       : str
    full_name  : str = ""

    # Name Lock
    canonical_name      : str            = Field(default="")
    alias_canonical_map : dict[str, str] = Field(default_factory=dict)

    # Identity
    aliases          : list[str] = Field(default_factory=list)
    active_identity  : str       = Field(default="")
    identity_context : str       = Field(default="")
    current_title    : str = ""
    faction          : str = ""
    cultivation_path : str = ""
    current_level    : str = ""
    signature_skills : list[str] = Field(default_factory=list)
    combat_style     : str = ""
    role             : str = Field(description="MC|Party Member|Enemy|NPC|Mentor|Rival ...")
    archetype        : str = "UNKNOWN"
    personality_traits : list[str] = Field(
        default_factory=list,
        description="4-6 câu mô tả, đủ ngữ cảnh, không keyword ngắn",
    )

    # Speech
    pronoun_self         : str               = ""
    formality_level      : str               = "medium"
    formality_note       : str               = ""
    how_refers_to_others : list[PronounEntry] = Field(default_factory=list)
    speech_quirks        : list[str]          = Field(default_factory=list)

    habitual_behaviors : list[HabitualBehavior]   = Field(default_factory=list)
    relationships      : list[RelationshipDetail] = Field(default_factory=list)
    relationship_to_mc : str = ""
    current_goal       : str = ""
    hidden_goal        : str = ""
    current_conflict   : str = ""


# ── Relationship update ───────────────────────────────────────────

class RelationshipUpdate(BaseModel):
    character_a       : str
    character_b       : str
    chapter           : str
    event             : str   = Field(description="Mô tả cụ thể sự kiện")
    new_type          : str   = ""
    new_feeling       : str   = ""
    new_status        : str   = ""
    new_dynamic       : str   = Field(default="")
    new_tension       : str   = ""
    promote_to_strong : bool  = Field(
        default=False,
        description="True khi xưng hô weak đã được xác nhận → nâng lên strong",
    )

    # ── EPS update fields (v5.0) ──────────────────────────────────
    new_intimacy_level : int       = Field(
        default=0,
        description="0 = không thay đổi. 1–5 = cập nhật mức độ thân mật mới.",
    )
    new_eps_signals    : list[str] = Field(
        default_factory=list,
        description="Dấu hiệu mới về mức độ thân mật để append vào eps_signals.",
    )


# ── Top-level response ────────────────────────────────────────────

class TranslationResult(BaseModel):
    translation          : str                      = Field(description="Bản dịch hoàn chỉnh")
    new_terms            : list[TermDetail]          = Field(default_factory=list)
    new_characters       : list[CharacterDetail]     = Field(default_factory=list)
    relationship_updates : list[RelationshipUpdate]  = Field(default_factory=list)
    skill_updates        : list[SkillUpdate]         = Field(
        default_factory=list,
        description="Kỹ năng MỚI hoặc TIẾN HÓA. Đã có → KHÔNG ghi lại.",
    )


# ── EPS constants (dùng bởi characters.py và prompt_builder.py) ───

EPS_LABELS = {
    1: ("FORMAL",      "lạnh lùng/trang trọng — giữ kính ngữ, câu đầy đủ"),
    2: ("NEUTRAL",     "mặc định — xưng hô theo dynamic đã chốt"),
    3: ("FRIENDLY",    "thân thiện — xưng hô thoải mái, câu ngắn hơn"),
    4: ("CLOSE",       "rất thân — bỏ kính ngữ, có thể dùng nickname"),
    5: ("INTIMATE",    "yêu/gia đình — ngôn ngữ đặc biệt, thân mật tuyệt đối"),
}

EPS_BAR = {1: "█░░░░", 2: "██░░░", 3: "███░░", 4: "████░", 5: "█████"}


# ── Schema helper (giữ lại cho tương lai nếu cần structured output) ──

def _strip(schema: dict) -> dict:
    """Xóa additionalProperties để Gemini API không reject schema."""
    schema.pop("additionalProperties", None)
    for v in schema.values():
        if isinstance(v, dict):
            _strip(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _strip(item)
    return schema