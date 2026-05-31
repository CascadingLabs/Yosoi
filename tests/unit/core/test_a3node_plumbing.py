"""Pipeline → fetcher plumbing for the experimental_a3node opt-in."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from yosoi.core.pipeline import Pipeline


def _stub(mocker: MockerFixture, *, enabled: bool) -> Pipeline:
    stub = Pipeline.__new__(Pipeline)
    stub._experimental_a3node = enabled
    stub._allow_downloads = False
    stub.console = mocker.MagicMock()
    return stub


@pytest.mark.parametrize('fetcher_type', ['headless', 'headful', 'waterfall'])
def test_browser_fetchers_receive_a3node_flag(mocker: MockerFixture, fetcher_type: str):
    stub = _stub(mocker, enabled=True)
    cf = mocker.patch('yosoi.core.pipeline.create_fetcher')

    stub._create_fetcher(fetcher_type, console=stub.console)

    assert cf.call_args.kwargs['experimental_a3node'] is True
    assert cf.call_args.kwargs['console'] is stub.console


def test_disabled_flag_is_forwarded_as_false(mocker: MockerFixture):
    stub = _stub(mocker, enabled=False)
    cf = mocker.patch('yosoi.core.pipeline.create_fetcher')

    stub._create_fetcher('headless', console=stub.console)

    assert cf.call_args.kwargs['experimental_a3node'] is False


def test_simple_fetcher_gets_no_a3node_kwarg(mocker: MockerFixture):
    stub = _stub(mocker, enabled=True)
    cf = mocker.patch('yosoi.core.pipeline.create_fetcher')

    stub._create_fetcher('simple', console=stub.console)

    assert 'experimental_a3node' not in cf.call_args.kwargs
    assert 'console' not in cf.call_args.kwargs
