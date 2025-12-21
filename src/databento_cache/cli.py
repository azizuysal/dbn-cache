import signal
import sys
from datetime import date
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
from rich.text import Text

from .cache import DataCache
from .client import DatabentoClient
from .exceptions import DownloadCancelledError
from .models import DownloadProgress, DownloadStatus

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


def parse_date(value: str) -> date:
    """Parse date string (YYYY-MM-DD)."""
    return date.fromisoformat(value)


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(prog_name="databento-cache")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Databento data cache utility."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema (e.g., ohlcv-1m)")
@click.option("--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)")
@click.option("--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)")
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
def download(symbol: str, schema: str, start: date, end: date, dataset: str) -> None:
    """Download and cache data for a symbol."""
    cache = DataCache()
    cancelled = False
    original_handler = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum: int, frame: FrameType | None) -> None:
        nonlocal cancelled
        cancelled = True
        console.print("\n[yellow]Cancelling...[/yellow]")

    if ".v." in symbol or ".n." in symbol:
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

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            MofNCompleteColumn(),
            BarColumn(bar_width=30, complete_style="green", finished_style="green"),
            TaskProgressColumn(),
            RemainingTimeColumn(),
            console=console,
        )

        with progress:
            task_id = progress.add_task(f"Downloading {symbol}", total=None)
            completed = 0

            def on_progress(p: DownloadProgress) -> None:
                nonlocal completed
                if progress.tasks[task_id].total is None:
                    progress.update(task_id, total=p.total)

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

    except ValueError as e:
        if "API key" in str(e):
            console.print(
                Panel(
                    "Missing API key. Set the [cyan]DATABENTO_API_KEY[/cyan] "
                    "environment variable.",
                    title="Configuration Error",
                    border_style="red",
                    expand=False,
                )
            )
        else:
            console.print(
                Panel(
                    f"[red]ValueError:[/red] {e}",
                    title="Error",
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

    finally:
        signal.signal(signal.SIGINT, original_handler)


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
        ranges_str = ", ".join(f"{r.start} to {r.end}" for r in item.ranges)
        size_mb = item.size_bytes / (1024 * 1024)
        click.echo(f"{item.dataset}/{item.symbol}/{item.schema_}")
        click.echo(f"  Ranges: {ranges_str}")
        click.echo(f"  Size: {size_mb:.2f} MB")


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema")
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
def info(symbol: str, schema: str, dataset: str) -> None:
    """Show cache info for a symbol."""
    cache = DataCache()
    result = cache.info(symbol, schema, dataset)
    if result is None:
        click.echo(f"No cached data for {symbol}/{schema}")
        return

    ranges_str = ", ".join(f"{r.start} to {r.end}" for r in result.ranges)
    size_mb = result.size_bytes / (1024 * 1024)
    click.echo(f"Symbol: {result.symbol}")
    click.echo(f"Schema: {result.schema_}")
    click.echo(f"Dataset: {result.dataset}")
    click.echo(f"Ranges: {ranges_str}")
    click.echo(f"Size: {size_mb:.2f} MB")


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema")
@click.option("--start", required=True, type=parse_date, help="Start date")
@click.option("--end", required=True, type=parse_date, help="End date")
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
def cost(symbol: str, schema: str, start: date, end: date, dataset: str) -> None:
    """Estimate download cost."""
    client = DatabentoClient()
    estimated = client.get_cost(symbol, schema, start, end, dataset)
    click.echo(f"Estimated cost: ${estimated:.2f}")


if __name__ == "__main__":
    main()
