"""
src/littrans/engine/pipeline.py — Điều phối pipeline dịch tuần tự.

Luồng (3-call, mặc định duy nhất từ v5.1):
  ① Nạp tài liệu, lọc chương chưa dịch
  ② Vòng lặp tuần tự:
       a. Scout refresh (nếu đến kỳ) + Pre-call
       b. Translation call (plain text)
       c. Post-processor: 14-pass code cleanup (TRƯỚC quality_check)
       d. Quality check cơ học
       e. Post-call (review + metadata)
       f. Retry Trans-call nếu Post báo retry_required
       g. Sync staging → Active
  ③ Retry pass (RETRY_FAILED_PASSES vòng)
  ④ Final sync + Auto-merge + Tổng kết

[v5.1] post_processor.run() được gọi ngay sau mỗi call_translation(),
       TRƯỚC quality_check() và Post-call. Đảm bảo AI Review thấy text
       đã clean → giảm false positive "retry_required".

[v5.1] Bible mode: bỏ qua filter_glossary/chars/arc_mem khi
       bible_mode=True — tất cả context đến từ BibleStore.

[v5.2] Xóa legacy 1-call flow (USE_THREE_CALL). Pipeline luôn dùng 3-call.
       Fix silent exception trong Bible mode → logging thay vì pass.
"""
from __future__ import annotations

import os
import re
import time
import logging
from pathlib import Path

from littrans.config.settings import settings
from littrans.utils.io_utils import load_text, atomic_write
from littrans.utils.text_normalizer import normalize as normalize_text
from littrans.utils.post_processor  import run as pp_run, report as pp_report
from littrans.managers.glossary   import filter_glossary, add_new_terms, has_pending_terms, count_pending_terms
from littrans.managers.characters import (filter_characters, update_from_response,
                                           sync_staging_to_active, has_staging_chars,
                                           rotate_to_archive, touch_seen, character_stats)
from littrans.managers.skills     import load_skills_for_chapter, add_skill_updates, skills_stats
from littrans.managers.name_lock  import build_name_lock_table, validate_translation, lock_stats
from littrans.managers.memory     import load_recent as load_arc_memory
from littrans.engine.scout        import run as scout_run, should_refresh, load_context_notes
from littrans.engine.prompt_builder import build as build_prompt, build_translation_prompt
from littrans.engine.quality_guard  import check as quality_check
from littrans.llm.client import (
    call_translation,
    translation_model_info, is_rate_limit, handle_api_error, key_pool,
)


