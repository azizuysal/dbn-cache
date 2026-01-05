import signal
import sys
from collections.abc import Callable
from datetime import date
from functools import wraps
from types import FrameType

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    Task,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt
from rich.text import Text

from .cache import DataCache
from .client import DatabentoClient
from .exceptions import DownloadCancelledError, EmptyDataError, MissingAPIKeyError
from .models import (
    CacheStatus,
    DataQualityIssue,
    DownloadProgress,
    DownloadStatus,
)
from .utils import (
    filter_by_symbol_prefix,
    format_date_ranges,
    has_lookahead_bias,
    parse_date,
)

console = Console()

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
}


class RemainingTimeColumn(TimeRemainingColumn):
    """Show remaining time only when meaningful (hide zeros/unknown)."""

    def render(self, task: Task) -> Text:
        remaining = task.time_remaining
        if remaining is None or remaining <= 0:
            return Text("")
        minutes, seconds = divmod(int(remaining), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return Text(
                f"remaining {hours}:{minutes:02d}:{seconds:02d}",
                style="progress.remaining",
            )
        return Text(f"remaining {minutes}:{seconds:02d}", style="progress.remaining")


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(prog_name="dbn")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Databento data cache utility."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _canonicalize_symbol(symbol: str) -> str:
    """Canonicalize symbol for display.

    - Continuous futures: es.c.0 → ES.c.0 (root uppercase, roll type lowercase)
    - Explicit contracts: esu24 → ESU24 (all uppercase)
    """
    if "." in symbol:
        # Continuous futures or parent: ES.c.0, ES.FUT
        parts = symbol.split(".")
        parts[0] = parts[0].upper()
        return ".".join(parts)
    # Explicit contract: ESU24
    return symbol.upper()


def _do_download(
    cache: DataCache,
    symbol: str,
    schema: str,
    start: date,
    end: date,
    dataset: str,
) -> None:
    """Execute the download with progress bar."""
    cancelled = False
    original_handler = signal.getsignal(signal.SIGINT)

    bar_column = BarColumn(
        bar_width=30,
        complete_style="green",
        finished_style="green",
        pulse_style="green",
    )
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        MofNCompleteColumn(),
        bar_column,
        TaskProgressColumn(),
        RemainingTimeColumn(),
        console=console,
    )

    def handle_sigint(signum: int, frame: FrameType | None) -> None:
        nonlocal cancelled
        cancelled = True
        progress.console.print("[yellow]Cancelling...[/yellow]")

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        try:
            with progress:
                task_id = progress.add_task(f"Downloading {symbol}", total=None)
                completed = 0
                warned = False

                def on_progress(p: DownloadProgress) -> None:
                    nonlocal completed, warned
                    if progress.tasks[task_id].total is None:
                        progress.update(task_id, total=p.total)

                    if p.quality_warnings > 0 and not warned:
                        warned = True
                        bar_column.complete_style = "yellow"
                        bar_column.finished_style = "yellow"

                    if p.status == DownloadStatus.DOWNLOADING:
                        progress.update(
                            task_id,
                            description=f"Downloading {symbol} [{p.partition.label}]",
                        )
                    elif p.status == DownloadStatus.COMPLETED:
                        completed = p.current
                        progress.update(task_id, completed=completed)

                result = cache.download(
                    symbol,
                    schema,
                    start,
                    end,
                    dataset,
                    on_progress=on_progress,
                    cancelled=lambda: cancelled,
                )

            console.print(
                f"[green]Successfully cached {len(result.paths)} file(s) "
                f"for {symbol}[/green]"
            )

        finally:
            issues = cache.get_quality_issues(symbol, schema, dataset, start, end)
            if issues:
                _display_data_quality_issues(issues)

    finally:
        signal.signal(signal.SIGINT, original_handler)


