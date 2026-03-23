"""
src/littrans/llm/token_budget.py — Ước tính và quản lý token budget.

Gemini dùng SentencePiece → heuristic nhẹ thay vì tokenize thật:
  - Tiếng Việt : ~3 ký tự / token  (có dấu → token dense)
  - Tiếng Anh  : ~4 ký tự / token
  - JSON/code  : ~3.5 ký tự / token

PRIORITY ORDER (cắt từ ít quan trọng nhất):
  1. NameLock           ← KHÔNG bao giờ cắt
  2. Instructions       ← KHÔNG bao giờ cắt
  3. Context Notes      ← KHÔNG cắt (tức thì)
  4. Arc Memory         ← Giảm 3 → 1 entry khi cần
  5. Active Characters  ← Bỏ chars phụ (giữ top 5 relevant)
  6. Staging Glossary   ← Bỏ khi rất tight
  7. Arc Memory hoàn toàn ← Last resort

[v4.2] Character scoring dùng regex word-boundary thay vì str.count()
       để tránh false match cho tên ngắn (vd: "Li" match vào "likely").

[v4.3 FIX] Đồng bộ regex pattern với name_lock.py:
       Dùng lookaround Unicode (?<![^\W_])...(?![^\W_]) thay vì
       (?<![a-zA-Z0-9_]) vốn chỉ xử lý ASCII.

       Vấn đề cũ: (?<![a-zA-Z0-9_]) không nhận ra ký tự tiếng Việt
       có dấu (ấ, ổ, ư...) là word character → False Positive khi tên
       xuất hiện dính liền ký tự có dấu.

       Pattern mới (?<![^\W_]) tương đương: "không đứng trước ký tự
       nào mà KHÔNG phải non-word hoặc dấu gạch dưới" — hoạt động
       đúng với mọi Unicode script.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

from littrans.core.patterns import word_boundary_count

SOFT_LIMIT_RATIO = 0.80

_CHARS_PER_TOKEN = {"vn": 3.0, "en": 4.0, "json": 3.5}


def estimate_tokens(text: str, lang: str = "vn") -> int:
    if not text:
        return 0
    cpt = _CHARS_PER_TOKEN.get(lang, 3.0)
    return max(1, int(len(text) / cpt))


def _score_character_relevance(name: str, profile: str, chapter_text_lower: str) -> int:
    """
    Tính điểm liên quan của nhân vật với chương hiện tại.

    [FIX v4.3] Dùng lookaround Unicode thay vì ASCII character class:
      TRƯỚC: (?<![a-zA-Z0-9_])...(?![a-zA-Z0-9_])
             → Sai với tiếng Việt: "ỹAn" → "ỹ" không trong [a-zA-Z0-9_]
               nên match "An" dù dính với ký tự có dấu.

      SAU: (?<![^\W_])...(?![^\W_])
           → Nhất quán với name_lock.py và characters.py.
           → \\W = non-word (bao gồm space, dấu câu, ký tự đặc biệt).
           → [^\W_] = word character trừ dấu gạch dưới.
           → Lookaround này đúng với mọi Unicode, kể cả tiếng Việt.

    Điểm = số lần xuất hiện có word-boundary + bonus 100 nếu không phải Archive.
    """
    count = word_boundary_count(name.lower(), chapter_text_lower)

    archive_penalty = 0 if "[ARCHIVE]" not in profile else -50
    return count + 100 + archive_penalty  # +100 để chars non-archive luôn > 0


@dataclass
class BudgetContext:
    # Không bao giờ cắt
    instructions      : str = ""
    char_instructions : str = ""
    name_lock         : str = ""
    context_notes     : str = ""

    # Có thể giảm
    arc_memory_text  : str        = field(default_factory=str)
    arc_entries_full : list[str]  = field(default_factory=list)

    # Có thể cắt bớt
    char_profiles  : dict[str, str]         = field(default_factory=dict)
    glossary_ctx   : dict[str, list[str]]   = field(default_factory=dict)

    chapter_text   : str = ""
    budget_limit   : int = 150_000

    def token_breakdown(self) -> dict[str, int]:
        return {
            "instructions"    : estimate_tokens(self.instructions),
            "char_instructions": estimate_tokens(self.char_instructions),
            "name_lock"       : estimate_tokens(self.name_lock),
            "context_notes"   : estimate_tokens(self.context_notes),
            "arc_memory"      : estimate_tokens(self.arc_memory_text),
            "characters"      : estimate_tokens("\n".join(self.char_profiles.values())),
            "glossary"        : estimate_tokens(
                "\n".join(l for lines in self.glossary_ctx.values() for l in lines)
            ),
            "chapter"         : estimate_tokens(self.chapter_text, "en"),
        }

    def total_tokens(self) -> int:
        return sum(self.token_breakdown().values())

    def soft_limit(self) -> int:
        return int(self.budget_limit * SOFT_LIMIT_RATIO)


def apply_budget(ctx: BudgetContext) -> BudgetContext:
    """Cắt bớt context nếu vượt soft limit. In-place, cũng trả về ctx."""
    soft  = ctx.soft_limit()
    total = ctx.total_tokens()
    if total <= soft:
        return ctx

    logging.warning(f"[TokenBudget] Vượt soft limit: {total}/{soft} token")

    # ── Bước 1: Giảm Arc Memory → 1 entry ────────────────────────
    if ctx.arc_entries_full and len(ctx.arc_entries_full) > 1:
        saved = estimate_tokens(ctx.arc_memory_text) - estimate_tokens(ctx.arc_entries_full[-1])
        ctx.arc_memory_text = ctx.arc_entries_full[-1]
        total -= saved
        print(f"  ✂️  [Budget] Arc Memory: {len(ctx.arc_entries_full)} → 1 entry (~{saved:,} tk)")
        if total <= soft:
            return _log_final(ctx, total, soft)

    # ── Bước 2: Bỏ staging glossary ──────────────────────────────
    if "staging" in ctx.glossary_ctx:
        saved = estimate_tokens("\n".join(ctx.glossary_ctx.pop("staging")))
        total -= saved
        print(f"  ✂️  [Budget] Bỏ staging glossary (~{saved:,} tk)")
        if total <= soft:
            return _log_final(ctx, total, soft)

    # ── Bước 3: Cắt character profiles phụ (giữ top 5) ───────────
    if len(ctx.char_profiles) > 5:
        ch_lower = ctx.chapter_text.lower()
        scored   = sorted(
            ctx.char_profiles.items(),
            key=lambda kv: _score_character_relevance(kv[0], kv[1], ch_lower),
            reverse=True,
        )
        keep         = dict(scored[:5])
        dropped_text = "\n".join(p for n, p in ctx.char_profiles.items() if n not in keep)
        saved        = estimate_tokens(dropped_text)
        ctx.char_profiles = keep
        total -= saved
        dropped_names = [n for n, _ in scored[5:]]
        print(f"  ✂️  [Budget] Bỏ {len(dropped_names)} char profiles phụ (~{saved:,} tk): "
              f"{', '.join(dropped_names[:3])}{'...' if len(dropped_names) > 3 else ''}")
        if total <= soft:
            return _log_final(ctx, total, soft)

    # ── Last resort: bỏ toàn bộ Arc Memory ──────────────────────
    if ctx.arc_memory_text:
        saved = estimate_tokens(ctx.arc_memory_text)
        ctx.arc_memory_text = ""
        total -= saved
        print(f"  ✂️  [Budget] Bỏ toàn bộ Arc Memory (~{saved:,} tk) — budget rất tight!")

    return _log_final(ctx, total, soft)


def _log_final(ctx: BudgetContext, total: int, soft: int) -> BudgetContext:
    pct    = int(total / soft * 100) if soft else 0
    status = "✅" if total <= soft else "⚠️"
    print(f"  {status} [Budget] Sau cắt: ~{total:,}/{soft:,} token ({pct}%)")
    return ctx