"""
src/littrans/ui/epub_ui.py — EPUB Processor UI tab.

Flow hiển thị:
  Tab 1 Upload  → upload .epub, chọn options, chạy
  Tab 2 Hàng chờ → danh sách epub/ đang đợi
  Tab 3 Kết quả → inputs/{name}/ đã tạo, sẵn sàng dịch
"""
from __future__ import annotations

import queue
import time
import threading
from pathlib import Path
from typing import Any


def _get_settings():
    from littrans.config.settings import settings
    return settings


def render_epub_tab(S: Any) -> None:
    import streamlit as st

    st.subheader("📚 EPUB Processor")
    st.caption("Chuyển đổi file .epub thành chapters trong `inputs/{tên_epub}/` sẵn sàng dịch")

    for key, default in [
        ("epub_running", False),
        ("epub_q",       None),
        ("epub_logs",    []),
    ]:
        if key not in S:
            S[key] = default

    # Kiểm tra deps
    try:
        import ebooklib
        from bs4 import BeautifulSoup
    except ImportError:
        st.error(
            "❌ Thiếu thư viện.\n\n"
            "```bash\npip install ebooklib beautifulsoup4\n```"
        )
        return

    settings = _get_settings()
    t_upload, t_queue, t_result = st.tabs(["📤 Upload & Xử lý", "📋 Hàng chờ", "✅ Kết quả"])

    with t_upload:
        _tab_upload(S, settings)
    with t_queue:
        _tab_queue(S, settings)
    with t_result:
        _tab_result(S, settings)


# ═══════════════════════════════════════════════════════════════════
# TAB 1 — UPLOAD & XỬ LÝ
# ═══════════════════════════════════════════════════════════════════

