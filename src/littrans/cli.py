"""
src/littrans/cli.py — Toàn bộ CLI sub-commands (Typer).

Commands:
    translate                  — Dịch tất cả chương chưa dịch
    retranslate [KEYWORD]      — Dịch lại 1 chương cụ thể
    clean glossary             — Phân loại & merge thuật ngữ
    clean characters           — Quản lý character profile
    fix-names                  — Sửa tên vi phạm Name Lock
    stats                      — Thống kê nhanh

[v4.5] Dual-Model: thêm --provider / --model cho translate và retranslate.
"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from littrans.config.settings import settings

app       = typer.Typer(name="littrans", help="LitRPG / Tu Tiên Translation Pipeline v4.5", add_completion=False)
console   = Console()
clean_app = typer.Typer(help="Công cụ làm sạch & quản lý data")
app.add_typer(clean_app, name="clean")
# Bible CLI group
try:
    from littrans.bible.bible_cli import bible_app
    app.add_typer(bible_app, name="bible")
except ImportError:
    pass  # Bible package chưa có — bỏ qua



# ═══════════════════════════════════════════════════════════════════
# TRANSLATE — dịch tất cả chương chưa dịch
# ═══════════════════════════════════════════════════════════════════

@app.command()
def translate(
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p",
        help="Override TRANSLATION_PROVIDER: gemini | anthropic",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Override TRANSLATION_MODEL, ví dụ: claude-sonnet-4-6",
    ),
):
    """Dịch tất cả chương chưa có bản dịch trong inputs/."""
    _apply_model_override(provider, model)
    from littrans.engine.pipeline import Pipeline
    Pipeline().run()


# ═══════════════════════════════════════════════════════════════════
# RETRANSLATE — dịch lại 1 chương
# ═══════════════════════════════════════════════════════════════════

@app.command()
def retranslate(
    keyword: Optional[str] = typer.Argument(None, help="Số thứ tự hoặc một phần tên file"),
    list_chapters: bool    = typer.Option(False, "--list", "-l", help="Liệt kê tất cả chương"),
    update_data:   bool    = typer.Option(False, "--update-data", help="Cập nhật Glossary/Characters/Skills sau dịch"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p",
        help="Override TRANSLATION_PROVIDER: gemini | anthropic",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Override TRANSLATION_MODEL, ví dụ: claude-opus-4-6",
    ),
):
    """Dịch lại một chương cụ thể (ghi đè bản dịch cũ)."""
    _apply_model_override(provider, model)

    from littrans.engine.pipeline import Pipeline
    pipeline  = Pipeline()
    all_files = pipeline.sorted_inputs()

    if not all_files:
        console.print("[red]❌ Không có file nào trong inputs/[/red]")
        raise typer.Exit(1)

    if list_chapters:
        _print_chapter_list(all_files)
        return

    target = _resolve_target(keyword, all_files)
    if not target:
        raise typer.Exit(1)

    _confirm_retranslate(target, update_data)
    if not typer.confirm("Xác nhận dịch lại?", default=False):
        console.print("Huỷ.")
        return

    pipeline.retranslate(target, update_data=update_data)


# ═══════════════════════════════════════════════════════════════════
# CLEAN GLOSSARY
# ═══════════════════════════════════════════════════════════════════

@clean_app.command("glossary")
def clean_glossary_cmd():
    """Phân loại & merge thuật ngữ trong Staging vào đúng Glossary file."""
    from littrans.tools.clean_glossary import clean_glossary
    clean_glossary()


# ═══════════════════════════════════════════════════════════════════
# CLEAN CHARACTERS
# ═══════════════════════════════════════════════════════════════════

class CharAction(str, Enum):
    review   = "review"
    merge    = "merge"
    fix      = "fix"
    export   = "export"
    validate = "validate"
    archive  = "archive"


@clean_app.command("characters")
def clean_characters_cmd(
    action: CharAction = typer.Option(CharAction.review, "--action", "-a", help="Hành động"),
):
    """Quản lý Character Profile (review / merge / fix / export / validate / archive)."""
    from littrans.tools.clean_characters import run_action
    run_action(action.value)


# ═══════════════════════════════════════════════════════════════════
# FIX-NAMES
# ═══════════════════════════════════════════════════════════════════

@app.command("fix-names")
def fix_names_cmd(
    list_violations: bool = typer.Option(False, "--list",        help="Liệt kê vi phạm"),
    dry_run:         bool = typer.Option(False, "--dry-run",      help="Xem trước, không ghi file"),
    all_chapters:    bool = typer.Option(False, "--all-chapters", help="Sửa toàn bộ chương"),
    clear:           bool = typer.Option(False, "--clear",        help="Xóa name_fixes.json"),
):
    """Sửa tên vi phạm Name Lock trong các bản dịch đã có."""
    from littrans.tools.fix_names import cmd_list, cmd_fix, load_fixes
    from littrans.utils.io_utils import load_json

    fixes_path = settings.data_dir / "name_fixes.json"

    if clear:
        if fixes_path.exists():
            fixes_path.unlink()
            console.print(f"[green]🗑️  Đã xóa {fixes_path}[/green]")
        else:
            console.print(f"[yellow]⚠️  {fixes_path} không tồn tại[/yellow]")
        return

    data = load_fixes(fixes_path)
    if list_violations:
        cmd_list(data)
        return
    cmd_fix(data, fixes_path, all_chapters=all_chapters, dry_run=dry_run)


# ═══════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════

@app.command()
def stats():
    """Thống kê nhanh: nhân vật, glossary, kỹ năng, name lock."""
    from littrans.managers.characters import character_stats
    from littrans.managers.glossary   import glossary_stats
    from littrans.managers.skills     import skills_stats
    from littrans.managers.name_lock  import lock_stats
    from littrans.llm.client          import key_pool, translation_model_info

    c  = character_stats()
    g  = glossary_stats()
    sk = skills_stats()
    nl = lock_stats()
    kp = key_pool.stats()

    table = Table(title="LiTTrans Pipeline Stats", show_header=True)
    table.add_column("Mục", style="cyan")
    table.add_column("Giá trị", style="green")

    table.add_row("Trans-call model",   translation_model_info())
    table.add_row("Scout/Pre/Post",     f"{settings.gemini_model} (gemini)")
    table.add_section()
    table.add_row("Nhân vật Active",    str(c["active"]))
    table.add_row("Nhân vật Archive",   str(c["archive"]))
    table.add_row("Nhân vật Staging",   str(c["staging"]))
    if c.get("emotional"):
        table.add_row("  Có emotion state", str(c["emotional"]))
    table.add_section()
    for cat, cnt in g.items():
        if cnt:
            table.add_row(f"Glossary [{cat}]", str(cnt))
    table.add_section()
    table.add_row("Kỹ năng tổng",      str(sk["total"]))
    table.add_row("  Tiến hóa",        str(sk["evolution"]))
    table.add_row("Name Lock",         str(nl["total_locked"]))
    table.add_section()
    table.add_row("API Keys (Gemini)", f"{kp['total_keys']} key(s), active #{kp['active_idx']+1}")

    console.print(table)


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _apply_model_override(provider: Optional[str], model: Optional[str]) -> None:
    """
    Override settings.translation_provider / translation_model tại runtime.
    Dùng khi user truyền --provider / --model qua CLI — không cần sửa .env.
    """
    if provider:
        provider = provider.strip().lower()
        if provider not in ("gemini", "anthropic"):
            console.print(
                f"[red]❌ --provider phải là 'gemini' hoặc 'anthropic', "
                f"nhận được: '{provider}'[/red]"
            )
            raise typer.Exit(1)
        object.__setattr__(settings, "translation_provider", provider)
        console.print(f"[green]⚙️  Provider override: {provider}[/green]")

    if model:
        model = model.strip()
        object.__setattr__(settings, "translation_model", model)
        console.print(f"[green]⚙️  Model override: {model}[/green]")

    # Validate sớm: anthropic provider cần API key
    if settings.translation_provider == "anthropic" and not settings.anthropic_api_key:
        console.print(
            "[red]❌ Cần ANTHROPIC_API_KEY trong .env khi dùng --provider anthropic[/red]"
        )
        raise typer.Exit(1)


def _print_chapter_list(all_files: list[str]) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=5)
    table.add_column("Trạng thái", width=12)
    table.add_column("Tên file")

    for i, fn in enumerate(all_files, 1):
        base, _ = os.path.splitext(fn)
        translated = (settings.output_dir / f"{base}_VN.txt").exists()
        status = "[green]✅ Đã dịch[/green]" if translated else "[dim]⬜ Chưa dịch[/dim]"
        table.add_row(str(i), status, fn)
    console.print(table)


def _resolve_target(keyword: Optional[str], all_files: list[str]) -> Optional[str]:
    if not keyword:
        _print_chapter_list(all_files)
        choice = typer.prompt("Nhập số thứ tự hoặc một phần tên file")
        return _resolve_target(choice, all_files)

    if keyword.isdigit():
        idx = int(keyword) - 1
        if 0 <= idx < len(all_files):
            return all_files[idx]
        console.print(f"[red]❌ Số thứ tự {keyword} không hợp lệ[/red]")
        return None

    found = [f for f in all_files if keyword.lower() in f.lower()]
    if len(found) == 1:
        console.print(f"[green]✅ Tìm thấy: {found[0]}[/green]")
        return found[0]
    if len(found) > 1:
        for i, f in enumerate(found, 1):
            console.print(f"  {i}. {f}")
        sub = typer.prompt("Chọn số thứ tự")
        if sub.isdigit() and 1 <= int(sub) <= len(found):
            return found[int(sub) - 1]
    console.print(f"[red]❌ Không tìm thấy '{keyword}'[/red]")
    return None


def _confirm_retranslate(target: str, update_data: bool) -> None:
    base, _ = os.path.splitext(target)
    out     = settings.output_dir / f"{base}_VN.txt"
    status  = "[yellow]✅ Đã có bản dịch — sẽ GHI ĐÈ[/yellow]" if out.exists() else "⬜ Chưa dịch"
    data_s  = "[green]✅ Có[/green]" if update_data else "[dim]❌ Không[/dim]"
    console.print(f"\n  File         : {target}")
    console.print(f"  Trạng thái   : {status}")
    console.print(f"  Cập nhật data: {data_s}")
    console.print(f"  Trans model  : {settings.translation_model} ({settings.translation_provider})")