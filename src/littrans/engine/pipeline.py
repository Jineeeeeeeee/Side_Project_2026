"""
src/littrans/engine/pipeline.py — Điều phối pipeline dịch tuần tự.

Luồng (USE_THREE_CALL=true — mặc định):
  ① Nạp tài liệu, lọc chương chưa dịch
  ② Vòng lặp tuần tự:
       a. Scout refresh (nếu đến kỳ) + Pre-call
       b. Translation call (plain text)
       c. Post-call (review + auto_fix + metadata)
       d. Retry Trans-call nếu Post báo retry_required
       e. Sync staging → Active
  ③ Retry pass (RETRY_FAILED_PASSES vòng)
  ④ Final sync + Auto-merge + Tổng kết

Luồng cũ (USE_THREE_CALL=false):
  Giữ nguyên như v4.1 — 1 call nặng với structured JSON output.
"""
from __future__ import annotations

import os
import re
import time
import logging
import tempfile
from pathlib import Path

from littrans.config.settings import settings
from littrans.utils.io_utils import load_text, atomic_write
from littrans.managers.glossary   import filter_glossary, add_new_terms, has_pending_terms, count_pending_terms
from littrans.managers.characters import (filter_characters, update_from_response,
                                           sync_staging_to_active, has_staging_chars,
                                           rotate_to_archive, touch_seen, character_stats)
from littrans.managers.skills     import load_skills_for_chapter, add_skill_updates, skills_stats
from littrans.managers.name_lock  import build_name_lock_table, validate_translation, lock_stats
from littrans.managers.memory     import load_recent as load_arc_memory
from littrans.engine.scout        import run as scout_run, should_refresh, load_context_notes
from littrans.engine.prompt_builder import build as build_prompt, build_translation_prompt
from littrans.engine.quality_guard  import check as quality_check, build_retry_prompt
from littrans.llm.client            import call_gemini, call_gemini_translation, is_rate_limit, handle_api_error, key_pool


