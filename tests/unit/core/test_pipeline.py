"""Unit tests for Pipeline._validate_with_contract."""

from unittest.mock import MagicMock

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract


def test_pipeline_validate_with_contract_success():
    """_validate_with_contract returns validated dict on success."""

    class SimpleContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    pipeline = MagicMock(spec=Pipeline)
    pipeline.contract = SimpleContract
    pipeline.console = MagicMock()
    pipeline.logger = MagicMock()

    result = Pipeline._validate_with_contract(pipeline, {'title': '  Book  ', 'price': '£9.99'})

    assert result['title'] == 'Book'
    assert result['price'] == 9.99


def test_pipeline_validate_with_contract_fallback_on_error():
    """_validate_with_contract falls back to raw data on validation error."""

    class StrictContract(Contract):
        price: float = ys.Price()

    pipeline = MagicMock(spec=Pipeline)
    pipeline.contract = StrictContract
    pipeline.console = MagicMock()
    pipeline.logger = MagicMock()

    raw = {'price': 'not-a-number'}
    result = Pipeline._validate_with_contract(pipeline, raw)

    assert result is raw
    pipeline.logger.warning.assert_called_once()
