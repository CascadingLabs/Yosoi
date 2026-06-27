"""Deterministic span-contract eval set for Yosoi observability.

Asserts that the standardized span attribute contract (see
:mod:`yosoi.utils.observability`) is emitted consistently across every "view"
the pipeline exposes — the three LLM backends and the A3Node replay/probe
branch — so a single Langfuse view reads uniformly regardless of which path a
run took.

This is a :mod:`pydantic_evals` ``Dataset``: each :class:`Case` is one scenario,
a thin driver exercises the real instrumented code path against mocked
transports (no live LLM, no network, no browser), and :class:`SpanContractEvaluator`
inspects the captured OTel spans against the contract. It is deterministic and
CI-runnable; the selector-cache ``yosoi.cache.*`` view is covered by the
companion ``test_cache_path_contract.py`` (a real two-pass pipeline run, which
is better expressed with pytest fixtures than a self-contained driver).
"""

from __future__ import annotations

import sys
import time
import types
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, cast

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from yosoi.utils import observability as obs

# ---------------------------------------------------------------------------
# Scenario + expectation model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """One driveable observability view, dispatched through :data:`DRIVERS`."""

    kind: str


@dataclass(frozen=True)
class ExpectedSpan:
    """A span the contract requires, with the attribute values it must carry."""

    name: str
    attrs: dict[str, Any] = field(default_factory=dict)


CapturedSpan = dict[str, Any]  # {'name': str, 'attributes': dict[str, Any]}


# ---------------------------------------------------------------------------
# Capture + patch helpers (self-contained — no pytest fixtures, so the dataset
# can also be run as a script)
# ---------------------------------------------------------------------------


