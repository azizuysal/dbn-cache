from datetime import date
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from dbn_cache.cli import main
from dbn_cache.exceptions import DownloadCancelledError, MissingAPIKeyError
from dbn_cache.models import CachedData, CachedDataInfo, DateRange


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
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
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
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
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
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
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
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
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
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
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
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
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
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
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


class TestCliBatchDownload:
    def test_batch_from_with_start_end_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "download",
                "NQ",
                "-s",
                "ohlcv-1m",
                "--from",
                "2020",
                "--start",
                "2020-01-01",
            ],
        )
        assert result.exit_code == 1
        assert "--start/--end cannot be used with --from/--to" in result.output

    def test_batch_from_with_specific_contract_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["download", "NQH25", "-s", "ohlcv-1m", "--from", "2020"],
        )
        assert result.exit_code == 1
        assert "Cannot use --from with specific contract" in result.output

    def test_batch_from_with_unsupported_root_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["download", "VX", "-s", "ohlcv-1m", "--from", "2020"],
        )
        assert result.exit_code == 1
        assert "not a supported futures root" in result.output

    def test_batch_download_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["download", "-h"])
        assert result.exit_code == 0
        assert "--from" in result.output
        assert "--to" in result.output
        assert "Batch download" in result.output


class TestCliList:
    def test_list_empty(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = []

            result = runner.invoke(main, ["list"])
            assert result.exit_code == 0
            assert "No cached data found" in result.output


class TestCliCost:
    def test_cost(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.client.DatabentoClient") as mock_client_cls:
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


class TestCliUpdate:
    def test_update_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["update", "-h"])
        assert result.exit_code == 0
        assert "Update cached data from last cached date to yesterday" in result.output
        assert "--schema" in result.output
        assert "--all" in result.output

    def test_update_no_symbol_no_all(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["update"])
        assert result.exit_code == 1
        assert "Either provide a SYMBOL or use --all flag" in result.output

    def test_update_symbol_and_all(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["update", "ES.c.0", "--all"])
        assert result.exit_code == 1
        assert "Cannot use both SYMBOL and --all flag" in result.output

    def test_update_no_cached_data(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = []

            result = runner.invoke(main, ["update", "ES.c.0", "-s", "ohlcv-1m"])
            assert result.exit_code == 1
            assert "No Cached Data" in result.output
            assert "dbn download" in result.output

    def test_update_already_up_to_date(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = [
                CachedDataInfo(
                    dataset="GLBX.MDP3",
                    symbol="ES.c.0",
                    schema="ohlcv-1m",
                    ranges=[DateRange(start=date(2024, 1, 1), end=date.today())],
                    size_bytes=1024,
                )
            ]
            mock_cache.get_update_range.return_value = None

            result = runner.invoke(main, ["update", "ES.c.0", "-s", "ohlcv-1m"])
            assert result.exit_code == 0
            assert "already up to date" in result.output

    def test_update_success(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = [
                CachedDataInfo(
                    dataset="GLBX.MDP3",
                    symbol="ES.c.0",
                    schema="ohlcv-1m",
                    ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
                    size_bytes=1024,
                )
            ]
            mock_cache.get_update_range.return_value = (
                date(2024, 7, 1),
                date(2024, 12, 31),
            )
            mock_cache.download.return_value = CachedData([Path("/tmp/test.parquet")])

            result = runner.invoke(main, ["update", "ES.c.0", "-s", "ohlcv-1m"])
            assert result.exit_code == 0
            assert "Updating" in result.output
            assert "Updated 1 item" in result.output

    def test_update_all_schemas(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = [
                CachedDataInfo(
                    dataset="GLBX.MDP3",
                    symbol="ES.c.0",
                    schema="ohlcv-1m",
                    ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
                    size_bytes=1024,
                ),
                CachedDataInfo(
                    dataset="GLBX.MDP3",
                    symbol="ES.c.0",
                    schema="trades",
                    ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
                    size_bytes=2048,
                ),
            ]
            mock_cache.get_update_range.return_value = (
                date(2024, 7, 1),
                date(2024, 12, 31),
            )
            mock_cache.download.return_value = CachedData([Path("/tmp/test.parquet")])

            result = runner.invoke(main, ["update", "ES.c.0"])
            assert result.exit_code == 0
            assert "ohlcv-1m" in result.output
            assert "trades" in result.output

    def test_update_lookahead_bias_warning(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = [
                CachedDataInfo(
                    dataset="GLBX.MDP3",
                    symbol="ES.v.0",
                    schema="ohlcv-1m",
                    ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
                    size_bytes=1024,
                )
            ]
            mock_cache.get_update_range.return_value = (
                date(2024, 7, 1),
                date(2024, 12, 31),
            )
            mock_cache.download.return_value = CachedData([Path("/tmp/test.parquet")])

            result = runner.invoke(main, ["update", "ES.v.0", "-s", "ohlcv-1m"])
            assert result.exit_code == 0
            assert "look-ahead bias" in result.output

    def test_update_all_flag(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = [
                CachedDataInfo(
                    dataset="GLBX.MDP3",
                    symbol="ES.c.0",
                    schema="ohlcv-1m",
                    ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
                    size_bytes=1024,
                ),
                CachedDataInfo(
                    dataset="GLBX.MDP3",
                    symbol="NQ.c.0",
                    schema="ohlcv-1m",
                    ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
                    size_bytes=2048,
                ),
            ]
            mock_cache.get_update_range.return_value = (
                date(2024, 7, 1),
                date(2024, 12, 31),
            )
            mock_cache.download.return_value = CachedData([Path("/tmp/test.parquet")])

            result = runner.invoke(main, ["update", "--all"])
            assert result.exit_code == 0
            assert "ES.c.0" in result.output
            assert "NQ.c.0" in result.output
            assert "Updated 2 item" in result.output

    def test_update_all_empty_cache(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = []

            result = runner.invoke(main, ["update", "--all"])
            assert result.exit_code == 1
            assert "No cached data found" in result.output

    def test_update_no_symbol_no_cached_data(self) -> None:
        runner = CliRunner()
        with patch("dbn_cache.cache.DataCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.list_cached.return_value = []

            result = runner.invoke(main, ["update", "ES.c.0"])
            assert result.exit_code == 1
            assert "No Cached Data" in result.output
