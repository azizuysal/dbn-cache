# dbn-cache

Download and cache historical market data from Databento.

## Installation

### As a library

```bash
uv add dbn-cache
# or
pip install dbn-cache
```

### CLI only (global install)

```bash
uv tool install dbn-cache
# or
pipx install dbn-cache
# or
mise use -g pipx:dbn-cache
```

## Configuration

Set your Databento API key:

```bash
export DATABENTO_API_KEY=db-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Optionally configure cache location:

```bash
export DATABENTO_CACHE_DIR=/path/to/cache
```

Default cache locations:
- **Unix/Mac:** `~/.databento`
- **Windows:** `%LOCALAPPDATA%\databento`

## CLI Usage

The CLI is available as `dbn` (or `dbn-cache`):

```bash
# Show help
dbn -h
dbn download -h

# Download E-mini S&P 500 continuous futures (1-minute OHLCV)
dbn download ES.c.0 --schema ohlcv-1m --start 2024-01-01 --end 2024-12-01

# Download specific contract (dates auto-detected for supported futures)
dbn download NQH25 --schema ohlcv-1m

# Batch download all quarterly contracts for a root symbol
dbn download NQ --schema ohlcv-1m --from 2016              # 2016 to present
dbn download NQ --schema ohlcv-1m --from 2016 --to 2020    # 2016 to 2020

# Override auto-detection with explicit dates
dbn download ESZ24 --schema trades --start 2024-11-01 --end 2024-12-01

# Download from different dataset (default: GLBX.MDP3)
dbn download AAPL --schema trades --start 2024-01-01 --end 2024-01-31 -d XNAS.ITCH

# Update cached data to yesterday (historical data has 24h delay)
dbn update ES.c.0                # Update all schemas for symbol
dbn update ES.c.0 -s ohlcv-1m    # Update specific schema
dbn update --all                  # Update everything in cache

# List cached data (table view with quality indicators)
dbn list                    # All cached data
dbn list NQ                 # Filter by symbol prefix
dbn list -s ohlcv-1m        # Filter by schema
dbn list -v                 # Verbose output with quality details
dbn list -v ES.c.0          # Verbose for specific symbol

# Estimate cost before downloading
dbn cost ES.c.0 --schema trades --start 2024-01-01 --end 2024-12-01

# Verify cache integrity (check for missing files)
dbn verify
dbn verify --fix  # Rebuild missing metadata and remove stale entries

# Reference commands
dbn datasets  # List available datasets
dbn schemas   # List available schemas
dbn symbols   # Show symbol format examples
```

### Auto-Detection for Futures Contracts

For supported futures contracts, dates are automatically calculated based on contract specifications:

```bash
# No --start/--end needed - dates auto-detected
dbn download NQH25 --schema ohlcv-1m
# → Downloads: Dec 6, 2024 to Mar 21, 2025

# Adjust rollover buffer (default 14 days before front-month)
dbn download NQH25 --schema ohlcv-1m --rollover-days 7

# Explicit dates still work and override auto-detection
dbn download NQH25 --schema ohlcv-1m --start 2024-12-01 --end 2025-03-21
```

### Batch Download

Download all quarterly contracts for a root symbol over a year range:

```bash
# Download NQ contracts from 2016 to present
dbn download NQ --schema ohlcv-1m --from 2016

# Download NQ contracts from 2016 to 2020
dbn download NQ --schema ohlcv-1m --from 2016 --to 2020
# → Downloads: NQH16, NQM16, NQU16, NQZ16, NQH17, ..., NQZ20 (20 contracts)
```

This downloads all quarterly contracts (March, June, September, December) for the specified years. Each contract's dates are auto-detected. Already-cached contracts are skipped.

**Symbol format:** `ROOT` + `MONTH_CODE` + `2-DIGIT_YEAR`

| Input | Interpreted As |
|-------|---------------|
| `NQH25` | March 2025 |
| `NQH16` | March 2016 |
| `ESZ24` | December 2024 |

Always use 2-digit years (e.g., `NQH25`, not `NQH5`).

**Supported products:**
- **Equity index:** ES, NQ, RTY, YM, EMD, MES, MNQ, M2K, MYM, NKD, NIY
- **Treasuries:** ZB, ZN, ZF, ZT, UB
- **Metals:** GC, SI, HG, PL, PA

**Date calculation:**
- **End:** Contract expiration date
- **Start:** Previous quarterly contract expiration minus rollover buffer

For other symbols (stocks, continuous futures, unsupported products), `--start` and `--end` remain required.

### Shell Completions

```bash
# Zsh (add to .zshrc)
eval "$(dbn completions zsh)"

