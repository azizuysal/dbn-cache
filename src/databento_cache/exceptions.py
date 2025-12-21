class CacheMissError(Exception):
    """Requested data is not in cache."""


class PartialCacheError(Exception):
    """Only part of the requested date range is cached."""
