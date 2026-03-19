"""
src/littrans/tools/clean_glossary.py — Phân loại & merge thuật ngữ vào Glossary files.

Workflow:
  1. Đọc Staging_Terms.md + section "Mới" từ mọi Glossary file
  2. Dùng Gemini phân loại vào 5 category chuẩn
  3. Append vào đúng Glossary_*.md, bỏ qua duplicate
  4. Backup file cũ → .bak
  5. Xóa staging & section "Mới" đã phân loại
"""
from __future__ import annotations

import re
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from littrans.config.settings import settings
from littrans.utils.io_utils import load_text, atomic_write
from littrans.utils.data_versioning import backup

_NEW_SECTION = "Mới — chờ phân loại"

CATEGORY_LABELS = {
    "pathways"      : "Hệ thống tu luyện / Sequence / Pathway titles",
    "organizations" : "Tổ chức, hội phái, bang nhóm, thế lực",
    "items"         : "Vật phẩm, linh vật, vũ khí, đan dược, artifact",
    "locations"     : "Địa danh, thành phố, vùng đất, cõi giới, dungeon",
    "general"       : "Thuật ngữ chung, tên nhân vật, kỹ năng, khái niệm khác",
}


# ── Pydantic ──────────────────────────────────────────────────────

class CategorizedTerm(BaseModel):
    english   : str
    vietnamese: str
    category  : str = Field(description=f"Phải là một trong: {list(CATEGORY_LABELS)}")


class CategorizationResult(BaseModel):
    terms: list[CategorizedTerm]


# ── Parse helpers ─────────────────────────────────────────────────

def _parse_raw(text: str) -> list[dict]:
    terms: list[dict] = []
    seen: set[str]    = set()
    for line in text.splitlines():
        s = re.sub(r"^[\*\-\+]\s*", "", line.strip())
        if ":" in s and not s.startswith("#"):
            eng, _, vie = s.partition(":")
            eng = eng.strip()
            if eng and eng.lower() not in seen:
                terms.append({"english": eng, "vietnamese": vie.strip()})
                seen.add(eng.lower())
    return terms


def _existing_terms_set() -> set[str]:
    found: set[str] = set()
    for path in settings.glossary_files.values():
        for line in load_text(path).splitlines():
            s = re.sub(r"^[\*\-\+]\s*", "", line.strip())
            if ":" in s:
                eng = s.split(":", 1)[0].strip()
                if eng:
                    found.add(eng.lower())
    return found


def _extract_new_section(text: str) -> list[dict]:
    hdr = f"## {_NEW_SECTION}"
    if hdr not in text:
        return []
    start    = text.index(hdr) + len(hdr)
    next_sec = text.find("\n## ", start)
    block    = text[start:next_sec] if next_sec != -1 else text[start:]
    return _parse_raw(block)


def _remove_new_section(text: str) -> str:
    hdr = f"## {_NEW_SECTION}"
    if hdr not in text:
        return text
    start    = text.index(hdr)
    next_sec = text.find("\n## ", start + len(hdr))
    if next_sec != -1:
        text = text[:start].rstrip() + "\n" + text[next_sec:]
    else:
        text = text[:start].rstrip() + "\n"
    return text


def _resolve_category(cat: str) -> str:
    cat_l = cat.strip().lower()
    for c in CATEGORY_LABELS:
        if c == cat_l:
            return c
    for key, label in CATEGORY_LABELS.items():
        if cat_l in label.lower():
            return key
    for key, label in CATEGORY_LABELS.items():
        if len(cat_l) >= 4 and (cat_l in key or cat_l in label.lower()):
            return key
    return "general"


# ── AI categorization ─────────────────────────────────────────────

def _categorize(raw_terms: list[dict]) -> list[CategorizedTerm]:
    from littrans.llm.client import call_gemini_json

    terms_text = "\n".join(f"- {t['english']}: {t['vietnamese']}" for t in raw_terms)
    cat_list   = "\n".join(f"  - {k}: {v}" for k, v in CATEGORY_LABELS.items())

    system = (
        f"Bạn là chuyên gia biên tập từ điển cho truyện LitRPG / Tu Tiên.\n"
        f"Phân loại từng thuật ngữ vào đúng nhóm:\n{cat_list}\n\n"
        f"Quy tắc:\n"
        f"- pathways: hệ thống tu luyện, Sequence pathway, cảnh giới\n"
        f"- organizations: tổ chức, hội, môn phái\n"
        f"- items: vật phẩm cụ thể, vũ khí, đan dược\n"
        f"- locations: địa danh, tên nơi chốn\n"
        f"- general: tên nhân vật, kỹ năng, khái niệm chung\n\n"
        f"QUAN TRỌNG: Trả về đúng key (pathways/organizations/items/locations/general).\n"
        f"Trả về JSON với schema: {{\"terms\": [{{\"english\": ..., \"vietnamese\": ..., \"category\": ...}}]}}\n"
        f"KHÔNG giải thích thêm. KHÔNG dùng markdown code block."
    )

    print(f"  🤖 Phân loại {len(raw_terms)} thuật ngữ với Gemini...")
    data = call_gemini_json(system, f"Phân loại:\n\n{terms_text}")
    return CategorizationResult.model_validate(data).terms


