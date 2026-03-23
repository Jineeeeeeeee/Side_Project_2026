"""
src/littrans/cli/commands.py — Toàn bộ CLI sub-commands (Typer).

[Refactor] cli.py → cli/commands.py. engine→core, managers→context, bible→context, tools→cli.
[v5.4] Multi-novel: thêm --novel / -n option cho translate, retranslate, stats.
       novel argument = tên subfolder trong inputs/.
       Khi không truyền novel → tự detect nếu chỉ có 1 novel, hoặc prompt chọn.
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

app       = typer.Typer(name="littrans", help="LitRPG / Tu Tiên Translation Pipeline v5.4", add_completion=False)
console   = Console()
clean_app = typer.Typer(help="Công cụ làm sạch & quản lý data")
app.add_typer(clean_app, name="clean")

try:
    from littrans.context.bible_cli import bible_app
    app.add_typer(bible_app, name="bible")
except ImportError:
    pass


# ── Novel resolution helper ───────────────────────────────────────

def _resolve_novel(novel: Optional[str]) -> str:
    """
    Xác định novel cần dùng.

    Ưu tiên:
      1. novel argument truyền vào CLI
      2. NOVEL_NAME trong .env
      3. Nếu inputs/ có đúng 1 subfolder → tự chọn (+ cảnh báo)
      4. Nếu có nhiều subfolder → show danh sách và exit

    Returns:
        Tên novel (có thể rỗng nếu dùng flat structure).
    """
    if novel:
        return novel.strip()

    # Đã có NOVEL_NAME trong .env
    if settings.novel_name:
        return settings.novel_name

    # Scan inputs/ xem có subfolder không
    from littrans.config.settings import get_available_novels
    novels = get_available_novels()

    if not novels:
        # Flat structure — không có subfolder
        return ""

    if len(novels) == 1:
        console.print(f"[dim]→ Tự chọn novel duy nhất: [bold]{novels[0]}[/bold][/dim]")
        return novels[0]

    # Nhiều novel → phải chỉ định
    console.print("\n[yellow]⚠️  Có nhiều novel trong inputs/. Chỉ định với --novel:[/yellow]\n")
    for i, n in enumerate(novels, 1):
        console.print(f"  {i}. {n}")
    console.print(f"\n[dim]Ví dụ: python scripts/main.py translate --novel {novels[0]}[/dim]\n")
    raise typer.Exit(1)


def _apply_novel_and_model(
    novel   : Optional[str],
    provider: Optional[str],
    model   : Optional[str],
) -> None:
    """Set novel + model overrides trước khi chạy pipeline."""
    resolved = _resolve_novel(novel)
    if resolved:
        from littrans.config.settings import set_novel
        set_novel(resolved)

    _apply_model_override(provider, model)


# ── TRANSLATE ─────────────────────────────────────────────────────

@app.command()
def translate(
    book    : Optional[str] = typer.Option(None, "--book", "-b",
                              help="Tên epub đã xử lý (vd: --book mybook → dịch inputs/mybook/)"),
    novel   : Optional[str] = typer.Option(None, "--novel", "-n",
                              help="Tên novel"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    model   : Optional[str] = typer.Option(None, "--model", "-m"),
):
    """Dịch tất cả chương chưa có bản dịch."""
    _apply_novel_and_model(novel, provider, model)
    from littrans.core.pipeline import Pipeline
    Pipeline().run(book=book or "")


# ── RETRANSLATE ───────────────────────────────────────────────────

@app.command()
def retranslate(
    keyword: Optional[str] = typer.Argument(None,
                                help="Số thứ tự hoặc một phần tên file"),
    novel  : Optional[str] = typer.Option(None, "--novel", "-n",
                                help="Tên novel"),
    list_chapters: bool    = typer.Option(False, "--list", "-l",
                                help="Liệt kê tất cả chương"),
    update_data  : bool    = typer.Option(False, "--update-data",
                                help="Cập nhật Glossary/Characters/Skills sau dịch"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    model   : Optional[str] = typer.Option(None, "--model", "-m"),
):
    """Dịch lại một chương cụ thể."""
    _apply_novel_and_model(novel, provider, model)
    from littrans.core.pipeline import Pipeline
    pipeline  = Pipeline()
    all_files = pipeline.sorted_inputs()
    if not all_files:
        console.print("[red]❌ Không có file nào[/red]"); raise typer.Exit(1)
    if list_chapters:
        _print_chapter_list(all_files); return
    target = _resolve_target(keyword, all_files)
    if not target: raise typer.Exit(1)
    _confirm_retranslate(target, update_data)
    if not typer.confirm("Xác nhận dịch lại?", default=False):
        console.print("Huỷ."); return
    pipeline.retranslate(target, update_data=update_data)


# ── LIST NOVELS ───────────────────────────────────────────────────

@app.command("list-novels")
def list_novels():
    """Liệt kê tất cả novel có trong inputs/."""
    from littrans.config.settings import get_available_novels
    novels = get_available_novels()

    if not novels:
        console.print("[yellow]Chưa có novel nào. Tạo subfolder trong inputs/.[/yellow]")
        console.print("[dim]Ví dụ: inputs/TenTruyen1/chapter_001.txt[/dim]")
        return

    table = Table(title="Danh sách Novel", show_header=True)
    table.add_column("Novel", style="cyan")
    table.add_column("Chapters", style="green")
    table.add_column("Đã dịch", style="yellow")
    table.add_column("Output dir")

    for novel_name in novels:
        inp = settings.input_dir / novel_name
        out = settings.output_dir / novel_name
        ch_total  = len([f for f in inp.iterdir() if f.suffix in (".txt", ".md")])
        ch_done   = len(list(out.glob("*_VN.txt"))) if out.exists() else 0
        table.add_row(
            novel_name,
            str(ch_total),
            f"{ch_done}/{ch_total}",
            str(out) if out.exists() else "—",
        )

    console.print(table)


# ── CLEAN GLOSSARY ────────────────────────────────────────────────

@clean_app.command("glossary")
def clean_glossary_cmd(
    novel: Optional[str] = typer.Option(None, "--novel", "-n"),
):
    """Phân loại & merge thuật ngữ trong Staging vào đúng Glossary file."""
    resolved = _resolve_novel(novel)
    if resolved:
        from littrans.config.settings import set_novel
        set_novel(resolved)
    from littrans.cli.tool_clean_glossary import clean_glossary
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
    action  : CharAction      = typer.Option(CharAction.review, "--action", "-a"),
    novel   : Optional[str]   = typer.Option(None, "--novel", "-n"),
    name    : Optional[str]   = typer.Option(None, "--name"),
    rel     : Optional[str]   = typer.Option(None, "--rel"),
    chapter : Optional[str]   = typer.Option(None, "--chapter", "-c"),
    chapter2: Optional[str]   = typer.Option(None, "--chapter2"),
):
    """Quản lý Character Profile."""
    resolved = _resolve_novel(novel)
    if resolved:
        from littrans.config.settings import set_novel
        set_novel(resolved)
    from littrans.cli.tool_clean_chars import run_action
    run_action(action.value, name=name, chapter=chapter, chapter2=chapter2, rel=rel)

epub_app = typer.Typer(help="📚 EPUB Processor — bóc tách file .epub thành chapters")
app.add_typer(epub_app, name="epub")


@epub_app.command("process")
def epub_process(
    file   : Optional[str] = typer.Argument(None, help="Tên file .epub (trống = xử lý tất cả)"),
):
    """Bóc tách .epub → inputs/{tên_epub}/ rồi dịch bằng translate --book {tên_epub}."""
    _check_epub_deps()
    from littrans.tools.epub_processor import process_epub, process_all_epubs

    if file:
        epub_path = settings.epub_dir / file
        if not epub_path.exists():
            epub_path = Path(file)
        if not epub_path.exists():
            console.print(f"[red]❌ Không tìm thấy: {file}[/red]"); raise typer.Exit(1)
        console.print(f"\n📖 Xử lý: [cyan]{epub_path.name}[/cyan]")
        r = process_epub(epub_path)
        console.print(f"\n[green]✅[/green] {r.chapters_written} chapters → inputs/{r.epub_name}/")
        console.print(f"   Dịch: [cyan]python scripts/main.py translate --book {r.epub_name}[/cyan]")
        if r.errors:
            for e in r.errors: console.print(f"  [red]❌ {e}[/red]")
    else:
        results = process_all_epubs()
        for r in results:
            console.print(
                f"\n[green]✅[/green] {r.epub_name}: "
                f"{r.chapters_written} chapters → inputs/{r.epub_name}/"
            )
            console.print(
                f"   Dịch: [cyan]python scripts/main.py translate --book {r.epub_name}[/cyan]"
            )


@epub_app.command("list")
def epub_list():
    """Liệt kê file .epub đang chờ xử lý trong epub/."""
    files = sorted(settings.epub_dir.glob("*.epub")) if settings.epub_dir.exists() else []
    if not files:
        console.print(f"[dim]Không có file .epub nào trong {settings.epub_dir}/[/dim]")
        return
    table = Table(title=f"📚 EPUB ({settings.epub_dir}/)", show_header=True)
    table.add_column("File", style="cyan")
    table.add_column("Kích thước", justify="right")
    for ep in files:
        table.add_row(ep.name, f"{ep.stat().st_size/1_048_576:.1f} MB")
    console.print(table)


def _check_epub_deps():
    try:
        import ebooklib; from bs4 import BeautifulSoup
    except ImportError:
        console.print("[red]❌ pip install ebooklib beautifulsoup4[/red]")
        raise typer.Exit(1)

# ── FIX-NAMES ─────────────────────────────────────────────────────

@app.command("fix-names")
def fix_names_cmd(
    novel          : Optional[str] = typer.Option(None, "--novel", "-n"),
    list_violations: bool = typer.Option(False, "--list"),
    dry_run        : bool = typer.Option(False, "--dry-run"),
    all_chapters   : bool = typer.Option(False, "--all-chapters"),
    clear          : bool = typer.Option(False, "--clear"),
):
    """Sửa tên vi phạm Name Lock trong các bản dịch đã có."""
    resolved = _resolve_novel(novel)
    if resolved:
        from littrans.config.settings import set_novel
        set_novel(resolved)

    from littrans.cli.tool_fix import cmd_list, cmd_fix, load_fixes
    # [v5.4] name_fixes.json lưu trong novel_data_dir
    fixes_path = settings.novel_data_dir / "name_fixes.json"

    if clear:
        if fixes_path.exists():
            fixes_path.unlink()
            console.print(f"[green]🗑️  Đã xóa {fixes_path}[/green]")
        else:
            console.print(f"[yellow]⚠️  {fixes_path} không tồn tại[/yellow]")
        return

    data = load_fixes(fixes_path)
    if list_violations: cmd_list(data); return
    cmd_fix(data, fixes_path, all_chapters=all_chapters, dry_run=dry_run)


# ── STATS ─────────────────────────────────────────────────────────

@app.command()
def stats(
    novel: Optional[str] = typer.Option(None, "--novel", "-n"),
):
    """Thống kê nhanh: nhân vật, glossary, kỹ năng, name lock."""
    resolved = _resolve_novel(novel)
    if resolved:
        from littrans.config.settings import set_novel
        set_novel(resolved)

    from littrans.context.characters import character_stats
    from littrans.context.glossary   import glossary_stats
    from littrans.context.skills     import skills_stats
    from littrans.context.name_lock  import lock_stats
    from littrans.llm.client         import key_pool, translation_model_info

    c  = character_stats(); g = glossary_stats(); sk = skills_stats()
    nl = lock_stats(); kp = key_pool.stats()

    table = Table(title=f"LiTTrans Stats{f' — {settings.novel_name}' if settings.novel_name else ''}",
                  show_header=True)
    table.add_column("Mục", style="cyan")
    table.add_column("Giá trị", style="green")

    if settings.novel_name:
        table.add_row("Novel",            settings.novel_name)
        table.add_row("Data dir",         str(settings.novel_data_dir))
        table.add_section()

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
        if provider not in ("gemini", "anthropic"):
            console.print(f"[red]❌ --provider phải là 'gemini' hoặc 'anthropic'[/red]")
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
    table.add_column("#", width=5)
    table.add_column("Trạng thái", width=12)
    table.add_column("Tên file")
    for i, fn in enumerate(all_files, 1):
        base, _ = os.path.splitext(fn)
        translated = (settings.active_output_dir / f"{base}_VN.txt").exists()
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
    out     = settings.active_output_dir / f"{base}_VN.txt"
    status  = "[yellow]✅ Đã có bản dịch — sẽ GHI ĐÈ[/yellow]" if out.exists() else "⬜ Chưa dịch"
    data_s  = "[green]✅ Có[/green]" if update_data else "[dim]❌ Không[/dim]"
    console.print(f"\n  File         : {target}")
    if settings.novel_name:
        console.print(f"  Novel        : {settings.novel_name}")
    console.print(f"  Trạng thái   : {status}")
    console.print(f"  Cập nhật data: {data_s}")
    console.print(f"  Trans model  : {settings.translation_model} ({settings.translation_provider})")