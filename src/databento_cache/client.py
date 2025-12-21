import os
from datetime import date

import databento as db

from .exceptions import MissingAPIKeyError
from .utils import detect_stype


class DatabentoClient:
    """Wrapper around databento.Historical client."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize client.

        Args:
            api_key: Databento API key. If not provided, uses DATABENTO_API_KEY env var.
        """
        key = api_key or os.environ.get("DATABENTO_API_KEY")
        if not key:
            raise MissingAPIKeyError
        self._client = db.Historical(key)

    def fetch(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
        stype: str | None = None,
    ) -> db.DBNStore:
        """Fetch data from Databento API.

        Args:
            symbol: Symbol to fetch (e.g., 'ES.c.0', 'ESZ24')
            schema: Data schema (e.g., 'ohlcv-1m', 'trades')
            start: Start date (inclusive)
            end: End date (inclusive)
            dataset: Databento dataset (default: GLBX.MDP3 for CME)
            stype: Symbol type. Auto-detected if not provided.

        Returns:
            DBNStore containing the fetched data.
        """
        stype_in = stype or detect_stype(symbol)
        return self._client.timeseries.get_range(
            dataset=dataset,
            symbols=symbol,
            schema=schema,
            stype_in=stype_in,
            start=start.isoformat(),
            end=end.isoformat(),
        )

    def get_cost(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
        stype: str | None = None,
    ) -> float:
        """Estimate cost before downloading.

        Returns:
            Estimated cost in USD.
        """
        stype_in = stype or detect_stype(symbol)
        return self._client.metadata.get_cost(
            dataset=dataset,
            symbols=symbol,
            schema=schema,
            stype_in=stype_in,
            start=start.isoformat(),
            end=end.isoformat(),
        )
