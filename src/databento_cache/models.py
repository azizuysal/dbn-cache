from datetime import date, datetime
from pathlib import Path

import pandas as pd
import polars as pl
from pydantic import BaseModel, Field


class DateRange(BaseModel):
    """A date range (inclusive on both ends)."""

    start: date
    end: date


class ContractSpecs(BaseModel):
    """Contract specifications for futures."""

    multiplier: float | None = None
    tick_size: float | None = None
    currency: str | None = None


class SymbolMeta(BaseModel):
    """Metadata for a cached symbol/schema combination."""

    dataset: str
    symbol: str
    stype: str
    schema_: str = Field(alias="schema")
    ranges: list[DateRange]
    updated_at: datetime
    cache_version: int = 1
    contract_specs: ContractSpecs | None = None

    model_config = {"populate_by_name": True}


class CachedDataInfo(BaseModel):
    """Summary info about cached data."""

    dataset: str
    symbol: str
    schema_: str = Field(alias="schema")
    ranges: list[DateRange]
    size_bytes: int

    model_config = {"populate_by_name": True}


class CachedData:
    """Wrapper for cached parquet files with multi-library access."""

    def __init__(self, paths: list[Path]) -> None:
        self._paths = sorted(paths)

    @property
    def paths(self) -> list[Path]:
        """Get paths to cached parquet files."""
        return self._paths

    def to_polars(self) -> pl.LazyFrame:
        """Load data as Polars LazyFrame."""
        if not self._paths:
            return pl.LazyFrame()
        return pl.scan_parquet(self._paths)

    def to_pandas(self) -> pd.DataFrame:
        """Load data as Pandas DataFrame."""
        if not self._paths:
            return pd.DataFrame()
        lf = self.to_polars()
        return lf.collect().to_pandas()

    def __repr__(self) -> str:
        return f"CachedData(paths={len(self._paths)} files)"
