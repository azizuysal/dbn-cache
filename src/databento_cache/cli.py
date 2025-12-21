from datetime import date

import click

from .cache import DataCache
from .client import DatabentoClient


def parse_date(value: str) -> date:
    """Parse date string (YYYY-MM-DD)."""
    return date.fromisoformat(value)


@click.group()
@click.version_option()
def main() -> None:
    """Databento data cache utility."""


@main.command()
@click.argument("symbol")
@click.option("--schema", "-s", required=True, help="Data schema (e.g., ohlcv-1m)")
@click.option("--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)")
@click.option("--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)")
@click.option("--dataset", "-d", default="GLBX.MDP3", help="Databento dataset")
def download(symbol: str, schema: str, start: date, end: date, dataset: str) -> None:
    """Download and cache data for a symbol."""
    cache = DataCache()
    click.echo(f"Downloading {symbol} {schema} from {start} to {end}...")
    result = cache.download(symbol, schema, start, end, dataset)
    click.echo(f"Cached {len(result.paths)} files")


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
