"""CLI for dbn-cache - uses lazy imports for fast startup."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from functools import wraps
from typing import TYPE_CHECKING, Any

import click
from rich.console import Console, Group
from rich.live import Live
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
from rich.table import Table
from rich.text import Text

from .exceptions import DownloadCancelledError, EmptyDataError, MissingAPIKeyError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .cache import DataCache
    from .models import (
        CachedDataInfo,
        DataQualityIssue,
        DownloadProgress,
    )

console = Console()

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
}


# =============================================================================
# Lazy imports for heavy modules (polars, pandas, databento, exchange_calendars)
# =============================================================================


def _import_cache() -> type:
    """Lazy import DataCache."""
    from .cache import DataCache

    return DataCache


def _import_client() -> type:
    """Lazy import DatabentoClient."""
    from .client import DatabentoClient

    return DatabentoClient


def _import_futures() -> dict[str, Any]:
    """Lazy import futures module functions."""
    from .futures import (
        generate_quarterly_contracts,
        get_contract_dates,
        is_supported_contract,
        is_supported_root,
        parse_contract_symbol,
    )

    return {
        "generate_quarterly_contracts": generate_quarterly_contracts,
        "get_contract_dates": get_contract_dates,
        "is_supported_contract": is_supported_contract,
        "is_supported_root": is_supported_root,
        "parse_contract_symbol": parse_contract_symbol,
    }


def _import_models() -> dict[str, Any]:
    """Lazy import models."""
    from .models import (
        CachedDataInfo,
        CacheStatus,
        DataQualityIssue,
        DownloadProgress,
        DownloadStatus,
    )

    return {
        "CachedDataInfo": CachedDataInfo,
        "CacheStatus": CacheStatus,
        "DataQualityIssue": DataQualityIssue,
        "DownloadProgress": DownloadProgress,
        "DownloadStatus": DownloadStatus,
    }


def _import_utils() -> dict[str, Any]:
    """Lazy import utils."""
    from .utils import (
        filter_by_symbol_prefix,
        format_date_ranges,
        has_lookahead_bias,
        parse_date,
        utc_today,
    )

    return {
        "filter_by_symbol_prefix": filter_by_symbol_prefix,
        "format_date_ranges": format_date_ranges,
        "has_lookahead_bias": has_lookahead_bias,
        "parse_date": parse_date,
        "utc_today": utc_today,
    }


# =============================================================================
# CLI helpers
# =============================================================================


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
    models = _import_models()
    DownloadStatus = models["DownloadStatus"]

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
            )

        console.print(
            f"[green]Successfully cached {len(result.paths)} file(s) "
            f"for {symbol}[/green]"
        )

    finally:
        issues = cache.get_quality_issues(symbol, schema, dataset, start, end)
        if issues:
            _display_data_quality_issues(issues)


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


def _parse_date_option(value: str) -> date:
    """Parse date from string for click options."""
    utils = _import_utils()
    return utils["parse_date"](value)


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema (e.g., ohlcv-1m)")
@click.option(
    "--start", type=_parse_date_option, default=None, help="Start date (YYYY-MM-DD)"
)
@click.option(
    "--end", type=_parse_date_option, default=None, help="End date (YYYY-MM-DD)"
)
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
@click.option("--force", "-f", is_flag=True, help="Force redownload without prompting")
@click.option(
    "--rollover-days",
    type=int,
    default=14,
    help="Days before front-month to start (for auto-detected dates)",
)
@click.option(
    "--from",
    "from_year",
    type=int,
    default=None,
    help="Start year for batch download (e.g., 2016)",
)
@click.option(
    "--to",
    "to_year",
    type=int,
    default=None,
    help="End year for batch download (default: current year)",
)
@_handle_download_errors
def download(
    symbol: str,
    schema: str,
    start: date | None,
    end: date | None,
    dataset: str,
    force: bool,
    rollover_days: int,
    from_year: int | None,
    to_year: int | None,
) -> None:
    """Download and cache data for a symbol.

    \b
    Single contract (dates auto-detected):
      dbn download NQH25 -s ohlcv-1m
      dbn download NQH25 -s ohlcv-1m --rollover-days 7

    \b
    Batch download (all quarterly contracts):
      dbn download NQ -s ohlcv-1m --from 2016           # 2016 to now
      dbn download NQ -s ohlcv-1m --from 2016 --to 2020 # 2016 to 2020

    \b
    Explicit dates (any symbol):
      dbn download NQ.c.0 -s ohlcv-1m --start 2024-01-01 --end 2024-12-01

    \b
    Symbol formats:
      NQH25   = Specific contract (Mar 2025)
      NQ      = Root symbol (use with --from for batch)
      NQ.c.0  = Continuous futures (requires --start/--end)
    """
    # Lazy imports
    DataCache = _import_cache()
    futures = _import_futures()
    models = _import_models()
    utils = _import_utils()

    is_supported_contract = futures["is_supported_contract"]
    is_supported_root = futures["is_supported_root"]
    get_contract_dates = futures["get_contract_dates"]
    generate_quarterly_contracts = futures["generate_quarterly_contracts"]
    has_lookahead_bias = utils["has_lookahead_bias"]
    utc_today = utils["utc_today"]
    CacheStatus = models["CacheStatus"]

    symbol = _canonicalize_symbol(symbol)

    # Batch mode: download all quarterly contracts for a root symbol
    if from_year is not None:
        # Validate batch mode options
        if start is not None or end is not None:
            console.print(
                "[red]Error:[/red] --start/--end cannot be used with --from/--to.\n"
                "[dim]Use --from/--to for batch download, or --start/--end for "
                "explicit date range.[/dim]"
            )
            sys.exit(1)

        if is_supported_contract(symbol):
            console.print(
                f"[red]Error:[/red] Cannot use --from with specific contract "
                f"'{symbol}'.\n"
                "[dim]Use just the root symbol (e.g., 'NQ' instead of 'NQH25').[/dim]"
            )
            sys.exit(1)

        if not is_supported_root(symbol):
            console.print(
                f"[red]Error:[/red] '{symbol}' is not a supported futures root.\n"
                "[dim]Supported roots: ES, NQ, RTY, YM, MES, MNQ, M2K, MYM, "
                "ZB, ZN, ZF, ZT, UB, GC, SI, HG, PL, PA[/dim]"
            )
            sys.exit(1)

        all_contracts = generate_quarterly_contracts(symbol, from_year, to_year)
        yesterday = utc_today() - timedelta(days=1)

        # Filter out contracts whose data is not yet available
        contracts: list[str] = []
        for contract in all_contracts:
            start, _ = get_contract_dates(contract, rollover_days=rollover_days)
            if start <= yesterday:
                contracts.append(contract)

        if not contracts:
            console.print(
                "[yellow]No contracts available yet for the specified range.[/yellow]"
            )
            return

        _batch_download(symbol, schema, dataset, contracts, force, rollover_days)
        return

    # Single-symbol mode
    cache = DataCache()

    # Look-ahead bias warning for volume/OI-based continuous futures
    if has_lookahead_bias(symbol):
        console.print(
            Panel(
                f"Symbol [cyan]{symbol}[/cyan] uses volume or open-interest "
                "based roll logic.\n\n"
                "Roll dates are determined using data that wouldn't have been "
                "available at the time.\n"
                "For backtesting, consider using [cyan].c.0[/cyan] "
                "(calendar-based rolls) instead.",
                title="Look-Ahead Bias Warning",
                border_style="yellow",
                expand=False,
            )
        )

    # Auto-detect dates for supported futures contracts
    if start is None and end is None:
        if is_supported_contract(symbol):
            start, expiration = get_contract_dates(symbol, rollover_days=rollover_days)
            yesterday = utc_today() - timedelta(days=1)
            if expiration > yesterday:
                end = yesterday
                console.print(
                    f"[dim]Auto-detected: {start} to {end} (active contract, "
                    f"capped at yesterday)[/dim]"
                )
            else:
                end = expiration
                console.print(f"[dim]Auto-detected: {start} to {end}[/dim]")
        else:
            console.print(
                "[red]Error:[/red] --start and --end are required for this symbol.\n"
                "[dim]Date auto-detection only works for supported futures contracts "
                "(e.g., NQH25).[/dim]"
            )
            sys.exit(1)

    # Validate dates are provided
    if start is None or end is None:
        console.print(
            "[red]Error:[/red] Both --start and --end are required.\n"
            "[dim]Use 'dbn download SYMBOL -s SCHEMA --start YYYY-MM-DD "
            "--end YYYY-MM-DD'[/dim]"
        )
        sys.exit(1)

    # Check cache status
    cache_status = cache.check_cache(symbol, schema, start, end, dataset)

    if cache_status.status == CacheStatus.COMPLETE:
        if force:
            console.print(
                f"[yellow]Re-downloading {symbol} ({start} to {end})...[/yellow]"
            )
            cache.clear_cache(symbol, schema, start, end, dataset)
        else:
            console.print(
                f"[green]✓ Data already cached for {symbol}[/green] ({start} to {end})"
            )
            answer = Prompt.ask(
                "Re-download?",
                choices=["y", "n"],
                default="n",
            )
            if answer.lower() != "y":
                return
            cache.clear_cache(symbol, schema, start, end, dataset)
    elif cache_status.status == CacheStatus.PARTIAL:
        console.print(
            f"[yellow]Partial data found for {symbol}.[/yellow] "
            "Downloading missing partitions..."
        )
        if force:
            cache.clear_cache(symbol, schema, start, end, dataset)

    _do_download(cache, symbol, schema, start, end, dataset)


def _batch_download(
    root: str,
    schema: str,
    dataset: str,
    contracts: list[str],
    force: bool,
    rollover_days: int,
) -> None:
    """Download multiple contracts with unified progress display."""
    # Lazy imports
    DataCache = _import_cache()
    futures = _import_futures()
    models = _import_models()
    utils = _import_utils()

    get_contract_dates = futures["get_contract_dates"]
    CacheStatus = models["CacheStatus"]
    utc_today = utils["utc_today"]

    cache = DataCache()
    total = len(contracts)

    # Tracking state
    success_count = 0
    skip_count = 0
    error_count = 0
    quality_issues: dict[str, list[DataQualityIssue]] = {}
    errors: list[tuple[str, str]] = []
    cancelled = False

    # Current download state
    current_contract = ""
    current_partition = ""
    partition_current = 0
    partition_total = 0
    current_has_warnings = False

    def build_display() -> Group:
        """Build the live display content."""
        lines: list[str] = []

        # Header: "NQ ohlcv-1m: 15/45 contracts"
        completed = success_count + skip_count + error_count
        lines.append(
            f"[bold]{root}[/bold] [blue]{schema}[/blue]: {completed}/{total} contracts"
        )

        # Current download progress (if downloading)
        if current_contract and partition_total > 0:
            # Build progress bar with color based on quality warnings
            pct = partition_current / partition_total if partition_total else 0
            filled = int(pct * 20)
            bar_color = "yellow" if current_has_warnings else "green"
            bar = "━" * filled + "╸" + "─" * (19 - filled) if filled < 20 else "━" * 20
            lines.append(
                f"  [cyan]▶[/cyan] {current_contract} [{current_partition}] "
                f"[{bar_color}]{bar}[/{bar_color}] "
                f"{partition_current}/{partition_total}"
            )
        elif current_contract:
            lines.append(f"  [cyan]▶[/cyan] {current_contract}...")

        # Running totals
        parts: list[str] = []
        if success_count:
            parts.append(f"[green]✓ {success_count} downloaded[/green]")
        if skip_count:
            parts.append(f"[dim]○ {skip_count} skipped[/dim]")
        if error_count:
            parts.append(f"[red]✗ {error_count} errors[/red]")
        if parts:
            lines.append("  " + " | ".join(parts))

        return Group(*[Text.from_markup(line) for line in lines])

    try:
        with Live(build_display(), console=console, refresh_per_second=10) as live:
            for contract in contracts:
                current_contract = contract
                current_partition = ""
                partition_current = 0
                partition_total = 0
                current_has_warnings = False
                live.update(build_display())

                try:
                    # Get contract dates
                    start, expiration = get_contract_dates(
                        contract, rollover_days=rollover_days
                    )
                    yesterday = utc_today() - timedelta(days=1)
                    end = min(expiration, yesterday)

                    # Check cache status
                    cache_status = cache.check_cache(
                        contract, schema, start, end, dataset
                    )

                    if cache_status.status == CacheStatus.COMPLETE and not force:
                        skip_count += 1
                        live.update(build_display())
                        continue
                    elif force:
                        cache.clear_cache(contract, schema, start, end, dataset)

                    # Download with progress callback
                    def on_progress(p: DownloadProgress) -> None:
                        nonlocal current_partition, partition_current, partition_total
                        nonlocal current_has_warnings
                        partition_total = p.total
                        partition_current = p.current
                        current_partition = p.partition.label
                        if p.quality_warnings > 0:
                            current_has_warnings = True
                        live.update(build_display())

                    cache.download(
                        contract,
                        schema,
                        start,
                        end,
                        dataset,
                        on_progress=on_progress,
                    )

                    # Check for quality issues
                    issues = cache.get_quality_issues(
                        contract, schema, dataset, start, end
                    )
                    if issues:
                        quality_issues[contract] = issues

                    success_count += 1

                except EmptyDataError:
                    skip_count += 1
                except KeyboardInterrupt:
                    cancelled = True
                    break
                except Exception as e:
                    error_count += 1
                    errors.append((contract, str(e)))

                live.update(build_display())

        # Final display is shown by Live context exit
        current_contract = ""  # Clear current contract indicator

    except KeyboardInterrupt:
        cancelled = True

    # Print final summary
    console.print()
    if cancelled:
        console.print(
            f"[yellow]Cancelled.[/yellow] {success_count} downloaded, "
            f"{skip_count} skipped."
        )
    else:
        console.print(
            f"[bold]Done.[/bold] {success_count} downloaded, "
            f"{skip_count} skipped, {error_count} errors."
        )

    # Show errors
    if errors:
        console.print()
        console.print("[red]Errors:[/red]")
        for contract, err in errors:
            console.print(f"  {contract}: {err}")

    # Show quality issues
    if quality_issues:
        console.print()
        total_issues = sum(len(v) for v in quality_issues.values())
        console.print(f"[yellow]Data quality issues ({total_issues} total):[/yellow]")
        for contract, issues in sorted(quality_issues.items()):
            dates = ", ".join(str(i.date) for i in issues[:3])
            if len(issues) > 3:
                dates += f" (+{len(issues) - 3} more)"
            console.print(f"  {contract}: {dates}")

    if cancelled:
        sys.exit(130)


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
    # Lazy imports
    DataCache = _import_cache()
    utils = _import_utils()

    filter_by_symbol_prefix = utils["filter_by_symbol_prefix"]
    has_lookahead_bias = utils["has_lookahead_bias"]

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
    cancelled = False

    try:
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
            except KeyboardInterrupt:
                raise
            except Exception as e:
                error_count += 1
                errors.append((item.symbol, item.schema_, str(e)))
                console.print("  [red]✗ Failed[/red]")
    except KeyboardInterrupt:
        cancelled = True

    console.print()
    if cancelled:
        console.print("[yellow]Cancelled[/yellow]")
    if updated_count > 0:
        console.print(f"[green]✓ Updated {updated_count} item(s)[/green]")
    if up_to_date_count > 0:
        console.print(f"[green]✓ {up_to_date_count} item(s) already up to date[/green]")
    if error_count > 0:
        console.print(f"[red]✗ {error_count} item(s) failed:[/red]")
        for sym, sch, err in errors:
            console.print(f"  [red]• {sym}/{sch}: {err}[/red]")

    if cancelled:
        sys.exit(130)
    if error_count > 0:
        sys.exit(1)


def _format_size(size_bytes: int) -> str:
    """Format size in human-readable units."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


