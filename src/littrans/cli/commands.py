"""
src/littrans/cli/commands.py — Toàn bộ CLI sub-commands (Typer).

[Refactor] cli.py → cli/commands.py. engine→core, managers→context, bible→context, tools→cli.
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

app       = typer.Typer(name="littrans", help="LitRPG / Tu Tiên Translation Pipeline v5.3", add_completion=False)
console   = Console()
clean_app = typer.Typer(help="Công cụ làm sạch & quản lý data")
app.add_typer(clean_app, name="clean")

try:
    from littrans.context.bible_cli import bible_app   # ← ĐỔI: bible → context
    app.add_typer(bible_app, name="bible")
except ImportError:
    pass


# ── TRANSLATE ─────────────────────────────────────────────────────

@app.command()
def translate(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Override TRANSLATION_PROVIDER: gemini | anthropic"),
    model: Optional[str]    = typer.Option(None, "--model", "-m", help="Override TRANSLATION_MODEL"),
):
    """Dịch tất cả chương chưa có bản dịch trong inputs/."""
    _apply_model_override(provider, model)
    from littrans.core.pipeline import Pipeline   # ← ĐỔI: engine → core
    Pipeline().run()


# ── RETRANSLATE ───────────────────────────────────────────────────

@app.command()
def retranslate(
    keyword: Optional[str] = typer.Argument(None, help="Số thứ tự hoặc một phần tên file"),
    list_chapters: bool    = typer.Option(False, "--list", "-l", help="Liệt kê tất cả chương"),
    update_data:   bool    = typer.Option(False, "--update-data", help="Cập nhật Glossary/Characters/Skills sau dịch"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    model: Optional[str]    = typer.Option(None, "--model", "-m"),
):
    """Dịch lại một chương cụ thể."""
    _apply_model_override(provider, model)
    from littrans.core.pipeline import Pipeline   # ← ĐỔI
    pipeline  = Pipeline()
    all_files = pipeline.sorted_inputs()
    if not all_files:
        console.print("[red]❌ Không có file nào trong inputs/[/red]"); raise typer.Exit(1)
    if list_chapters:
        _print_chapter_list(all_files); return
    target = _resolve_target(keyword, all_files)
    if not target: raise typer.Exit(1)
    _confirm_retranslate(target, update_data)
    if not typer.confirm("Xác nhận dịch lại?", default=False):
        console.print("Huỷ."); return
    pipeline.retranslate(target, update_data=update_data)


# ── CLEAN GLOSSARY ────────────────────────────────────────────────

@clean_app.command("glossary")
def clean_glossary_cmd():
    """Phân loại & merge thuật ngữ trong Staging vào đúng Glossary file."""
    from littrans.cli.tool_clean_glossary import clean_glossary   # ← ĐỔI: tools → cli
    clean_glossary()


# ── CLEAN CHARACTERS ─────────────────────────────────────────────

class CharAction(str, Enum):
    review   = "review"
    merge    = "merge"
    fix      = "fix"
    export   = "export"
    validate = "validate"
    archive  = "archive"
    log      = "log"
    diff     = "diff"
 
 
@clean_app.command("characters")
def clean_characters_cmd(
    action  : CharAction      = typer.Option(CharAction.review, "--action", "-a",
                                  help="Hành động: review|merge|fix|export|validate|archive|log|diff"),
    name    : Optional[str]   = typer.Option(None, "--name", "-n",
                                  help="Tên nhân vật (dùng với log, diff)"),
    rel     : Optional[str]   = typer.Option(None, "--rel",
                                  help="Tên nhân vật kia (lọc log theo relationship)"),
    chapter : Optional[str]   = typer.Option(None, "--chapter", "-c",
                                  help="Chương A (dùng với diff). VD: chapter_031.txt"),
    chapter2: Optional[str]   = typer.Option(None, "--chapter2",
                                  help="Chương B (dùng với diff). VD: chapter_050.txt"),
):
    """Quản lý Character Profile.
 
    Ví dụ:
      python main.py clean characters --action log
      python main.py clean characters --action log --name Klein
      python main.py clean characters --action log --name Klein --rel Arthur
      python main.py clean characters --action diff --name Klein --chapter chapter_010.txt --chapter2 chapter_040.txt
    """
    from littrans.cli.tool_clean_chars import run_action
    run_action(
        action.value,
        name    = name,
        chapter = chapter,
        chapter2= chapter2,
        rel     = rel,
    )


# ── FIX-NAMES ─────────────────────────────────────────────────────

@app.command("fix-names")
def fix_names_cmd(
    list_violations: bool = typer.Option(False, "--list",         help="Liệt kê vi phạm"),
    dry_run:         bool = typer.Option(False, "--dry-run",       help="Xem trước, không ghi file"),
    all_chapters:    bool = typer.Option(False, "--all-chapters",  help="Sửa toàn bộ chương"),
    clear:           bool = typer.Option(False, "--clear",         help="Xóa name_fixes.json"),
):
    """Sửa tên vi phạm Name Lock trong các bản dịch đã có."""
    from littrans.cli.tool_fix import cmd_list, cmd_fix, load_fixes   # ← ĐỔI: tools → cli
    from littrans.utils.io_utils import load_json

    fixes_path = settings.data_dir / "name_fixes.json"

    if clear:
        if fixes_path.exists():
            fixes_path.unlink(); console.print(f"[green]🗑️  Đã xóa {fixes_path}[/green]")
        else: console.print(f"[yellow]⚠️  {fixes_path} không tồn tại[/yellow]")
        return

    data = load_fixes(fixes_path)
    if list_violations: cmd_list(data); return
    cmd_fix(data, fixes_path, all_chapters=all_chapters, dry_run=dry_run)


# ── STATS ─────────────────────────────────────────────────────────

@app.command()
def stats():
    """Thống kê nhanh: nhân vật, glossary, kỹ năng, name lock."""
    from littrans.context.characters import character_stats   # ← ĐỔI
    from littrans.context.glossary   import glossary_stats    # ← ĐỔI
    from littrans.context.skills     import skills_stats      # ← ĐỔI
    from littrans.context.name_lock  import lock_stats        # ← ĐỔI
    from littrans.llm.client         import key_pool, translation_model_info

    c  = character_stats(); g = glossary_stats(); sk = skills_stats(); nl = lock_stats(); kp = key_pool.stats()

    table = Table(title="LiTTrans Pipeline Stats", show_header=True)
    table.add_column("Mục", style="cyan"); table.add_column("Giá trị", style="green")
    table.add_row("Trans-call model",   translation_model_info())
    table.add_row("Scout/Pre/Post",     f"{settings.gemini_model} (gemini)")
    table.add_section()
    table.add_row("Nhân vật Active",    str(c["active"]))
    table.add_row("Nhân vật Archive",   str(c["archive"]))
    table.add_row("Nhân vật Staging",   str(c["staging"]))
    if c.get("emotional"): table.add_row("  Có emotion state", str(c["emotional"]))
    table.add_section()
    for cat, cnt in g.items():
        if cnt: table.add_row(f"Glossary [{cat}]", str(cnt))
    table.add_section()
    table.add_row("Kỹ năng tổng",      str(sk["total"]))
    table.add_row("  Tiến hóa",        str(sk["evolution"]))
    table.add_row("Name Lock",         str(nl["total_locked"]))
    table.add_section()
    table.add_row("API Keys (Gemini)", f"{kp['total_keys']} key(s), active #{kp['active_idx']+1}")
    console.print(table)


# ── HELPERS ───────────────────────────────────────────────────────

def _apply_model_override(provider: Optional[str], model: Optional[str]) -> None:
    if provider:
        provider = provider.strip().lower()
        if provider not in ("gemini","anthropic"):
            console.print(f"[red]❌ --provider phải là 'gemini' hoặc 'anthropic', nhận được: '{provider}'[/red]")
            raise typer.Exit(1)
        object.__setattr__(settings, "translation_provider", provider)
        console.print(f"[green]⚙️  Provider override: {provider}[/green]")
    if model:
        model = model.strip()
        object.__setattr__(settings, "translation_model", model)
        console.print(f"[green]⚙️  Model override: {model}[/green]")
    if settings.translation_provider == "anthropic" and not settings.anthropic_api_key:
        console.print("[red]❌ Cần ANTHROPIC_API_KEY trong .env khi dùng --provider anthropic[/red]")
        raise typer.Exit(1)


def _print_chapter_list(all_files: list[str]) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=5); table.add_column("Trạng thái", width=12); table.add_column("Tên file")
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
        if 0 <= idx < len(all_files): return all_files[idx]
        console.print(f"[red]❌ Số thứ tự {keyword} không hợp lệ[/red]"); return None
    found = [f for f in all_files if keyword.lower() in f.lower()]
    if len(found) == 1:
        console.print(f"[green]✅ Tìm thấy: {found[0]}[/green]"); return found[0]
    if len(found) > 1:
        for i, f in enumerate(found, 1): console.print(f"  {i}. {f}")
        sub = typer.prompt("Chọn số thứ tự")
        if sub.isdigit() and 1 <= int(sub) <= len(found): return found[int(sub) - 1]
    console.print(f"[red]❌ Không tìm thấy '{keyword}'[/red]"); return None


def _confirm_retranslate(target: str, update_data: bool) -> None:
    base, _ = os.path.splitext(target)
    out     = settings.output_dir / f"{base}_VN.txt"
    status  = "[yellow]✅ Đã có bản dịch — sẽ GHI ĐÈ[/yellow]" if out.exists() else "⬜ Chưa dịch"
    data_s  = "[green]✅ Có[/green]" if update_data else "[dim]❌ Không[/dim]"
    console.print(f"\n  File         : {target}")
    console.print(f"  Trạng thái   : {status}")
    console.print(f"  Cập nhật data: {data_s}")
    console.print(f"  Trans model  : {settings.translation_model} ({settings.translation_provider})")
