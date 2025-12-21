# databento-cache

Download and cache historical market data from Databento.

## Installation

### As a library

```bash
uv add databento-cache
# or
pip install databento-cache
```

### CLI only (global install)

```bash
uv tool install databento-cache
# or
pipx install databento-cache
```

## Configuration

Set your Databento API key:

```bash
export DATABENTO_API_KEY=db-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Optionally configure cache location (default: `~/.databento`):

```bash
export DATABENTO_CACHE_DIR=/path/to/cache
```

## CLI Usage

The CLI is available as `dbn` (or `databento-cache`):

```bash
# Show help
dbn -h
dbn download -h

# Download E-mini S&P 500 continuous futures (1-minute OHLCV)
dbn download ES.c.0 --schema ohlcv-1m --start 2024-01-01 --end 2024-12-01

# Download specific contract
dbn download ESZ24 --schema trades --start 2024-11-01 --end 2024-12-01

# List cached data
dbn list

# Show info for specific symbol
dbn info ES.c.0 --schema ohlcv-1m

# Show data quality issues
dbn quality ES.c.0 --schema ohlcv-1m

# Estimate cost before downloading
dbn cost ES.c.0 --schema trades --start 2024-01-01 --end 2024-12-01

# Verify cache integrity (check for missing files)
dbn verify
dbn verify --fix  # Remove stale metadata for missing files

# Reference commands
dbn datasets  # List available datasets
dbn schemas   # List available schemas
dbn symbols   # Show symbol format examples
```

### Shell Completions

```bash
# Zsh (add to .zshrc)
eval "$(dbn completions zsh)"

# Bash (add to .bashrc)
eval "$(dbn completions bash)"

# Fish
dbn completions fish > ~/.config/fish/completions/dbn.fish
```

## Cancellation & Error Handling

- Press `Ctrl+C` to cancel gracefully; partial downloads are saved and can be resumed
- All errors are caught and displayed with clear messages (no unhandled exceptions)

## Library Usage

```python
from datetime import date
from databento_cache import DataCache

# Initialize cache (uses ~/.databento by default)
cache = DataCache()

# Download and cache data
data = cache.download("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 12, 1))

# Get as Polars LazyFrame
df = data.to_polars().collect()

# Or as Pandas DataFrame
df = data.to_pandas()

# Ensure data is cached (downloads only if missing)
data = cache.ensure("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 12, 1))

# Get cached data (raises CacheMissError if not cached)
from databento_cache import CacheMissError

try:
    data = cache.get("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 12, 1))
except CacheMissError:
    print("Data not cached")

# Get data quality issues
issues = cache.get_quality_issues("ES.c.0", "ohlcv-1m")
for issue in issues:
    print(f"{issue.date}: {issue.issue_type}")

# Custom cache location
cache = DataCache(cache_dir=Path("/path/to/cache"))
```

## Supported Symbols

### Explicit Contracts
- `ESZ24` - E-mini S&P 500, December 2024
- `CLF25` - Crude Oil, January 2025

### Continuous Futures
- `ES.c.0` - Front month by calendar (safe for backtesting)
- `ES.v.0` - Front month by volume (**has look-ahead bias**)
- `ES.n.0` - Front month by open interest (**has look-ahead bias**)

### Parent Symbology
- `ES.FUT` - All E-mini S&P 500 contracts

## Schemas

| Schema | Description | Partition |
|--------|-------------|-----------|
| `ohlcv-1d` | Daily OHLCV | Monthly |
| `ohlcv-1h` | Hourly OHLCV | Monthly |
| `ohlcv-1m` | 1-minute OHLCV | Monthly |
| `ohlcv-1s` | 1-second OHLCV | Monthly |
| `trades` | Individual trades | Daily |
| `mbp-1` | Top of book | Daily |
| `mbp-10` | 10 levels of book | Daily |
| `mbo` | Market by order | Daily |

## Cache Structure

```
~/.databento/
└── GLBX.MDP3/
    └── ES_c_0/
        └── ohlcv-1m/
            ├── meta.json
            └── 2024/
                ├── 01.parquet
                ├── 02.parquet
                └── ...
```

## Look-Ahead Bias Warning

When using continuous futures for backtesting:

- ✅ `ES.c.0` (calendar) - Roll dates are fixed, safe for backtesting
- ⚠️ `ES.v.0` (volume) - Roll dates determined by future volume data
- ⚠️ `ES.n.0` (open interest) - Roll dates determined by future OI data

For accurate backtesting, use calendar-based continuous contracts (`.c.`) or download individual contracts and implement your own roll logic.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run pyright
```