# Schema order: coarsest to finest granularity
_SCHEMA_ORDER = {"ohlcv-1d": 0, "ohlcv-1h": 1, "ohlcv-1m": 2, "ohlcv-1s": 3}


def _item_sort_key(item: CachedDataInfo) -> tuple[str, int, int, int, int, str]:
    """Sort key for cached data items.

    Order: root symbol, then continuous contracts before individual contracts,
    then chronologically by year/month, then schema (1d → 1h → 1m → 1s).
    """
    futures = _import_futures()
    is_supported_contract = futures["is_supported_contract"]
    parse_contract_symbol = futures["parse_contract_symbol"]

    schema_idx = _SCHEMA_ORDER.get(item.schema_, 99)
    # Individual contracts (NQH25, ESZ24, etc.)
    if is_supported_contract(item.symbol):
        try:
            root, month, year = parse_contract_symbol(item.symbol)
            return (root, 1, year, month, schema_idx, item.schema_)
        except ValueError:
            pass
    # Continuous contracts (NQ.c.0, ES.c.0) - sort before individual contracts
    if ".c." in item.symbol or ".n." in item.symbol or ".v." in item.symbol:
        root = item.symbol.split(".")[0]
        return (root, 0, 0, 0, schema_idx, item.schema_)
    # Other symbols (AAPL, etc.) - sort alphabetically
    return (item.symbol, 2, 0, 0, schema_idx, item.schema_)


