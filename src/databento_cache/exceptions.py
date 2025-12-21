class CacheMissError(Exception):
    """Requested data is not in cache."""


class PartialCacheError(Exception):
    """Only part of the requested date range is cached."""


class DownloadCancelledError(Exception):
    """Download was cancelled by user."""

    def __init__(self, completed: int, total: int) -> None:
        self.completed = completed
        self.total = total
        super().__init__(f"Download cancelled after {completed}/{total} partitions")