def _tab_upload(S: Any, settings) -> None:
    import streamlit as st

    with st.expander("📤 Upload file .epub", expanded=True):
        uploaded = st.file_uploader(
            "Chọn file .epub",
            type=["epub"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if uploaded:
            settings.epub_dir.mkdir(parents=True, exist_ok=True)
            for f in uploaded:
                (settings.epub_dir / f.name).write_bytes(f.getvalue())
            st.success(f"✅ Đã lưu {len(uploaded)} file vào `{settings.epub_dir}/`")

    st.divider()
    st.markdown("#### Kết quả sẽ được tạo tại:")
    st.code("inputs/{tên_epub}/chapter_0001.txt\ninputs/{tên_epub}/chapter_0002.txt\n...")
    st.caption("Sau đó dịch bằng: `python scripts/main.py translate --book {tên_epub}`")
    st.divider()

    epub_files = sorted(settings.epub_dir.glob("*.epub")) if settings.epub_dir.exists() else []

    if not epub_files:
        st.info(f"Chưa có file .epub nào trong `{settings.epub_dir}/`. Upload để bắt đầu.")
        return

    st.markdown(f"**{len(epub_files)} file sẵn sàng xử lý:**")
    for ep in epub_files[:10]:
        st.caption(f"  📖 {ep.name}  ({ep.stat().st_size/1_048_576:.1f} MB)")
    if len(epub_files) > 10:
        st.caption(f"  ... và {len(epub_files)-10} file khác")

    col_btn, col_info = st.columns([1, 3])
    if not S.epub_running:
        if col_btn.button("▶ Bắt đầu xử lý", type="primary"):
            S.epub_logs = []
            S.epub_q    = queue.Queue()
            _launch(S.epub_q)
            S.epub_running = True
            st.rerun()
    else:
        col_btn.button("⏳ Đang xử lý…", disabled=True)
        col_info.warning("🔄 Đừng đóng cửa sổ.")

    if S.epub_running or S.epub_logs:
        _handle_log(S)


def _launch(log_queue: queue.Queue) -> None:
    def _worker():
        import io, sys, traceback

        class _Cap(io.TextIOBase):
            def write(self, t: str) -> int:
                s = t.rstrip()
                if s:
                    log_queue.put(s)
                elif "\n" in t:
                    log_queue.put("")
                return len(t)
            def flush(self): pass

        old = sys.stdout
        sys.stdout = _Cap()
        try:
            from littrans.tools.epub_processor import process_all_epubs
            process_all_epubs(log_queue=log_queue)
        except Exception as e:
            log_queue.put(f"❌ Lỗi: {e}")
            for ln in traceback.format_exc().splitlines()[-8:]:
                if ln.strip():
                    log_queue.put(f"   {ln}")
        finally:
            sys.stdout = old
            log_queue.put("__DONE__")

    threading.Thread(target=_worker, daemon=True).start()


def _handle_log(S: Any) -> None:
    import streamlit as st

    if S.epub_running:
        q    = S.epub_q
        done = False
        while True:
            try:
                msg = q.get_nowait()
                if msg == "__DONE__":
                    done = True
                else:
                    S.epub_logs.append(msg)
            except queue.Empty:
                break
        if done:
            S.epub_running = False
            S.epub_logs.append("─" * 56)
            S.epub_logs.append("✅ Hoàn tất! Sang tab Kết quả để xem chapters.")

    if S.epub_logs:
        st.markdown("**Log:**")
        st.code("\n".join(S.epub_logs[-300:]), language=None)

    if S.epub_running:
        time.sleep(1.0)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════
# TAB 2 — HÀNG CHỜ
# ═══════════════════════════════════════════════════════════════════

def _tab_queue(S: Any, settings) -> None:
    import streamlit as st

    col1, col2 = st.columns([4, 1])
    col1.markdown(f"#### 📋 `{settings.epub_dir}/`")
    if col2.button("↺", key="epub_q_refresh"):
        st.rerun()

    if not settings.epub_dir.exists():
        st.info("Thư mục epub/ chưa tồn tại.")
        return

    files = sorted(settings.epub_dir.glob("*.epub"))
    if not files:
        st.info("Không có file .epub nào đang chờ.")
        return

    for ep in files:
        c1, c2, c3 = st.columns([4, 1, 1])
        c1.write(f"📖 {ep.name}")
        c2.caption(f"{ep.stat().st_size/1_048_576:.1f} MB")
        if c3.button("🗑", key=f"del_epub_{ep.name}"):
            ep.unlink()
            st.rerun()


# ═══════════════════════════════════════════════════════════════════
# TAB 3 — KẾT QUẢ
# ═══════════════════════════════════════════════════════════════════

def _tab_result(S: Any, settings) -> None:
    import streamlit as st

    col1, col2 = st.columns([4, 1])
    col1.markdown("#### ✅ Chapters đã tạo trong `inputs/`")
    if col2.button("↺", key="epub_r_refresh"):
        st.rerun()

    input_dir = settings.input_dir
    if not input_dir.exists():
        st.info("inputs/ chưa có dữ liệu.")
        return

    # Tìm tất cả sub-folder trong inputs/ (mỗi folder = 1 epub đã xử lý)
    book_dirs = sorted([d for d in input_dir.iterdir() if d.is_dir()])

    if not book_dirs:
        st.info("Chưa có sách nào được xử lý. Chạy pipeline để tạo chapters.")
        return

    for book_dir in book_dirs:
        chapters = sorted(book_dir.glob("*.txt"))
        if not chapters:
            continue

        with st.expander(f"📚 **{book_dir.name}**  —  {len(chapters)} chapters", expanded=False):
            st.code(
                f"# Dịch sách này:\npython scripts/main.py translate --book {book_dir.name}",
                language="bash",
            )
            st.caption(f"📁 `inputs/{book_dir.name}/`")

            # Preview 3 chương đầu
            for ch in chapters[:3]:
                preview = ch.read_text(encoding='utf-8', errors='replace')[:200]
                st.caption(f"`{ch.name}`  →  {preview[:80]}…")
            if len(chapters) > 3:
                st.caption(f"... và {len(chapters)-3} chương khác")

            # Nút xóa cả book
            if st.button(f"🗑 Xóa tất cả chapters của '{book_dir.name}'",
                         key=f"del_book_{book_dir.name}"):
                import shutil
                shutil.rmtree(book_dir)
                st.rerun()