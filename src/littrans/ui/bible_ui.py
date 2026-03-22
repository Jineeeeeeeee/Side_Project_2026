"""
src/littrans/ui/bible_ui.py — Bible System UI components cho Streamlit.

6 sub-tabs:
  📊 Overview    — scan progress, stats, nút scan
  🗃️ Database   — search entities, filter by type
  🌍 WorldBuilding — cultivation system, rules
  📜 Main Lore  — chapter summaries, plot threads, revelations
  🔍 Consistency — health score, issues, run validate
  ⬇️ Export      — format selector, download

Tái dụng từ app.py:
  _poll()           — drain queue
  _show_log()       — display log
  run_background()  — background thread

[v1.0] Initial implementation — Bible System Sprint 6
"""
from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any


def _get_store():
    """Lazy-load BibleStore với settings hiện tại."""
    from littrans.config.settings import settings
    from littrans.bible.bible_store import BibleStore
    return BibleStore(settings.bible_dir)


def _bible_available() -> bool:
    try:
        from littrans.config.settings import settings
        return settings.bible_available
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# CACHED DATA LOADERS
# ═══════════════════════════════════════════════════════════════════

def _get_bible_stats(ttl: int = 5):
    """Load Bible stats với simple TTL."""
    import streamlit as st
    @st.cache_data(ttl=ttl)
    def _load():
        try:
            return _get_store().get_stats()
        except Exception:
            return {}
    return _load()


# ═══════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════════

def render_bible_tab(S: Any) -> None:
    """
    Entry point — render toàn bộ tab Bible.
    S = st.session_state (được pass vào để tránh circular import).
    """
    import streamlit as st

    st.subheader("📖 Bible System")

    # Session state keys cho Bible
    for key, default in [
        ("bible_scan_running", False),
        ("bible_scan_q",       None),
        ("bible_scan_logs",    []),
        ("bible_crossref_running", False),
        ("bible_crossref_q",   None),
        ("bible_crossref_logs",[]),
        ("bible_export_done",  False),
    ]:
        if key not in S:
            S[key] = default

    if not _bible_available():
        _render_bible_empty(S)
        return

    tabs = st.tabs([
        "📊 Overview",
        "🗃️ Database",
        "🌍 WorldBuilding",
        "📜 Main Lore",
        "🔍 Consistency",
        "⬇️ Export",
    ])

    with tabs[0]: _render_overview(S)
    with tabs[1]: _render_database(S)
    with tabs[2]: _render_worldbuilding(S)
    with tabs[3]: _render_main_lore(S)
    with tabs[4]: _render_consistency(S)
    with tabs[5]: _render_export(S)


# ═══════════════════════════════════════════════════════════════════
# EMPTY STATE
# ═══════════════════════════════════════════════════════════════════

def _render_bible_empty(S: Any) -> None:
    import streamlit as st

    st.info(
        "📖 **Bible System chưa có data.**\n\n"
        "Bible scan đọc toàn bộ chương trong `inputs/` và xây dựng knowledge base "
        "gồm 3 tầng: Database (nhân vật, kỹ năng, địa danh...), "
        "WorldBuilding (hệ thống tu luyện, quy luật thế giới), "
        "và Main Lore (tóm tắt chương, plot threads, revelations).\n\n"
        "Bật **BIBLE_MODE=true** trong ⚙️ Cài đặt và chạy scan để bắt đầu."
    )

    st.markdown("### 🚀 Bắt đầu Bible Scan")

    col1, col2, col3 = st.columns(3)
    depth = col1.selectbox(
        "Depth", ["quick", "standard", "deep"],
        index=1, key="bible_init_depth",
        help="quick: nhanh · standard: đầy đủ · deep: kỹ nhất",
    )

    _render_scan_controls(S, depth, force=False, label="▶ Bắt đầu Scan")


# ═══════════════════════════════════════════════════════════════════
# OVERVIEW
# ═══════════════════════════════════════════════════════════════════

