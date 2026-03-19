"""
src/littrans/managers/glossary.py — Glossary phân category + Aho-Corasick filter.

5 file category + 1 staging:
  Glossary_Pathways.md      Glossary_Organizations.md   Glossary_Items.md
  Glossary_Locations.md     Glossary_General.md          Staging_Terms.md

[v4 FIX] Aho-Corasick cache key bao gồm max_mtime → tự invalidate khi file thay đổi.
"""
from __future__ import annotations

import os
import re
import threading
import logging

from littrans.config.settings import settings
from littrans.utils.io_utils import load_text, atomic_write

try:
    import ahocorasick
    _AHO = True
except ImportError:
    _AHO = False

_lock         = threading.Lock()
_aho_cache: dict = {}
_aho_lock     = threading.Lock()
_AHO_CACHE_MAX = 5
_NEW_SECTION  = "Mới — chờ phân loại"


# ── Parse ────────────────────────────────────────────────────────

def _parse(text: str) -> dict[str, str]:
    """text → {term_lower: original_line}"""
    terms: dict[str, str] = {}
    for line in text.splitlines():
        clean = re.sub(r"^[\*\-\+]\s*", "", line.strip())
        if ":" in clean and not clean.startswith("#"):
            eng = clean.split(":", 1)[0].strip()
            if eng:
                terms[eng.lower()] = line
    return terms


def _load_all() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for cat, path in settings.glossary_files.items():
        result[cat] = _parse(load_text(path))
    result["staging"] = _parse(load_text(settings.staging_terms_file))
    return result


# ── Filter ───────────────────────────────────────────────────────

def filter_glossary(chapter_text: str) -> dict[str, list[str]]:
    """
    Trả về {category: [lines]} chỉ gồm term XUẤT HIỆN trong chapter_text.
    """
    all_terms  = _load_all()
    text_lower = chapter_text.lower()

    flat: dict[str, tuple[str, str]] = {}
    for cat, terms in all_terms.items():
        for t, line in terms.items():
            if t not in flat:
                flat[t] = (cat, line)

    if not flat:
        return {}

    matched: dict[str, list[str]] = {}

    if _AHO:
        auto = _get_automaton(flat)
        for end_idx, (term, (cat, line)) in auto.iter(text_lower):
            start  = end_idx - len(term) + 1
            before = text_lower[start - 1] if start > 0 else " "
            after  = text_lower[end_idx + 1] if end_idx + 1 < len(text_lower) else " "
            if len(term) <= 1 or (not before.isalnum() and not after.isalnum()):
                _add(matched, cat, line)
    else:
        for term, (cat, line) in flat.items():
            try:
                hit = bool(re.search(rf"\b{re.escape(term)}\b", text_lower))
            except re.error:
                hit = term in text_lower
            if hit:
                _add(matched, cat, line)

    return matched


def _add(d: dict, cat: str, line: str) -> None:
    d.setdefault(cat, [])
    if line not in d[cat]:
        d[cat].append(line)


# ── Aho-Corasick cache với mtime invalidation ─────────────────────

def _get_mtime() -> float:
    all_paths = list(settings.glossary_files.values()) + [settings.staging_terms_file]
    mtimes    = []
    for p in all_paths:
        try:
            mtimes.append(os.path.getmtime(str(p)))
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0


def _get_automaton(flat: dict):
    mtime_rounded = round(_get_mtime())
    cache_key     = hash((frozenset(flat.keys()), mtime_rounded))

    with _aho_lock:
        if cache_key in _aho_cache:
            return _aho_cache[cache_key]

        A = ahocorasick.Automaton()
        for t, payload in flat.items():
            A.add_word(t, (t, payload))
        A.make_automaton()

        if len(_aho_cache) >= _AHO_CACHE_MAX:
            oldest_key = next(iter(_aho_cache))
            del _aho_cache[oldest_key]

        _aho_cache[cache_key] = A
        return A


# ── Write ────────────────────────────────────────────────────────

def add_new_terms(new_terms: list, source_chapter: str) -> int:
    """
    Ghi thuật ngữ mới (thread-safe).
    IMMEDIATE_MERGE=true  → ghi thẳng vào category file
    IMMEDIATE_MERGE=false → ghi vào Staging_Terms.md
    """
    if not new_terms:
        return 0

    with _lock:
        existing: set[str] = set()
        for terms in _load_all().values():
            existing.update(terms.keys())

        by_cat: dict[str, list[str]] = {}
        for term in new_terms:
            eng = term.english.strip()
            vie = term.vietnamese.strip()
            cat = getattr(term, "category", "general")
            if cat not in settings.glossary_files:
                cat = "general"
            if eng and eng.lower() not in existing:
                by_cat.setdefault(cat, []).append(f"- {eng}: {vie}")
                existing.add(eng.lower())

        if not by_cat:
            return 0

        total = 0
        if settings.immediate_merge:
            for cat, lines in by_cat.items():
                _append_to_file(settings.glossary_files[cat], lines)
                total += len(lines)
        else:
            all_lines = [l for lines in by_cat.values() for l in lines]
            _append_staging(all_lines, source_chapter)
            total = len(all_lines)

    return total


def _append_to_file(path, lines: list[str]) -> None:
    content = load_text(path)
    block   = "\n".join(lines)
    if f"## {_NEW_SECTION}" in content:
        content = content.rstrip("\n") + f"\n{block}\n"
    else:
        content = content.rstrip("\n") + f"\n\n## {_NEW_SECTION}\n{block}\n"
    atomic_write(path, content)


def _append_staging(lines: list[str], source: str) -> None:
    existing = load_text(settings.staging_terms_file)
    with open(settings.staging_terms_file, "a", encoding="utf-8") as f:
        if not existing.strip():
            f.write("# Staging Terms\n\n")
        f.write(f"\n## Từ chương: {source}\n")
        f.writelines(l + "\n" for l in lines)


# ── Stats ────────────────────────────────────────────────────────

def has_pending_terms() -> bool:
    return bool(load_text(settings.staging_terms_file).strip())


def count_pending_terms() -> int:
    return load_text(settings.staging_terms_file).count("\n- ")


def glossary_stats() -> dict[str, int]:
    return {cat: len(terms) for cat, terms in _load_all().items()}
