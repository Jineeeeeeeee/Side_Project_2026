"""
clean_glossary.py — Phân loại & merge thuật ngữ vào các Glossary file (v3)

Cấu trúc v3 dùng NHIỀU FILE theo category thay vì 1 file duy nhất:
  data/glossary/Glossary_Pathways.md      ← Hệ thống tu luyện, Sequence titles
  data/glossary/Glossary_Organizations.md ← Tổ chức, hội phái
  data/glossary/Glossary_Items.md         ← Vật phẩm, linh vật
  data/glossary/Glossary_Locations.md     ← Địa danh
  data/glossary/Glossary_General.md       ← Thuật ngữ chung, tên riêng
  data/glossary/Staging_Terms.md          ← Thuật ngữ mới, chờ xử lý

Workflow:
  1. Đọc Staging_Terms.md + section "## Mới — chờ phân loại" từ mọi file
  2. Dùng Gemini phân loại vào 5 categories chuẩn
  3. Append vào đúng file Glossary_*.md, bỏ qua duplicate
  4. Backup file cũ → .bak
  5. Xóa Staging_Terms.md + xóa section "Mới" đã phân loại

Chạy: python clean_glossary.py
"""

import os
import sys
import re
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv, find_dotenv
from pydantic import BaseModel, Field, ValidationError

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(find_dotenv())

