"""Tests for per-(domain, contract) discovery-mode persistence."""

import pytest

from yosoi.storage.discovery_strategy import DiscoveryStrategyStorage


@pytest.fixture
def storage(tmp_path, mocker):
    d = tmp_path / 'discovery'
    d.mkdir()
    mocker.patch('yosoi.storage.discovery_strategy.init_yosoi', return_value=d)
    return DiscoveryStrategyStorage()


class TestDiscoveryStrategyStorage:
    async def test_save_and_load_round_trip(self, storage):
        await storage.save('example.com', 'sig1', 'mcp')

        assert await storage.load('example.com', 'sig1') == 'mcp'

    async def test_load_missing_returns_none(self, storage):
        assert await storage.load('missing.com', 'sig1') is None

    async def test_keyed_by_contract_signature(self, storage):
        await storage.save('example.com', 'sigA', 'mcp')

        # A different contract on the same domain is not poisoned.
        assert await storage.load('example.com', 'sigB') is None

    async def test_rejects_unknown_mode(self, storage):
        await storage.save('example.com', 'sig1', 'bogus')  # type: ignore[arg-type]

        assert await storage.load('example.com', 'sig1') is None