def _render_overview(S: Any) -> None:
    import streamlit as st

    try:
        store    = _get_store()
        stats    = store.get_stats()
        progress = store.get_scan_progress()
        meta     = stats.get("meta", {})
        by_type  = stats.get("by_type", {})
    except Exception as e:
        st.error(f"Lỗi load Bible stats: {e}")
        return

    # Progress
    total   = max(1, progress.get("total", 1))
    scanned = progress.get("scanned", 0)
    pct     = scanned / total
    st.progress(pct, text=f"Scanned: {scanned}/{total} ({int(pct*100)}%)")

    # Metrics row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Nhân vật",  by_type.get("character", 0))
    m2.metric("Kỹ năng",   by_type.get("skill", 0))
    m3.metric("Địa danh",  by_type.get("location", 0))
    m4.metric("Lore chaps",stats.get("lore_chapters", 0))

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Vật phẩm",  by_type.get("item", 0))
    m6.metric("Tổ chức",   by_type.get("faction", 0))
    m7.metric("Khái niệm", by_type.get("concept", 0))
    staging = stats.get("staging", 0)
    m8.metric("Staging",   staging,
              delta="cần consolidate" if staging else None,
              delta_color="inverse")

    st.divider()

    # Scan controls
    st.markdown("### Scan")
    col1, col2, col3, col4 = st.columns(4)
    depth    = col1.selectbox("Depth", ["quick", "standard", "deep"], index=1, key="ov_depth")
    new_only = col2.checkbox("Chỉ chương mới", value=True, key="ov_new_only")
    force    = col3.checkbox("Force re-scan", value=False, key="ov_force",
                              disabled=new_only)

    _render_scan_controls(S, depth, force=force and not new_only,
                          new_only=new_only, label="▶ Scan",
                          col=col4)

    # Pending staging
    if staging > 0:
        st.warning(f"⚠️  {staging} staging files chờ consolidation.")
        if st.button("🔄 Consolidate ngay", key="ov_consolidate"):
            _run_consolidation()

    # Scan log
    if S.bible_scan_running or S.bible_scan_logs:
        _handle_scan_log(S)


def _render_scan_controls(S, depth, force=False, new_only=True,
                           label="▶ Scan", col=None) -> None:
    import streamlit as st
    container = col or st

    if not S.bible_scan_running:
        if container.button(label, type="primary", key=f"scan_btn_{label[:4]}"):
            S.bible_scan_logs = []
            S.bible_scan_q    = queue.Queue()
            _launch_bible_scan(S.bible_scan_q, depth=depth,
                               force=force, new_only=new_only)
            S.bible_scan_running = True
            st.rerun()
    else:
        container.button("⏳ Đang scan…", disabled=True, key="scan_running")


def _launch_bible_scan(log_queue: queue.Queue, depth: str,
                        force: bool, new_only: bool) -> None:
    """Chạy BibleScanner trong background thread."""
    import threading, sys, traceback

    def _worker():
        import io
        old_out = sys.stdout

        class _Cap(io.TextIOBase):
            def write(self, t):
                if t.strip():
                    log_queue.put(t.rstrip())
                return len(t)
            def flush(self): pass

        sys.stdout = _Cap()
        try:
            from littrans.config.settings import settings
            object.__setattr__(settings, "bible_scan_depth", depth)
            from littrans.bible.bible_scanner import BibleScanner
            from littrans.bible.bible_store import BibleStore
            store   = BibleStore(settings.bible_dir)
            scanner = BibleScanner(store)
            if new_only:
                scanner.scan_new_only()
            else:
                scanner.scan_all(force=force)
        except Exception as e:
            log_queue.put(f"❌ Lỗi: {e}")
            for line in traceback.format_exc().splitlines()[-5:]:
                if line.strip():
                    log_queue.put(f"   {line}")
        finally:
            sys.stdout = old_out
            log_queue.put("__DONE__")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _handle_scan_log(S: Any) -> None:
    import streamlit as st
    if S.bible_scan_running:
        q: queue.Queue = S.bible_scan_q
        done = False
        while True:
            try:
                msg = q.get_nowait()
                if msg == "__DONE__":
                    done = True
                else:
                    S.bible_scan_logs.append(msg)
            except queue.Empty:
                break
        if done:
            S.bible_scan_running = False
            S.bible_scan_logs.append("─" * 56)
            S.bible_scan_logs.append("✅ Scan hoàn tất.")
            import streamlit as st
            st.cache_data.clear()

    if S.bible_scan_logs:
        st.markdown("**Scan log:**")
        st.code("\n".join(S.bible_scan_logs[-200:]), language=None)

    if S.bible_scan_running:
        time.sleep(1.0)
        st.rerun()


def _run_consolidation() -> None:
    import streamlit as st
    try:
        from littrans.bible.bible_store import BibleStore
        from littrans.bible.bible_consolidator import BibleConsolidator
        from littrans.config.settings import settings
        store   = BibleStore(settings.bible_dir)
        staging = store.load_all_staging()
        result  = BibleConsolidator(store).run(staging)
        store.clear_staging([s.source_chapter for s in staging])
        st.success(
            f"✅ Consolidated: +{result.chars_added} nhân vật · "
            f"+{result.entities_added} entities · "
            f"+{result.lore_chapters} lore entries"
        )
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Consolidation lỗi: {e}")