logging.basicConfig(
    filename="logs/translation_errors.log",
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

if not GEMINI_API_KEY:
    print("❌ Lỗi: Không tìm thấy GEMINI_API_KEY trong file .env")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# Ánh xạ category key → file path (đồng bộ với core/config.py)
GLOSSARY_DIR   = Path("data/glossary")
STAGING_FILE   = GLOSSARY_DIR / "Staging_Terms.md"
GLOSSARY_FILES = {
    "pathways"      : GLOSSARY_DIR / "Glossary_Pathways.md",
    "organizations" : GLOSSARY_DIR / "Glossary_Organizations.md",
    "items"         : GLOSSARY_DIR / "Glossary_Items.md",
    "locations"     : GLOSSARY_DIR / "Glossary_Locations.md",
    "general"       : GLOSSARY_DIR / "Glossary_General.md",
}

# Tên hiển thị trong prompt
CATEGORY_LABELS = {
    "pathways"      : "Hệ thống tu luyện / Sequence / Pathway titles",
    "organizations" : "Tổ chức, hội phái, bang nhóm, thế lực",
    "items"         : "Vật phẩm, linh vật, vũ khí, đan dược, artifact",
    "locations"     : "Địa danh, thành phố, vùng đất, cõi giới, dungeon",
    "general"       : "Thuật ngữ chung, tên nhân vật, kỹ năng, khái niệm khác",
}

CATEGORIES     = list(GLOSSARY_FILES.keys())
_CAT_LOWER     = [c.lower() for c in CATEGORIES]
_NEW_SECTION   = "Mới — chờ phân loại"


# ── Pydantic Models ───────────────────────────────────────────────────────────
class CategorizedTerm(BaseModel):
    english   : str = Field(description="Thuật ngữ tiếng Anh gốc")
    vietnamese: str = Field(description="Bản dịch tiếng Việt")
    category  : str = Field(description=f"Phải là một trong: {CATEGORIES}")

class CategorizationResult(BaseModel):
    terms: list[CategorizedTerm]


# ── I/O ───────────────────────────────────────────────────────────────────────
def _load(path) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")

def _save(path, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")

def _ensure_dirs():
    GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(exist_ok=True)


# ── Parse helpers ─────────────────────────────────────────────────────────────
def parse_raw_terms(text: str) -> list[dict]:
    """Đọc text (staging hoặc "Mới" section) → list {english, vietnamese}."""
    terms = []
    seen  = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        clean = re.sub(r"^[\*\-\+]\s*", "", stripped)
        if ":" in clean:
            eng, _, vie = clean.partition(":")
            eng = eng.strip(); vie = vie.strip()
            if eng and eng.lower() not in seen:
                terms.append({"english": eng, "vietnamese": vie})
                seen.add(eng.lower())
    return terms

def existing_terms_set() -> set[str]:
    """Tập hợp tất cả terms đã có (từ tất cả files)."""
    found = set()
    for path in GLOSSARY_FILES.values():
        for line in _load(path).splitlines():
            clean = re.sub(r"^[\*\-\+]\s*", "", line.strip())
            if ":" in clean:
                eng = clean.split(":", 1)[0].strip()
                if eng:
                    found.add(eng.lower())
    return found

def _extract_new_section(text: str) -> list[dict]:
    """Đọc section '## Mới — chờ phân loại' từ một file glossary."""
    HDR = f"## {_NEW_SECTION}"
    if HDR not in text:
        return []
    start = text.index(HDR) + len(HDR)
    next_sec = text.find("\n## ", start)
    block = text[start:next_sec] if next_sec != -1 else text[start:]
    return parse_raw_terms(block)

def _remove_new_section(text: str) -> str:
    """Xóa section '## Mới — chờ phân loại' khỏi nội dung file."""
    HDR = f"## {_NEW_SECTION}"
    if HDR not in text:
        return text
    start = text.index(HDR)
    next_sec = text.find("\n## ", start + len(HDR))
    if next_sec != -1:
        text = text[:start].rstrip() + "\n" + text[next_sec:]
    else:
        text = text[:start].rstrip() + "\n"
    return text

def _resolve_category(cat: str) -> str:
    """Ánh xạ chuỗi category từ AI về key chuẩn (pathways/organizations/items/locations/general)."""
    cat_l = cat.strip().lower()
    # Exact match
    for c in CATEGORIES:
        if c == cat_l:
            return c
    # Canonical label contains AI output
    for key, label in CATEGORY_LABELS.items():
        if cat_l in label.lower():
            return key
    # Partial: AI output contained in key or label
    for key, label in CATEGORY_LABELS.items():
        if len(cat_l) >= 4 and (cat_l in key or cat_l in label.lower()):
            return key
    return "general"


# ── AI Categorization ─────────────────────────────────────────────────────────
def categorize_terms(raw_terms: list[dict]) -> list[CategorizedTerm]:
    terms_text = "\n".join(f"- {t['english']}: {t['vietnamese']}" for t in raw_terms)
    cat_list   = "\n".join(f"  - {k}: {v}" for k, v in CATEGORY_LABELS.items())

    system_prompt = f"""Bạn là chuyên gia biên tập từ điển cho truyện LitRPG / Tu Tiên.
Nhiệm vụ: Phân loại từng thuật ngữ vào đúng nhóm trong danh sách sau:

{cat_list}

Quy tắc:
- pathways: hệ thống tu luyện, Sequence pathway, title tu tiên, cảnh giới
- organizations: tổ chức, hội, môn phái, thế lực chính trị
- items: vật phẩm cụ thể, vũ khí, giáp, đan dược, artifact có tên
- locations: địa danh, tên nơi chốn
- general: tên nhân vật, kỹ năng, thuật ngữ hệ thống, khái niệm chung

QUAN TRỌNG: Trả về đúng key (pathways/organizations/items/locations/general), không thêm gì khác.
Trả về JSON theo schema, KHÔNG giải thích thêm.
"""

    print(f"  🤖 Phân loại {len(raw_terms)} thuật ngữ với Gemini...")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"Phân loại các thuật ngữ sau:\n\n{terms_text}",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
            response_schema=CategorizationResult,
            response_mime_type="application/json",
        ),
    )

    if response.parsed and isinstance(response.parsed, CategorizationResult):
        return response.parsed.terms

    raw_text   = response.text or ""
    clean_text = re.sub(r"^```json\s*|```\s*$", "", raw_text.strip(), flags=re.MULTILINE)
    data       = json.loads(clean_text)
    return CategorizationResult.model_validate(data).terms


