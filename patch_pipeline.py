"""
patch_pipeline.py — Tự động inject Bible mode vào pipeline.py.

Chạy từ thư mục gốc project:
    python patch_pipeline.py

Thay đổi:
  1. __init__: nếu BIBLE_MODE=true → sync characters từ Bible
  2. _translate_three_call: nếu BIBLE_MODE+BIBLE_AVAILABLE → dùng Bible prompt builder
  3. Sau post_result OK → cập nhật Bible MainLore
"""
from pathlib import Path

TARGET = Path("src/littrans/engine/pipeline.py")
if not TARGET.exists():
    print(f"❌ Không tìm thấy {TARGET}")
    exit(1)

content = TARGET.read_text(encoding="utf-8")

if "bible_mode" in content:
    print("✅ pipeline.py đã được patch — bỏ qua.")
    exit(0)

# ── Patch 1: __init__ — sync from Bible ───────────────────────────
INIT_INJECT = """
        # [Bible Mode] Sync characters từ Bible vào Characters_Active
        if settings.bible_mode and settings.bible_available:
            try:
                from littrans.bible.pipeline_bible_patch import init_characters_from_bible
                init_characters_from_bible()
            except Exception as _e:
                print(f"  ⚠️  Bible init: {_e}")
"""
INIT_ANCHOR = '        if not self._char_instructions:\n            print("⚠️  Không tìm thấy prompts/character_profile.md")'
content = content.replace(INIT_ANCHOR, INIT_ANCHOR + INIT_INJECT)

# ── Patch 2: _translate_three_call — Bible prompt builder ─────────
PROMPT_INJECT = """
        # ── [Bible Mode] Chọn prompt builder ─────────────────────
        if settings.bible_mode and settings.bible_available:
            from littrans.bible.pipeline_bible_patch import build_bible_system_prompt
            system_prompt = build_bible_system_prompt(
                instructions = self._instructions,
                text         = text,
                filename     = filename,
                chapter_map  = chapter_map,
                name_lock    = name_lock,
                budget_limit = settings.budget_limit,
            )
        else:
"""

# Tìm anchor: dòng build_translation_prompt(
OLD_PROMPT = "        system_prompt = build_translation_prompt(\n            instructions    = self._instructions,"
NEW_PROMPT = PROMPT_INJECT + "            system_prompt = build_translation_prompt(\n            instructions    = self._instructions,"

content = content.replace(OLD_PROMPT, NEW_PROMPT)

# ── Patch 3: Sau post_result OK → update Bible MainLore ───────────
POST_INJECT = """
                # [Bible Mode] Update MainLore từ post metadata
                if settings.bible_mode and settings.bible_available and post_result.ok:
                    try:
                        from littrans.bible.pipeline_bible_patch import update_bible_from_post
                        update_bible_from_post(post_result, filename, text)
                    except Exception as _e:
                        pass  # không block pipeline
"""

POST_ANCHOR = "        if not skip_data_update and post_result.ok:\n            self._update_data_from_post(post_result, filename, chapter_index, char_profiles)"
content = content.replace(POST_ANCHOR, POST_INJECT + POST_ANCHOR)

TARGET.write_text(content, encoding="utf-8")
print("✅ pipeline.py đã được patch!")
print("   Bible mode sẽ kích hoạt khi BIBLE_MODE=true trong .env")