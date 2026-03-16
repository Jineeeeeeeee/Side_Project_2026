"""
core/models.py — Pydantic schemas cho toàn bộ pipeline.
Gemini API không chấp nhận additionalProperties → _strip() xóa đệ quy.
"""
from pydantic import BaseModel, Field


class TermDetail(BaseModel):
    english    : str = Field(description="Thuật ngữ tiếng Anh gốc")
    vietnamese : str = Field(description="Bản dịch tiếng Việt")
    category   : str = Field(default="general",
                             description="pathways|organizations|items|locations|general")


class HabitualBehavior(BaseModel):
    behavior         : str
    trigger          : str
    intensity        : str  = Field(description="subtle|medium|strong")
    narrative_effect : str
    evidence_chapters: list[str] = Field(default_factory=list)
    confidence       : float     = Field(default=0.7)


class RelationshipEvent(BaseModel):
    chapter: str
    event  : str


class PronounEntry(BaseModel):
    target: str = Field(description="Tên nhân vật HOẶC default_ally/default_enemy/default_elder")
    style : str = Field(description="Đại từ + ngữ cảnh. VD: 'Cậu (thân thiết)'")


class RelationshipDetail(BaseModel):
    with_character : str
    rel_type       : str
    feeling        : str
    dynamic        : str  = Field(
        description=(
            "Cặp đại từ 2 chiều: VD 'Tao/Mày', 'Tớ/Cậu'. "
            "ĐÂY LÀ NGUỒN ƯU TIÊN CAO NHẤT khi dịch hội thoại giữa 2 nhân vật này."
        )
    )
    pronoun_status : str  = Field(
        default="weak",
        description=(
            "weak  = chưa có tương tác đủ để chốt, chọn tạm dựa trên ngữ cảnh. "
            "strong = đã được xác nhận qua tương tác trực tiếp, KHÔNG thay đổi "
            "trừ khi có sự kiện bắt buộc (phản bội, tra khảo, lật mặt, đổi phe...)."
        )
    )
    current_status : str
    tension_points : list[str]               = Field(default_factory=list)
    history        : list[RelationshipEvent] = Field(default_factory=list)


class CharacterDetail(BaseModel):
    name      : str
    full_name : str = ""

    # ── Name Lock ──────────────────────────────────────────────────
    canonical_name     : str             = Field(
        default="",
        description=(
            "Tên CHUẨN dùng xuyên suốt bản dịch. "
            "Để trống nếu giữ nguyên tiếng Anh. "
            "VD: 'Klein' -> để trống; 'The Fool' -> 'Gã Ngốc'."
        )
    )
    alias_canonical_map: dict[str, str]  = Field(
        default_factory=dict,
        description=(
            "Map alias tiếng Anh -> bản chuẩn tiếng Việt. "
            "VD: {'Shadow Scythe': 'Hắc Liêm Thần'}."
        )
    )

    # ── Identity ───────────────────────────────────────────────────
    aliases          : list[str] = Field(default_factory=list)
    active_identity  : str       = Field(default="",
                                         description="Alias/danh tính đang dùng nếu khác tên thật")
    identity_context : str       = Field(default="",
                                         description="Ngữ cảnh dùng alias. VD: 'Khi ở Hội Tarot'")
    current_title    : str = ""
    faction          : str = ""
    cultivation_path : str = ""
    current_level    : str = ""
    signature_skills : list[str] = Field(default_factory=list)
    combat_style     : str = ""
    role             : str = Field(description="MC|Party Member|Enemy|NPC|Mentor|Rival ...")
    archetype        : str = "UNKNOWN"
    personality_traits: list[str] = Field(
        default_factory=list,
        description="4-6 câu mô tả, đủ ngữ cảnh, không keyword ngắn"
    )

    # ── Speech ─────────────────────────────────────────────────────
    pronoun_self        : str                = ""
    formality_level     : str                = "medium"
    formality_note      : str                = ""
    how_refers_to_others: list[PronounEntry] = Field(default_factory=list)
    speech_quirks       : list[str]          = Field(default_factory=list)

    habitual_behaviors  : list[HabitualBehavior]   = Field(default_factory=list)
    relationships       : list[RelationshipDetail] = Field(default_factory=list)
    relationship_to_mc  : str = ""
    current_goal        : str = ""
    hidden_goal         : str = ""
    current_conflict    : str = ""


class RelationshipUpdate(BaseModel):
    character_a       : str
    character_b       : str
    chapter           : str
    event             : str  = Field(description="Mô tả cụ thể sự kiện thay đổi quan hệ")
    new_type          : str  = ""
    new_feeling       : str  = ""
    new_status        : str  = ""
    new_dynamic       : str  = Field(
        default="",
        description=(
            "Cặp đại từ mới nếu thay đổi. "
            "Chỉ điền khi có sự kiện bắt buộc (phản bội, tra khảo, lật mặt, đổi phe...)."
        )
    )
    new_tension       : str  = ""
    promote_to_strong : bool = Field(
        default=False,
        description=(
            "True khi xưng hô weak đã được xác nhận qua tương tác trực tiếp "
            "-> nâng lên strong. Sau đó KHÔNG thay đổi trừ sự kiện bắt buộc."
        )
    )


class SkillUpdate(BaseModel):
    """Kỹ năng mới hoặc kỹ năng tiến hóa — lưu vào Skills.json."""
    english      : str = Field(description="Tên kỹ năng tiếng Anh gốc")
    vietnamese   : str = Field(description="Tên kỹ năng tiếng Việt (dùng ngoặc vuông: [Tên])")
    owner        : str = Field(default="", description="Tên nhân vật sở hữu kỹ năng")
    skill_type   : str = Field(
        default="active",
        description="active|passive|ultimate|evolution|system"
    )
    evolved_from : str = Field(
        default="",
        description="Tên kỹ năng gốc nếu đây là kỹ năng tiến hóa. Để trống nếu là kỹ năng mới."
    )
    description  : str = Field(default="", description="Mô tả ngắn hiệu ứng kỹ năng")
    first_seen   : str = Field(default="", description="Chương xuất hiện lần đầu")


class TranslationResult(BaseModel):
    translation          : str                     = Field(
        description="Bản dịch hoàn chỉnh, giữ nguyên Markdown gốc"
    )
    new_terms            : list[TermDetail]         = Field(default_factory=list)
    new_characters       : list[CharacterDetail]    = Field(default_factory=list)
    relationship_updates : list[RelationshipUpdate] = Field(default_factory=list)
    skill_updates        : list[SkillUpdate]        = Field(
        default_factory=list,
        description=(
            "Kỹ năng MỚI hoặc TIẾN HÓA xuất hiện trong chương này. "
            "Nếu kỹ năng đã có trong Skills.json -> KHÔNG ghi lại. "
            "Nếu không có -> []."
        )
    )


def _strip(schema: dict) -> dict:
    schema.pop("additionalProperties", None)
    for v in schema.values():
        if isinstance(v, dict):
            _strip(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _strip(item)
    return schema


GEMINI_SCHEMA = _strip(TranslationResult.model_json_schema())