def _group_futures_contracts(
    items: list[CachedDataInfo],
) -> list[dict[str, str | int | bool | list[CachedDataInfo]]]:
    """Group futures contracts by root symbol and schema.

    Returns a list of groups, where each group is either:
    - A single non-contract item
    - A group of contracts with the same root and schema
    """
    from collections import defaultdict

    futures = _import_futures()
    is_supported_contract = futures["is_supported_contract"]
    parse_contract_symbol = futures["parse_contract_symbol"]

    # Separate contracts from non-contracts
    contract_groups: dict[tuple[str, str, str], list[CachedDataInfo]] = defaultdict(
        list
    )
    non_contracts: list[CachedDataInfo] = []

    for item in items:
        if is_supported_contract(item.symbol):
            try:
                root, _, _ = parse_contract_symbol(item.symbol)
                key = (root, item.schema_, item.dataset)
                contract_groups[key].append(item)
            except ValueError:
                non_contracts.append(item)
        else:
            non_contracts.append(item)

    # Build result list
    results: list[dict[str, str | int | bool | list[CachedDataInfo]]] = []

    # Add non-contracts as individual items
    for item in non_contracts:
        results.append({"type": "single", "items": [item]})

    # Add contract groups - sort by (root, schema_order)
    def group_sort_key(
        item: tuple[tuple[str, str, str], list[CachedDataInfo]],
    ) -> tuple[str, int, str]:
        (root, schema, _dataset), _items = item
        return (root, _SCHEMA_ORDER.get(schema, 99), schema)

    for (root, schema, dataset), group_items in sorted(
        contract_groups.items(), key=group_sort_key
    ):
        # Sort contracts chronologically (year, month)
        def contract_sort_key(item: CachedDataInfo) -> tuple[int, int]:
            try:
                _, month, year = parse_contract_symbol(item.symbol)
                return (year, month)
            except ValueError:
                return (9999, 0)

        group_items.sort(key=contract_sort_key)

        # Check for gaps - generate expected contracts and compare
        if len(group_items) >= 2:
            first = group_items[0].symbol
            last = group_items[-1].symbol
            _, first_month, first_year = parse_contract_symbol(first)
            _, last_month, last_year = parse_contract_symbol(last)

            # Count expected quarterly contracts
            expected_count = 0
            for year in range(first_year, last_year + 1):
                for month in (3, 6, 9, 12):
                    if (year == first_year and month < first_month) or (
                        year == last_year and month > last_month
                    ):
                        continue
                    expected_count += 1

            has_gaps = len(group_items) < expected_count
        else:
            has_gaps = False

        results.append(
            {
                "type": "group",
                "root": root,
                "schema": schema,
                "dataset": dataset,
                "items": group_items,
                "has_gaps": has_gaps,
            }
        )

    # Sort results: continuous contracts first, then groups, then other symbols
    def result_sort_key(
        r: dict[str, str | int | bool | list[CachedDataInfo]],
    ) -> tuple[str, int, int, str]:
        if r["type"] == "single":
            items_list = r["items"]
            if isinstance(items_list, list) and len(items_list) > 0:
                item = items_list[0]
                # Continuous contracts before individual contracts
                if ".c." in item.symbol or ".n." in item.symbol or ".v." in item.symbol:
                    root = item.symbol.split(".")[0]
                    return (root, 0, _SCHEMA_ORDER.get(item.schema_, 99), item.schema_)
                return (
                    item.symbol,
                    2,
                    _SCHEMA_ORDER.get(item.schema_, 99),
                    item.schema_,
                )
            return ("", 2, 99, "")
        # Contract groups after continuous contracts
        root = str(r.get("root", ""))
        schema = str(r.get("schema", ""))
        return (root, 1, _SCHEMA_ORDER.get(schema, 99), schema)

    results.sort(key=result_sort_key)
    return results


