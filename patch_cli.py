"""
patch_cli.py — Tự động mount Bible CLI vào cli.py.
Chạy từ thư mục gốc: python patch_cli.py
"""
from pathlib import Path

TARGET = Path("src/littrans/cli.py")
if not TARGET.exists():
    print(f"❌ Không tìm thấy {TARGET}")
    exit(1)

content = TARGET.read_text(encoding="utf-8")

if "bible_app" in content:
    print("✅ cli.py đã có Bible commands — bỏ qua.")
    exit(0)

# 1. Import bible_app
IMPORT_INJECT = """
# Bible CLI group
try:
    from littrans.bible.bible_cli import bible_app
    app.add_typer(bible_app, name="bible")
except ImportError:
    pass  # Bible package chưa có — bỏ qua
"""
# Thêm sau dòng app.add_typer(clean_app, ...)
ANCHOR = 'app.add_typer(clean_app, name="clean")'
content = content.replace(ANCHOR, ANCHOR + IMPORT_INJECT)

TARGET.write_text(content, encoding="utf-8")
print("✅ cli.py đã được patch!")
print("   Thử: littrans bible --help")