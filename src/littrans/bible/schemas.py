"""
src/littrans/bible/schemas.py — Pydantic schemas cho 3 tầng Bible System.

Tầng 1 — Database:
  BibleCharacter, BibleItem, BibleLocation, BibleSkill, BibleFaction, BibleConcept

Tầng 2 — WorldBuilding:
  BibleWorldBuilding (cultivation, geography, rules, economy, cosmology)

Tầng 3 — Main Lore:
  BibleChapterSummary, BibleEvent, BiblePlotThread, BibleRevelation

Staging:
  ScanOutput — raw output từ 1 scan call, chưa được hợp nhất

[v1.0] Initial implementation — Bible System Sprint 1
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# TẦNG 1 — DATABASE
# ═══════════════════════════════════════════════════════════════════

class BibleRelationship(BaseModel):
    """Quan hệ giữa 2 entity trong Database."""
    target_id       : str  = ""   # char_id / faction_id / ...
    target_name     : str  = ""   # human-readable fallback
    rel_type        : str  = ""   # ally|enemy|neutral|romantic|family|mentor|rival
    dynamic         : str  = ""   # cặp đại từ: "Tao/Mày", "Ta/Ngươi"
    eps_level       : int  = 2    # 1–5 Emotional Proximity Signal
    description     : str  = ""
    established_chapter: str = ""


class BibleCharacter(BaseModel):
    """Nhân vật — entity chính của Database."""
    id              : str  = ""          # auto: "char_001"
    type            : str = "character"
    canonical_name  : str  = ""          # "Lý Thanh Vân" — dùng trong bản dịch
    en_name         : str  = ""          # "Li Qingyan" — tên gốc tiếng Anh
    aliases         : list[str] = Field(default_factory=list)
    alias_canonical_map: dict[str, str] = Field(default_factory=dict)  # {en_alias: vn_alias}

    # Xuất hiện
    first_appearance: str  = ""          # "chapter_001.txt"
    last_seen       : str  = ""
    chapter_count   : int  = 0           # số chương xuất hiện

    # Trạng thái
    status          : str  = "alive"     # alive|dead|unknown|ascended|sealed
    role            : str  = "Unknown"
    archetype       : str  = "UNKNOWN"

    # Tu luyện / Power
    faction_id      : str  = ""
    cultivation     : dict[str, Any] = Field(default_factory=dict)
    # {realm, realm_id, constitution, notes}
    skill_ids       : list[str] = Field(default_factory=list)
    combat_style    : str  = ""

    # Nhân cách & lời thoại
    personality_summary : str        = ""
    pronoun_self        : str        = ""
    speech_quirks       : list[str]  = Field(default_factory=list)

    # Quan hệ
    relationships   : list[BibleRelationship] = Field(default_factory=list)
    relationship_to_mc: str = ""

    # Lore
    key_moments     : list[dict[str, str]] = Field(default_factory=list)
    # [{chapter, description, significance}]
    secrets         : list[dict[str, str]] = Field(default_factory=list)
    # [{revealed_chapter, secret, foreshadowed_in}]
    current_goal    : str  = ""
    hidden_goal     : str  = ""

    # Tags tìm kiếm
    tags            : list[str] = Field(default_factory=list)

    # Meta
    confidence      : float = 1.0
    last_updated    : str   = ""


class BibleItem(BaseModel):
    """Vật phẩm, vũ khí, đan dược, artifact."""
    id              : str  = ""
    type            : str = "item"
    canonical_name  : str  = ""
    en_name         : str  = ""
    item_type       : str  = ""    # weapon|pill|artifact|treasure|material|other
    rarity          : str  = ""    # common|rare|epic|legendary|divine
    description     : str  = ""
    effects         : list[str] = Field(default_factory=list)
    owner_ids       : list[str] = Field(default_factory=list)  # char_id list
    location_id     : str  = ""
    first_appearance: str  = ""
    last_seen       : str  = ""
    tags            : list[str] = Field(default_factory=list)
    confidence      : float = 1.0
    last_updated    : str   = ""


class BibleLocation(BaseModel):
    """Địa danh, vùng đất, cõi giới, dungeon."""
    id              : str  = ""
    type            : str = "location"
    canonical_name  : str  = ""
    en_name         : str  = ""
    location_type   : str  = ""    # city|realm|dungeon|sect|mountain|country|other
    parent_id       : str  = ""    # chứa trong location nào (vd: city trong country)
    description     : str  = ""
    controlling_faction_id: str = ""
    notable_features: list[str] = Field(default_factory=list)
    first_appearance: str  = ""
    tags            : list[str] = Field(default_factory=list)
    confidence      : float = 1.0
    last_updated    : str   = ""


class BibleSkill(BaseModel):
    """Kỹ năng, chiêu thức, phép thuật."""
    id              : str  = ""
    type            : str = "skill"
    canonical_name  : str  = ""    # "[Hỏa Cầu]"
    en_name         : str  = ""    # "Fireball"
    skill_type      : str  = ""    # active|passive|ultimate|evolution|system|technique
    user_ids        : list[str] = Field(default_factory=list)  # char_id list
    description     : str  = ""
    effects         : list[str] = Field(default_factory=list)
    requirements    : str  = ""    # điều kiện sử dụng / cảnh giới
    evolution_chain : list[str] = Field(default_factory=list)  # canonical names theo thứ tự
    evolved_from_id : str  = ""
    first_appearance: str  = ""
    tags            : list[str] = Field(default_factory=list)
    confidence      : float = 1.0
    last_updated    : str   = ""


class BibleFaction(BaseModel):
    """Tổ chức, hội phái, môn phái, thế lực."""
    id              : str  = ""
    type            : str = "faction"
    canonical_name  : str  = ""
    en_name         : str  = ""
    faction_type    : str  = ""    # sect|guild|country|family|organization|other
    description     : str  = ""
    leader_id       : str  = ""
    member_ids      : list[str] = Field(default_factory=list)
    headquarters_id : str  = ""    # location_id
    allied_faction_ids  : list[str] = Field(default_factory=list)
    enemy_faction_ids   : list[str] = Field(default_factory=list)
    power_level     : str  = ""
    first_appearance: str  = ""
    tags            : list[str] = Field(default_factory=list)
    confidence      : float = 1.0
    last_updated    : str   = ""


class BibleConcept(BaseModel):
    """Khái niệm thế giới: pathway, law, principle, system element."""
    id              : str  = ""
    type            : str = "concept"
    canonical_name  : str  = ""
    en_name         : str  = ""
    concept_type    : str  = ""    # pathway|law|principle|system|other
    description     : str  = ""
    related_ids     : list[str] = Field(default_factory=list)
    first_appearance: str  = ""
    tags            : list[str] = Field(default_factory=list)
    confidence      : float = 1.0
    last_updated    : str   = ""


# ── Database index entry ──────────────────────────────────────────

class IndexEntry(BaseModel):
    """Entry trong search index — map name_lower → {id, type}."""
    id   : str
    type : str   # character|item|location|skill|faction|concept
    name : str   # canonical_name
    en   : str   # en_name


# ═══════════════════════════════════════════════════════════════════
# TẦNG 2 — WORLDBUILDING
# ═══════════════════════════════════════════════════════════════════

class CultivationRealm(BaseModel):
    """Một cảnh giới trong hệ thống tu luyện."""
    id          : str  = ""
    name_vn     : str  = ""    # "Phàm Cảnh"
    name_en     : str  = ""    # "Mortal Realm"
    order       : int  = 0     # thứ tự từ thấp → cao
    description : str  = ""
    sub_levels  : list[str] = Field(default_factory=list)
    notable_chars: list[str] = Field(default_factory=list)  # char_id


class CultivationSystem(BaseModel):
    """Hệ thống tu luyện tổng thể."""
    name        : str  = ""
    pathway_type: str  = ""    # cultivation|sequence|class|other
    description : str  = ""
    realms      : list[CultivationRealm] = Field(default_factory=list)
    notes       : str  = ""


class GeographyEntry(BaseModel):
    id          : str  = ""
    name_vn     : str  = ""
    name_en     : str  = ""
    description : str  = ""
    parent      : str  = ""    # contained in


class WorldRule(BaseModel):
    """Quy luật thế giới — đã được xác nhận rõ ràng trong truyện."""
    description     : str  = ""
    source_chapter  : str  = ""
    category        : str  = ""    # power|magic|social|cosmological|other
    confidence      : float = 1.0


class BibleWorldBuilding(BaseModel):
    """Tầng 2 — Kiến thức thế giới tích lũy."""
    cultivation_systems : list[CultivationSystem] = Field(default_factory=list)
    geography           : list[GeographyEntry]    = Field(default_factory=list)
    history_notes       : list[str]               = Field(default_factory=list)
    economy_notes       : list[str]               = Field(default_factory=list)
    cosmology_notes     : list[str]               = Field(default_factory=list)
    confirmed_rules     : list[WorldRule]          = Field(default_factory=list)
    last_updated        : str = ""


# ═══════════════════════════════════════════════════════════════════
# TẦNG 3 — MAIN LORE
# ═══════════════════════════════════════════════════════════════════

class BibleChapterSummary(BaseModel):
    """Tóm tắt 1 chương — append-only."""
    chapter         : str  = ""    # "chapter_042.txt"
    chapter_index   : int  = 0
    title           : str  = ""    # tiêu đề chương nếu có
    pov_char_id     : str  = ""    # nhân vật POV chính
    location_id     : str  = ""    # địa điểm chính
    summary         : str  = ""    # tóm tắt 3–5 câu
    key_events      : list[str] = Field(default_factory=list)   # event_ids
    new_entity_ids  : list[str] = Field(default_factory=list)   # entity mới trong chương
    tone            : str  = ""    # action|drama|mystery|comedy|exposition|transition
    scanned_at      : str  = ""


class BibleEvent(BaseModel):
    """Sự kiện lớn có ảnh hưởng xuyên suốt."""
    id              : str  = ""   # "event_001"
    chapter         : str  = ""
    event_type      : str  = ""   # battle|revelation|death|alliance|betrayal|breakthrough|other
    title           : str  = ""   # tóm tắt ngắn
    description     : str  = ""
    participants    : list[str] = Field(default_factory=list)   # char_ids
    location_id     : str  = ""
    consequence     : str  = ""   # ảnh hưởng dài hạn
    foreshadows     : list[str] = Field(default_factory=list)   # event_ids tiếp theo
    resolves        : list[str] = Field(default_factory=list)   # event_ids trước đó
    significance    : str  = "medium"   # low|medium|high|critical


class BiblePlotThread(BaseModel):
    """Tuyến truyện — mở/tiến/đóng theo chương."""
    id              : str  = ""   # "thread_001"
    name            : str  = ""   # "Bí ẩn nguồn gốc MC"
    opened_chapter  : str  = ""
    closed_chapter  : str  = ""   # trống nếu còn mở
    status          : str  = "open"   # open|closed|abandoned
    key_chapters    : list[str] = Field(default_factory=list)
    key_event_ids   : list[str] = Field(default_factory=list)
    summary         : str  = ""
    resolution      : str  = ""   # kết quả cuối khi closed


class BibleRevelation(BaseModel):
    """Tiết lộ lớn — thường có foreshadow trước."""
    id              : str  = ""
    chapter         : str  = ""
    title           : str  = ""
    description     : str  = ""
    foreshadowed_in : list[str] = Field(default_factory=list)   # chapters
    related_thread_ids: list[str] = Field(default_factory=list)
    impact          : str  = ""   # ảnh hưởng đến plot/characters


class BibleMainLore(BaseModel):
    """Tầng 3 — Lore chính, append-only."""
    chapter_summaries : list[BibleChapterSummary] = Field(default_factory=list)
    events            : list[BibleEvent]           = Field(default_factory=list)
    plot_threads      : list[BiblePlotThread]      = Field(default_factory=list)
    revelations       : list[BibleRevelation]      = Field(default_factory=list)
    last_chapter_scanned: str = ""
    event_counter     : int  = 0
    thread_counter    : int  = 0
    revelation_counter: int  = 0


# ═══════════════════════════════════════════════════════════════════
# STAGING — raw scan output chưa được hợp nhất
# ═══════════════════════════════════════════════════════════════════

class ScanCandidate(BaseModel):
    """Một entity candidate từ scan — chưa được verify."""
    entity_type     : str  = ""   # character|item|location|skill|faction|concept
    en_name         : str  = ""
    canonical_name  : str  = ""   # đề xuất từ AI
    existing_id     : str  = ""   # nếu AI cho là đã biết
    is_new          : bool = True
    description     : str  = ""
    raw_data        : dict[str, Any] = Field(default_factory=dict)   # data đầy đủ
    confidence      : float = 1.0
    context_snippet : str  = ""   # đoạn văn trích dẫn


class ScanWorldBuildingClue(BaseModel):
    """Manh mối về thế giới từ scan."""
    category        : str  = ""   # cultivation|geography|rule|history|economy|cosmology
    description     : str  = ""
    raw_text        : str  = ""   # đoạn gốc
    confidence      : float = 0.8


class ScanLoreEntry(BaseModel):
    """Lore entry từ scan 1 chương."""
    chapter_summary : str  = ""
    tone            : str  = ""
    pov_char        : str  = ""   # en_name
    location        : str  = ""   # en_name
    key_events      : list[dict[str, Any]] = Field(default_factory=list)
    # [{type, title, description, participants: list[str], consequence}]
    plot_threads_opened : list[dict[str, Any]] = Field(default_factory=list)
    plot_threads_closed : list[dict[str, Any]] = Field(default_factory=list)   # {thread_name, resolution}
    revelations     : list[dict[str, Any]] = Field(default_factory=list)
    # [{title, description, foreshadowed_in: list[str]}]
    relationship_changes: list[dict[str, Any]] = Field(default_factory=list)
    # [{char_a, char_b, event, new_status}]


class ScanOutput(BaseModel):
    """Raw output từ 1 scan call — lưu trong staging/."""
    source_chapter          : str  = ""
    chapter_index           : int  = 0
    scan_depth              : str  = "standard"   # quick|standard|deep
    database_candidates     : list[ScanCandidate]         = Field(default_factory=list)
    worldbuilding_clues     : list[ScanWorldBuildingClue] = Field(default_factory=list)
    lore_entry              : ScanLoreEntry               = Field(default_factory=ScanLoreEntry)
    scanned_at              : str  = ""
    model_used              : str  = ""
    raw_response            : dict[str, Any] = Field(default_factory=dict)  # raw JSON từ AI


# ═══════════════════════════════════════════════════════════════════
# META & REPORTS
# ═══════════════════════════════════════════════════════════════════

class BibleMeta(BaseModel):
    """Metadata Bible — lưu trong meta.json."""
    schema_version          : str  = "1.0"
    story_title             : str  = ""
    total_chapters          : int  = 0
    scanned_chapters        : int  = 0
    last_scanned_chapter    : str  = ""
    scan_depth_used         : str  = "standard"
    cross_ref_last_run      : str  = ""
    entity_counts           : dict[str, int] = Field(default_factory=dict)
    # {character:N, item:N, location:N, skill:N, faction:N, concept:N}
    created_at              : str  = ""
    last_updated            : str  = ""


class ConsistencyIssue(BaseModel):
    """Mâu thuẫn được phát hiện bởi CrossReferenceEngine."""
    issue_type  : str  = ""    # character|timeline|worldbuilding|plot
    severity    : str  = ""    # error|warning|info
    description : str  = ""
    evidence    : list[str] = Field(default_factory=list)   # chapter references
    entity_ids  : list[str] = Field(default_factory=list)   # liên quan
    suggestion  : str  = ""


class ConsistencyReport(BaseModel):
    """Báo cáo từ CrossReferenceEngine."""
    total_issues    : int   = 0
    errors          : list[ConsistencyIssue] = Field(default_factory=list)
    warnings        : list[ConsistencyIssue] = Field(default_factory=list)
    infos           : list[ConsistencyIssue] = Field(default_factory=list)
    health_score    : float = 1.0   # 0.0 (nhiều lỗi) → 1.0 (hoàn hảo)
    generated_at    : str   = ""
    chapters_checked: int   = 0


# ═══════════════════════════════════════════════════════════════════
# TYPE ALIASES
# ═══════════════════════════════════════════════════════════════════

# Union type cho tất cả Database entities
DatabaseEntity = BibleCharacter | BibleItem | BibleLocation | BibleSkill | BibleFaction | BibleConcept

# Map entity_type string → Pydantic class
ENTITY_MODELS: dict[str, type] = {
    "character" : BibleCharacter,
    "item"      : BibleItem,
    "location"  : BibleLocation,
    "skill"     : BibleSkill,
    "faction"   : BibleFaction,
    "concept"   : BibleConcept,
}

# Thứ tự ưu tiên lưu file trong database/
DATABASE_FILES = ("characters", "items", "locations", "skills", "factions", "concepts")