@main.command("list")
@click.argument("symbol", required=False, default=None)
@click.option("--schema", "-s", default=None, help="Filter by schema")
@click.option("--dataset", "-d", default=None, help="Filter by dataset")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def list_cached(
    symbol: str | None,
    schema: str | None,
    dataset: str | None,
    verbose: bool,
) -> None:
    """List cached data.

    \b
    Table view (default):
      dbn list                    # List all cached data
      dbn list NQ                 # Filter by symbol prefix
      dbn list -s ohlcv-1m        # Filter by schema

    \b
    Detailed view:
      dbn list -v                 # Verbose output for all
      dbn list -v ES.c.0          # Verbose output for specific symbol
    """
    # Lazy imports
    DataCache = _import_cache()
    utils = _import_utils()
    filter_by_symbol_prefix = utils["filter_by_symbol_prefix"]

    cache = DataCache()
    items = cache.list_cached(dataset)

    if not items:
        console.print("[dim]No cached data found.[/dim]")
        return

    # Filter by symbol prefix if provided
    if symbol:
        symbol = _canonicalize_symbol(symbol)
        items = filter_by_symbol_prefix(items, symbol)

    # Filter by schema if provided
    if schema:
        items = [item for item in items if item.schema_ == schema]

    if not items:
        console.print("[dim]No cached data matches the filter.[/dim]")
        return

    total_size = sum(item.size_bytes for item in items)
    total_items = len(items)

    if verbose:
        _list_verbose(items, total_items, total_size)
    else:
        _list_table(items, total_items, total_size)