# ── Merge into files ──────────────────────────────────────────────

def _merge_into_files(categorized: list[CategorizedTerm]) -> dict[str, int]:
    existing = _existing_terms_set()
    by_cat: dict[str, list[CategorizedTerm]] = {c: [] for c in CATEGORY_LABELS}
    skipped = 0

    for term in categorized:
        cat = _resolve_category(term.category)
        if term.english.lower() not in existing:
            by_cat[cat].append(term)
            existing.add(term.english.lower())
        else:
            skipped += 1

    if skipped:
        print(f"  ⏭️  Bỏ qua {skipped} từ đã có")

    added: dict[str, int] = {}
    for cat, terms in by_cat.items():
        if not terms:
            continue
        path    = settings.glossary_files[cat]
        content = load_text(path)

        if path.exists():
            backup(path)

        if content and not content.endswith("\n"):
            content += "\n"
        new_lines = "\n".join(f"- {t.english}: {t.vietnamese}" for t in terms)

        if not content.strip():
            content = f"# Glossary — {CATEGORY_LABELS[cat]}\n\n{new_lines}\n"
        elif f"## {_NEW_SECTION}" in content:
            content = content.rstrip("\n") + f"\n{new_lines}\n"
        else:
            content = content.rstrip("\n") + f"\n\n## {_NEW_SECTION}\n{new_lines}\n"

        atomic_write(path, content)
        added[cat] = len(terms)
        print(f"  📁 {path.name}: +{len(terms)} thuật ngữ")

    return added


# ── Main ──────────────────────────────────────────────────────────

def clean_glossary() -> None:
    settings.glossary_dir.mkdir(parents=True, exist_ok=True)

    staging_text  = load_text(settings.staging_terms_file)
    staging_terms = _parse_raw(staging_text) if staging_text.strip() else []

    new_section_terms: list[dict] = []
    for path in settings.glossary_files.values():
        new_section_terms.extend(_extract_new_section(load_text(path)))

    seen: set[str] = set()
    all_terms: list[dict] = []
    for t in staging_terms + new_section_terms:
        key = t["english"].lower()
        if key not in seen:
            seen.add(key)
            all_terms.append(t)

    if not all_terms:
        print("✅ Không có thuật ngữ nào cần phân loại.")
        return

    print(f"\n📋 {len(all_terms)} thuật ngữ cần phân loại "
          f"({len(staging_terms)} từ Staging, {len(new_section_terms)} từ section 'Mới')\n")

    try:
        categorized = _categorize(all_terms)
    except Exception as e:
        print(f"❌ Lỗi phân loại: {e}")
        logging.error(f"clean_glossary: {e}")
        return

    print("\n📊 Kết quả phân loại:")
    by_cat_preview: dict[str, list] = {}
    for t in categorized:
        by_cat_preview.setdefault(_resolve_category(t.category), []).append(t.english)
    for cat, terms in sorted(by_cat_preview.items()):
        preview = ", ".join(terms[:5]) + ("..." if len(terms) > 5 else "")
        print(f"   {cat}: {len(terms)} từ → {preview}")

    print()
    added_total = _merge_into_files(categorized)

    if new_section_terms:
        for path in settings.glossary_files.values():
            text = load_text(path)
            if f"## {_NEW_SECTION}" in text:
                atomic_write(path, _remove_new_section(text))
        print(f"  🗑️  Đã xóa section 'Mới' (đã phân loại xong)")

    if staging_text and staging_text.strip():
        archive = settings.glossary_dir / f"Staging_Terms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak.md"
        shutil.move(str(settings.staging_terms_file), str(archive))
        print(f"  📁 Staging → {archive.name}")

    total = sum(added_total.values())
    print(f"\n✅ Hoàn tất: {total} thuật ngữ vào {len(added_total)} file\n")
