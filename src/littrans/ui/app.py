"""
src/littrans/ui/app.py — LiTTrans Web UI (Streamlit)

[v5.4] Multi-novel:
  - Novel selector trong sidebar (selectbox từ inputs/)
  - Khi đổi novel → set_novel() + clear cache
  - load_chapters(novel_name) nhận arg để cache đúng
  - run_background() được truyền novel_name
"""
from __future__ import annotations

import html
import queue
import re
import sys
import time
from pathlib import Path
from typing import Any

# ── Project root → sys.path ───────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[3]
for _p in [str(_ROOT), str(_ROOT / "src")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
from littrans.ui.bible_ui import render_bible_tab as render_bible
from littrans.ui.epub_ui import render_epub_tab as render_epub
import streamlit.components.v1 as components

st.set_page_config(
    page_title="LiTTrans",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state ─────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "page"          : "translate",
    "running"       : False,
    "run_thread"    : None,
    "log_q"         : None,
    "logs"          : [],
    "rt_running"    : False,
    "rt_thread"     : None,
    "rt_q"          : None,
    "rt_logs"       : [],
    "sel_ch"        : 0,
    "show_rt"       : False,
    "clean_running" : False,
    "clean_q"       : None,
    "clean_logs"    : [],
    "settings_saved": False,
    # Multi-novel
    "current_novel" : "",
    # Bible System
    "bible_scan_running"    : False,
    "bible_scan_q"          : None,
    "bible_scan_logs"       : [],
    "bible_crossref_running": False,
    "bible_crossref_q"      : None,
    "bible_crossref_logs"   : [],
    "bible_export_done"     : False,
    # epub
    "epub_running"          : False,
    "epub_q"                : None,
    "epub_logs"             : [],
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

S = st.session_state

# ── CSS ───────────────────────────────────────────────────────────
st.markdown("""
<style>
.badge { display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px;margin:1px; }
.badge-ok   { background:#EAF3DE;color:#3B6D11; }
.badge-warn { background:#FAEEDA;color:#633806; }
.badge-err  { background:#FCEBEB;color:#791F1F; }
.badge-info { background:#E6F1FB;color:#0C447C; }
.badge-dim  { background:#F1EFE8;color:#444441; }
.novel-pill { display:inline-block;background:#EEEDFE;color:#3C3489;font-size:12px;font-weight:600;padding:3px 10px;border-radius:99px; }
.strong-lock { color:#3B6D11;font-size:11px; }
.weak-lock   { color:#BA7517;font-size:11px; }
</style>
""", unsafe_allow_html=True)

# ── .env helpers ──────────────────────────────────────────────────
_ENV_PATH = _ROOT / ".env"

def _load_env() -> dict[str, str]:
    try:
        from dotenv import dotenv_values
        return {k: (v or "") for k, v in dotenv_values(str(_ENV_PATH)).items()}
    except Exception:
        return {}

def _save_env(updates: dict[str, str]) -> None:
    try:
        from dotenv import set_key
        if not _ENV_PATH.exists():
            _ENV_PATH.write_text("")
        for k, v in updates.items():
            set_key(str(_ENV_PATH), k, v)
    except Exception as exc:
        raise RuntimeError(f"Không thể lưu .env: {exc}") from exc


# ── Novel helpers ─────────────────────────────────────────────────

def _get_available_novels() -> list[str]:
    """Scan inputs/ tìm subfolder chứa .txt/.md = novel."""
    try:
        from littrans.config.settings import get_available_novels
        return get_available_novels()
    except Exception:
        inp = _ROOT / "inputs"
        if not inp.exists():
            return []
        return sorted([
            d.name for d in inp.iterdir()
            if d.is_dir() and not d.name.startswith(".")
            and any(f.suffix in (".txt", ".md") for f in d.iterdir())
        ])


def _apply_novel(name: str) -> None:
    """Set novel trong settings và clear tất cả cache liên quan."""
    from littrans.config.settings import set_novel
    set_novel(name)
    load_chapters.clear()
    load_stats.clear()
    load_characters.clear()
    load_glossary_data.clear()


# ── Cached data loaders ───────────────────────────────────────────

@st.cache_data(ttl=10)
def load_chapters(novel_name: str = "") -> list[dict]:
    """[v5.4] novel_name là cache key — đổi novel → cache khác."""
    try:
        from littrans.config.settings import settings
        input_dir  = settings.active_input_dir
        output_dir = settings.active_output_dir
    except Exception:
        input_dir  = _ROOT / "inputs" / novel_name if novel_name else _ROOT / "inputs"
        output_dir = _ROOT / "outputs" / novel_name if novel_name else _ROOT / "outputs"

    if not input_dir.exists():
        return []

    files = sorted(
        [f for f in input_dir.iterdir() if f.suffix in (".txt", ".md")],
        key=lambda s: [int(t) if t.isdigit() else t.lower()
                       for t in re.split(r"(\d+)", s.name)],
    )
    result = []
    for i, fp in enumerate(files):
        base    = fp.stem
        vn_path = output_dir / f"{base}_VN.txt"
        result.append({
            "idx"    : i,
            "name"   : fp.name,
            "path"   : fp,
            "size"   : f"{fp.stat().st_size // 1024} KB",
            "vn_path": vn_path,
            "done"   : vn_path.exists(),
        })
    return result


@st.cache_data(ttl=30)
def load_chapter_content(path_str: str, vn_path_str: str, done: bool) -> dict[str, str]:
    raw = ""
    vn  = ""
    try:
        raw = Path(path_str).read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if done:
        try:
            vn = Path(vn_path_str).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return {"raw": raw, "vn": vn}


@st.cache_data(ttl=4)
def load_characters() -> dict[str, dict]:
    try:
        from littrans.context.characters import load_active, load_archive
        return {
            "active" : load_active().get("characters", {}),
            "archive": load_archive().get("characters", {}),
        }
    except Exception:
        return {"active": {}, "archive": {}}


@st.cache_data(ttl=4)
def load_glossary_data() -> dict[str, list[tuple[str, str]]]:
    try:
        from littrans.context.glossary import _load_all
        raw = _load_all()
    except Exception:
        return {}
    result: dict[str, list] = {}
    for cat, terms in raw.items():
        entries = []
        for _, line in terms.items():
            clean = re.sub(r"^[\*\-\+]\s*", "", line.strip())
            if ":" in clean and not clean.startswith("#"):
                eng, _, vn = clean.partition(":")
                if eng.strip():
                    entries.append((eng.strip(), vn.strip()))
        if entries:
            result[cat] = entries
    return result


@st.cache_data(ttl=5)
def load_stats() -> dict:
    try:
        from littrans.context.characters import character_stats
        from littrans.context.glossary   import glossary_stats
        from littrans.context.skills     import skills_stats
        from littrans.context.name_lock  import lock_stats
        return {
            "chars" : character_stats(),
            "glos"  : glossary_stats(),
            "skills": skills_stats(),
            "lock"  : lock_stats(),
        }
    except Exception:
        return {"chars": {}, "glos": {}, "skills": {}, "lock": {}}


# ── HTML viewer components ────────────────────────────────────────

def _paras_to_html(text: str) -> str:
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paras:
        return "<p style='color:#999;font-style:italic'>Không có nội dung.</p>"
    return "".join(
        f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>"
        for p in paras
    )


def split_view(raw: str, vn: str, height: int = 520) -> None:
    raw_html = _paras_to_html(raw)
    vn_html  = _paras_to_html(vn)
    widget   = f"""<!DOCTYPE html><html><head><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;background:transparent}}
.wrap{{display:flex;height:{height}px;border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden}}
.pane{{flex:1;overflow-y:auto;padding:14px 18px;line-height:1.85;color:#1a1a1a}}
.pane+.pane{{border-left:0.5px solid #e0e0e0}}
.lbl{{font-size:10px;font-weight:600;letter-spacing:.08em;color:#aaa;margin-bottom:12px;text-transform:uppercase}}
p{{margin-bottom:10px}}p:last-child{{margin:0}}
@media(prefers-color-scheme:dark){{body{{background:transparent}}.pane{{color:#ddd;background:#0e1117}}.wrap,.pane+.pane{{border-color:#2a2a2a}}}}
</style></head><body>
<div class="wrap">
  <div class="pane" id="L"><div class="lbl">Bản gốc (EN)</div>{raw_html}</div>
  <div class="pane" id="R"><div class="lbl">Bản dịch (VN)</div>{vn_html}</div>
</div>
<script>
var L=document.getElementById('L'),R=document.getElementById('R'),busy=false;
L.addEventListener('scroll',function(){{if(busy)return;busy=true;var r=L.scrollTop/Math.max(1,L.scrollHeight-L.clientHeight);R.scrollTop=r*(R.scrollHeight-R.clientHeight);setTimeout(function(){{busy=false;}},60);}});
R.addEventListener('scroll',function(){{if(busy)return;busy=true;var r=R.scrollTop/Math.max(1,R.scrollHeight-R.clientHeight);L.scrollTop=r*(L.scrollHeight-L.clientHeight);setTimeout(function(){{busy=false;}},60);}});
</script></body></html>"""
    components.html(widget, height=height + 6, scrolling=False)


def diff_view(raw: str, vn: str, height: int = 520) -> None:
    import difflib
    raw_p = [p.strip() for p in raw.replace("\r\n", "\n").split("\n\n") if p.strip()]
    vn_p  = [p.strip() for p in vn.replace("\r\n",  "\n").split("\n\n") if p.strip()]
    ops   = difflib.SequenceMatcher(None, raw_p, vn_p, autojunk=False).get_opcodes()
    tag_a: dict[int, str] = {}
    tag_b: dict[int, str] = {}
    for tag, i1, i2, j1, j2 in ops:
        if tag == "replace":
            for i in range(i1, i2): tag_a[i] = "chg"
            for j in range(j1, j2): tag_b[j] = "chg"
        elif tag == "delete":
            for i in range(i1, i2): tag_a[i] = "del"
        elif tag == "insert":
            for j in range(j1, j2): tag_b[j] = "add"
    def render(paras, tags):
        out = []
        for i, p in enumerate(paras):
            t = tags.get(i, "")
            esc = html.escape(p).replace(chr(10), "<br>")
            cls = f' class="{t}"' if t else ""
            out.append(f"<p{cls}>{esc}</p>")
        return "".join(out) or "<p style='color:#999'>—</p>"
    raw_html = render(raw_p, tag_a)
    vn_html  = render(vn_p,  tag_b)
    widget = f"""<!DOCTYPE html><html><head><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px}}
.wrap{{display:flex;height:{height}px;border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden}}
.pane{{flex:1;overflow-y:auto;padding:14px 18px;line-height:1.85;color:#1a1a1a}}
.pane+.pane{{border-left:0.5px solid #e0e0e0}}
.lbl{{font-size:10px;font-weight:600;letter-spacing:.08em;color:#aaa;margin-bottom:12px;text-transform:uppercase}}
p{{margin-bottom:10px}}p:last-child{{margin:0}}
.add{{background:rgba(99,153,34,.13);border-left:2px solid #639922;padding-left:8px;margin-left:-10px;border-radius:0 3px 3px 0}}
.del{{background:rgba(163,45,45,.08);border-left:2px solid #A32D2D;padding-left:8px;margin-left:-10px;opacity:.5;text-decoration:line-through}}
.chg{{background:rgba(133,79,11,.1);border-left:2px solid #EF9F27;padding-left:8px;margin-left:-10px;border-radius:0 3px 3px 0}}
@media(prefers-color-scheme:dark){{.pane{{color:#ddd;background:#0e1117}}.wrap,.pane+.pane{{border-color:#2a2a2a}}}}
</style></head><body>
<div class="wrap">
  <div class="pane"><div class="lbl">Bản gốc (EN)</div>{raw_html}</div>
  <div class="pane"><div class="lbl">Bản dịch (VN)</div>{vn_html}</div>
</div></body></html>"""
    components.html(widget, height=height + 6, scrolling=False)


# ── Queue polling + log display ───────────────────────────────────

def _poll(q_key: str, logs_key: str, thread_key: str | None = None) -> bool:
    q: queue.Queue | None = S.get(q_key)
    if q is None: return False
    done = False
    while True:
        try:
            msg = q.get_nowait()
            if msg == "__DONE__": done = True
            else: S[logs_key].append(msg)
        except queue.Empty:
            break
    if not done and thread_key:
        thread = S.get(thread_key)
        if thread is not None and not thread.is_alive():
            S[logs_key].append("⚠️  Background thread đã dừng bất ngờ.")
            done = True
    return done


def _show_log(logs: list[str], height: int = 200) -> None:
    st.code("\n".join(logs[-300:]) if logs else "(chờ log...)", language=None)


# ══════════════════════════════════════════════════════════════════
# PAGE: DỊCH
# ══════════════════════════════════════════════════════════════════

def render_translate() -> None:
    chapters = load_chapters(S.current_novel)
    done  = sum(1 for c in chapters if c["done"])
    total = len(chapters)

    st.subheader("Dịch chương")

    # ── Upload ─────────────────────────────────────────────────────
    with st.expander("📁 Upload file chương", expanded=not chapters):
        uploaded = st.file_uploader(
            "Chọn file .txt / .md", type=["txt", "md"],
            accept_multiple_files=True, label_visibility="collapsed",
        )
        if uploaded:
            try:
                from littrans.config.settings import settings as cfg
                inp = cfg.active_input_dir
            except Exception:
                novel = S.current_novel
                inp = _ROOT / "inputs" / novel if novel else _ROOT / "inputs"
            inp.mkdir(parents=True, exist_ok=True)
            for f in uploaded:
                (inp / f.name).write_bytes(f.getvalue())
            st.success(f"✅ Đã lưu {len(uploaded)} file → `{inp}`")
            load_chapters.clear()
            st.rerun()

    # ── Chapter list ───────────────────────────────────────────────
    if not chapters:
        if S.current_novel:
            st.info(f"Chưa có file nào trong `inputs/{S.current_novel}/`. Upload file để bắt đầu.")
        else:
            st.info("Chưa có file nào trong `inputs/`. Upload file hoặc tạo subfolder novel.")
    else:
        h0, h1, h2, h3 = st.columns([0.4, 3, 0.8, 1.5])
        h0.caption("STT"); h1.caption("File")
        h2.caption("Kích thước"); h3.caption("Trạng thái")
        for ch in chapters:
            c0, c1, c2, c3 = st.columns([0.4, 3, 0.8, 1.5])
            c0.write(f"`{ch['idx']+1:03d}`")
            c1.write(ch["name"])
            c2.write(ch["size"])
            if ch["done"]:
                c3.markdown('<span class="badge badge-ok">✅ Đã dịch</span>', unsafe_allow_html=True)
            else:
                c3.markdown('<span class="badge badge-warn">⬜ Chưa dịch</span>', unsafe_allow_html=True)

    if total:
        pct = done / total
        st.progress(pct, text=f"Tổng: {done}/{total} ({int(pct*100)}%)")

    st.divider()

    col_btn, col_info = st.columns([1, 4])
    if not S.running:
        if col_btn.button("▶ Chạy pipeline", type="primary",
                          disabled=not chapters or not total - done):
            S.logs  = []
            S.log_q = queue.Queue()
            from littrans.ui.runner import run_background
            # [v5.4] Truyền novel_name vào background thread
            S.run_thread = run_background(
                S.log_q, mode="run", novel_name=S.current_novel
            )
            S.running = True
            st.rerun()
        if total and done == total:
            col_info.info("✅ Tất cả chương đã được dịch.")
    else:
        col_btn.button("⏹ Đang chạy…", disabled=True)
        col_info.warning("🔄 Pipeline đang chạy — đừng đóng cửa sổ.")

    if S.running or S.logs:
        if S.running:
            done_flag = _poll("log_q", "logs", "run_thread")
            if done_flag:
                S.running = False
                S.logs.append("─" * 56)
                S.logs.append("✅ Pipeline hoàn tất.")
                load_chapters.clear()
                load_stats.clear()
        st.markdown("**Log:**")
        _show_log(S.logs)
        if S.running:
            time.sleep(0.9)
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# PAGE: XEM CHƯƠNG
# ══════════════════════════════════════════════════════════════════

def render_chapters() -> None:
    chapters = load_chapters(S.current_novel)
    if not chapters:
        st.info("Chưa có file nào.")
        return

    col_list, col_view = st.columns([1, 3.2])

    with col_list:
        search = st.text_input("🔍", placeholder="Tìm chương…",
                               label_visibility="collapsed", key="ch_s")
        filtered = [c for c in chapters
                    if not search or search.lower() in c["name"].lower()]
        st.caption(f"{len(filtered)} / {len(chapters)} chương")
        for ch in filtered:
            icon = "✅" if ch["done"] else "⬜"
            is_sel = (ch["idx"] == S.sel_ch)
            if st.button(f"{icon} {ch['name']}", key=f"chbtn_{ch['idx']}",
                         use_container_width=True,
                         type="primary" if is_sel else "secondary"):
                S.sel_ch  = ch["idx"]
                S.show_rt = False
                S.rt_logs = []
                st.rerun()

    with col_view:
        idx = S.sel_ch if S.sel_ch < len(chapters) else 0
        _render_chapter_detail(chapters[idx])


def _render_chapter_detail(ch: dict) -> None:
    content = load_chapter_content(str(ch["path"]), str(ch["vn_path"]), ch["done"])
    raw = content["raw"]
    vn  = content["vn"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("File", ch["name"])
    m2.metric("Kích thước", ch["size"])
    m3.metric("Bản dịch", "✅ Có" if ch["done"] else "❌ Chưa")
    nl_count = 0
    if ch["done"] and vn:
        try:
            from littrans.context.name_lock import build_name_lock_table, validate_translation
            nl_count = len(validate_translation(vn, build_name_lock_table()))
        except Exception:
            pass
    nl_label = f"⚠️ {nl_count} vi phạm" if nl_count else "✅ 0 vi phạm"
    m4.metric("Name Lock", nl_label)

    tabs = st.tabs(["🔀 Song song", "📄 Bản gốc", "🇻🇳 Bản dịch", "⚡ Diff"])

    with tabs[0]:
        if not ch["done"]:
            st.info("Chương chưa dịch — chỉ hiển thị bản gốc.")
            st.text_area("", raw, height=420, disabled=True, label_visibility="collapsed")
        elif not raw:
            st.warning("Không đọc được file gốc.")
        else:
            split_view(raw, vn)

    with tabs[1]:
        if raw:
            st.text_area("", raw, height=500, disabled=True, label_visibility="collapsed")
        else:
            st.info("Không đọc được file gốc.")

    with tabs[2]:
        if ch["done"] and vn:
            st.text_area("", vn, height=500, disabled=True, label_visibility="collapsed")
            c1, c2 = st.columns([1, 5])
            c2.download_button("⬇ Tải xuống", data=vn.encode("utf-8"),
                               file_name=f"{ch['path'].stem}_VN.txt",
                               mime="text/plain", key="dl_vn")
        elif not ch["done"]:
            st.info("Chương chưa được dịch.")
        else:
            st.warning("Không đọc được file dịch.")

    with tabs[3]:
        if not ch["done"]:
            st.info("Cần có bản dịch để xem diff.")
        elif not raw or not vn:
            st.warning("Thiếu nội dung để so sánh.")
        else:
            diff_view(raw, vn)

    # ── Retranslate panel ──────────────────────────────────────────
    st.divider()
    rt_col, _ = st.columns([1, 5])
    btn_label = "✕ Đóng" if S.show_rt else "↺ Dịch lại…"
    if rt_col.button(btn_label, key="rt_toggle", type="secondary"):
        S.show_rt = not S.show_rt
        S.rt_logs = []
        st.rerun()

    if S.show_rt:
        with st.container(border=True):
            st.markdown(f"**↺ Dịch lại — `{ch['name']}`**")
            if ch["done"]:
                st.warning("⚠️  Bản dịch hiện tại sẽ bị **ghi đè** sau khi dịch lại.")
            c1, c2 = st.columns(2)
            update_data = c1.checkbox("Cập nhật data", value=False, key="rt_upd")
            force_scout = c2.checkbox("Chạy Scout AI trước", value=False, key="rt_scout")

            if not S.rt_running:
                if st.button("⚡ Xác nhận dịch lại", type="primary", key="rt_confirm"):
                    S.rt_logs = []
                    S.rt_q    = queue.Queue()
                    all_files_list = [c["name"] for c in load_chapters(S.current_novel)]
                    from littrans.ui.runner import run_background
                    # [v5.4] Truyền novel_name
                    S.rt_thread = run_background(
                        S.rt_q,
                        mode          = "retranslate",
                        novel_name    = S.current_novel,
                        filename      = ch["name"],
                        update_data   = update_data,
                        force_scout   = force_scout,
                        all_files     = all_files_list,
                        chapter_index = ch["idx"],
                    )
                    S.rt_running = True
                    st.rerun()
            else:
                st.info("⏳ Đang dịch lại…")

            if S.rt_running or S.rt_logs:
                if S.rt_running:
                    rt_done = _poll("rt_q", "rt_logs", "rt_thread")
                    if rt_done:
                        S.rt_running = False
                        S.rt_logs.append("─" * 56)
                        S.rt_logs.append("✅ Dịch lại hoàn tất.")
                        load_chapters.clear()
                        load_stats.clear()
                _show_log(S.rt_logs)
                if S.rt_running:
                    time.sleep(0.9)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════
# PAGE: NHÂN VẬT
# ══════════════════════════════════════════════════════════════════

def render_characters() -> None:
    chars_data = load_characters()
    active  = chars_data["active"]
    archive = chars_data["archive"]

    if not active and not archive:
        st.info("Chưa có nhân vật nào. Chạy pipeline để tạo dữ liệu.")
        return

    tab_a, tab_b = st.tabs([f"Active ({len(active)})", f"Archive ({len(archive)})"])
    for tab, chars, label in [(tab_a, active, "active"), (tab_b, archive, "archive")]:
        with tab:
            if not chars:
                st.info(f"Không có nhân vật nào trong {label}.")
                continue
            search = st.text_input("🔍", placeholder="Tìm tên...",
                                   label_visibility="collapsed", key=f"cs_{label}")
            filtered = {k: v for k, v in chars.items()
                        if not search or search.lower() in k.lower()}
            st.caption(f"{len(filtered)} nhân vật")
            cols = st.columns(3)
            for i, (name, profile) in enumerate(filtered.items()):
                with cols[i % 3]:
                    _char_card(name, profile)


def _char_card(name: str, p: dict) -> None:
    speech = p.get("speech", {})
    power  = p.get("power", {})
    ident  = p.get("identity", {})
    arc    = p.get("arc_status", {})
    em     = p.get("emotional_state", {})
    rels   = p.get("relationships", {})

    palettes = [
        ("#E1F5EE", "#085041"), ("#EEEDFE", "#3C3489"),
        ("#E6F1FB", "#0C447C"), ("#FAEEDA", "#633806"),
        ("#FCEBEB", "#791F1F"), ("#EAF3DE", "#3B6D11"),
    ]
    bg, fg   = palettes[sum(ord(c) for c in name) % len(palettes)]
    initials = "".join(w[0].upper() for w in name.split()[:2]) or name[:2].upper()

    state = em.get("current", "normal")
    em_map = {
        "angry"  : '<span class="badge badge-err">ANGRY</span>',
        "hurt"   : '<span class="badge badge-warn">HURT</span>',
        "changed": '<span class="badge badge-info">CHANGED</span>',
    }
    em_html = em_map.get(state, "")

    pronoun_self = speech.get("pronoun_self", "—")
    level        = power.get("current_level", "—")
    faction      = ident.get("faction", p.get("faction", ""))
    goal_raw     = arc.get("current_goal", "") if arc else ""
    goal         = goal_raw[:70] + "…" if len(goal_raw) > 70 else goal_raw
    history      = p.get("_history", [])

    with st.container(border=True):
        avatar_col, info_col = st.columns([1, 4])
        with avatar_col:
            st.markdown(
                f'<div style="width:38px;height:38px;border-radius:50%;'
                f'background:{bg};color:{fg};display:flex;align-items:center;'
                f'justify-content:center;font-size:13px;font-weight:600">'
                f'{initials}</div>', unsafe_allow_html=True,
            )
        with info_col:
            st.markdown(f"**{name}**")
            st.caption(p.get("role", "?"))
            if em_html:
                st.markdown(em_html, unsafe_allow_html=True)

        tab_profile, tab_history = st.tabs(["Profile", f"Lịch sử ({len(history)})"])

        with tab_profile:
            st.caption(f"Tự xưng: **{pronoun_self}** · Cấp: **{level}**")
            if faction: st.caption(f"Phe: {faction}")
            if goal:    st.caption(f"Mục tiêu: {goal}")
            for other, rel in list(rels.items())[:2]:
                dyn    = rel.get("dynamic", "")
                status = rel.get("pronoun_status", "weak")
                if not dyn: continue
                icon = "✓" if status == "strong" else "🔸"
                css  = "strong-lock" if status == "strong" else "weak-lock"
                st.markdown(
                    f'<span class="{css}">{icon} {name} ↔ {other}: <b>{dyn}</b></span>',
                    unsafe_allow_html=True,
                )

        with tab_history:
            _render_char_history(name, p)


def _render_char_history(name: str, p: dict) -> None:
    try:
        from littrans.context.char_history import get_log, get_log_rel, get_log_all_rels
    except ImportError:
        st.caption("char_history module chưa được cài.")
        return

    history = get_log(p, limit=30)
    if not history:
        st.caption("Chưa có lịch sử thay đổi nào.")
        return

    rel_options = ["Tất cả"] + list(p.get("relationships", {}).keys())
    sel_rel = st.selectbox("Lọc theo", rel_options,
                           key=f"hist_rel_{name}", label_visibility="collapsed")

    if sel_rel != "Tất cả":
        history = get_log_rel(p, sel_rel, limit=20)
        st.caption(f"{len(history)} commits liên quan đến {sel_rel}")
    else:
        st.caption(f"{len(p.get('_history', []))} commits · đang hiển thị {len(history)} gần nhất")

    trigger_badge_map = {
        "post_call"          : ("badge-info", "post_call"),
        "scout"              : ("badge-ok",   "scout"),
        "relationship_update": ("badge-warn", "rel"),
        "manual"             : ("badge-dim",  "manual"),
    }

    for commit in history:
        cid     = commit["commit"]
        trigger = commit.get("trigger", "")
        ts      = commit.get("timestamp", "")
        changes = commit.get("changes", {})
        badge_cls, badge_label = trigger_badge_map.get(trigger, ("badge-dim", trigger))

        with st.expander(f"{cid}  ·  {ts}", expanded=False):
            st.markdown(f'<span class="badge {badge_cls}">{badge_label}</span>',
                        unsafe_allow_html=True)
            if "__created__" in changes:
                st.caption("_(nhân vật được tạo lần đầu)_")
                continue
            for field, diff in changes.items():
                if not isinstance(diff, dict): continue
                if "added" in diff:
                    st.markdown(f"`{field}`")
                    for item in diff.get("added", []):
                        st.markdown(f'<span style="color:var(--color-text-success)">+ {item}</span>',
                                    unsafe_allow_html=True)
                    for item in diff.get("removed", []):
                        st.markdown(f'<span style="color:var(--color-text-danger);text-decoration:line-through">- {item}</span>',
                                    unsafe_allow_html=True)
                elif "old" in diff:
                    old_v = str(diff["old"]) if diff["old"] else "_(trống)_"
                    new_v = str(diff["new"]) if diff["new"] else "_(trống)_"
                    st.markdown(f"`{field}`")
                    col1, col2 = st.columns(2)
                    col1.markdown(f'<span style="color:var(--color-text-danger)">- {old_v}</span>',
                                  unsafe_allow_html=True)
                    col2.markdown(f'<span style="color:var(--color-text-success)">+ {new_v}</span>',
                                  unsafe_allow_html=True)

    if sel_rel == "Tất cả":
        try:
            from littrans.context.char_history import get_log_all_rels
            all_rel_h = get_log_all_rels(p)
            if all_rel_h:
                st.divider()
                st.caption("Relationship commits:")
                for target, commits in all_rel_h.items():
                    st.caption(f"  ↔ {target}: {len(commits)} commits")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# PAGE: TỪ ĐIỂN
# ══════════════════════════════════════════════════════════════════

def render_glossary() -> None:
    import pandas as pd
    glos = load_glossary_data()
    if not glos:
        st.info("Glossary chưa có dữ liệu. Chạy pipeline để tự động thêm thuật ngữ.")
        return

    staging_count = len(glos.get("staging", []))
    if staging_count:
        st.info(f"📖 Scout AI đề xuất **{staging_count}** thuật ngữ mới đang chờ trong Staging. "
                "Nhấn **🔄 Clean glossary** bên dưới để phân loại và xác nhận vào đúng category.")

    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    sel_cat = c1.selectbox("Category", ["Tất cả"] + list(glos.keys()),
                           label_visibility="collapsed", key="glos_cat")
    search = c2.text_input("🔍", placeholder="Tìm thuật ngữ…",
                           label_visibility="collapsed", key="glos_q")
    with c3:
        if not S.clean_running:
            if st.button("🔄 Clean glossary"):
                S.clean_logs = []
                S.clean_q    = queue.Queue()
                from littrans.ui.runner import run_background
                # [v5.4] Truyền novel_name
                run_background(S.clean_q, mode="clean_glossary", novel_name=S.current_novel)
                S.clean_running = True
                st.rerun()
        else:
            st.button("⏳ Đang phân loại…", disabled=True)
    with c4:
        if st.button("↺ Refresh"):
            load_glossary_data.clear()
            st.rerun()

    _cat_label = {
        "pathways": "pathway", "organizations": "org", "items": "item",
        "locations": "location", "general": "general", "staging": "⏳ staging",
    }
    rows = []
    for cat, entries in glos.items():
        if sel_cat != "Tất cả" and cat != sel_cat: continue
        for eng, vn in entries:
            if search and search.lower() not in eng.lower() and search.lower() not in vn.lower():
                continue
            rows.append({"Tiếng Anh": eng, "Tiếng Việt": vn, "Category": _cat_label.get(cat, cat)})

    if rows:
        st.caption(f"{len(rows)} thuật ngữ")
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True,
                     column_config={"Category": st.column_config.TextColumn(width="small")})
    else:
        st.info("Không tìm thấy thuật ngữ phù hợp.")

    if S.clean_running or S.clean_logs:
        if S.clean_running:
            done_flag = _poll("clean_q", "clean_logs")
            if done_flag:
                S.clean_running = False
                S.clean_logs.append("✅ Clean glossary hoàn tất.")
                load_glossary_data.clear()
                load_stats.clear()
        if S.clean_logs:
            st.markdown("**Log:**")
            _show_log(S.clean_logs)
        if S.clean_running:
            time.sleep(0.9)
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# PAGE: THỐNG KÊ
# ══════════════════════════════════════════════════════════════════

def render_stats() -> None:
    import pandas as pd
    s        = load_stats()
    chapters = load_chapters(S.current_novel)
    done  = sum(1 for c in chapters if c["done"])
    total = len(chapters)

    st.subheader("Thống kê pipeline")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Chương đã dịch", f"{done} / {total}",
              delta=f"{int(done/total*100)}%" if total else None)
    m2.metric("Nhân vật active",  s["chars"].get("active", 0))
    m3.metric("Nhân vật archive", s["chars"].get("archive", 0))
    em_count = s["chars"].get("emotional", 0)
    m4.metric("Có emotion state", em_count, delta_color="inverse")

    st.divider()
    glos        = s.get("glos", {})
    total_terms = sum(v for k, v in glos.items() if k != "staging")
    staging_terms = glos.get("staging", 0)
    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Thuật ngữ tổng",    total_terms)
    m6.metric("  Staging (chờ)",   staging_terms,
              delta="cần phân loại" if staging_terms else None, delta_color="inverse")
    m7.metric("Kỹ năng tổng",      s["skills"].get("total", 0))
    m8.metric("Name Lock entries", s["lock"].get("total_locked", 0))

    chart_data = {k: v for k, v in glos.items() if v and k != "staging"}
    if chart_data:
        st.divider()
        st.markdown("**Phân bổ Glossary theo category**")
        import pandas as pd
        df = pd.DataFrame.from_dict(chart_data, orient="index", columns=["Thuật ngữ"])
        st.bar_chart(df, color="#3B6D11")

    if total:
        st.divider()
        pct = done / total
        st.progress(pct)
        st.caption(f"{done}/{total} chương · {int(pct*100)}% hoàn thành")
        rows = [{"Chương": c["name"], "Trạng thái": "✅ Đã dịch" if c["done"] else "⬜ Chưa",
                 "Kích thước": c["size"]} for c in chapters]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════
# PAGE: CÀI ĐẶT
# ══════════════════════════════════════════════════════════════════

def render_settings() -> None:
    env = _load_env()

    def e(key, default=""): return env.get(key, default)
    def ei(key, default):
        try: return int(env.get(key, str(default)))
        except: return default
    def ef(key, default):
        try: return float(env.get(key, str(default)))
        except: return default
    def eb(key, default):
        v = env.get(key, "").strip().lower()
        return v in ("true", "1", "yes", "on") if v else default

    hcol1, hcol2, hcol3 = st.columns([4, 1, 1])
    hcol1.subheader("Cài đặt")
    save_clicked  = hcol2.button("💾 Lưu .env", type="primary")
    reset_clicked = hcol3.button("↺ Mặc định")

    if S.settings_saved:
        st.success("✅ Đã lưu vào `.env` — khởi động lại pipeline để áp dụng.")
        S.settings_saved = False

    if not _ENV_PATH.exists():
        st.warning(f"⚠️  Chưa có file `.env`. Điền thông tin và nhấn **Lưu .env** để tạo.")

    tabs = st.tabs([
        "🔑 API", "⚙️ Pipeline", "🔭 Scout AI",
        "📖 Glossary Suggest", "👤 Nhân vật",
        "💰 Token Budget", "🔀 Merge & Retry", "📁 Đường dẫn",
    ])
    updates: dict[str, str] = {}

    with tabs[0]:
        st.markdown("#### Gemini API Keys")
        k_primary = st.text_input("Primary key", value=e("GEMINI_API_KEY"), type="password")
        k_fb1     = st.text_input("Fallback key 1", value=e("FALLBACK_KEY_1"), type="password")
        k_fb2     = st.text_input("Fallback key 2", value=e("FALLBACK_KEY_2"), type="password")
        updates.update({"GEMINI_API_KEY": k_primary, "FALLBACK_KEY_1": k_fb1, "FALLBACK_KEY_2": k_fb2})
        st.divider()
        st.markdown("#### Model & Key Rotation")
        c1, c2 = st.columns(2)
        _models  = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-exp", "gemini-1.5-pro"]
        cur_model = e("GEMINI_MODEL", "gemini-2.5-flash")
        model_idx = _models.index(cur_model) if cur_model in _models else 0
        model  = c1.selectbox("Gemini model", _models, index=model_idx)
        rotate = c2.number_input("Key rotate threshold", 1, 10, ei("KEY_ROTATE_THRESHOLD", 3))
        updates["GEMINI_MODEL"] = model
        updates["KEY_ROTATE_THRESHOLD"] = str(rotate)
        st.divider()
        st.markdown("#### Translation Model (Dual-Model)")
        provider_opts = ["gemini", "anthropic"]
        cur_provider  = e("TRANSLATION_PROVIDER", "gemini")
        provider_idx  = provider_opts.index(cur_provider) if cur_provider in provider_opts else 0
        provider_sel  = st.selectbox("Translation provider", provider_opts, index=provider_idx)
        trans_model   = st.text_input("Translation model (để trống = mặc định)", value=e("TRANSLATION_MODEL", ""))
        anthropic_key = st.text_input("Anthropic API Key", value=e("ANTHROPIC_API_KEY"), type="password")
        updates.update({"TRANSLATION_PROVIDER": provider_sel, "TRANSLATION_MODEL": trans_model,
                        "ANTHROPIC_API_KEY": anthropic_key})

    with tabs[1]:
        st.info("Pipeline luôn dùng **3-call flow** (Pre → Trans → Post).", icon="ℹ️")
        c1, c2, c3 = st.columns(3)
        pre_s  = c1.slider("Pre-call sleep (s)",  0, 30, ei("PRE_CALL_SLEEP", 5))
        post_s = c2.slider("Post-call sleep (s)", 0, 30, ei("POST_CALL_SLEEP", 5))
        post_r = c3.number_input("Post max retries", 0, 5, ei("POST_CALL_MAX_RETRIES", 2))
        retry_q = st.toggle("Retry Trans-call khi Post báo lỗi", value=eb("TRANS_RETRY_ON_QUALITY", True))
        updates.update({"PRE_CALL_SLEEP": str(pre_s), "POST_CALL_SLEEP": str(post_s),
                        "POST_CALL_MAX_RETRIES": str(post_r),
                        "TRANS_RETRY_ON_QUALITY": "true" if retry_q else "false"})
        st.divider()
        st.markdown("#### Timing & Giới hạn")
        c1, c2, c3, c4 = st.columns(4)
        max_ret   = c1.number_input("Max retries", 1, 20, ei("MAX_RETRIES", 5))
        succ_s    = c2.slider("Success sleep (s)", 0, 120, ei("SUCCESS_SLEEP", 30), step=5)
        rl_s      = c3.slider("Rate limit sleep (s)", 10, 300, ei("RATE_LIMIT_SLEEP", 60), step=10)
        min_chars = c4.number_input("Min chars/chapter", 0, 5000, ei("MIN_CHARS_PER_CHAPTER", 500), step=100)
        updates.update({"MAX_RETRIES": str(max_ret), "SUCCESS_SLEEP": str(succ_s),
                        "RATE_LIMIT_SLEEP": str(rl_s), "MIN_CHARS_PER_CHAPTER": str(min_chars)})

    with tabs[2]:
        c1, c2, c3 = st.columns(3)
        scout_ev = c1.slider("Scout refresh every", 1, 20, ei("SCOUT_REFRESH_EVERY", 5))
        scout_lb = c2.slider("Scout lookback", 2, 30, ei("SCOUT_LOOKBACK", 10))
        arc_win  = c3.slider("Arc memory window", 1, 10, ei("ARC_MEMORY_WINDOW", 3))
        updates.update({"SCOUT_REFRESH_EVERY": str(scout_ev), "SCOUT_LOOKBACK": str(scout_lb),
                        "ARC_MEMORY_WINDOW": str(arc_win)})

    with tabs[3]:
        suggest_on = st.toggle("Bật Glossary Suggest", value=eb("SCOUT_SUGGEST_GLOSSARY", True))
        updates["SCOUT_SUGGEST_GLOSSARY"] = "true" if suggest_on else "false"
        c1, c2 = st.columns(2)
        min_conf  = c1.slider("Confidence tối thiểu", 0.0, 1.0, ef("SCOUT_SUGGEST_MIN_CONFIDENCE", 0.7), step=0.05, disabled=not suggest_on)
        max_terms = c2.number_input("Số thuật ngữ tối đa / lần Scout", 1, 50, ei("SCOUT_SUGGEST_MAX_TERMS", 20), disabled=not suggest_on)
        updates["SCOUT_SUGGEST_MIN_CONFIDENCE"] = str(round(min_conf, 2))
        updates["SCOUT_SUGGEST_MAX_TERMS"]      = str(max_terms)

    with tabs[4]:
        c1, c2 = st.columns(2)
        arch_a = c1.slider("Archive after chapters", 10, 200, ei("ARCHIVE_AFTER_CHAPTERS", 60), step=10)
        emo_r  = c2.slider("Emotion reset chapters", 1, 20, ei("EMOTION_RESET_CHAPTERS", 5))
        updates.update({"ARCHIVE_AFTER_CHAPTERS": str(arch_a), "EMOTION_RESET_CHAPTERS": str(emo_r)})

    with tabs[5]:
        budget = st.number_input("Budget limit (0 = tắt)", min_value=0, step=10000,
                                 value=ei("BUDGET_LIMIT", 150000))
        updates["BUDGET_LIMIT"] = str(budget)

    with tabs[6]:
        c1, c2, c3 = st.columns(3)
        imm = c1.toggle("Immediate merge", value=eb("IMMEDIATE_MERGE", True))
        ag  = c2.toggle("Auto merge glossary", value=eb("AUTO_MERGE_GLOSSARY", False))
        ac  = c3.toggle("Auto merge characters", value=eb("AUTO_MERGE_CHARACTERS", False))
        updates.update({"IMMEDIATE_MERGE": "true" if imm else "false",
                        "AUTO_MERGE_GLOSSARY": "true" if ag else "false",
                        "AUTO_MERGE_CHARACTERS": "true" if ac else "false"})
        rfp = st.number_input("Retry failed passes", 0, 10, ei("RETRY_FAILED_PASSES", 3))
        updates["RETRY_FAILED_PASSES"] = str(rfp)

    with tabs[7]:
        st.markdown("#### Thư mục làm việc")
        st.info("📚 Data của mỗi novel được lưu tự động trong `outputs/<TenNovel>/data/`. "
                "Chỉ cần đặt file chương vào `inputs/<TenNovel>/`.", icon="ℹ️")
        _path_defs = [
            ("INPUT_DIR",   "inputs",  "Thư mục gốc chứa các folder novel"),
            ("OUTPUT_DIR",  "outputs", "Thư mục bản dịch + data (tự tạo subfolders)"),
            ("PROMPTS_DIR", "prompts", "system_agent.md, character_profile.md"),
        ]
        for key, default, desc in _path_defs:
            val = st.text_input(f"`{key}`", value=e(key, default), help=desc)
            updates[key] = val

    if save_clicked:
        try:
            _save_env({k: v for k, v in updates.items() if v is not None})
            load_stats.clear()
            S.settings_saved = True
        except Exception as exc:
            st.error(f"❌ Lỗi khi lưu: {exc}")
        else:
            st.rerun()

    if reset_clicked:
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# SIDEBAR + MAIN
# ══════════════════════════════════════════════════════════════════

def _render_novel_selector() -> None:
    """[v5.4] Novel selector trong sidebar."""
    novels = _get_available_novels()

    if not novels:
        # Flat mode — không có subfolder
        st.sidebar.caption("📁 Flat mode (1 truyện)")
        st.sidebar.caption("Tạo subfolder trong `inputs/` để dùng multi-novel")
        # Đảm bảo novel rỗng trong flat mode
        if S.current_novel:
            S.current_novel = ""
            _apply_novel("")
        return

    # Có novels → hiện selectbox
    current = S.current_novel if S.current_novel in novels else novels[0]

    selected = st.sidebar.selectbox(
        "📚 Novel",
        novels,
        index=novels.index(current) if current in novels else 0,
        key="novel_selector_sb",
    )

    if selected != S.current_novel:
        S.current_novel = selected
        _apply_novel(selected)
        # Reset page state khi đổi novel
        S.sel_ch  = 0
        S.logs    = []
        S.rt_logs = []
        st.rerun()
    elif not S.current_novel:
        # Lần đầu load
        S.current_novel = selected
        _apply_novel(selected)


def main() -> None:
    with st.sidebar:
        st.markdown("## 📖 LiTTrans")
        st.caption("v5.4 — LitRPG / Tu Tiên Pipeline")
        st.divider()

        # ── Novel selector ──────────────────────────────────────
        _render_novel_selector()
        st.divider()

        # ── Navigation ──────────────────────────────────────────
        _pages = {
            "translate" : "📄  Dịch",
            "chapters"  : "🔍  Xem chương",
            "characters": "👤  Nhân vật",
            "glossary"  : "📚  Từ điển",
            "stats"     : "📊  Thống kê",
            "settings"  : "⚙️   Cài đặt",
            "bible"     : "📖  Bible",
            "epub"      : "📚  EPUB",
        }
        for key, label in _pages.items():
            t = "primary" if S.page == key else "secondary"
            if st.button(label, key=f"nav_{key}", use_container_width=True, type=t):
                S.page    = key
                S.show_rt = False
                st.rerun()

        st.divider()

        # ── Progress & badges ────────────────────────────────────
        try:
            chs  = load_chapters(S.current_novel)
            done = sum(1 for c in chs if c["done"])
            total= len(chs)
            if total:
                st.progress(done / total)
                st.caption(f"{done}/{total} chương")

            try:
                from littrans.context.glossary import glossary_stats
                glos_s    = glossary_stats()
                staging_n = glos_s.get("staging", 0)
                if staging_n:
                    st.markdown(
                        f'<span class="badge badge-warn">📖 {staging_n} thuật ngữ chờ phân loại</span>',
                        unsafe_allow_html=True,
                    )
            except Exception:
                pass
        except Exception:
            pass

        if S.running:
            st.warning("🔄 Pipeline đang chạy…")
        if S.rt_running:
            st.info("↺ Đang dịch lại…")
        if S.clean_running:
            st.info("🧹 Đang clean…")

        st.divider()
        st.caption(f"Root: `{_ROOT.name}`")
        env_ok = _ENV_PATH.exists()
        st.caption("✅ .env found" if env_ok else "⚠️  .env chưa có")

    # ── Đảm bảo settings luôn đồng bộ với current_novel ──────────
    # (cần thiết sau Streamlit rerun)
    if S.current_novel:
        try:
            from littrans.config.settings import settings, set_novel
            if settings.novel_name != S.current_novel:
                set_novel(S.current_novel)
        except Exception:
            pass

    _route = {
        "translate" : render_translate,
        "chapters"  : render_chapters,
        "characters": render_characters,
        "glossary"  : render_glossary,
        "stats"     : render_stats,
        "settings"  : render_settings,
        "bible"     : lambda: render_bible(S),
        "epub"      : lambda: render_epub(S),
    }
    _route.get(S.page, render_translate)()


main()