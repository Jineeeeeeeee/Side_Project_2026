"""
core/token_budget.py — Ước tính và quản lý token budget trước khi gọi API.

[v4] MỚI:
  Gemini dùng SentencePiece (không tương thích tiktoken/BPE), nên module này
  dùng heuristic nhẹ thay vì tokenize thật:
    - Tiếng Việt: ~3 ký tự / token  (nhiều dấu → token dense)
    - Tiếng Anh / ASCII: ~4 ký tự / token
    - JSON / code: ~3.5 ký tự / token

  Kết quả là ESTIMATE, không phải chính xác — mục tiêu là tránh vượt
  context window, không phải đếm chính xác từng token.

  PRIORITY ORDER (cắt từ cuối lên đầu nếu vượt budget):
    1. NameLock           ← KHÔNG BAO GIỜ cắt
    2. Instructions       ← KHÔNG BAO GIỜ cắt
    3. Context Notes      ← KHÔNG cắt (quan trọng tức thì)
    4. Arc Memory         ← Cắt từ 3 → 1 entry khi cần
    5. Active Characters  ← Cắt chars phụ (không có trong chapter)
    6. Archive Characters ← Cắt toàn bộ nếu không còn chỗ
    7. Staging Glossary   ← Cắt khi budget rất tight

  Gemini 2.5 Flash context window: 1M token (rất lớn)
  Soft limit mặc định: 80% của BUDGET_LIMIT để an toàn
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

# ── Heuristic constants ───────────────────────────────────────────
_CHARS_PER_TOKEN_VN   = 3.0   # tiếng Việt (có dấu, dày token)
_CHARS_PER_TOKEN_EN   = 4.0   # tiếng Anh / ASCII
_CHARS_PER_TOKEN_JSON = 3.5   # JSON/structured

# Default budget (tokens). Điều chỉnh qua .env BUDGET_LIMIT
# Gemini 2.5 Flash: 1_000_000 token context
# Dùng 150_000 làm mặc định — vừa đủ cho chapter + context đầy đủ,
# vừa tránh cost vô lý cho chapter ngắn.
DEFAULT_BUDGET       = 150_000
SOFT_LIMIT_RATIO     = 0.80    # cắt khi > 80% budget


# ── Token estimation ─────────────────────────────────────────────
def estimate_tokens(text: str, lang: str = "vn") -> int:
    """
    Ước tính số token của một đoạn text.
    lang: "vn" | "en" | "json"
    """
    if not text:
        return 0
    chars_per_token = {
        "vn"  : _CHARS_PER_TOKEN_VN,
        "en"  : _CHARS_PER_TOKEN_EN,
        "json": _CHARS_PER_TOKEN_JSON,
    }.get(lang, _CHARS_PER_TOKEN_VN)
    return max(1, int(len(text) / chars_per_token))


# ── Budget context ────────────────────────────────────────────────
@dataclass
class BudgetContext:
    """
    Chứa các thành phần prompt đã được tính token.
    Dùng để quyết định cắt gì trước khi build prompt.
    """
    # Không bao giờ cắt
    instructions   : str = ""
    char_instructions: str = ""
    name_lock      : str = ""
    context_notes  : str = ""
    json_requirements: str = ""

    # Có thể giảm
    arc_memory_text : str = ""        # có thể giảm xuống 1 entry
    arc_entries_full: list[str] = field(default_factory=list)   # list entry đầy đủ

    # Có thể cắt bớt
    char_profiles   : dict[str, str] = field(default_factory=dict)
    glossary_ctx    : dict[str, list[str]] = field(default_factory=dict)

    # Meta
    chapter_text    : str = ""
    budget_limit    : int = DEFAULT_BUDGET

    def token_breakdown(self) -> dict[str, int]:
        """Trả về token estimate cho từng thành phần."""
        return {
            "instructions"    : estimate_tokens(self.instructions, "vn"),
            "char_instructions": estimate_tokens(self.char_instructions, "vn"),
            "name_lock"       : estimate_tokens(self.name_lock, "vn"),
            "context_notes"   : estimate_tokens(self.context_notes, "vn"),
            "json_req"        : estimate_tokens(self.json_requirements, "vn"),
            "arc_memory"      : estimate_tokens(self.arc_memory_text, "vn"),
            "characters"      : estimate_tokens("\n".join(self.char_profiles.values()), "vn"),
            "glossary"        : estimate_tokens(
                "\n".join(l for lines in self.glossary_ctx.values() for l in lines), "vn"
            ),
            "chapter"         : estimate_tokens(self.chapter_text, "en"),
        }

    def total_tokens(self) -> int:
        return sum(self.token_breakdown().values())

    def soft_limit(self) -> int:
        return int(self.budget_limit * SOFT_LIMIT_RATIO)


def apply_budget(ctx: BudgetContext) -> BudgetContext:
    """
    Kiểm tra budget và cắt bớt context nếu cần.
    Trả về BudgetContext đã được điều chỉnh (in-place).
    Log ra console khi có cắt bớt.
    """
    soft = ctx.soft_limit()
    total = ctx.total_tokens()

    if total <= soft:
        return ctx  # đủ budget, không cần làm gì

    breakdown = ctx.token_breakdown()
    logging.warning(f"[TokenBudget] Vượt soft limit: {total}/{soft} token")

    # ── Bước 1: Cắt Arc Memory từ 3 → 1 entry ────────────────────
    if ctx.arc_entries_full and len(ctx.arc_entries_full) > 1:
        old_arc_tokens = breakdown["arc_memory"]
        ctx.arc_memory_text = ctx.arc_entries_full[-1]   # chỉ giữ entry mới nhất
        new_arc_tokens = estimate_tokens(ctx.arc_memory_text, "vn")
        saved = old_arc_tokens - new_arc_tokens
        total -= saved
        print(f"  ✂️  [TokenBudget] Cắt Arc Memory: {len(ctx.arc_entries_full)} → 1 entry "
              f"(tiết kiệm ~{saved:,} token)")
        if total <= soft:
            _log_final(total, soft)
            return ctx

    # ── Bước 2: Cắt bỏ staging glossary (ít quan trọng nhất) ──────
    if "staging" in ctx.glossary_ctx and ctx.glossary_ctx["staging"]:
        staging_tokens = estimate_tokens(
            "\n".join(ctx.glossary_ctx["staging"]), "vn"
        )
        del ctx.glossary_ctx["staging"]
        total -= staging_tokens
        print(f"  ✂️  [TokenBudget] Bỏ staging glossary (~{staging_tokens:,} token)")
        if total <= soft:
            _log_final(total, soft)
            return ctx

    # ── Bước 3: Cắt bớt character profiles phụ ───────────────────
    # Giữ lại nhân vật có tên xuất hiện nhiều nhất trong chapter
    if len(ctx.char_profiles) > 3:
        # Tính relevance score: số lần tên xuất hiện trong chapter
        chapter_lower = ctx.chapter_text.lower()
        scored = []
        for name, profile in ctx.char_profiles.items():
            score = chapter_lower.count(name.lower())
            # Nhân vật MC / ARCHIVE: ưu tiên giữ
            is_important = "MC" in profile or "[ARCHIVE]" not in profile
            scored.append((name, profile, score + (100 if is_important else 0)))
        scored.sort(key=lambda x: x[2], reverse=True)

        # Giữ top 5, bỏ phần còn lại
        keep = dict((name, profile) for name, profile, _ in scored[:5])
        dropped = len(ctx.char_profiles) - len(keep)
        if dropped > 0:
            dropped_tokens = estimate_tokens(
                "\n".join(p for n, p in ctx.char_profiles.items() if n not in keep), "vn"
            )
            ctx.char_profiles = keep
            total -= dropped_tokens
            print(f"  ✂️  [TokenBudget] Bỏ {dropped} char profiles phụ (~{dropped_tokens:,} token)")
            if total <= soft:
                _log_final(total, soft)
                return ctx

    # ── Bước 4 (last resort): Cắt bớt Arc Memory hoàn toàn ───────
    if ctx.arc_memory_text:
        arc_tokens = estimate_tokens(ctx.arc_memory_text, "vn")
        ctx.arc_memory_text = ""
        total -= arc_tokens
        print(f"  ✂️  [TokenBudget] Bỏ toàn bộ Arc Memory (~{arc_tokens:,} token). "
              f"Budget rất tight!")

    _log_final(total, soft)
    return ctx


def _log_final(total: int, soft: int) -> None:
    pct = int(total / soft * 100) if soft else 0
    status = "✅" if total <= soft else "⚠️"
    print(f"  {status} [TokenBudget] Sau cắt: ~{total:,}/{soft:,} token ({pct}%)")


def log_budget_stats(ctx: BudgetContext) -> None:
    """In breakdown token ra console khi debug."""
    bd = ctx.token_breakdown()
    total = sum(bd.values())
    soft  = ctx.soft_limit()
    print(f"\n  📊 Token Budget: ~{total:,}/{ctx.budget_limit:,} (soft limit {soft:,})")
    for k, v in sorted(bd.items(), key=lambda x: -x[1]):
        bar = "█" * min(20, v // 500)
        print(f"     {k:<18} {v:>6,}  {bar}")
    print()