# ── Merge vào file đúng ───────────────────────────────────────────────────────
def merge_into_glossary_files(categorized: list[CategorizedTerm]) -> dict[str, int]:
    """
    Append mỗi term đã phân loại vào đúng Glossary_*.md file.
    Trả về {category: số term đã thêm}.
    """
    existing = existing_terms_set()
    by_cat: dict[str, list[CategorizedTerm]] = {c: [] for c in CATEGORIES}
    skipped = 0

    for term in categorized:
        cat = _resolve_category(term.category)
        if term.english.lower() not in existing:
            by_cat[cat].append(term)
            existing.add(term.english.lower())
        else:
            skipped += 1

    if skipped:
        print(f"  ⏭️  Bỏ qua {skipped} từ đã có trong glossary")

    added = {}
    for cat, terms in by_cat.items():
        if not terms:
            continue
        path    = GLOSSARY_FILES[cat]
        content = _load(path)

        if content and not content.endswith("\n"):
            content += "\n"

        new_lines = "\n".join(f"- {t.english}: {t.vietnamese}" for t in terms)

        if not content.strip():
            # File mới: thêm header
            label = CATEGORY_LABELS[cat]
            content = f"# Glossary — {label}\n\n{new_lines}\n"
        elif f"## {_NEW_SECTION}" in content:
            content = content.rstrip("\n") + f"\n{new_lines}\n"
        else:
            content = content.rstrip("\n") + f"\n\n## {_NEW_SECTION}\n{new_lines}\n"

        # Backup trước khi ghi
        if path.exists():
            shutil.copy2(path, str(path) + ".bak")

        _save(path, content)
        added[cat] = len(terms)
        print(f"  📁 {path.name}: +{len(terms)} thuật ngữ")

    return added


# ── Main ──────────────────────────────────────────────────────────────────────
def clean_glossary() -> None:
    _ensure_dirs()

    # Thu thập tất cả terms cần phân loại
    staging_text  = _load(STAGING_FILE)
    staging_terms = parse_raw_terms(staging_text) if staging_text.strip() else []

    new_section_terms = []
    for path in GLOSSARY_FILES.values():
        text = _load(path)
        new_section_terms.extend(_extract_new_section(text))

    # Deduplicate
    seen: set = set()
    all_terms: list[dict] = []
    for t in staging_terms + new_section_terms:
        key = t["english"].lower()
        if key not in seen:
            seen.add(key)
            all_terms.append(t)

    if not all_terms:
        print("✅ Không có thuật ngữ nào cần phân loại.")
        return

    print(f"\n📋 Tìm thấy {len(all_terms)} thuật ngữ cần phân loại")
    print(f"   ({len(staging_terms)} từ Staging, {len(new_section_terms)} từ section 'Mới')")
    print(f"   Model: {GEMINI_MODEL}\n")

    # Phân loại bằng AI
    try:
        categorized = categorize_terms(all_terms)
    except Exception as e:
        print(f"❌ Lỗi phân loại: {e}")
        logging.error(f"clean_glossary: {e}")
        return

    # Preview
    print("\n📊 Kết quả phân loại:")
    by_cat_preview: dict[str, list] = {}
    for t in categorized:
        resolved = _resolve_category(t.category)
        by_cat_preview.setdefault(resolved, []).append(t.english)
    for cat, terms in sorted(by_cat_preview.items()):
        label = CATEGORY_LABELS.get(cat, cat)
        preview = ", ".join(terms[:5]) + ("..." if len(terms) > 5 else "")
        print(f"   {cat} ({label[:30]}): {len(terms)} từ → {preview}")

    # Merge
    print()
    added_total = merge_into_glossary_files(categorized)

    # Dọn dẹp section "Mới" trong từng file (sau khi đã phân loại)
    if new_section_terms:
        for path in GLOSSARY_FILES.values():
            text = _load(str(path))
            if f"## {_NEW_SECTION}" in text:
                cleaned = _remove_new_section(text)
                _save(path, cleaned)
        print(f"  🗑️  Đã xóa section 'Mới — chờ phân loại' (đã phân loại xong)")

    # Archive Staging_Terms.md
    if staging_text and staging_text.strip():
        archive = GLOSSARY_DIR / f"Staging_Terms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak.md"
        shutil.move(str(STAGING_FILE), str(archive))
        print(f"  📁 Staging cũ → {archive.name}")
        print(f"     (Xóa file .bak.md nếu không cần)")

    total = sum(added_total.values())
    print(f"\n✅ Hoàn tất: đã merge {total} thuật ngữ vào {len(added_total)} file glossary\n")


if __name__ == "__main__":
    clean_glossary()
