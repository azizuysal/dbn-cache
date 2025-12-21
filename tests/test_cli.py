from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from databento_cache.cli import main
from databento_cache.exceptions import DownloadCancelledError, MissingAPIKeyError
from databento_cache.models import CachedData


class TestCliHelp:
    def test_help_no_command(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert "Databento data cache utility" in result.output
        assert "download" in result.output
        assert "list" in result.output

    def test_help_short_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["-h"])
        assert result.exit_code == 0
        assert "Databento data cache utility" in result.output

    def test_download_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["download", "-h"])
        assert result.exit_code == 0
        assert "--schema" in result.output
        assert "--start" in result.output
        assert "--end" in result.output


class TestCliDownload:
    def test_download_success(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.download.return_value = CachedData([Path("/tmp/test.parquet")])

            result = runner.invoke(
                main,
                [
                    "download",
                    "ES.c.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-01-31",
                ],
            )
            assert result.exit_code == 0
            assert "Successfully cached" in result.output

    def test_download_lookahead_bias_warning(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.download.return_value = CachedData([Path("/tmp/test.parquet")])

            result = runner.invoke(
                main,
                [
                    "download",
                    "ES.v.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-01-31",
                ],
            )
            assert result.exit_code == 0
            assert "Look-Ahead Bias Warning" in result.output

    def test_download_cancelled(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.download.side_effect = DownloadCancelledError(2, 5)

            result = runner.invoke(
                main,
                [
                    "download",
                    "ES.c.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-05-31",
                ],
            )
            assert result.exit_code == 130
            assert "Cancelled" in result.output
            assert "2" in result.output

    def test_download_permission_error(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            err = PermissionError("Permission denied")
            err.filename = "/path/to/file"
            mock_cache.download.side_effect = err

            result = runner.invoke(
                main,
                [
                    "download",
                    "ES.c.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-01-31",
                ],
            )
            assert result.exit_code == 1
            assert "Permission denied" in result.output

    def test_download_storage_error(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.download.side_effect = OSError("No space left on device")

            result = runner.invoke(
                main,
                [
                    "download",
                    "ES.c.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-01-31",
                ],
            )
            assert result.exit_code == 1
            assert "Storage error" in result.output

    def test_download_generic_error(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.download.side_effect = ValueError("Something went wrong")

            result = runner.invoke(
                main,
                [
                    "download",
                    "ES.c.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-01-31",
                ],
            )
            assert result.exit_code == 1
            assert "ValueError" in result.output

    def test_download_missing_required_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["download", "ES.c.0"])
        assert result.exit_code != 0
        assert "Missing option" in result.output

    def test_download_missing_api_key(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.download.side_effect = MissingAPIKeyError()

            result = runner.invoke(
                main,
                [
                    "download",
                    "ES.c.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-01-31",
                ],
            )
            assert result.exit_code == 1
            assert "Configuration Error" in result.output
            assert "DATABENTO_API_KEY" in result.output


class TestCliList:
    def test_list_empty(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = []

            result = runner.invoke(main, ["list"])
            assert result.exit_code == 0
            assert "No cached data found" in result.output


class TestCliInfo:
    def test_info_not_cached(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.info.return_value = None

            result = runner.invoke(main, ["info", "ES.c.0", "-s", "ohlcv-1m"])
            assert result.exit_code == 0
            assert "No cached data" in result.output


class TestCliCost:
    def test_cost(self) -> None:
        runner = CliRunner()
        with patch("databento_cache.cli.DatabentoClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.get_cost.return_value = 12.50

            result = runner.invoke(
                main,
                [
                    "cost",
                    "ES.c.0",
                    "-s",
                    "ohlcv-1m",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-12-01",
                ],
            )
            assert result.exit_code == 0
            assert "$12.50" in result.output
