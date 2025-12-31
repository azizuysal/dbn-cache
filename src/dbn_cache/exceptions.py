class CacheMissError(Exception):
    """Requested data is not in cache."""


class PartialCacheError(Exception):
    """Only part of the requested date range is cached."""


class MissingAPIKeyError(Exception):
    """API key is missing."""

    def __init__(self) -> None:
        super().__init__(
            "API key required. Set DATABENTO_API_KEY environment variable."
        )


class DownloadCancelledError(Exception):
    """Download was cancelled by user."""

    def __init__(self, completed: int, total: int) -> None:
        self.completed = completed
        self.total = total
        super().__init__(f"Download cancelled after {completed}/{total} partitions")


class EmptyDataError(Exception):
    """Downloaded data is empty (symbol may not exist in dataset)."""

    def __init__(self, symbol: str, dataset: str) -> None:
        self.symbol = symbol
        self.dataset = dataset
        super().__init__(
            f"No data returned for {symbol} in {dataset}. "
            "Symbol may not exist in this dataset."
        )
