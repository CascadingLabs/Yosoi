"""Unit tests for Pipeline._validate_with_contract."""

import types

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract


def _make_pipeline_stub(contract, mocker):
    """Create a minimal object that satisfies _validate_with_contract's needs."""
    stub = types.SimpleNamespace(
        contract=contract,
        console=mocker.MagicMock(),
        logger=mocker.MagicMock(),
    )
    return stub


def test_pipeline_validate_with_contract_success(mocker):
    """_validate_with_contract returns validated dict on success."""

    class SimpleContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    stub = _make_pipeline_stub(SimpleContract, mocker)
    result = Pipeline._validate_with_contract(stub, {'title': '  Book  ', 'price': '£9.99'})

    assert result['title'] == 'Book'
    assert result['price'] == 9.99


def test_pipeline_validate_with_contract_fallback_on_error(mocker):
    """_validate_with_contract falls back to raw data on validation error."""

    class StrictContract(Contract):
        price: float = ys.Price()

    stub = _make_pipeline_stub(StrictContract, mocker)
    raw = {'price': 'not-a-number'}
    result = Pipeline._validate_with_contract(stub, raw)

    assert result is raw
    stub.logger.warning.assert_called_once()
