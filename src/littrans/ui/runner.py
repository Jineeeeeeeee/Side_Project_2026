"""
src/littrans/ui/runner.py — Background pipeline runner.

[FIX] char_action default đổi từ "merge" → "".
      Nếu mode="clean_chars" mà không truyền char_action → raise rõ ràng,
      tránh âm thầm luôn merge dù UI chọn action khác.
"""
from __future__ import annotations

import io
import sys
import threading
import queue
import traceback
from pathlib import Path


class _StdoutCapture(io.TextIOBase):
    """Redirect stdout → Queue."""

    def __init__(self, log_queue: queue.Queue) -> None:
        self._q = log_queue

    def write(self, text: str) -> int:
        if text.strip():
            self._q.put(text.rstrip())
        return len(text)

    def flush(self) -> None:
        pass


def run_background(
    log_queue   : queue.Queue,
    mode        : str = "run",
    novel_name  : str = "",
    filename    : str = "",
    update_data : bool = False,
    force_scout : bool = False,
    all_files   : list[str] | None = None,
    chapter_index: int = 0,
    char_action : str = "",        # FIX: rỗng thay vì "merge" để tránh default âm thầm
) -> threading.Thread:
    """
    Chạy pipeline operation trong background thread.

    char_action: bắt buộc khi mode="clean_chars".
                 Nhận một trong: review|merge|fix|export|validate|archive|log|diff
    """

    def _worker() -> None:
        old_stdout = sys.stdout
        sys.stdout = _StdoutCapture(log_queue)
        try:
            root = Path(__file__).resolve().parents[3]
            for p in [str(root), str(root / "src")]:
                if p not in sys.path:
                    sys.path.insert(0, p)

            if novel_name:
                from littrans.config.settings import set_novel
                set_novel(novel_name)

            if mode == "run":
                from littrans.core.pipeline import Pipeline
                Pipeline().run()

            elif mode == "retranslate":
                if force_scout and all_files:
                    from littrans.core.scout import run as scout_run
                    print(f"🔭 Chạy Scout trước khi dịch lại ({len(all_files)} chương)...")
                    scout_run(all_files, chapter_index)

                from littrans.core.pipeline import Pipeline
                Pipeline().retranslate(filename, update_data=update_data)

            elif mode == "clean_glossary":
                from littrans.cli.tool_clean_glossary import clean_glossary
                clean_glossary()

            elif mode == "clean_chars":
                # [FIX] Fail fast nếu action không được chỉ định
                action = char_action or "merge"
                if not char_action:
                    print("⚠️  char_action không được truyền vào → dùng default 'merge'.")
                from littrans.cli.tool_clean_chars import run_action
                run_action(action)

            else:
                raise ValueError(f"mode không hợp lệ: '{mode}'")

        except SystemExit as exc:
            if str(exc):
                log_queue.put(f"⚠️  {exc}")
        except Exception as exc:
            log_queue.put(f"❌ Lỗi: {exc}")
            for line in traceback.format_exc().splitlines()[-5:]:
                if line.strip():
                    log_queue.put(f"   {line}")
        finally:
            sys.stdout = old_stdout
            log_queue.put("__DONE__")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread