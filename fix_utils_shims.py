"""
fix_utils_shims.py — Chạy file này để replace utils duplicate files bằng redirect shim.
Dùng Python thay vì bash diff để tránh vấn đề CRLF trên Windows.

Chạy từ project root:
    python fix_utils_shims.py
"""
from pathlib import Path

SHIM_TEXT_NORMALIZER = '''\
"""
src/littrans/utils/text_normalizer.py — Redirect shim.

[v5.3 Refactor] File đã chuyển về core/text_normalizer.py.
Giữ lại để không break import cũ. Không sửa file này.
"""
from littrans.core.text_normalizer import (  # noqa: F401
    normalize,
)

__all__ = ["normalize"]
'''

SHIM_POST_PROCESSOR = '''\
"""
src/littrans/utils/post_processor.py — Redirect shim.

[v5.3 Refactor] File đã chuyển về core/post_processor.py.
Giữ lại để không break import cũ. Không sửa file này.
"""
from littrans.core.post_processor import (  # noqa: F401
    run,
    report,
)

__all__ = ["run", "report"]
'''


def normalize_content(text: str) -> str:
    """Strip CRLF → LF và trailing whitespace để so sánh đúng trên Windows."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def replace_with_shim(utils_path: Path, core_path: Path, shim_content: str) -> None:
    if not core_path.exists():
        print(f"  ⚠️  Không tìm thấy {core_path} — bỏ qua.")
        return

    if not utils_path.exists():
        print(f"  ⚠️  Không tìm thấy {utils_path} — bỏ qua.")
        return

    utils_text = utils_path.read_text(encoding="utf-8", errors="replace")
    core_text  = core_path.read_text(encoding="utf-8", errors="replace")

    utils_norm = normalize_content(utils_text)
    core_norm  = normalize_content(core_text)

    lines_utils = len(utils_norm.splitlines())
    lines_core  = len(core_norm.splitlines())

    if utils_norm == core_norm:
        match_status = "✅ nội dung giống nhau (sau normalize CRLF)"
    else:
        # Count how many lines differ
        u_lines = utils_norm.splitlines()
        c_lines = core_norm.splitlines()
        diff_lines = sum(1 for a, b in zip(u_lines, c_lines) if a != b)
        diff_lines += abs(len(u_lines) - len(c_lines))
        match_status = f"ℹ️  khác {diff_lines} dòng (có thể do refactor chưa sync)"

    print(f"  {match_status}")
    print(f"  utils: {lines_utils} lines → shim: {len(shim_content.splitlines())} lines")

    # Write shim với LF endings
    utils_path.write_text(shim_content, encoding="utf-8", newline="\n")
    print(f"  ✅ Replaced: {utils_path}")


def main() -> None:
    root = Path(".")

    # Verify đang ở project root
    if not (root / "src" / "littrans" / "ui" / "app.py").exists():
        print("❌ Không tìm thấy src/littrans/ui/app.py")
        print("   Hãy chạy script này từ project root.")
        raise SystemExit(1)

    print("\n── Fix 3: utils/text_normalizer.py → redirect shim ─────────")
    replace_with_shim(
        utils_path=root / "src" / "littrans" / "utils" / "text_normalizer.py",
        core_path =root / "src" / "littrans" / "core"  / "text_normalizer.py",
        shim_content=SHIM_TEXT_NORMALIZER,
    )

    print("\n── Fix 4: utils/post_processor.py → redirect shim ──────────")
    replace_with_shim(
        utils_path=root / "src" / "littrans" / "utils" / "post_processor.py",
        core_path =root / "src" / "littrans" / "core"  / "post_processor.py",
        shim_content=SHIM_POST_PROCESSOR,
    )

    print("\n── Verify imports ───────────────────────────────────────────")
    import subprocess, sys
    checks = [
        ("utils.text_normalizer", "from littrans.utils.text_normalizer import normalize; print('text_normalizer OK')"),
        ("utils.post_processor",  "from littrans.utils.post_processor import run, report; print('post_processor OK')"),
        ("core.text_normalizer",  "from littrans.core.text_normalizer import normalize; print('core normalize OK')"),
        ("core.post_processor",   "from littrans.core.post_processor import run; print('core post_processor OK')"),
    ]
    env_path = str(root / "src")
    for label, code in checks:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={**__import__("os").environ, "PYTHONPATH": env_path},
        )
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip()}")
        else:
            print(f"  ❌ {label}: {result.stderr.strip()[:120]}")

    print("\n✅ Xong.\n")


if __name__ == "__main__":
    main()