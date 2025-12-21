from unittest.mock import patch

from click.testing import CliRunner

from databento_cache.cli import main


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
