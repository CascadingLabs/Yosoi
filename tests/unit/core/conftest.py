"""Shared helpers for `yosoi.core.pipeline` unit tests.

The Pipeline stub historically lived as a near-duplicate `_make_pipeline_stub`
helper in five separate test modules (`test_pipeline.py`,
`test_multi_item.py` — twice — `test_pipeline_observability.py`,
`test_pipeline_iterative.py`). Each independently grew an
`_inner_llm_config` field when CAS-78 wired the action-plan hook through
``Pipeline._build_prepare_page``. Consolidating here so the next field-shape
change touches one site, not five.

Exposed as a plain module-level function (not a pytest fixture) so tests
can keep calling it directly — ``_make_pipeline_stub(mocker, ...)`` — without
threading a fixture through every test signature.
"""

from __future__ import annotations

from typing import Any

import yosoi as ys
from yosoi.core.pipeline import Pipeline


class _DefaultStubContract(ys.Contract):
    """The default Contract for stubs that don't pin a specific shape.

    Tests that probe Contract-shape-dependent code paths (multi-item root
    resolution, list-field expansion, semantic validation) should pass their
    own ``contract=...``. Tests that don't care use this.
    """

    title: str = ys.Title()
    price: float = ys.Price()


def make_pipeline_stub(
    mocker: Any,
    contract: type[ys.Contract] | None = None,
    *,
    with_normalize_url: bool = False,
    session_id: str | None = None,
    observability_storage: bool = False,
    record_url_stats: Any | None = None,
) -> Pipeline:
    """Build a fully-mocked ``Pipeline`` stub.

    Args:
        mocker: pytest-mock's ``mocker`` fixture handle.
        contract: Pin the Contract used by the stub. Defaults to
            :class:`_DefaultStubContract`.
        with_normalize_url: When True, patches ``stub.normalize_url`` to a
            pass-through AsyncMock so ``Pipeline.scrape`` can be invoked
            without hitting the real URL normalisation path.
        session_id: When set, attaches ``session_id`` + ``_url_start`` on the
            stub. The observability test path expects both.
        observability_storage: When True, additionally stubs
            ``storage.load_selectors`` to return None (cache-miss). The
            observability path inspects that return; other paths don't.
        record_url_stats: When set, makes ``tracker.record_url`` return the
            given DomainStats-shaped value instead of a bare AsyncMock.
    """
    from yosoi.core.discovery.config import LLMConfig
    from yosoi.models.selectors import SelectorLevel
    from yosoi.utils.signatures import contract_signature

    stub = Pipeline.__new__(Pipeline)
    stub.contract = contract or _DefaultStubContract  # type: ignore[assignment]
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.discovery = mocker.MagicMock()
    stub.discovery.discover_selectors = mocker.AsyncMock()
    stub.verifier = mocker.MagicMock()
    stub.extractor = mocker.MagicMock()
    stub.storage = mocker.MagicMock()
    stub.storage.load_snapshots.return_value = None
    if observability_storage:
        stub.storage.load_selectors.return_value = None
    stub.tracker = mocker.MagicMock()
    if record_url_stats is not None:
        stub.tracker.record_url = mocker.AsyncMock(return_value=record_url_stats)
    else:
        stub.tracker.record_url = mocker.AsyncMock()
    stub._client = mocker.AsyncMock()
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.output_formats = ['json']
    stub.force = False
    stub.selector_level = SelectorLevel.CSS
    stub._contract_sig = contract_signature(stub.contract)
    # The action-plan hook _build_prepare_page reads _inner_llm_config to
    # construct a per-call agent. Stubs need it present even though _fetch
    # is mocked downstream and the agent is never invoked.
    stub._inner_llm_config = LLMConfig(provider='test', model_name='test-model', api_key='fake')
    if with_normalize_url:
        mocker.patch.object(stub, 'normalize_url', new=mocker.AsyncMock(side_effect=lambda u: u))
    if session_id is not None:
        stub.session_id = session_id
        stub._url_start = 0.0
    return stub


def make_minimal_pipeline_stub(mocker: Any, contract: type[ys.Contract] | None = None) -> Pipeline:
    """Bare stub for tests that only need ``contract``, ``console``, ``logger``,
    and ``_contract_sig`` — the multi-item ``_resolve_root`` tests, for instance.

    Smaller than ``make_pipeline_stub`` so its callers don't carry unused
    mock attributes; useful guard against accidentally relying on a mocked
    subsystem that hasn't been set up for the test in question.
    """
    stub = Pipeline.__new__(Pipeline)
    stub.contract = contract or _DefaultStubContract  # type: ignore[assignment]
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub._contract_sig = 'test-sig'
    return stub