# ═══════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════

def _render_database(S: Any) -> None:
    import streamlit as st
    import pandas as pd

    try:
        store = _get_store()
    except Exception as e:
        st.error(f"Load lỗi: {e}"); return

    # Toolbar
    c1, c2, c3 = st.columns([3, 2, 1])
    search = c1.text_input("🔍 Tìm entity", placeholder="Tên nhân vật, địa danh...",
                            label_visibility="collapsed", key="db_search")
    etype  = c2.selectbox(
        "Loại", ["Tất cả", "character", "skill", "location", "item", "faction", "concept"],
        label_visibility="collapsed", key="db_type",
    )
    if c3.button("↺", key="db_refresh"):
        st.cache_data.clear(); st.rerun()

    # Load entities
    all_entities: list[dict] = []
    types_to_load = (
        ["character", "skill", "location", "item", "faction", "concept"]
        if etype == "Tất cả" else [etype]
    )
    for t in types_to_load:
        for e in store.get_all_entities(t):
            all_entities.append(e)

    # Filter by search
    if search:
        sl = search.lower()
        all_entities = [
            e for e in all_entities
            if sl in (e.get("canonical_name") or "").lower()
            or sl in (e.get("en_name") or "").lower()
            or sl in (e.get("description") or "").lower()
        ]

    st.caption(f"{len(all_entities)} entities")

    if not all_entities:
        st.info("Không tìm thấy entity nào.")
        return

    # Show as cards (3 per row)
    cols = st.columns(3)
    for i, e in enumerate(all_entities[:60]):
        with cols[i % 3]:
            _entity_card(e)


def _entity_card(e: dict) -> None:
    import streamlit as st

    etype  = e.get("type", "?")
    cname  = e.get("canonical_name", e.get("en_name", "?"))
    ename  = e.get("en_name", "")
    eid    = e.get("id", "?")
    desc   = (e.get("description") or e.get("personality_summary") or "")[:80]

    TYPE_COLORS = {
        "character": ("#E1F5EE", "#085041"),
        "skill"    : ("#FAEEDA", "#633806"),
        "location" : ("#EEEDFE", "#3C3489"),
        "item"     : ("#E6F1FB", "#0C447C"),
        "faction"  : ("#FCEBEB", "#791F1F"),
        "concept"  : ("#EAF3DE", "#3B6D11"),
    }
    bg, fg = TYPE_COLORS.get(etype, ("#F1EFE8", "#444441"))

    with st.container(border=True):
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="background:{bg};color:{fg};padding:2px 8px;'
            f'border-radius:99px;font-size:11px;font-weight:600">{etype}</span>'
            f'<b>{cname}</b></div>',
            unsafe_allow_html=True,
        )
        if ename and ename != cname:
            st.caption(f"EN: {ename}")
        if desc:
            st.caption(desc)

        # Type-specific info
        if etype == "character":
            realm = (e.get("cultivation") or {}).get("realm", "")
            st.caption(
                f"Role: {e.get('role','?')} · "
                + (f"Cảnh giới: {realm} · " if realm else "")
                + f"Status: {e.get('status','?')}"
            )
        elif etype == "skill":
            st.caption(f"Type: {e.get('skill_type','?')}")
        elif etype == "location":
            st.caption(f"Type: {e.get('location_type','?')}")

        st.caption(f"ID: {eid}")


# ═══════════════════════════════════════════════════════════════════
# WORLDBUILDING
# ═══════════════════════════════════════════════════════════════════

def _render_worldbuilding(S: Any) -> None:
    import streamlit as st

    try:
        store = _get_store()
        wb    = store.get_worldbuilding()
    except Exception as e:
        st.error(f"Load lỗi: {e}"); return

    # Cultivation Systems
    if wb.cultivation_systems:
        st.markdown("### ⬆️ Cultivation Systems")
        for cs in wb.cultivation_systems:
            with st.expander(f"{cs.name} — {cs.pathway_type}", expanded=True):
                if cs.description:
                    st.write(cs.description)
                if cs.realms:
                    import pandas as pd
                    rows = [
                        {"Order": r.order, "VN": r.name_vn, "EN": r.name_en,
                         "Sub-levels": len(r.sub_levels)}
                        for r in cs.realms
                    ]
                    st.dataframe(pd.DataFrame(rows), hide_index=True,
                                 use_container_width=True)
    else:
        st.info("Chưa có cultivation system nào được scan.")

    # Rules
    st.markdown("### 📋 Confirmed Rules")
    if wb.confirmed_rules:
        for rule in wb.confirmed_rules:
            confidence_color = (
                "🟢" if rule.confidence >= 0.9 else
                "🟡" if rule.confidence >= 0.7 else "🔴"
            )
            st.markdown(
                f"{confidence_color} `[{rule.source_chapter}]` "
                f"**[{rule.category}]** {rule.description}"
            )
    else:
        st.info("Chưa có rules nào được confirm.")

    # History / Economy / Cosmology notes
    for title, notes in [
        ("📜 History", wb.history_notes),
        ("💰 Economy", wb.economy_notes),
        ("🌌 Cosmology", wb.cosmology_notes),
    ]:
        if notes:
            st.markdown(f"### {title}")
            for note in notes[:10]:
                st.markdown(f"- {note}")