@contextmanager
def capture_obs_spans():
    """Point the ``obs`` tracer at an isolated in-memory exporter for the block.

    Patches the :class:`~yosoi.utils.observability.LangfuseClient` singleton with
    a fake whose ``tracer`` writes to a private :class:`InMemorySpanExporter`, so
    ``obs.span`` / the annotate helpers fire (``client()`` is non-None) and land
    in an exporter isolated from any other test's spans. Restored on exit.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    fake = types.SimpleNamespace(
        tracer=provider.get_tracer('yosoi-obs-eval'), sdk=types.SimpleNamespace(flush=lambda: None)
    )
    langfuse_client_cls = cast(Any, obs.LangfuseClient)
    prev = obs.LangfuseClient._instance
    langfuse_client_cls._instance = fake
    try:
        yield exporter
    finally:
        langfuse_client_cls._instance = prev


@contextmanager
def _patch(target: Any, name: str, value: Any):
    """Temporarily set ``target.name = value`` (stdlib only — no unittest.mock)."""
    sentinel = object()
    old = getattr(target, name, sentinel)
    setattr(target, name, value)
    try:
        yield
    finally:
        if old is sentinel:
            delattr(target, name)
        else:
            setattr(target, name, old)


def _serialize(exporter: InMemorySpanExporter) -> list[CapturedSpan]:
    return [{'name': s.name, 'attributes': dict(s.attributes or {})} for s in exporter.get_finished_spans()]


# ---------------------------------------------------------------------------
# LLM-backend drivers
# ---------------------------------------------------------------------------

_HTML = '<html><body><h1 class="title">Headline here for the article body</h1><article>x</article></body></html>'


def _messages() -> list[Any]:
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    return [ModelRequest(parts=[UserPromptPart(content='extract the title')])]


def _params() -> Any:
    from pydantic_ai.models import ModelRequestParameters

    return ModelRequestParameters()


class _FakeAgentRun:
    def __init__(self, output: Any) -> None:
        self.output = output


class _FakeAgent:
    """Stand-in for the inner pydantic-ai Agent — returns a fixed selector."""

    def __init__(self, output: Any) -> None:
        self._output = output

    async def run(self, *_a: Any, **_k: Any) -> _FakeAgentRun:
        return _FakeAgentRun(self._output)


async def _drive_llm_api() -> None:
    """Direct-API backend: discovery span carries uniform ``yosoi.llm.*`` identity.

    The provider (``groq``) collapses to backend ``api``. ``create_model`` is
    swapped for ``TestModel`` so ``FieldDiscoveryAgent`` constructs without the
    groq package, then the inner agent is replaced with a fake returning a valid
    selector — the ``field_agent`` span (with its ``annotate_llm`` tags) is the
    unit under test, not the model output.
    """
    from pydantic_ai.models.test import TestModel

    from yosoi.core.discovery import field_agent as fa_mod
    from yosoi.core.discovery.config import LLMConfig
    from yosoi.models.selectors import FieldSelectors, SelectorLevel
    from yosoi.prompts.discovery import DiscoveryInput

    cfg = LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='test-key', temperature=0.0)
    with _patch(fa_mod, 'create_model', lambda _cfg: TestModel()):
        agent = fa_mod.FieldDiscoveryAgent(cfg)
    cast(Any, agent)._agent = _FakeAgent(FieldSelectors(primary='h1.title', fallback=None, tertiary=None))
    await agent.discover_field(
        field_name='headline',
        field_description='the article headline',
        discovery_input=DiscoveryInput(url='https://example.com', html=_HTML),
        target_level=SelectorLevel.CSS,
    )


@contextmanager
def _fake_claude_agent_sdk(*, text: str, usage: dict[str, Any] | None):
    """Inject a fake ``claude_agent_sdk`` module emitting one ``ResultMessage``."""

    class _Block:
        def __init__(self, t: str) -> None:
            self.text = t

    class ResultMessage:  # name matters: _call_sdk detects turn-end by class name
        def __init__(self) -> None:
            self.content = [_Block(text)]
            self.structured_output = None
            self.usage = usage

    async def query(*, prompt: str, options: Any):
        yield ResultMessage()

    mod = types.ModuleType('claude_agent_sdk')
    cast(Any, mod).ClaudeAgentOptions = lambda **_k: None
    cast(Any, mod).query = query
    prev = sys.modules.get('claude_agent_sdk')
    sys.modules['claude_agent_sdk'] = mod
    try:
        yield
    finally:
        if prev is None:
            sys.modules.pop('claude_agent_sdk', None)
        else:
            sys.modules['claude_agent_sdk'] = prev


async def _drive_llm_claude_sdk() -> None:
    """Claude Agent SDK backend: emits the unified ``llm.transport`` span."""
    from yosoi.integrations.claude_sdk import ClaudeSDKModel

    model = ClaudeSDKModel(model_name='claude-opus-4-7')
    usage = {'input_tokens': 12, 'output_tokens': 5, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
    with _fake_claude_agent_sdk(text='hi', usage=usage):
        await model.request(_messages(), None, _params())


async def _drive_llm_opencode() -> None:
    """OpenCode backend: emits the unified ``llm.transport`` span with extras."""
    import httpx2

    from yosoi.integrations.opencode import OpenCodeModel

    base = 'http://opencode.eval'
    model = OpenCodeModel(provider_id='openai', model_id='gpt-5.3-codex-spark', base_url=base)
    routes = {
        '/session': httpx2.Response(200, json={'id': 'ses'}),
        '/session/ses/message': httpx2.Response(
            200,
            json={
                'info': {'tokens': {'input': 12, 'output': 5, 'cache': {'read': 0, 'write': 0}}},
                'parts': [{'type': 'text', 'text': 'hi'}],
            },
        ),
    }
    original_client = httpx2.AsyncClient

    class _Client:
        def __init__(self, *, base_url: str, timeout: int) -> None:
            self.base_url = base_url
            self.timeout = timeout

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, path: str, json: object | None = None) -> httpx2.Response:
            response = routes[path]
            response._request = httpx2.Request('POST', f'{self.base_url}{path}')
            return response

    cast(Any, httpx2).AsyncClient = _Client
    try:
        await model.request(_messages(), None, _params())
    finally:
        httpx2.AsyncClient = original_client


# ---------------------------------------------------------------------------
# A3Node drivers (drive the real _do_fetch dispatch with fake browser + storage)
# ---------------------------------------------------------------------------


class _FakeTab:
    def __init__(self, html: str) -> None:
        self._html = html

    async def goto(self, url: str, timeout: float | None = None) -> None:
        return None

    async def content(self) -> str:
        return self._html

    async def eval_js(self, expr: str) -> dict[str, Any]:
        return {}


class _FakePool:
    def __init__(self, html: str) -> None:
        self._html = html

    def acquire(self):
        html = self._html

        @asynccontextmanager
        async def _cm():
            yield _FakeTab(html)

        return _cm()


class _FakeStorage:
    """Minimal A3NodeStorage stand-in — keeps recipes in memory, no disk."""

    def __init__(self) -> None:
        self.replays = 0
        self._last: list[Any] = []

    async def save(self, domain: str, acts: list[Any]) -> None:
        self._last = list(acts)

    async def load(self, domain: str):
        from yosoi.storage.a3node import A3Node

        return A3Node(domain=domain, acts=list(self._last), discovered_at='2026-01-01T00:00:00+00:00')

    async def record_replay(self, domain: str) -> None:
        self.replays += 1

    async def load_all(self) -> dict[str, Any]:
        return {}


def _make_fake_domloader(*, replay_ok: bool, html: str):
    class _FDL:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def run(self, _tab: Any):  # probe
            return types.SimpleNamespace(html=html, success=True, acts=[])

        async def replay(self, _tab: Any, acts: list[Any]):
            return types.SimpleNamespace(html=(html if replay_ok else None), success=replay_ok, acts=acts)

    return _FDL


async def _drive_a3node(*, experimental: bool, stored_acts: list[Any] | None, replay_ok: bool) -> None:
    """Run the real ``_do_fetch`` dispatch with fakes for pool/storage/DOMLoader."""
    from yosoi.core.fetcher import voiddriver as vd
    from yosoi.storage.a3node import A3Node

    domain = 'news.example.com'
    url = f'https://{domain}/article'
    fetcher = vd.HeadlessFetcher(experimental_a3node=experimental, min_content_length=10)
    fetcher._pool = _FakePool(_HTML)
    if experimental:
        cast(Any, fetcher)._a3node_storage = _FakeStorage()
        if stored_acts is not None:
            fetcher._a3node_cache = {
                domain: A3Node(domain=domain, acts=list(stored_acts), discovered_at='2026-01-01T00:00:00+00:00')
            }

    with (
        _patch(vd, 'DOMLoader', _make_fake_domloader(replay_ok=replay_ok, html=_HTML)),
        _patch(vd, '_JITTER_MAX_S', 0.0),
        obs.span('fetch', url=url),
    ):
        await fetcher._do_fetch(url, time.time(), 'fetch')


def _act(kind: str) -> Any:
    from yosoi.storage.a3node import ActRecord

    return ActRecord(kind=kind, cycles=1)


# ---------------------------------------------------------------------------
# Scenario registry + dataset
# ---------------------------------------------------------------------------

A = obs  # local alias keeps the metadata table readable

DRIVERS: dict[str, Any] = {
    'llm-api': _drive_llm_api,
    'llm-claude-sdk': _drive_llm_claude_sdk,
    'llm-opencode': _drive_llm_opencode,
    'a3-disabled': lambda: _drive_a3node(experimental=False, stored_acts=None, replay_ok=False),
    'a3-probe': lambda: _drive_a3node(experimental=True, stored_acts=None, replay_ok=False),
    'a3-replay': lambda: _drive_a3node(experimental=True, stored_acts=[], replay_ok=True),
    'a3-fell-back': lambda: _drive_a3node(experimental=True, stored_acts=[_act('load_more')], replay_ok=False),
}


_CASES: list[Case[Scenario, list[CapturedSpan], tuple[ExpectedSpan, ...]]] = [
    Case(
        name='llm-api',
        inputs=Scenario('llm-api'),
        metadata=(
            ExpectedSpan(
                'field_agent[headline]',
                {
                    A.ATTR_LLM_BACKEND: A.BACKEND_API,
                    A.ATTR_LLM_PROVIDER: 'groq',
                    A.ATTR_LLM_MODEL: 'llama-3.3-70b-versatile',
                },
            ),
        ),
    ),
    Case(
        name='llm-claude-sdk',
        inputs=Scenario('llm-claude-sdk'),
        metadata=(
            ExpectedSpan(
                A.LLM_TRANSPORT_SPAN,
                {
                    A.ATTR_LLM_BACKEND: A.BACKEND_CLAUDE_SDK,
                    A.ATTR_LLM_MODEL: 'claude-opus-4-7',
                    A.ATTR_LLM_STRUCTURED: False,
                },
            ),
        ),
    ),
    Case(
        name='llm-opencode',
        inputs=Scenario('llm-opencode'),
        metadata=(
            ExpectedSpan(
                A.LLM_TRANSPORT_SPAN,
                {
                    A.ATTR_LLM_BACKEND: A.BACKEND_OPENCODE,
                    A.ATTR_LLM_MODEL: 'openai:gpt-5.3-codex-spark',
                    A.ATTR_LLM_STRUCTURED: False,
                },
            ),
        ),
    ),
    Case(
        name='a3-disabled',
        inputs=Scenario('a3-disabled'),
        metadata=(ExpectedSpan('fetch', {A.ATTR_A3_MODE: A.A3_MODE_DISABLED}),),
    ),
    Case(
        name='a3-probe',
        inputs=Scenario('a3-probe'),
        metadata=(ExpectedSpan('fetch', {A.ATTR_A3_MODE: A.A3_MODE_PROBE}),),
    ),
    Case(
        name='a3-replay',
        inputs=Scenario('a3-replay'),
        metadata=(ExpectedSpan('fetch', {A.ATTR_A3_MODE: A.A3_MODE_REPLAY, A.ATTR_A3_REPLAYED: True}),),
    ),
    Case(
        name='a3-fell-back',
        inputs=Scenario('a3-fell-back'),
        metadata=(ExpectedSpan('fetch', {A.ATTR_A3_MODE: A.A3_MODE_REPLAY, A.ATTR_A3_FELL_BACK: True}),),
    ),
]


@dataclass
class SpanContractEvaluator(Evaluator[Scenario, list[CapturedSpan], tuple[ExpectedSpan, ...]]):
    """Assert the captured spans satisfy the case's expected span contract."""

    def evaluate(
        self, ctx: EvaluatorContext[Scenario, list[CapturedSpan], tuple[ExpectedSpan, ...]]
    ) -> dict[str, bool]:
        captured = ctx.output or []
        results: dict[str, bool] = {}
        for exp in ctx.metadata or ():
            matches = [c for c in captured if c['name'] == exp.name]
            results[f'{exp.name}: emitted'] = bool(matches)
            if not matches:
                results[f'{exp.name}: attrs'] = False
                continue
            attrs_ok = True
            for key, want in exp.attrs.items():
                got = next((m['attributes'][key] for m in matches if key in m['attributes']), None)
                attrs_ok = attrs_ok and got == want
            results[f'{exp.name}: attrs'] = attrs_ok
        return results


async def run_scenario(scenario: Scenario) -> list[CapturedSpan]:
    """Task: drive one scenario and return its captured spans for evaluation."""
    with capture_obs_spans() as exporter:
        await DRIVERS[scenario.kind]()
    return _serialize(exporter)


def build_dataset() -> Dataset[Scenario, list[CapturedSpan], tuple[ExpectedSpan, ...]]:
    return Dataset(name='observability-span-contract', cases=_CASES, evaluators=[SpanContractEvaluator()])
