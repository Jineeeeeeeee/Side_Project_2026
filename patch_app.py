"""
patch_app.py — Tự động thêm tab Bible vào app.py.
Chạy từ thư mục gốc: python patch_app.py
"""
from pathlib import Path

TARGET = Path("src/littrans/ui/app.py")
if not TARGET.exists():
    print(f"❌ Không tìm thấy {TARGET}")
    exit(1)

content = TARGET.read_text(encoding="utf-8")

if "bible" in content and "render_bible" in content:
    print("✅ app.py đã có tab Bible — bỏ qua.")
    exit(0)

# 1. Thêm "bible" vào _pages dict
OLD_PAGES = '"settings"  : "⚙️   Cài đặt",'
NEW_PAGES = '"settings"  : "⚙️   Cài đặt",\n        "bible"     : "📖  Bible",'
content = content.replace(OLD_PAGES, NEW_PAGES)

# 2. Thêm session state defaults cho Bible
OLD_DEFAULTS = '"settings_saved": False,'
NEW_DEFAULTS = '"settings_saved": False,\n    # Bible System\n    "bible_scan_running"    : False,\n    "bible_scan_q"          : None,\n    "bible_scan_logs"       : [],\n    "bible_crossref_running": False,\n    "bible_crossref_q"      : None,\n    "bible_crossref_logs"   : [],\n    "bible_export_done"     : False,'
content = content.replace(OLD_DEFAULTS, NEW_DEFAULTS)

# 3. Thêm render_bible function trước main()
INJECT_BEFORE_MAIN = '\n# ══════════════════════════════════════════════════════════════\n# PAGE: DỊCH\n'
BIBLE_RENDER = '''
# ══════════════════════════════════════════════════════════════
# PAGE: BIBLE
# ══════════════════════════════════════════════════════════════
def render_bible() -> None:
    try:
        from littrans.ui.bible_ui import render_bible_tab
        render_bible_tab(S)
    except ImportError:
        import streamlit as st
        st.warning("⚠️  Bible System chưa được cài đặt.")
    except Exception as e:
        import streamlit as st
        st.error(f"Bible UI lỗi: {e}")

'''
content = content.replace(INJECT_BEFORE_MAIN, BIBLE_RENDER + INJECT_BEFORE_MAIN)

# 4. Thêm route cho "bible"
OLD_ROUTE = '"settings"  : render_settings,'
NEW_ROUTE = '"settings"  : render_settings,\n        "bible"     : render_bible,'
content = content.replace(OLD_ROUTE, NEW_ROUTE)

TARGET.write_text(content, encoding="utf-8")
print("✅ app.py đã được patch — tab 📖 Bible đã được thêm!")
print("   Khởi động lại Web UI để xem thay đổi.")