def _list_table(
    items: list[CachedDataInfo],
    total_items: int,
    total_size: int,
) -> None:
    """Display cached data in table format."""
    utils = _import_utils()
    format_date_ranges = utils["format_date_ranges"]

    table = Table(show_header=True, header_style="bold")
    table.add_column("Symbol", style="cyan")
    table.add_column("Schema", style="blue")
    table.add_column("Date Range")
    table.add_column("Size", justify="right")
    table.add_column("Quality", justify="center")

    groups = _group_futures_contracts(items)

    for group in groups:
        group_items = group["items"]
        if not isinstance(group_items, list):
            continue

        if group["type"] == "single":
            item = group_items[0]
            ranges_str = format_date_ranges(item.ranges)
            size_str = _format_size(item.size_bytes)

            # Quality issues are already loaded with the item
            if item.quality_issues:
                quality_str = f"[yellow]⚠ {len(item.quality_issues)}[/yellow]"
            else:
                quality_str = "[green]✓[/green]"

            table.add_row(item.symbol, item.schema_, ranges_str, size_str, quality_str)
        else:
            # Grouped contracts
            root = str(group["root"])
            schema_ = str(group["schema"])
            has_gaps = group.get("has_gaps", False)
            count = len(group_items)

            # Symbol column: "NQ (45)" or "NQ (6, gaps)"
            gaps_suffix = ", gaps" if has_gaps else ""
            symbol_str = f"{root} ({count}{gaps_suffix})"

            # Date range: "NQH16 → NQH26"
            first_symbol = group_items[0].symbol
            last_symbol = group_items[-1].symbol
            range_str = f"{first_symbol} → {last_symbol}"

            # Total size
            group_size = sum(i.size_bytes for i in group_items)
            size_str = _format_size(group_size)

            # Quality issues across all contracts (already loaded)
            total_issues = sum(len(item.quality_issues) for item in group_items)

            if total_issues > 0:
                quality_str = f"[yellow]⚠ {total_issues}[/yellow]"
            else:
                quality_str = "[green]✓[/green]"

            table.add_row(symbol_str, schema_, range_str, size_str, quality_str)

    console.print(table)
    console.print()
    console.print(f"[dim]{total_items} items, {_format_size(total_size)} total[/dim]")
    console.print("[dim]Use 'dbn list -v' for details.[/dim]")


