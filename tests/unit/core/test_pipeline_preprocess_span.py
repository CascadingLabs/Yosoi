"""End-to-end check that the CAS-18 preprocessor emits the expected Langfuse span.

Spike spec calls for a page-level span carrying ``tokens_in``,
``tokens_out``, ``tier_applied``, and ``transform_count``. We verify the
attributes land on the actual exported OTel span when the experimental
flag is on, using the in-memory ``span_exporter`` fixture from
``tests/conftest.py``.
"""

from __future__ import annotations

import pytest

from yosoi.core.cleaning.preprocess import HTMLPreprocessor
from yosoi.core.pipeline import Pipeline
from yosoi.models.results import FetchResult
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability as obs

# Real-ish HTML that exercises every transform: a script tag, a JSON-LD
# block, a comment, an inline style/event handler, and an inline SVG.
SAMPLE_HTML = (
    '<!DOCTYPE html><html><head>'
    '<title>Spike sample</title>'
    '<script src="/app.js"></script>'
    '<script type="application/ld+json">{"@type":"Article"}</script>'
    '</head><body>'
    '<!-- nav --><nav onclick="x" data-v-abc style="color:red">menu</nav>'
    '<svg viewBox="0 0 10 10"><title>icon</title><path d="M0 0L1 1"/></svg>'
    '<main><h1 class="t">Hello</h1><p>Body content for the preprocessor.</p></main>'
    '</body></html>'
)


@pytest.fixture
def _active_observability(mocker):
    """Install a fake Langfuse client whose tracer is the test TracerProvider's."""
    from opentelemetry import trace

    obs.reset_for_tests()
    fake = mocker.MagicMock()
    fake.tracer = trace.get_tracer('yosoi-test')
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    return fake


@pytest.fixture
def preprocess_pipeline_stub(mocker):
    """Minimal Pipeline stub with the preprocessor wired up."""
    stub = Pipeline.__new__(Pipeline)
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.preprocessor = HTMLPreprocessor()
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.selector_level = SelectorLevel.CSS
    stub.use_experimental_preprocess = True
    return stub


@pytest.mark.usefixtures('_active_observability')
def test_clean_emits_preprocess_span_with_spike_attributes(preprocess_pipeline_stub: Pipeline, span_exporter) -> None:
    """``preprocess`` span carries every attribute the spike spec lists."""
    result = FetchResult(url='https://example.com', html=SAMPLE_HTML)
    out = preprocess_pipeline_stub._clean('https://example.com', result)
    assert out is not None
    assert out, 'preprocessor produced empty output'

    spans = span_exporter.get_finished_spans()
    pp_spans = [s for s in spans if s.name == 'preprocess']
    assert len(pp_spans) == 1, f'expected one preprocess span, got {[s.name for s in spans]}'
    attrs = pp_spans[0].attributes or {}

    # Every spike-required attribute is set.
    assert 'tokens_in' in attrs
    assert 'tokens_out' in attrs
    assert 'tier_applied' in attrs
    assert 'transform_count' in attrs
    # Plus the derived ratio for monitor convenience.
    assert 'reduction_ratio' in attrs

    # Sanity on values.
    assert attrs['tokens_in'] >= attrs['tokens_out']
    assert attrs['tier_applied'] == 'tier1+tier2'
    assert attrs['transform_count'] >= 1
    assert 0.0 < float(attrs['reduction_ratio']) <= 1.0


@pytest.mark.usefixtures('_active_observability')
def test_clean_does_not_emit_preprocess_span_when_flag_off(mocker, span_exporter) -> None:
    """Flag off ⇒ cleaner runs, no ``preprocess`` span emitted."""
    stub = Pipeline.__new__(Pipeline)
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.cleaner.clean_html.return_value = '<body>cleaned</body>'
    stub.preprocessor = None
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.selector_level = SelectorLevel.CSS

    result = FetchResult(url='https://example.com', html=SAMPLE_HTML)
    out = Pipeline._clean(stub, 'https://example.com', result)
    assert out == '<body>cleaned</body>'
    assert stub.cleaner.clean_html.called

    pp_spans = [s for s in span_exporter.get_finished_spans() if s.name == 'preprocess']
    assert pp_spans == []
