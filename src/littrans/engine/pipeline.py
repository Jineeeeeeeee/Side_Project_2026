"""
src/littrans/engine/pipeline.py — Điều phối pipeline dịch tuần tự.

Luồng:
  ① Nạp tài liệu, lọc chương chưa dịch
  ② Vòng lặp tuần tự:
       a. Scout refresh (nếu đến kỳ)
       b. Dịch chương (translate_one)
       c. Sync staging → Active
  ③ Retry pass (RETRY_FAILED_PASSES vòng)
  ④ Final sync + Auto-merge + Tổng kết
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
from littrans.engine.prompt_builder import build as build_prompt
from littrans.engine.quality_guard  import check as quality_check, build_retry_prompt
from littrans.llm.client            import call_gemini, is_rate_limit, handle_api_error, key_pool


class Pipeline:
    """Singleton-like orchestrator. Tạo 1 instance, gọi .run() hoặc .retranslate()."""

    def __init__(self) -> None:
        self._instructions      = load_text(settings.prompt_agent_file)
        self._char_instructions = load_text(settings.prompt_character_file)
        if not self._char_instructions:
            print("⚠️  Không tìm thấy prompts/character_profile.md")

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
        filename       : str,
        filepath       : str,
        out_filepath   : str,
        chapter_index  : int,
        skip_data_update: bool = False,
    ) -> bool:
        """Dịch 1 chương. Trả về True nếu thành công."""
        text = load_text(filepath)
        if not text.strip():
            print(f"  ⚠️  File rỗng: {filename}"); return False
        if settings.min_chars_per_chapter > 0 and len(text) < settings.min_chars_per_chapter:
            print(f"  ⚠️  Chương ngắn: {len(text)} ký tự")

        print(f"\n▶  [{chapter_index+1}] Dịch: {filename}")

        # Build context
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

                # Quality check
                ok, msg = quality_check(result.translation, text)
                if not ok:
                    logging.warning(f"{filename} | attempt {attempt} | Quality: {msg}")
                    print(f"  ⚠️  Lỗi chất lượng ({attempt}/{settings.max_retries}): {msg}")
                    if attempt < settings.max_retries:
                        quality_warning = msg
                        print(f"  🔄 Yêu cầu dịch lại...")
                        self._wait_quality(attempt)
                        continue
                    else:
                        print(f"  ⚠️  Vẫn còn lỗi sau {settings.max_retries} lần. Ghi file để kiểm tra.")

                # Name Lock validate
                violations = validate_translation(result.translation, name_lock)
                if violations:
                    print(f"  🔒 Name Lock — {len(violations)} vi phạm:")
                    for w in violations: print(f"     {w}")
                    logging.warning(f"{filename} | Name Lock:\n" + "\n".join(violations))
                    self._record_violations(violations, name_lock, filename)

                # Write output
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
        print(f"\n{'═'*62}")
        print(f"  Pipeline Dịch Truyện v4.1 — {settings.gemini_model}")
        print(f"{'─'*62}")
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