# ═══════════════════════════════════════════════════════════════════
# MAIN LORE
# ═══════════════════════════════════════════════════════════════════

def _render_main_lore(S: Any) -> None:
    import streamlit as st

    try:
        store = _get_store()
        lore  = store._load_main_lore()
    except Exception as e:
        st.error(f"Load lỗi: {e}"); return

    lore_tabs = st.tabs(["📖 Summaries", "🧵 Plot Threads", "💡 Revelations"])

    # Summaries
    with lore_tabs[0]:
        summaries = lore.chapter_summaries
        st.caption(f"{len(summaries)} chapters với summary")
        search = st.text_input("🔍", placeholder="Tìm trong summaries...",
                               label_visibility="collapsed", key="lore_search")
        if search:
            summaries = [
                s for s in summaries
                if search.lower() in s.summary.lower()
                or search.lower() in s.chapter.lower()
            ]

        for s in reversed(summaries[-30:]):   # 30 gần nhất, mới nhất trước
            tone_color = {
                "action"    : "🔴",
                "drama"     : "💜",
                "mystery"   : "🔵",
                "comedy"    : "🟡",
                "exposition": "⚪",
                "transition": "⚫",
            }.get(s.tone, "⚪")
            with st.expander(f"{tone_color} {s.chapter} [{s.tone}]"):
                st.write(s.summary)
                if s.key_events:
                    st.markdown("**Key events:**")
                    for ev in s.key_events:
                        st.markdown(f"  - {ev}")

    # Plot Threads
    with lore_tabs[1]:
        open_t   = lore.plot_threads and [t for t in lore.plot_threads if t.status == "open"]
        closed_t = lore.plot_threads and [t for t in lore.plot_threads if t.status == "closed"]

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"#### 🟢 Đang mở ({len(open_t or [])})")
            for t in (open_t or []):
                with st.container(border=True):
                    st.markdown(f"**{t.name}**")
                    st.caption(f"Từ: {t.opened_chapter}")
                    if t.summary:
                        st.write(t.summary[:150])
        with col2:
            st.markdown(f"#### ✅ Đã đóng ({len(closed_t or [])})")
            for t in (closed_t or []):
                with st.container(border=True):
                    st.markdown(f"**{t.name}**")
                    st.caption(f"{t.opened_chapter} → {t.closed_chapter}")
                    if t.resolution:
                        st.write(t.resolution[:150])

    # Revelations
    with lore_tabs[2]:
        revs = lore.revelations
        st.caption(f"{len(revs)} revelations")
        show_spoiler = st.checkbox("Hiện spoiler", value=False, key="rev_spoiler")

        for r in revs:
            with st.expander(f"💡 {r.title} [{r.chapter}]"):
                if show_spoiler:
                    st.write(r.description)
                    if r.foreshadowed_in:
                        st.caption(f"Foreshadowed in: {', '.join(r.foreshadowed_in)}")
                else:
                    st.info("🔒 Spoiler ẩn — bật 'Hiện spoiler' để xem.")


# ═══════════════════════════════════════════════════════════════════
# CONSISTENCY
# ═══════════════════════════════════════════════════════════════════

def _render_consistency(S: Any) -> None:
    import streamlit as st

    col1, col2 = st.columns([2, 1])
    col1.markdown("### 🔍 Bible Consistency Check")

    run_btn = col2.button("▶ Chạy Validate", type="primary", key="crossref_run",
                           disabled=S.bible_crossref_running)

    if run_btn:
        S.bible_crossref_logs = []
        S.bible_crossref_q    = queue.Queue()
        _launch_crossref(S.bible_crossref_q)
        S.bible_crossref_running = True
        st.rerun()

    if S.bible_crossref_running or S.bible_crossref_logs:
        _handle_crossref_log(S)
        return

    # Hiển thị cross_ref_last_run từ meta
    try:
        store = _get_store()
        meta  = store.load_meta()
        if meta.cross_ref_last_run:
            st.caption(f"Lần chạy cuối: {meta.cross_ref_last_run}")
        else:
            st.info("Chưa chạy cross-reference. Nhấn **▶ Chạy Validate** để kiểm tra.")
    except Exception:
        pass