def _list_verbose(
    items: list[CachedDataInfo],
    total_items: int,
    total_size: int,
) -> None:
    """Display cached data in verbose format."""
    utils = _import_utils()
    format_date_ranges = utils["format_date_ranges"]

    sorted_items = sorted(items, key=_item_sort_key)

    for i, item in enumerate(sorted_items):
        if i > 0:
            console.print()

        ranges_str = format_date_ranges(item.ranges)
        size_str = _format_size(item.size_bytes)

        console.print(f"[cyan]{item.symbol}[/cyan] / [blue]{item.schema_}[/blue]")
        console.print(f"  Dataset: {item.dataset}")
        console.print(f"  Ranges:  {ranges_str}")
        console.print(f"  Size:    {size_str}")

        # Show quality issues (already loaded with item)
        if item.quality_issues:
            console.print(
                f"  Quality: [yellow]⚠ {len(item.quality_issues)} issues[/yellow]"
            )
            for issue in item.quality_issues:
                console.print(f"    [dim]{issue.date}: {issue.issue_type}[/dim]")

    console.print()
    console.print(f"[dim]{total_items} items, {_format_size(total_size)} total[/dim]")


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema")
@click.option("--start", required=True, type=_parse_date_option, help="Start date")
@click.option("--end", required=True, type=_parse_date_option, help="End date")
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
def cost(symbol: str, schema: str, start: date, end: date, dataset: str) -> None:
    """Estimate download cost."""
    DatabentoClient = _import_client()

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
    # Lazy imports
    DataCache = _import_cache()
    models = _import_models()
    utils = _import_utils()

    filter_by_symbol_prefix = utils["filter_by_symbol_prefix"]
    format_date_ranges = utils["format_date_ranges"]
    CacheStatus = models["CacheStatus"]

    cache = DataCache()

    if fix:
        # Repair orphaned parquet files (files without metadata)
        repaired = cache.repair_metadata(dataset)
        for ds, sym, sch in repaired:
            console.print(f"[green]✓[/green] Rebuilt metadata for {sym}/{sch} ({ds})")

        # Fix metadata date ranges that don't match actual parquet data
        validated = cache.validate_metadata(dataset, fix=True)
        for _ds, sym, sch, msg in validated:
            console.print(f"[green]✓[/green] Fixed metadata for {sym}/{sch}: {msg}")

    all_cached = cache.list_cached(dataset)

    if symbol:
        all_cached = filter_by_symbol_prefix(all_cached, symbol)

    if schema:
        all_cached = [item for item in all_cached if item.schema_ == schema]

    if not all_cached:
        console.print("No cached data to verify.")
        return

    issues_found = 0

    # Check for metadata date mismatches (when not already fixed above)
    if not fix:
        validated = cache.validate_metadata(dataset)
        for _ds, sym, sch, msg in validated:
            issues_found += 1
            console.print(
                f"[yellow]⚠[/yellow] {sym}/{sch}: "
                f"metadata dates don't match data ({msg})"
            )

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
        console.print("\n[dim]Run with --fix to repair issues[/dim]")


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
    """Show symbol format examples."""
    console.print("[bold]Equities[/bold] [dim](-d XNAS.ITCH or DBEQ.BASIC)[/dim]")
    console.print("  [cyan]AAPL[/cyan]     Apple Inc.")
    console.print("  [cyan]MSFT[/cyan]     Microsoft Corp.")
    console.print("  [cyan]SPY[/cyan]      SPDR S&P 500 ETF")
    console.print()
    console.print("[bold]Options[/bold] [dim](-d OPRA.PILLAR)[/dim]")
    console.print("  [cyan]SPX.OPT[/cyan]  All SPX index options")
    console.print("  [cyan]AAPL.OPT[/cyan] All Apple options")
    console.print("  [cyan]SPXW.OPT[/cyan] SPX weekly options")
    console.print()
    console.print("[bold]Futures - Continuous[/bold] [dim](-d GLBX.MDP3)[/dim]")
    console.print("  [cyan]ES.c.0[/cyan]   Front-month E-mini S&P 500 (calendar roll)")
    console.print("  [cyan]ES.c.1[/cyan]   Second-month continuous")
    console.print(
        "  [yellow]ES.v.0[/yellow]   Volume-based roll [dim](has look-ahead bias)[/dim]"
    )
    console.print(
        "  [yellow]ES.n.0[/yellow]   Open interest roll "
        "[dim](has look-ahead bias)[/dim]"
    )
    console.print()
    console.print("[bold]Futures - Parent[/bold] [dim](all contracts)[/dim]")
    console.print("  [cyan]ES.FUT[/cyan]   All E-mini S&P 500 futures")
    console.print("  [cyan]NQ.FUT[/cyan]   All E-mini NASDAQ-100 futures")
    console.print("  [cyan]CL.FUT[/cyan]   All Crude Oil futures")
    console.print()
    console.print("[bold]Futures - Specific[/bold]")
    console.print("  [cyan]ESZ24[/cyan]    E-mini S&P 500 Dec 2024")
    console.print("  [cyan]NQH25[/cyan]    E-mini NASDAQ-100 Mar 2025")
    console.print("  [cyan]NQH16[/cyan]    E-mini NASDAQ-100 Mar 2016 (historical)")
    console.print()
    console.print("[bold]Year Format[/bold]")
    console.print("  Use 2-digit years: 25 → 2025, 16 → 2016")
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
@click.option("--start", type=_parse_date_option, help="Filter by start date")
@click.option("--end", type=_parse_date_option, help="Filter by end date")
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
    # Lazy imports
    DataCache = _import_cache()
    utils = _import_utils()
    filter_by_symbol_prefix = utils["filter_by_symbol_prefix"]

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