# Bash (add to .bashrc)
eval "$(dbn completions bash)"

# Fish
dbn completions fish > ~/.config/fish/completions/dbn.fish

# PowerShell (Windows)
dbn completions powershell >> $PROFILE
```

## Cancellation & Error Handling

- Press `Ctrl+C` to cancel gracefully; partial downloads are saved and can be resumed
- All errors are caught and displayed with clear messages (no unhandled exceptions)

## Library Usage

```python
from datetime import date
from dbn_cache import DataCache, get_contract_dates

# Initialize cache (uses ~/.databento by default)
cache = DataCache()

# Download and cache data
data = cache.download("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 12, 1))

# Auto-detect dates for supported futures contracts
data = cache.download("NQH25", "ohlcv-1m")  # Dates calculated automatically
data = cache.download("NQH25", "ohlcv-1m", rollover_days=7)  # Custom buffer

# Get contract dates directly
start, end = get_contract_dates("NQH25", rollover_days=14)
# → (date(2024, 12, 6), date(2025, 3, 21))

# Generate all quarterly contracts for batch download
from dbn_cache import generate_quarterly_contracts
contracts = generate_quarterly_contracts("NQ", 2016, 2020)
# → ['NQH16', 'NQM16', 'NQU16', 'NQZ16', 'NQH17', ..., 'NQZ20']
for symbol in contracts:
    cache.download(symbol, "ohlcv-1m")

# Get as Polars LazyFrame
df = data.to_polars().collect()

# Or as Pandas DataFrame
df = data.to_pandas()

# Ensure data is cached (downloads only if missing)
data = cache.ensure("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 12, 1))

# Update cached data to yesterday (returns None if already up to date)
data = cache.update("ES.c.0", "ohlcv-1m")  # Dataset inferred from cache

# Update all cached data
result = cache.update_all()
print(f"Updated: {result.updated_count}, Up to date: {result.up_to_date_count}")
if result.has_errors:
    for item, error in result.errors:
        print(f"  {item.symbol}/{item.schema_}: {error}")

# Get cached data (raises CacheMissError if not cached)
from dbn_cache import CacheMissError

try:
    data = cache.get("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 12, 1))
except CacheMissError:
    print("Data not cached")

# Get data quality issues
issues = cache.get_quality_issues("ES.c.0", "ohlcv-1m")
for issue in issues:
    print(f"{issue.date}: {issue.issue_type}")

# Repair orphaned parquet files (missing metadata)
repaired = cache.repair_metadata()
for dataset, symbol, schema in repaired:
    print(f"Rebuilt metadata for {symbol}/{schema}")

# Custom cache location
from pathlib import Path
cache = DataCache(cache_dir=Path("/path/to/cache"))
```

## Supported Symbols

### Stocks
- `AAPL` - Apple Inc. (use with `-d XNAS.ITCH` or other equity datasets)

### Options
- `SPX.OPT` - All SPX options (use with `-d OPRA.PILLAR`)

### Futures (CME Globex)
- `ESZ24` - Specific contract (E-mini S&P 500, December 2024)
- `ES.c.0` - Front month by calendar (safe for backtesting)
- `ES.v.0` - Front month by volume (**has look-ahead bias**)
- `ES.n.0` - Front month by open interest (**has look-ahead bias**)
- `ES.FUT` - All contracts for a product

Common products: `ES` (S&P 500), `NQ` (Nasdaq), `CL` (Crude Oil), `GC` (Gold), `6E` (Euro FX), `6J` (Yen), `ZB` (Treasury Bonds)

## Schemas

Run `dbn schemas` for the full list. Common schemas:

| Schema | Description | Partition |
|--------|-------------|-----------|
| `trades` | Executed trades | Daily |
| `ohlcv-1m` | 1-minute OHLCV bars | Monthly |
| `ohlcv-1h` | Hourly OHLCV bars | Monthly |
| `ohlcv-1d` | Daily OHLCV bars | Monthly |
| `mbp-1` | Top of book (L1) | Daily |
| `mbp-10` | 10 levels of book (L2) | Daily |
| `mbo` | Full order book | Daily |

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

## Market Calendar Integration

Downloads automatically skip market holidays and non-trading days using exchange calendars:

| Dataset | Calendar | Holiday Behavior |
|---------|----------|------------------|
| `GLBX.MDP3` | CME | Open most holidays with early close |
| `OPRA.PILLAR` | NYSE | Closed on federal holidays |
| `XNAS.ITCH` | NYSE | Closed on federal holidays |
| `DBEQ.BASIC` | NYSE | Closed on federal holidays |

This prevents API errors when downloading tick data on days when markets are closed.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run pyright
```