def _launch_crossref(log_queue: queue.Queue) -> None:
    import threading, sys, traceback

    def _worker():
        import io
        old_out = sys.stdout

        class _Cap(io.TextIOBase):
            def write(self, t):
                if t.strip(): log_queue.put(t.rstrip())
                return len(t)
            def flush(self): pass

        sys.stdout = _Cap()
        try:
            from littrans.bible.cross_reference import CrossReferenceEngine
            from littrans.bible.bible_exporter import BibleExporter
            store   = _get_store()
            report  = CrossReferenceEngine(store).run()
            log_queue.put(f"📊 Health: {report.health_score:.0%} · {report.total_issues} issues")
            log_queue.put(f"   Errors: {len(report.errors)} · Warnings: {len(report.warnings)}")
            for issue in report.errors[:3]:
                log_queue.put(f"   🔴 [{issue.issue_type}] {issue.description}")
            for issue in report.warnings[:3]:
                log_queue.put(f"   🟡 [{issue.issue_type}] {issue.description}")
            # Save report
            from pathlib import Path
            out = Path("Reports") / "bible_consistency.md"
            BibleExporter(store).export_consistency_report(out, report)
            log_queue.put(f"📄 Báo cáo: {out}")
        except Exception as e:
            log_queue.put(f"❌ Lỗi: {e}")
            for line in traceback.format_exc().splitlines()[-5:]:
                if line.strip(): log_queue.put(f"   {line}")
        finally:
            sys.stdout = old_out
            log_queue.put("__DONE__")

    threading.Thread(target=_worker, daemon=True).start()


def _handle_crossref_log(S: Any) -> None:
    import streamlit as st
    if S.bible_crossref_running:
        q: queue.Queue = S.bible_crossref_q
        done = False
        while True:
            try:
                msg = q.get_nowait()
                if msg == "__DONE__":
                    done = True
                else:
                    S.bible_crossref_logs.append(msg)
            except queue.Empty:
                break
        if done:
            S.bible_crossref_running = False
            S.bible_crossref_logs.append("✅ Cross-reference hoàn tất.")

    if S.bible_crossref_logs:
        st.code("\n".join(S.bible_crossref_logs), language=None)

    if S.bible_crossref_running:
        time.sleep(1.0)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════

def _render_export(S: Any) -> None:
    import streamlit as st

    st.markdown("### ⬇️ Export Bible")

    fmt   = st.selectbox(
        "Định dạng",
        ["markdown", "json", "timeline", "characters", "consistency"],
        key="exp_fmt",
    )
    scope = st.selectbox(
        "Phạm vi (chỉ cho markdown)",
        ["full", "characters", "worldbuilding", "lore"],
        key="exp_scope",
        disabled=(fmt != "markdown"),
    )

    if st.button("🔄 Tạo export", type="primary", key="exp_run"):
        try:
            from littrans.bible.bible_exporter import BibleExporter
            from pathlib import Path
            out_dir = Path("Reports")
            store   = _get_store()
            exp     = BibleExporter(store)
            fname_map = {
                "markdown"   : "bible_report.md",
                "json"       : "bible_full.json",
                "timeline"   : "bible_timeline.md",
                "characters" : "bible_characters.md",
                "consistency": "bible_consistency.md",
            }
            out = out_dir / fname_map[fmt]

            if fmt == "markdown":
                exp.export_markdown(out, scope)
            elif fmt == "json":
                exp.export_json(out)
            elif fmt == "timeline":
                exp.export_timeline(out)
            elif fmt == "characters":
                exp.export_characters_sheet(out)
            elif fmt == "consistency":
                from littrans.bible.cross_reference import CrossReferenceEngine
                report = CrossReferenceEngine(store).run()
                exp.export_consistency_report(out, report)

            S.bible_export_done = True

            # Download button
            if out.exists():
                content = out.read_text(encoding="utf-8")
                st.download_button(
                    label=f"⬇️ Tải {out.name}",
                    data=content.encode("utf-8"),
                    file_name=out.name,
                    mime="text/plain",
                    key="exp_download",
                )
                st.success(f"✅ Đã tạo: {out}")

        except Exception as e:
            st.error(f"❌ Export lỗi: {e}")