class Pipeline:
    """Singleton-like orchestrator. Tạo 1 instance, gọi .run() hoặc .retranslate()."""

    def __init__(self) -> None:
        self._instructions      = load_text(settings.prompt_agent_file)
        self._char_instructions = load_text(settings.prompt_character_file)
        if not self._char_instructions:
            print("⚠️  Không tìm thấy prompts/character_profile.md")

        # [Bible Mode] Sync characters từ Bible vào Characters_Active
        if settings.bible_mode and settings.bible_available:
            try:
                from littrans.bible.pipeline_bible_patch import init_characters_from_bible
                init_characters_from_bible()
            except Exception as _e:
                logging.warning(f"[Pipeline] Bible init lỗi: {_e}")
                print(f"  ⚠️  Bible init: {_e}")

        print(f"  ⚙️  Pipeline mode: 3-call (pre+trans+post)")

    # ── Public ────────────────────────────────────────────────────

    def run(self) -> None:
        """Dịch tất cả chương chưa có bản dịch."""
        if not settings.input_dir.exists():
            print(f"❌ Không tìm thấy '{settings.input_dir}'."); return

        all_files = self.sorted_inputs()
        if not all_files:
            print(f"❌ Không có file nào trong '{settings.input_dir}'."); return

        pending = self._get_pending(all_files)
        self._print_banner(all_files, pending)

        if not pending:
            print("✅ Tất cả chương đã được dịch.")
            self._final_merge(); return

        total_ok = total_fail = 0
        failed   = []
        chapters_done = 0

        for file_index, fn, fp, op in pending:
            if should_refresh(chapters_done):
                reason = "khởi động" if chapters_done == 0 else f"sau {chapters_done} chương"
                print(f"\n🔭 Scout AI ({reason})...")
                try:
                    scout_run(all_files, file_index)
                except Exception as e:
                    logging.error(f"Scout: {e}")
                    print(f"  ⚠️  Scout lỗi: {e}")

                n_archived = rotate_to_archive(file_index)
                if n_archived:
                    print(f"  📦 Archived {n_archived} nhân vật.")

            ok = self.translate_one(fn, fp, op, file_index)
            if ok:
                total_ok      += 1
                chapters_done += 1
                if settings.immediate_merge:
                    n, _ = sync_staging_to_active()
                    if n: print(f"  🔄 Merged {n} nhân vật → Active")
            else:
                total_fail += 1
                failed.append((file_index, fn, fp, op))

        failed = self._retry_passes(failed)

        if settings.immediate_merge:
            n, _ = sync_staging_to_active()
            if n: print(f"\n🔄 Final sync: {n} nhân vật → Active")

        self._final_merge()
        self._print_summary(total_ok, total_fail, failed)

    def retranslate(self, filename: str, update_data: bool = False) -> None:
        """Dịch lại 1 chương cụ thể."""
        all_files = self.sorted_inputs()
        if filename not in all_files:
            print(f"❌ Không tìm thấy '{filename}'."); return

        chapter_index = all_files.index(filename)
        fp = str(settings.input_dir  / filename)
        base, _  = os.path.splitext(filename)
        op = str(settings.output_dir / f"{base}_VN.txt")

        if os.path.exists(op):
            os.remove(op)
            print(f"🗑️  Đã xóa bản dịch cũ: {base}_VN.txt")

        print(f"\n{'═'*62}")
        print(f"  Retranslate — chương {chapter_index+1}/{len(all_files)}")
        print(f"  File: {filename}")
        print(f"  Cập nhật data: {'✅' if update_data else '❌'}")
        print(f"{'═'*62}\n")

        ok = self.translate_one(filename, fp, op, chapter_index, skip_data_update=not update_data)
        if ok:
            print(f"\n✅ Retranslate xong: {filename}")
            if update_data:
                sync_staging_to_active()
        else:
            print(f"\n❌ Retranslate thất bại: {filename}")

    def translate_one(
        self,
        filename        : str,
        filepath        : str,
        out_filepath    : str,
        chapter_index   : int,
        skip_data_update: bool = False,
    ) -> bool:
        """Dịch 1 chương — luôn dùng 3-call flow."""
        raw_text = load_text(filepath)
        if not raw_text.strip():
            print(f"  ⚠️  File rỗng: {filename}"); return False

        text = normalize_text(raw_text)

        if settings.min_chars_per_chapter > 0 and len(text) < settings.min_chars_per_chapter:
            print(f"  ⚠️  Chương ngắn: {len(text)} ký tự")

        print(f"\n▶  [{chapter_index+1}] Dịch: {filename}")

        return self._translate_three_call(
            filename, text, out_filepath, chapter_index, skip_data_update
        )

    # ── 3-call flow ───────────────────────────────────────────────

    def _translate_three_call(
        self,
        filename        : str,
        text            : str,
        out_filepath    : str,
        chapter_index   : int,
        skip_data_update: bool,
    ) -> bool:

        # ── Chuẩn bị context ─────────────────────────────────────
        name_lock    = build_name_lock_table()
        known_skills = load_skills_for_chapter(text)

        if settings.bible_mode and settings.bible_available:
            glossary_ctx  = {}
            char_profiles = {}
            arc_mem       = ""
            ctx_notes     = ""
            print(f"     [Bible mode] Name Lock: {len(name_lock)} · Skills: {len(known_skills)}")
        else:
            glossary_ctx  = filter_glossary(text)
            char_profiles = filter_characters(text)
            arc_mem       = load_arc_memory()
            ctx_notes     = load_context_notes()
            total_terms   = sum(len(v) for v in glossary_ctx.values())
            print(f"     Glossary: {total_terms} · Characters: {len(char_profiles)} · "
                  f"Name Lock: {len(name_lock)} · Skills: {len(known_skills)}")

        # ── Step 1: Pre-call ──────────────────────────────────────
        print(f"  🔍 Pre-call...")
        from littrans.engine.pre_processor import run as pre_run
        chapter_map = pre_run(text, name_lock, char_profiles, known_skills)
        if chapter_map.ok:
            print(f"  ✅ Chapter map: {len(chapter_map.active_names)} tên · "
                  f"{len(chapter_map.active_skills)} skill · "
                  f"{len(chapter_map.pronoun_pairs)} pronoun pair"
                  + (f" · {len(chapter_map.scene_warnings)} cảnh báo" if chapter_map.scene_warnings else ""))
        else:
            print(f"  ⚠️  Pre-call thất bại → dịch không có chapter map")

        time.sleep(settings.pre_call_sleep)

        # ── Step 2: Build system prompt ───────────────────────────
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
            system_prompt = build_translation_prompt(
                instructions    = self._instructions,
                glossary_ctx    = glossary_ctx,
                char_profiles   = char_profiles,
                arc_memory_text = arc_mem,
                context_notes   = ctx_notes,
                name_lock_table = name_lock,
                known_skills    = known_skills,
                chapter_map     = chapter_map,
                budget_limit    = settings.budget_limit,
                chapter_text    = text,
            )

        # ── Step 3: Translation call + retry loop ─────────────────
        translation       = ""
        retry_instruction = ""
        max_trans         = settings.max_retries

        for attempt in range(1, max_trans + 1):
            try:
                print(f"  ⚙️  Trans-call {attempt}/{max_trans} | {translation_model_info()}")
                input_text = (
                    f"⚠️ RETRY — {retry_instruction}\n\n---\n\n{text}"
                    if retry_instruction else text
                )
                translation = call_translation(system_prompt, input_text)

                # Post-processor: 14-pass code cleanup TRƯỚC quality_check
                translation, pp_changes = pp_run(translation)
                if pp_changes:
                    print(pp_report(pp_changes))

                # Mechanical quality check
                ok_mech, mech_msg = quality_check(translation, text)
                if not ok_mech:
                    print(f"  ⚠️  Lỗi cơ học ({attempt}/{max_trans}): {mech_msg}")
                    if attempt < max_trans:
                        retry_instruction = mech_msg
                        self._wait_quality(attempt)
                        continue
                    else:
                        print(f"  ⚠️  Vẫn còn lỗi cơ học sau {max_trans} lần.")

                break

            except Exception as e:
                logging.error(f"{filename} | trans attempt {attempt} | {e}")
                print(f"  ❌ Trans lỗi {attempt}/{max_trans}: {e}")
                handle_api_error(e)
                if attempt >= max_trans:
                    print(f"  🛑 Trans-call thất bại hoàn toàn."); return False
                self._wait(e, attempt)

        if not translation.strip():
            print(f"  🛑 Translation rỗng."); return False

        time.sleep(settings.post_call_sleep)

        # ── Step 4: Post-call + retry loop ────────────────────────
        from littrans.engine.post_analyzer import run as post_run, PostResult

        post_result = PostResult(
            final_translation = translation,
            passed            = True,
            ok                = False,
        )

        final_translation = translation

        for post_attempt in range(1, settings.post_call_max_retries + 2):
            print(f"  🔎 Post-call {post_attempt}/{settings.post_call_max_retries + 1}...")
            post_result = post_run(text, final_translation, chapter_map, filename)

            if not post_result.ok:
                print(f"  ⚠️  Post-call không hoạt động → dùng bản dịch hiện tại")
                break

            if post_result.issues:
                for issue in post_result.issues:
                    icon = "🔧" if issue.severity == "auto_fix" else "⚠️"
                    print(f"     {icon} [{issue.type}] {issue.detail[:80]}")

            if post_result.passed or not post_result.has_retry_required():
                break

            if (settings.trans_retry_on_quality
                    and post_attempt <= settings.post_call_max_retries):
                print(f"  🔄 Retry Trans-call do lỗi dịch thuật...")
                retry_instruction = post_result.retry_instruction
                time.sleep(settings.post_call_sleep)

                try:
                    input_text = f"⚠️ RETRY — {retry_instruction}\n\n---\n\n{text}"
                    final_translation = call_translation(system_prompt, input_text)

                    final_translation, pp_changes = pp_run(final_translation)
                    if pp_changes:
                        print(pp_report(pp_changes))

                    time.sleep(settings.post_call_sleep)
                except Exception as e:
                    logging.error(f"{filename} | post retry trans | {e}")
                    print(f"  ❌ Retry Trans lỗi: {e}")
                    break
            else:
                print(f"  ⚠️  Vẫn còn lỗi dịch thuật sau {settings.post_call_max_retries} lần retry → ghi file để review")
                final_translation = post_result.final_translation
                break

        # ── Name Lock validate ────────────────────────────────────
        violations = validate_translation(final_translation, name_lock)
        if violations:
            print(f"  🔒 Name Lock — {len(violations)} vi phạm:")
            for w in violations: print(f"     {w}")
            logging.warning(f"{filename} | Name Lock:\n" + "\n".join(violations))
            self._record_violations(violations, name_lock, filename)

        # ── Ghi file ──────────────────────────────────────────────
        atomic_write(out_filepath, final_translation)
        print(f"  ✅ Dịch xong: {filename}")

        # ── [Bible Mode] Update MainLore từ post metadata ─────────
        if settings.bible_mode and settings.bible_available and post_result.ok:
            try:
                from littrans.bible.pipeline_bible_patch import update_bible_from_post
                update_bible_from_post(post_result, filename, text)
            except Exception as _e:
                logging.warning(f"[Pipeline] Bible update lỗi {filename}: {_e}")
                print(f"  ⚠️  Bible update lỗi: {_e}")

        # ── Update data từ Post-call metadata ─────────────────────
        if not skip_data_update and post_result.ok:
            self._update_data_from_post(post_result, filename, chapter_index, char_profiles)

        touch_seen(list(char_profiles.keys()), chapter_index)
        time.sleep(settings.success_sleep)
        return True

    # ── Data update helpers ───────────────────────────────────────

    def _update_data_from_post(self, post_result, filename, chapter_index, char_profiles):
        """Update Master State từ metadata của Post-call."""
        from pydantic import ValidationError
        from littrans.llm.schemas import (
            TermDetail, CharacterDetail, RelationshipUpdate, RelationshipDetail,
            SkillUpdate, PronounEntry,
        )

        # ── new_terms ─────────────────────────────────────────────
        if post_result.new_terms:
            term_objects = []
            for t in post_result.new_terms:
                if not isinstance(t, dict):
                    continue
                try:
                    term_objects.append(TermDetail.model_validate(t))
                except (ValidationError, Exception) as e:
                    logging.warning(f"[Pipeline] TermDetail parse lỗi: {e}")
            if term_objects:
                n = add_new_terms(term_objects, filename)
                if n: print(f"  📝 Thuật ngữ mới: {n}")

        # ── skill_updates ─────────────────────────────────────────
        if post_result.skill_updates:
            skill_objects = []
            for s in post_result.skill_updates:
                if not isinstance(s, dict):
                    continue
                try:
                    skill_objects.append(SkillUpdate.model_validate(s))
                except (ValidationError, Exception) as e:
                    logging.warning(f"[Pipeline] SkillUpdate parse lỗi: {e}")
            if skill_objects:
                n = add_skill_updates(skill_objects, filename)
                if n: print(f"  ⚔️  Kỹ năng mới: {n}")

        # ── new_characters → CharacterDetail đầy đủ ──────────────
        char_objects = []
        if post_result.new_characters:
            for c in post_result.new_characters:
                if not isinstance(c, dict) or not c.get("name"):
                    continue
                try:
                    # Normalize nested lists trước khi validate
                    c_normalized = dict(c)
                    # how_refers_to_others: list[dict] → đảm bảo format đúng
                    how_raw = c_normalized.get("how_refers_to_others", [])
                    if isinstance(how_raw, dict):
                        # backward compat: dict → list
                        c_normalized["how_refers_to_others"] = [
                            {"target": k, "style": v} for k, v in how_raw.items()
                        ]
                    char_objects.append(CharacterDetail.model_validate(c_normalized))
                except (ValidationError, Exception) as e:
                    logging.warning(f"[Pipeline] CharacterDetail parse lỗi [{c.get('name','?')}]: {e}")

        # ── relationship_updates → RelationshipUpdate ─────────────
        rel_objects = []
        if post_result.relationship_updates:
            for r in post_result.relationship_updates:
                if not isinstance(r, dict) or not r.get("character_a") or not r.get("character_b"):
                    continue
                try:
                    r_normalized = dict(r)
                    r_normalized.setdefault("chapter", filename)
                    rel_objects.append(RelationshipUpdate.model_validate(r_normalized))
                except (ValidationError, Exception) as e:
                    logging.warning(f"[Pipeline] RelationshipUpdate parse lỗi: {e}")

        if char_objects or rel_objects:
            n_chars, n_rels = update_from_response(
                char_objects, rel_objects, filename, chapter_index,
            )
            if n_chars:
                dest = "Active" if settings.immediate_merge else "Staging"
                print(f"  👤 Nhân vật mới: {n_chars} → {dest}")
            if n_rels:
                print(f"  🔗 Quan hệ cập nhật: {n_rels}")

    # ── Helpers ───────────────────────────────────────────────────

    def sorted_inputs(self) -> list[str]:
        if not settings.input_dir.exists():
            return []
        files = [f for f in os.listdir(str(settings.input_dir)) if f.endswith((".txt", ".md"))]
        return sorted(files, key=lambda s: [
            int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s)
        ])

    def _get_pending(self, all_files: list[str]) -> list[tuple]:
        pending = []
        for i, fn in enumerate(all_files):
            base, _ = os.path.splitext(fn)
            out = str(settings.output_dir / f"{base}_VN.txt")
            if os.path.exists(out):
                print(f"⏭️  Bỏ qua (đã dịch): {fn}")
            else:
                pending.append((i, fn, str(settings.input_dir / fn), out))
        return pending

    def _retry_passes(self, failed: list) -> list:
        for retry_num in range(1, settings.retry_failed_passes + 1):
            still = [(fi, fn, fp, op) for fi, fn, fp, op in failed if not os.path.exists(op)]
            if not still:
                print(f"\n✅ Không còn chương thất bại (trước retry {retry_num})."); break
            print(f"\n{'─'*55}")
            print(f"🔄 Retry {retry_num}/{settings.retry_failed_passes} — {len(still)} chương")
            print(f"   Chờ {settings.rate_limit_sleep}s...")
            time.sleep(settings.rate_limit_sleep)
            new_failed = []
            for fi, fn, fp, op in still:
                ok = self.translate_one(fn, fp, op, fi)
                if ok and settings.immediate_merge:
                    sync_staging_to_active()
                elif not ok:
                    new_failed.append((fi, fn, fp, op))
            failed = new_failed
        return failed

    def _final_merge(self) -> None:
        if has_pending_terms():
            n = count_pending_terms()
            if settings.auto_merge_glossary:
                print(f"\n📚 Auto-merge ~{n} thuật ngữ...")
                from littrans.tools.clean_glossary import clean_glossary
                clean_glossary()
            else:
                print(f"\n💡 Có ~{n} thuật ngữ mới. Chạy: python main.py clean glossary")

        n_staging = has_staging_chars()
        if n_staging:
            if settings.auto_merge_characters:
                print(f"\n👤 Auto-merge {n_staging} nhân vật...")
                from littrans.tools.clean_characters import run_action
                run_action("merge")
            else:
                print(f"\n💡 Có {n_staging} nhân vật mới. Chạy: python main.py clean characters --action merge")

    def _wait(self, exc: Exception, attempt: int) -> None:
        if is_rate_limit(exc):
            print(f"  ⚠️  Rate limit → chờ {settings.rate_limit_sleep}s...")
            time.sleep(settings.rate_limit_sleep)
        else:
            delay = min(10 * (2 ** (attempt - 1)), 120)
            print(f"  ⏳ Backoff {delay}s...")
            time.sleep(delay)

    def _wait_quality(self, attempt: int) -> None:
        delay = min(5 * attempt, 30)
        print(f"  ⏳ Chờ {delay}s trước khi retry...")
        time.sleep(delay)

    def _record_violations(self, violations: list[str], name_lock: dict, filename: str) -> None:
        from littrans.utils.io_utils import load_json, save_json as _save
        fixes_path = settings.data_dir / "name_fixes.json"
        data  = load_json(fixes_path) or {"fixes": {}}
        fixes = data.setdefault("fixes", {})
        for v in violations:
            m = re.search(r"Tên gốc '(.+?)' còn sót → phải dùng '(.+?)'", v)
            if not m: continue
            wrong, correct = m.group(1).strip(), m.group(2).strip()
            if wrong not in fixes:
                fixes[wrong] = {"correct": correct, "chapters": []}
            entry = fixes[wrong]
            if entry.get("correct") != correct:
                entry["correct"] = correct
            if filename not in entry.get("chapters", []):
                entry.setdefault("chapters", []).append(filename)
        _save(fixes_path, data)

    def _print_banner(self, all_files: list[str], pending: list) -> None:
        stats = character_stats()
        nl    = lock_stats()
        sk    = skills_stats()
        kp    = key_pool.stats()
        budget_str = (
            "tắt" if settings.budget_limit == 0
            else f"{settings.budget_limit:,} token"
        )
        mode_str = "3-call (pre+trans+post)"
        print(f"\n{'═'*62}")
        trans_info  = translation_model_info()
        gemini_info = settings.gemini_model
        print(f"  Pipeline Dịch Truyện v5.2 — Trans: {trans_info}")
        print(f"  Scout/Pre/Post             — Gemini: {gemini_info}")
        print(f"{'─'*62}")
        print(f"  Mode             : {mode_str}")
        print(f"  Tổng chương      : {len(all_files)}")
        print(f"  Cần dịch         : {len(pending)}")
        print(f"  Nhân vật Active  : {stats['active']}"
              + (f" ({stats['emotional']} có emotion)" if stats.get('emotional') else ""))
        print(f"  Nhân vật Archive : {stats['archive']}")
        print(f"  Name Lock        : {nl['total_locked']} tên đã chốt")
        print(f"  Kỹ năng đã biết  : {sk['total']} ({sk['evolution']} tiến hóa)")
        print(f"  API Keys         : {kp['total_keys']} key(s) · active: #{kp['active_idx']+1}")
        print(f"  Token Budget     : {budget_str}")
        print(f"  Scout            : mỗi {settings.scout_refresh_every} chương, đọc {settings.scout_lookback}")
        print(f"  Merge mode       : {'Ngay sau mỗi chương' if settings.immediate_merge else 'Cuối pipeline'}")
        print(f"  Retry passes     : {settings.retry_failed_passes}")
        print(f"{'═'*62}\n")

    def _print_summary(self, total_ok: int, total_fail: int, failed: list) -> None:
        remaining = [fn for _, fn, _, op in failed if not os.path.exists(op)]
        kp = key_pool.stats()
        print(f"\n{'═'*62}")
        print(f"  ✅ Thành công : {total_ok} chương")
        print(f"  ❌ Thất bại   : {len(remaining)} chương")
        if remaining:
            for fn in remaining: print(f"     • {fn}")
        if kp['total_keys'] > 1:
            print(f"  🔑 Keys: {kp['total_keys']} · {kp['dead_keys']} exhausted · final #{kp['active_idx']+1}")
        print(f"{'═'*62}")