def _handle_download_errors[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Decorator to handle common download errors."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except DownloadCancelledError as e:
            console.print(
                Panel(
                    f"Download cancelled.\n"
                    f"Completed: [green]{e.completed}[/green] / {e.total} partitions\n"
                    f"Partial data saved. Re-run to resume.",
                    title="Cancelled",
                    border_style="yellow",
                    expand=False,
                )
            )
            sys.exit(130)
        except EmptyDataError as e:
            console.print(
                Panel(
                    f"No data returned for [cyan]{e.symbol}[/cyan].\n\n"
                    "This usually means the symbol doesn't exist in the dataset.\n"
                    f"[dim]Dataset: {e.dataset}[/dim]",
                    title="Empty Data",
                    border_style="yellow",
                    expand=False,
                )
            )
            sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled[/yellow]")
            sys.exit(130)
        except PermissionError as e:
            console.print(
                Panel(
                    f"[red]Permission denied:[/red] {e.filename}",
                    title="Error",
                    border_style="red",
                    expand=False,
                )
            )
            sys.exit(1)
        except OSError as e:
            console.print(
                Panel(
                    f"[red]Storage error:[/red] {e}",
                    title="Error",
                    border_style="red",
                    expand=False,
                )
            )
            sys.exit(1)
        except MissingAPIKeyError:
            console.print(
                Panel(
                    "Missing API key. Set the [cyan]DATABENTO_API_KEY[/cyan] "
                    "environment variable.",
                    title="Configuration Error",
                    border_style="red",
                    expand=False,
                )
            )
            sys.exit(1)
        except Exception as e:
            console.print(
                Panel(
                    f"[red]{type(e).__name__}:[/red] {e}",
                    title="Error",
                    border_style="red",
                    expand=False,
                )
            )
            sys.exit(1)

    return wrapper


def _display_data_quality_issues(issues: list[DataQualityIssue]) -> None:
    """Display data quality issues in a professional format."""
    dates_str = ", ".join(str(i.date) for i in issues)
    count = len(issues)

    console.print(
        Panel(
            f"[yellow]{count} day(s) have reduced data quality:[/yellow]\n"
            f"{dates_str}\n\n"
            "[dim]See: https://databento.com/docs/api-reference-historical/"
            "metadata/metadata-get-dataset-condition[/dim]",
            title="Data Quality Notice",
            border_style="yellow",
            expand=False,
        )
    )


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema (e.g., ohlcv-1m)")
@click.option("--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)")
@click.option("--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)")
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
@click.option("--force", "-f", is_flag=True, help="Force redownload without prompting")
@_handle_download_errors
def download(
    symbol: str, schema: str, start: date, end: date, dataset: str, force: bool
) -> None:
    """Download and cache data for a symbol."""
    symbol = _canonicalize_symbol(symbol)
    cache = DataCache()

    if has_lookahead_bias(symbol):
        console.print(
            Panel(
                f"[bold yellow]Warning:[/bold yellow] Symbol [cyan]{symbol}[/cyan] "
                "uses volume/OI-based rolls which have look-ahead bias.\n"
                "Use calendar rolls (.c.) for backtesting.",
                title="Look-Ahead Bias Warning",
                border_style="yellow",
                expand=False,
            )
        )
        console.print()

    cache_status = cache.check_cache(symbol, schema, start, end, dataset)

    if cache_status.status == CacheStatus.COMPLETE:
        if force:
            console.print(
                f"[yellow]Clearing cache and redownloading {symbol}...[/yellow]"
            )
            cache.clear_cache(symbol, schema, start, end, dataset)
        else:
            console.print(
                Panel(
                    f"All data for [cyan]{symbol}[/cyan] from {start} to {end} "
                    f"is already cached.\n"
                    f"Cached: [green]{cache_status.cached_partitions}[/green] "
                    f"partitions",
                    title="Data Already Cached",
                    border_style="green",
                    expand=False,
                )
            )
            choice = Prompt.ask(
                r"\[r]edownload or \[c]ancel?",
                choices=["r", "c"],
                default="c",
            )
            if choice == "c":
                console.print("[dim]Cancelled.[/dim]")
                return
            console.print("[yellow]Clearing cache and redownloading...[/yellow]")
            cache.clear_cache(symbol, schema, start, end, dataset)

    elif cache_status.status == CacheStatus.PARTIAL:
        if force:
            console.print(
                f"[yellow]Clearing cache and redownloading {symbol}...[/yellow]"
            )
            cache.clear_cache(symbol, schema, start, end, dataset)
        else:
            missing_str = format_date_ranges(cache_status.missing_ranges)
            cached_str = format_date_ranges(cache_status.cached_ranges)
            console.print(
                Panel(
                    f"Partial data exists for [cyan]{symbol}[/cyan] "
                    f"from {start} to {end}.\n\n"
                    f"[green]Cached:[/green] {cached_str} "
                    f"({cache_status.cached_partitions} partitions)\n"
                    f"[yellow]Missing:[/yellow] {missing_str} "
                    f"({cache_status.missing_partitions} partitions)",
                    title="Partial Cache",
                    border_style="yellow",
                    expand=False,
                )
            )
            choice = Prompt.ask(
                r"\[f]ill gaps, \[r]edownload all, or \[c]ancel?",
                choices=["f", "r", "c"],
                default="f",
            )
            if choice == "c":
                console.print("[dim]Cancelled.[/dim]")
                return
            if choice == "r":
                console.print("[yellow]Clearing cache and redownloading...[/yellow]")
                cache.clear_cache(symbol, schema, start, end, dataset)

    _do_download(cache, symbol, schema, start, end, dataset)


@main.command()
@click.argument("symbol", required=False)
@click.option("--schema", "-s", default=None, help="Schema to update (all if omitted)")
@click.option("--all", "update_all", is_flag=True, help="Update all cached data")
def update(symbol: str | None, schema: str | None, update_all: bool) -> None:
    """Update cached data from last cached date to yesterday (UTC).

    Downloads new data since the last update. Requires existing cached data.
    Dataset is inferred from the cached metadata. Historical data has a 24-hour
    embargo, so yesterday UTC is used as the default end date.

    \b
    Examples:
      dbn update ES.c.0              # Update all schemas for symbol
      dbn update ES.c.0 -s ohlcv-1m  # Update specific schema
      dbn update --all               # Update everything in cache
    """
    if not symbol and not update_all:
        console.print("[red]Error:[/red] Either provide a SYMBOL or use --all flag")
        sys.exit(1)

    if symbol and update_all:
        console.print("[red]Error:[/red] Cannot use both SYMBOL and --all flag")
        sys.exit(1)

    cache = DataCache()
    all_cached = cache.list_cached()

    if not all_cached:
        console.print(
            Panel(
                "No cached data found.\n\n"
                "Use [cyan]dbn download[/cyan] to fetch data first.",
                title="No Cached Data",
                border_style="yellow",
                expand=False,
            )
        )
        sys.exit(1)

    if update_all:
        matches = all_cached
    else:
        symbol = _canonicalize_symbol(symbol)  # type: ignore[arg-type]
        matches = filter_by_symbol_prefix(all_cached, symbol)
        if schema:
            matches = [m for m in matches if m.schema_ == schema]

    if not matches:
        if schema:
            console.print(
                Panel(
                    f"No cached data for [cyan]{symbol}[/cyan] with schema "
                    f"[blue]{schema}[/blue].\n\n"
                    "Use [cyan]dbn download[/cyan] to fetch initial data.",
                    title="No Cached Data",
                    border_style="yellow",
                    expand=False,
                )
            )
        else:
            console.print(
                Panel(
                    f"No cached data for [cyan]{symbol}[/cyan].\n\n"
                    "Use [cyan]dbn download[/cyan] to fetch initial data.",
                    title="No Cached Data",
                    border_style="yellow",
                    expand=False,
                )
            )
        sys.exit(1)

    updated_count = 0
    up_to_date_count = 0
    error_count = 0
    errors: list[tuple[str, str, str]] = []
    warned_symbols: set[str] = set()

    for item in matches:
        if has_lookahead_bias(item.symbol) and item.symbol not in warned_symbols:
            warned_symbols.add(item.symbol)
            console.print(
                f"[yellow]⚠ {item.symbol} has look-ahead bias "
                f"(volume/OI-based rolls)[/yellow]"
            )

        update_range = cache.get_update_range(item)
        if update_range is None:
            up_to_date_count += 1
            continue

        start, end = update_range
        console.print(
            f"Updating [cyan]{item.symbol}[/cyan]/[blue]{item.schema_}[/blue] "
            f"from {start} to {end}"
        )

        try:
            _do_download(cache, item.symbol, item.schema_, start, end, item.dataset)
            updated_count += 1
        except DownloadCancelledError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as e:
            error_count += 1
            errors.append((item.symbol, item.schema_, str(e)))
            console.print("  [red]✗ Failed[/red]")

    console.print()
    if updated_count > 0:
        console.print(f"[green]✓ Updated {updated_count} item(s)[/green]")
    if up_to_date_count > 0:
        console.print(f"[green]✓ {up_to_date_count} item(s) already up to date[/green]")
    if error_count > 0:
        console.print(f"[red]✗ {error_count} item(s) failed:[/red]")
        for sym, sch, err in errors:
            console.print(f"  [red]• {sym}/{sch}: {err}[/red]")
        sys.exit(1)


@main.command("list")
@click.option("--dataset", "-d", default=None, help="Filter by dataset")
def list_cached(dataset: str | None) -> None:
    """List cached data."""
    cache = DataCache()
    items = cache.list_cached(dataset)
    if not items:
        click.echo("No cached data found.")
        return

    for item in items:
        ranges_str = format_date_ranges(item.ranges)
        size_mb = item.size_bytes / (1024 * 1024)
        click.echo(f"{item.dataset}/{item.symbol}/{item.schema_}")
        click.echo(f"  Ranges: {ranges_str}")
        click.echo(f"  Size: {size_mb:.2f} MB")


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", default=None, help="Data schema (optional)")
@click.option("--dataset", "-d", default=None, help="Databento dataset (optional)")
def info(symbol: str, schema: str | None, dataset: str | None) -> None:
    """Show cache info for a symbol.

    If no schema is specified, shows all cached schemas for the symbol.
    Symbol matching is case-insensitive and supports prefix matching
    (e.g., 'nq' matches 'NQ.c.0', 'NQU24', etc.).
    """
    display_symbol = _canonicalize_symbol(symbol)
    cache = DataCache()
    all_cached = cache.list_cached(dataset)

    matches = filter_by_symbol_prefix(all_cached, symbol)

    if schema:
        matches = [item for item in matches if item.schema_ == schema]

    if not matches:
        if schema:
            console.print(f"No cached data for {display_symbol}/{schema}")
        else:
            console.print(f"No cached data for {display_symbol}")
        return

    for item in matches:
        ranges_str = format_date_ranges(item.ranges)
        size_mb = item.size_bytes / (1024 * 1024)
        console.print(f"[cyan]{item.symbol}[/cyan] / [blue]{item.schema_}[/blue]")
        console.print(f"  Dataset: {item.dataset}")
        console.print(f"  Ranges:  {ranges_str}")
        console.print(f"  Size:    {size_mb:.2f} MB")


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema")
@click.option("--start", required=True, type=parse_date, help="Start date")
@click.option("--end", required=True, type=parse_date, help="End date")
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
def cost(symbol: str, schema: str, start: date, end: date, dataset: str) -> None:
    """Estimate download cost."""
    symbol = _canonicalize_symbol(symbol)
    try:
        client = DatabentoClient()
        estimated = client.get_cost(symbol, schema, start, end, dataset)
        console.print(f"Estimated cost: [green]${estimated:.2f}[/green]")
    except MissingAPIKeyError:
        console.print(
            Panel(
                "Missing API key. Set the [cyan]DATABENTO_API_KEY[/cyan] "
                "environment variable.",
                title="Configuration Error",
                border_style="red",
                expand=False,
            )
        )
        sys.exit(1)
    except Exception as e:
        err_str = str(e)
        if "symbology" in err_str or "symbols could not be resolved" in err_str:
            console.print(
                Panel(
                    f"Symbol [cyan]{symbol}[/cyan] not found in dataset "
                    f"[cyan]{dataset}[/cyan].\n\n"
                    "[dim]Note: GLBX.MDP3 is for CME futures only. "
                    "For stocks, use the appropriate exchange dataset.[/dim]",
                    title="Symbol Not Found",
                    border_style="red",
                    expand=False,
                )
            )
        else:
            console.print(f"[red]{type(e).__name__}:[/red] {e}")
        sys.exit(1)


@main.command()
@click.option("--symbol", "-y", default=None, help="Filter by symbol (prefix match)")
@click.option("--schema", "-s", default=None, help="Filter by schema")
@click.option("--dataset", "-d", default=None, help="Filter by dataset")
@click.option(
    "--fix",
    is_flag=True,
    help="Rebuild missing metadata and remove stale entries",
)
def verify(
    symbol: str | None, schema: str | None, dataset: str | None, fix: bool
) -> None:
    """Verify cache integrity (check for missing files)."""
    cache = DataCache()

    # First, repair orphaned parquet files (files without metadata)
    if fix:
        repaired = cache.repair_metadata(dataset)
        for ds, sym, sch in repaired:
            console.print(f"[green]✓[/green] Rebuilt metadata for {sym}/{sch} ({ds})")

    all_cached = cache.list_cached(dataset)

    if symbol:
        all_cached = filter_by_symbol_prefix(all_cached, symbol)

    if schema:
        all_cached = [item for item in all_cached if item.schema_ == schema]

    if not all_cached:
        console.print("No cached data to verify.")
        return

    issues_found = 0
    for item in all_cached:
        for r in item.ranges:
            check = cache.check_cache(
                item.symbol, item.schema_, r.start, r.end, item.dataset
            )
            if check.status != CacheStatus.COMPLETE:
                issues_found += 1
                missing_str = format_date_ranges(check.missing_ranges)
                console.print(
                    f"[red]✗[/red] {item.symbol}/{item.schema_}: "
                    f"missing files for {missing_str}"
                )
                if fix:
                    cache.clear_cache(
                        item.symbol, item.schema_, r.start, r.end, item.dataset
                    )
                    console.print("  [yellow]→ Cleared stale metadata[/yellow]")

    if issues_found == 0:
        console.print(f"[green]✓[/green] All {len(all_cached)} cached items verified")
    elif not fix:
        console.print("\n[dim]Run with --fix to remove stale metadata[/dim]")


DATASETS: dict[str, str] = {
    "GLBX.MDP3": "CME Globex futures and options",
    "OPRA.PILLAR": "US options (all exchanges)",
    "IFEU.IMPACT": "ICE Futures Europe",
    "IFUS.IMPACT": "ICE Futures US",
    "NDEX.IMPACT": "Nodal Exchange power futures",
    "XEUR.EOBI": "Eurex fixed income and index derivatives",
    "DBEQ.BASIC": "Databento consolidated US equities",
    "XNAS.ITCH": "NASDAQ TotalView equities",
    "XNYS.PILLAR": "NYSE equities",
    "ARCX.PILLAR": "NYSE Arca equities",
    "XBOS.ITCH": "NASDAQ Boston equities",
    "BATS.PITCH": "CBOE BZX equities",
    "BATY.PITCH": "CBOE BYX equities",
    "EDGA.PITCH": "CBOE EDGA equities",
    "EDGX.PITCH": "CBOE EDGX equities",
    "IEXG.TOPS": "IEX exchange equities",
    "MEMX.MEMOIR": "MEMX exchange equities",
    "XASE.PILLAR": "NYSE American equities",
    "XCHI.PILLAR": "NYSE Chicago equities",
    "XNAS.BASIC": "NASDAQ equities (basic)",
    "XPSX.ITCH": "NASDAQ PSX equities",
}

SCHEMAS: dict[str, str] = {
    "trades": "Trade messages - executed trades",
    "ohlcv-1m": "OHLCV bars - 1-minute",
    "ohlcv-1h": "OHLCV bars - 1-hour",
    "ohlcv-1d": "OHLCV bars - daily",
    "ohlcv-1s": "OHLCV bars - 1-second",
    "mbp-1": "Market by price - top of book (L1)",
    "mbp-10": "Market by price - top 10 levels (L2)",
    "mbo": "Market by order - full order book",
    "tbbo": "Top of book BBO - best bid/offer",
    "bbo-1s": "BBO snapshots - 1-second intervals",
    "bbo-1m": "BBO snapshots - 1-minute intervals",
    "definition": "Instrument definitions and contract specs",
    "statistics": "Market statistics (open interest, settlement)",
    "status": "Trading status updates",
}


@main.command()
def datasets() -> None:
    """List available Databento datasets."""
    for ds, desc in DATASETS.items():
        console.print(f"[cyan]{ds:<16}[/cyan] {desc}")


@main.command()
def schemas() -> None:
    """List available data schemas."""
    for schema, desc in SCHEMAS.items():
        console.print(f"[cyan]{schema:<12}[/cyan] {desc}")


@main.command()
def symbols() -> None:
    """Show symbol format examples for futures."""
    console.print("[bold]Continuous Futures[/bold] (auto-rolling)")
    console.print("  [cyan]ES.c.0[/cyan]   Front-month E-mini S&P 500 (calendar roll)")
    console.print("  [cyan]ES.c.1[/cyan]   Second-month continuous")
    console.print("  [cyan]ES.c.2[/cyan]   Third-month continuous")
    console.print(
        "  [yellow]ES.v.0[/yellow]   Volume-based roll [dim](has look-ahead bias)[/dim]"
    )
    console.print(
        "  [yellow]ES.n.0[/yellow]   Open interest roll"
        " [dim](has look-ahead bias)[/dim]"
    )
    console.print()
    console.print("[bold]Parent Symbols[/bold] (all contracts)")
    console.print("  [cyan]ES.FUT[/cyan]  All E-mini S&P 500 futures")
    console.print("  [cyan]NQ.FUT[/cyan]  All E-mini NASDAQ-100 futures")
    console.print("  [cyan]CL.FUT[/cyan]  All Crude Oil futures")
    console.print()
    console.print("[bold]Specific Contracts[/bold]")
    console.print("  [cyan]ESZ24[/cyan]   E-mini S&P 500 Dec 2024")
    console.print("  [cyan]ESH25[/cyan]   E-mini S&P 500 Mar 2025")
    console.print("  [cyan]NQM25[/cyan]   E-mini NASDAQ-100 Jun 2025")
    console.print()
    console.print("[bold]Month Codes[/bold]")
    console.print(
        "  F=Jan  G=Feb  H=Mar  J=Apr  K=May  M=Jun  "
        "N=Jul  Q=Aug  U=Sep  V=Oct  X=Nov  Z=Dec"
    )


@main.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish", "powershell"]))
def completions(shell: str) -> None:
    """Generate shell completion script.

    \b
    Usage (Unix):
      eval "$(dbn completions zsh)"   # Add to .zshrc
      eval "$(dbn completions bash)"  # Add to .bashrc
      dbn completions fish > ~/.config/fish/completions/dbn.fish

    \b
    Usage (Windows PowerShell):
      dbn completions powershell >> $PROFILE
    """
    import os
    import subprocess

    env = os.environ.copy()
    env["_DBN_COMPLETE"] = f"{shell}_source"
    result = subprocess.run(["dbn"], env=env, capture_output=True, text=True)
    click.echo(result.stdout, nl=False)


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", default=None, help="Data schema (optional)")
@click.option("--dataset", "-d", default=None, help="Databento dataset (optional)")
@click.option("--start", type=parse_date, help="Filter by start date")
@click.option("--end", type=parse_date, help="Filter by end date")
def quality(
    symbol: str,
    schema: str | None,
    dataset: str | None,
    start: date | None,
    end: date | None,
) -> None:
    """Show data quality issues for a symbol.

    If no schema is specified, shows issues for all cached schemas.
    Symbol matching is case-insensitive and supports prefix matching
    (e.g., 'nq' matches 'NQ.c.0', 'NQU24', etc.).
    """
    display_symbol = _canonicalize_symbol(symbol)
    cache = DataCache()
    all_cached = cache.list_cached(dataset)

    matches = filter_by_symbol_prefix(all_cached, symbol)

    if schema:
        matches = [item for item in matches if item.schema_ == schema]

    if not matches:
        if schema:
            console.print(f"No cached data for {display_symbol}/{schema}")
        else:
            console.print(f"No cached data for {display_symbol}")
        return

    found_any = False
    for item in matches:
        issues = cache.get_quality_issues(
            item.symbol, item.schema_, item.dataset, start, end
        )
        if issues:
            found_any = True
            console.print(
                f"[cyan]{item.symbol}[/cyan] / [blue]{item.schema_}[/blue]: "
                f"[yellow]{len(issues)} issue(s)[/yellow]"
            )
            for issue in issues:
                console.print(f"  {issue.date}: {issue.issue_type}")

    if not found_any:
        console.print(f"No data quality issues recorded for {display_symbol}")


if __name__ == "__main__":
    main()