class Pipeline:
    """Singleton-like orchestrator. Tạo 1 instance, gọi .run() hoặc .retranslate()."""

    def __init__(self) -> None:
        self._instructions      = load_text(settings.prompt_agent_file)
        self._char_instructions = load_text(settings.prompt_character_file)
        if not self._char_instructions:
            print("⚠️  Không tìm thấy prompts/character_profile.md")

        mode = "3-call" if settings.use_three_call else "1-call (legacy)"
        print(f"  ⚙️  Pipeline mode: {mode}")

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
        """Dịch 1 chương. Dispatch sang 3-call hoặc 1-call tùy settings."""
        text = load_text(filepath)
        if not text.strip():
            print(f"  ⚠️  File rỗng: {filename}"); return False
        if settings.min_chars_per_chapter > 0 and len(text) < settings.min_chars_per_chapter:
            print(f"  ⚠️  Chương ngắn: {len(text)} ký tự")

        print(f"\n▶  [{chapter_index+1}] Dịch: {filename}")

        if settings.use_three_call:
            return self._translate_three_call(
                filename, text, out_filepath, chapter_index, skip_data_update
            )
        else:
            return self._translate_one_call(
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

        # Chuẩn bị context (dùng chung cho Pre và Trans call)
        glossary_ctx  = filter_glossary(text)
        char_profiles = filter_characters(text)
        arc_mem       = load_arc_memory()
        ctx_notes     = load_context_notes()
        name_lock     = build_name_lock_table()
        known_skills  = load_skills_for_chapter(text)

        total_terms = sum(len(v) for v in glossary_ctx.values())
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

        # ── Step 2: Translation call + retry loop ─────────────────
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

        translation     = ""
        retry_instruction = ""
        trans_attempts  = 0
        max_trans       = settings.max_retries

        for attempt in range(1, max_trans + 1):
            trans_attempts = attempt
            try:
                print(f"  ⚙️  Trans-call {attempt}/{max_trans} | {settings.gemini_model}")
                input_text = (
                    f"⚠️ RETRY — {retry_instruction}\n\n---\n\n{text}"
                    if retry_instruction else text
                )
                translation = call_gemini_translation(system_prompt, input_text)

                # Mechanical quality check (nhanh, không tốn API call)
                ok_mech, mech_msg = quality_check(translation, text)
                if not ok_mech:
                    print(f"  ⚠️  Lỗi cơ học ({attempt}/{max_trans}): {mech_msg}")
                    if attempt < max_trans:
                        retry_instruction = mech_msg
                        self._wait_quality(attempt)
                        continue
                    else:
                        print(f"  ⚠️  Vẫn còn lỗi cơ học sau {max_trans} lần.")

                break  # Translation pass — sang Post-call

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

        # ── Step 3: Post-call + retry loop ────────────────────────
        from littrans.engine.post_analyzer import run as post_run

        final_translation = translation
        post_ok = False

        for post_attempt in range(1, settings.post_call_max_retries + 2):
            print(f"  🔎 Post-call {post_attempt}/{settings.post_call_max_retries + 1}...")
            post_result = post_run(text, final_translation, chapter_map, filename)

            if not post_result.ok:
                # Post-call lỗi hoàn toàn — dùng bản dịch hiện tại và tiếp tục
                print(f"  ⚠️  Post-call không hoạt động → dùng bản dịch hiện tại")
                post_ok = True
                break

            # Log auto-fix
            if post_result.auto_fixed:
                fix_count = sum(1 for i in post_result.issues if i.severity == "auto_fix")
                print(f"  🔧 Auto-fixed {fix_count} lỗi trình bày")
                final_translation = post_result.final_translation

            # Log issues
            if post_result.issues:
                for issue in post_result.issues:
                    icon = "🔧" if issue.severity == "auto_fix" else "⚠️"
                    print(f"     {icon} [{issue.type}] {issue.detail[:80]}")

            if post_result.passed or not post_result.has_retry_required():
                post_ok = True
                break

            # Có retry_required → retry Trans-call nếu còn lượt
            if (settings.trans_retry_on_quality
                    and post_attempt <= settings.post_call_max_retries):
                print(f"  🔄 Retry Trans-call do lỗi dịch thuật...")
                retry_instruction = post_result.retry_instruction
                time.sleep(settings.post_call_sleep)

                # Retry Trans-call
                try:
                    input_text = f"⚠️ RETRY — {retry_instruction}\n\n---\n\n{text}"
                    final_translation = call_gemini_translation(system_prompt, input_text)
                    time.sleep(settings.post_call_sleep)
                except Exception as e:
                    logging.error(f"{filename} | post retry trans | {e}")
                    print(f"  ❌ Retry Trans lỗi: {e}")
                    post_ok = True  # không block pipeline
                    break
            else:
                # Hết lượt retry
                print(f"  ⚠️  Vẫn còn lỗi dịch thuật sau {settings.post_call_max_retries} lần retry → ghi file để review")
                final_translation = post_result.final_translation
                post_ok = True
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

        # ── Update data từ Post-call metadata ─────────────────────
        if not skip_data_update and post_result.ok:
            self._update_data_from_post(post_result, filename, chapter_index, char_profiles)

        touch_seen(list(char_profiles.keys()), chapter_index)
        time.sleep(settings.success_sleep)
        return True

    # ── 1-call flow (legacy) ──────────────────────────────────────

    def _translate_one_call(
        self,
        filename        : str,
        text            : str,
        out_filepath    : str,
        chapter_index   : int,
        skip_data_update: bool,
    ) -> bool:
        """Flow cũ — giữ nguyên logic v4.1."""
        glossary_ctx  = filter_glossary(text)
        char_profiles = filter_characters(text)
        arc_mem       = load_arc_memory()
        ctx_notes     = load_context_notes()
        name_lock     = build_name_lock_table()
        known_skills  = load_skills_for_chapter(text)

        total_terms = sum(len(v) for v in glossary_ctx.values())
        print(f"     Glossary: {total_terms} · Characters: {len(char_profiles)} · "
              f"Name Lock: {len(name_lock)} · Skills: {len(known_skills)}")

        system_prompt = build_prompt(
            instructions      = self._instructions,
            glossary_ctx      = glossary_ctx,
            char_profiles     = char_profiles,
            char_instructions = self._char_instructions,
            arc_memory_text   = arc_mem,
            context_notes     = ctx_notes,
            name_lock_table   = name_lock,
            known_skills      = known_skills,
            budget_limit      = settings.budget_limit,
            chapter_text      = text,
        )

        quality_warning = ""

        for attempt in range(1, settings.max_retries + 1):
            try:
                print(f"  ⚙️  API call {attempt}/{settings.max_retries} | {settings.gemini_model}")
                input_text = (
                    build_retry_prompt(text, quality_warning) if quality_warning else text
                )

                result = call_gemini(system_prompt, input_text)

                ok, msg = quality_check(result.translation, text)
                if not ok:
                    logging.warning(f"{filename} | attempt {attempt} | Quality: {msg}")
                    print(f"  ⚠️  Lỗi chất lượng ({attempt}/{settings.max_retries}): {msg}")
                    if attempt < settings.max_retries:
                        quality_warning = msg
                        self._wait_quality(attempt)
                        continue
                    else:
                        print(f"  ⚠️  Vẫn còn lỗi sau {settings.max_retries} lần.")

                violations = validate_translation(result.translation, name_lock)
                if violations:
                    print(f"  🔒 Name Lock — {len(violations)} vi phạm:")
                    for w in violations: print(f"     {w}")
                    logging.warning(f"{filename} | Name Lock:\n" + "\n".join(violations))
                    self._record_violations(violations, name_lock, filename)

                atomic_write(out_filepath, result.translation)
                print(f"  ✅ Dịch xong: {filename}")

                if not skip_data_update:
                    n_terms = add_new_terms(result.new_terms, filename)
                    if n_terms: print(f"  📝 Thuật ngữ mới: {n_terms}")

                    n_skills = add_skill_updates(result.skill_updates, filename)
                    if n_skills: print(f"  ⚔️  Kỹ năng mới: {n_skills}")

                    n_chars, n_rels = update_from_response(
                        result.new_characters, result.relationship_updates,
                        filename, chapter_index,
                    )
                    if n_chars:
                        dest = "Active" if settings.immediate_merge else "Staging"
                        print(f"  👤 Nhân vật mới: {n_chars} → {dest}")
                    if n_rels: print(f"  🔗 Quan hệ cập nhật: {n_rels}")

                touch_seen(list(char_profiles.keys()), chapter_index)
                time.sleep(settings.success_sleep)
                return True

            except Exception as e:
                logging.error(f"{filename} | attempt {attempt} | {e}")
                print(f"  ❌ Lỗi {attempt}/{settings.max_retries}: {e}")
                handle_api_error(e)
                if attempt >= settings.max_retries:
                    print(f"  🛑 Bỏ qua sau {settings.max_retries} lần."); return False
                self._wait(e, attempt)

        return False

    # ── Data update helpers ───────────────────────────────────────

    def _update_data_from_post(self, post_result, filename, chapter_index, char_profiles):
        """Update Master State từ metadata của Post-call."""
        from littrans.llm.schemas import (
            TermDetail, CharacterDetail, RelationshipUpdate, RelationshipDetail,
            SkillUpdate, PronounEntry, HabitualBehavior,
        )

        # ── new_terms ─────────────────────────────────────────────
        if post_result.new_terms:
            term_objects = []
            for t in post_result.new_terms:
                if not isinstance(t, dict) or not t.get("english"):
                    continue
                try:
                    term_objects.append(TermDetail(
                        english    = t["english"],
                        vietnamese = t.get("vietnamese", ""),
                        category   = t.get("category", "general"),
                    ))
                except Exception as e:
                    logging.warning(f"[Pipeline] TermDetail parse lỗi: {e}")
            if term_objects:
                n = add_new_terms(term_objects, filename)
                if n: print(f"  📝 Thuật ngữ mới: {n}")

        # ── skill_updates ─────────────────────────────────────────
        if post_result.skill_updates:
            skill_objects = []
            for s in post_result.skill_updates:
                if not isinstance(s, dict) or not s.get("english"):
                    continue
                try:
                    skill_objects.append(SkillUpdate(
                        english      = s["english"],
                        vietnamese   = s.get("vietnamese", ""),
                        owner        = s.get("owner", ""),
                        skill_type   = s.get("skill_type", "active"),
                        evolved_from = s.get("evolved_from", ""),
                        description  = s.get("description", ""),
                    ))
                except Exception as e:
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
                    # how_refers_to_others
                    how_list = []
                    for h in c.get("how_refers_to_others", []):
                        if isinstance(h, dict) and h.get("target"):
                            how_list.append(PronounEntry(
                                target = h["target"],
                                style  = h.get("style", ""),
                            ))

                    # relationships
                    rel_list = []
                    for r in c.get("relationships", []):
                        if not isinstance(r, dict) or not r.get("with_character"):
                            continue
                        rel_list.append(RelationshipDetail(
                            with_character = r["with_character"],
                            rel_type       = r.get("rel_type", "neutral"),
                            feeling        = r.get("feeling", ""),
                            dynamic        = r.get("dynamic", ""),
                            pronoun_status = r.get("pronoun_status", "weak"),
                            current_status = r.get("current_status", ""),
                            tension_points = r.get("tension_points", []),
                            history        = [],
                        ))

                    char_obj = CharacterDetail(
                        name                 = c["name"],
                        full_name            = c.get("full_name", ""),
                        canonical_name       = c.get("canonical_name", "").strip(),
                        alias_canonical_map  = {
                            k.strip(): v.strip()
                            for k, v in c.get("alias_canonical_map", {}).items()
                            if k.strip() and v.strip()
                        },
                        aliases              = c.get("aliases", []),
                        active_identity      = c.get("active_identity", ""),
                        identity_context     = c.get("identity_context", ""),
                        current_title        = c.get("current_title", ""),
                        faction              = c.get("faction", ""),
                        cultivation_path     = c.get("cultivation_path", ""),
                        current_level        = c.get("current_level", ""),
                        signature_skills     = c.get("signature_skills", []),
                        combat_style         = c.get("combat_style", ""),
                        role                 = c.get("role", "Unknown"),
                        archetype            = c.get("archetype", "UNKNOWN"),
                        personality_traits   = c.get("personality_traits", []),
                        pronoun_self         = c.get("pronoun_self", ""),
                        formality_level      = c.get("formality_level", "medium"),
                        formality_note       = c.get("formality_note", ""),
                        how_refers_to_others = how_list,
                        speech_quirks        = c.get("speech_quirks", []),
                        habitual_behaviors   = [],  # Post-call không extract hành vi
                        relationships        = rel_list,
                        relationship_to_mc   = c.get("relationship_to_mc", ""),
                        current_goal         = c.get("current_goal", ""),
                        hidden_goal          = c.get("hidden_goal", ""),
                        current_conflict     = c.get("current_conflict", ""),
                    )
                    char_objects.append(char_obj)
                except Exception as e:
                    name = c.get("name", "?")
                    logging.warning(f"[Pipeline] CharacterDetail parse lỗi [{name}]: {e}")

        # ── relationship_updates → RelationshipUpdate ─────────────
        rel_objects = []
        if post_result.relationship_updates:
            for r in post_result.relationship_updates:
                if not isinstance(r, dict) or not r.get("character_a") or not r.get("character_b"):
                    continue
                try:
                    rel_objects.append(RelationshipUpdate(
                        character_a       = r["character_a"],
                        character_b       = r["character_b"],
                        chapter           = filename,
                        event             = r.get("event", ""),
                        new_type          = r.get("new_type", ""),
                        new_feeling       = r.get("new_feeling", ""),
                        new_status        = r.get("new_status", ""),
                        new_dynamic       = r.get("new_dynamic", ""),
                        new_tension       = r.get("new_tension", ""),
                        promote_to_strong = bool(r.get("promote_to_strong", False)),
                    ))
                except Exception as e:
                    logging.warning(f"[Pipeline] RelationshipUpdate parse lỗi: {e}")

        # ── Gọi update_from_response nếu có dữ liệu ──────────────
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
        mode_str = "3-call (pre+trans+post)" if settings.use_three_call else "1-call (legacy)"
        print(f"\n{'═'*62}")
        print(f"  Pipeline Dịch Truyện v4.2 — {settings.gemini_model}")
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