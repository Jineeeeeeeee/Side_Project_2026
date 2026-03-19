"""
core/glossary.py — Glossary phân category.

Thay vì 1 file duy nhất, v3 dùng nhiều file:
  data/glossary/Glossary_Pathways.md      ← Hệ thống tu luyện, Sequence titles
  data/glossary/Glossary_Organizations.md ← Tổ chức, hội phái
  data/glossary/Glossary_Items.md         ← Vật phẩm, linh vật
  data/glossary/Glossary_Locations.md     ← Địa danh
  data/glossary/Glossary_General.md       ← Thuật ngữ chung, tên riêng
  data/glossary/Staging_Terms.md          ← Thuật ngữ mới, chờ phân loại

[v4] FIX: Aho-Corasick cache key bao gồm max_mtime của tất cả file glossary.
  Nếu người dùng sửa thủ công một file giữa chừng → cache tự invalidate → rebuild automaton.
  Cache size giới hạn _AHO_CACHE_MAX để tránh memory leak.
"""
import os, re, threading, logging, time
from .config import GLOSSARY_FILES, STAGING_TERMS_FILE, IMMEDIATE_MERGE
from .io_utils import load_text, save_text_atomic

try:
    import ahocorasick; _AHO = True
except ImportError:
    _AHO = False

_lock     = threading.Lock()
_aho_cache: dict = {}          # key → (Automaton, timestamp)
_aho_lock = threading.Lock()
_NEW_SECTION = "Mới — chờ phân loại"
_AHO_CACHE_MAX = 5             # giữ tối đa 5 phiên bản automaton


# ── Parse ────────────────────────────────────────────────────────
def _parse(text: str) -> dict[str, str]:
    """text → {term_lower: dòng gốc}"""
    terms = {}
    for line in text.splitlines():
        clean = re.sub(r"^[\*\-\+]\s*", "", line.strip())
        if ":" in clean:
            eng = clean.split(":", 1)[0].strip()
            if eng and not eng.startswith("#"):
                terms[eng.lower()] = line
    return terms

def _load_all() -> dict[str, dict[str, str]]:
    """Đọc tất cả files → {category: {term_lower: line}}"""
    result = {}
    for cat, path in GLOSSARY_FILES.items():
        result[cat] = _parse(load_text(str(path)))
    result["staging"] = _parse(load_text(str(STAGING_TERMS_FILE)))
    return result


# ── Filter ───────────────────────────────────────────────────────
def filter_glossary(chapter_text: str) -> dict[str, list[str]]:
    """
    Trả về {category: [dòng thuật ngữ liên quan]} chỉ gồm term
    XUẤT HIỆN trong chapter_text.
    """
    all_terms = _load_all()
    text_lower = chapter_text.lower()

    # Gộp flat để dùng 1 automaton duy nhất
    flat: dict[str, tuple[str, str]] = {}  # term → (cat, line)
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
            if len(term) <= 1:
                _add(matched, cat, line); continue
            start  = end_idx - len(term) + 1
            before = text_lower[start - 1] if start > 0 else " "
            after  = text_lower[end_idx + 1] if end_idx + 1 < len(text_lower) else " "
            if not before.isalnum() and not after.isalnum():
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

def _add(d: dict, cat: str, line: str):
    d.setdefault(cat, [])
    if line not in d[cat]:
        d[cat].append(line)


# ── [v4 FIX ①] Aho-Corasick cache với mtime invalidation ────────
def _get_glossary_mtime() -> float:
    """
    Trả về mtime lớn nhất trong tất cả file glossary.
    Nếu file không tồn tại → bỏ qua.
    """
    all_paths = list(GLOSSARY_FILES.values()) + [STAGING_TERMS_FILE]
    mtimes = []
    for p in all_paths:
        try:
            mtimes.append(os.path.getmtime(str(p)))
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0


def _get_automaton(flat: dict):
    """
    Trả về Aho-Corasick automaton đã build.

    Cache key = (hash của term keys, rounded mtime) để đảm bảo:
      - Term mới được thêm vào → keys thay đổi → cache miss
      - File glossary bị sửa thủ công mid-run → mtime thay đổi → cache miss
      - Không có gì thay đổi → cache hit, không rebuild

    Cache bị giới hạn _AHO_CACHE_MAX entry để tránh memory leak.
    """
    mtime_rounded = round(_get_glossary_mtime())  # round về giây để tránh float noise
    cache_key = hash((frozenset(flat.keys()), mtime_rounded))

    with _aho_lock:
        if cache_key in _aho_cache:
            return _aho_cache[cache_key]

        # Build automaton mới
        A = ahocorasick.Automaton()
        for t, payload in flat.items():
            A.add_word(t, (t, payload))
        A.make_automaton()

        # Evict entry cũ nhất nếu cache đầy
        if len(_aho_cache) >= _AHO_CACHE_MAX:
            oldest_key = next(iter(_aho_cache))
            del _aho_cache[oldest_key]
            logging.debug(f"[Glossary] Aho-Corasick cache evict (size={_AHO_CACHE_MAX})")

        _aho_cache[cache_key] = A
        logging.debug(f"[Glossary] Aho-Corasick rebuilt (terms={len(flat)}, mtime={mtime_rounded})")
        return A


# ── Write ────────────────────────────────────────────────────────
def add_new_terms(new_terms: list, source_chapter: str) -> int:
    """
    Ghi thuật ngữ mới (thread-safe).
    IMMEDIATE_MERGE=true  → ghi thẳng vào file category tương ứng
    IMMEDIATE_MERGE=false → ghi vào Staging_Terms.md
    Trả về số term thực sự được thêm.
    """
    if not new_terms:
        return 0
    with _lock:
        existing: set[str] = set()
        for cat, terms in _load_all().items():
            existing.update(terms.keys())

        by_category: dict[str, list[str]] = {}
        for term in new_terms:
            eng = term.english.strip()
            vie = term.vietnamese.strip()
            cat = getattr(term, "category", "general")
            if cat not in GLOSSARY_FILES:
                cat = "general"
            if eng and eng.lower() not in existing:
                by_category.setdefault(cat, []).append(f"- {eng}: {vie}")
                existing.add(eng.lower())

        if not by_category:
            return 0

        total = 0
        if IMMEDIATE_MERGE:
            for cat, lines in by_category.items():
                _append_to_file(str(GLOSSARY_FILES[cat]), lines, source_chapter)
                total += len(lines)
        else:
            all_lines = [l for lines in by_category.values() for l in lines]
            _append_staging(all_lines, source_chapter)
            total = len(all_lines)

    return total

def _append_to_file(path: str, lines: list[str], source: str):
    content = load_text(path)
    block = "\n".join(lines)
    if f"## {_NEW_SECTION}" in content:
        content = content.rstrip("\n") + f"\n{block}\n"
    else:
        content = content.rstrip("\n") + f"\n\n## {_NEW_SECTION}\n{block}\n"
    save_text_atomic(path, content)

def _append_staging(lines: list[str], source: str):
    existing = load_text(str(STAGING_TERMS_FILE))
    with open(STAGING_TERMS_FILE, "a", encoding="utf-8") as f:
        if not existing.strip():
            f.write("# Staging Terms\n\n")
        f.write(f"\n## Từ chương: {source}\n")
        f.writelines(l + "\n" for l in lines)

def has_pending_terms() -> bool:
    return bool(load_text(str(STAGING_TERMS_FILE)).strip())

def count_pending_terms() -> int:
    return load_text(str(STAGING_TERMS_FILE)).count("\n- ")

def glossary_stats() -> dict[str, int]:
    return {cat: len(terms) for cat, terms in _load_all().items()}