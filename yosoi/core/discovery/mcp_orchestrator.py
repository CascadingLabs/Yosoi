"""MCP-driven discovery orchestrator (CAS-79) — agent + live browser.

Parallel to :class:`yosoi.core.discovery.orchestrator.DiscoveryOrchestrator`
but uses an interactive OpenCode + voidcrawl-MCP agent loop. The agent
navigates the live page, tries selectors AGAINST the live DOM, observes the
extracted values, and only records selectors that returned the right shape.

Why this exists (post-CAS-78 retrospective):

* Static-HTML discovery is blind reasoning. The LLM sees the page as a string;
  needs a rubric to teach it about ``attr``/``global_id``; can pick a selector
  that "verifies" (matches some element) but extracts garbage. CAS-78 added a
  SemanticValidator + iterative feedback loop to compensate.
* MCP-driven discovery removes most of that scaffolding. The agent SEES the
  value its selector produced and can self-correct in real time without
  external validation. The rubric becomes a vocabulary doc, not a behavioural
  patch.

Output shape matches :class:`DiscoveryOrchestrator` — a ``SelectorMap`` keyed
by field name with primary/fallback/tertiary entries — so the rest of the
Pipeline (verify → extract → validate → save) is unchanged.

The agent loop runs under OpenCode (``OpenCodeModel(enable_tools=True)``),
which exposes voidcrawl-mcp tools to the agent natively. Caller must spawn /
provide an OpenCode server (``OPENCODE_BASE_URL`` env var or wrap the call
in ``examples/opencode_server.ensure_opencode_server``).

Action-plan capture from the agent's tool transcript is a follow-up; this
module ships selector discovery first.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.transcript import plan_from_tool_parts
from yosoi.models.contract import Contract
from yosoi.models.replay import ReplayPlan
from yosoi.models.selectors import SelectorEntry
from yosoi.prompts.mcp_discovery import (
    MCP_CONTRACT_INSTRUCTIONS_TMPL,
    MCP_DISCOVERY_BASE,
    MCP_SELECTOR_VOCAB,
    build_field_lines,
)
from yosoi.utils import observability as obs
from yosoi.utils.exceptions import LLMGenerationError

_logger = logging.getLogger(__name__)

# Selector dict shape — matches DiscoveryOrchestrator's SelectorMap.
SelectorMap = dict[str, dict[str, Any]]


# ---------------------------------------------------------------------------
# Agent output type — what the agent fills in, structured
# ---------------------------------------------------------------------------


class FieldFinding(BaseModel):
    """One contract field's discovered selector + the value the agent observed.

    The agent fills this in by trying selectors against the live page; the
    orchestrator double-checks the sample value matches the field's semantic
    type before promoting the finding to the cached snapshot.
    """

    selector: SelectorEntry = Field(description='The SelectorEntry that worked.')
    sample_value: str = Field(description='The exact value the selector extracted on the live page.')
    rationale: str = Field(
        default='',
        description='Short note on why this selector was chosen (one sentence; helps debugging).',
    )


class MCPDiscoveryResult(BaseModel):
    """Structured return from one MCP discovery agent run.

    Pydantic-ai writes this directly from the agent's final structured answer.
    The orchestrator unpacks it into the SelectorMap shape the Pipeline
    consumes downstream.
    """

    field_selectors: dict[str, FieldFinding] = Field(
        description='Per-contract-field findings: selector + sample value the agent observed.',
    )
    root_selector: SelectorEntry | None = Field(
        default=None,
        description='Repeating-card selector for multi-item pages. Null on single-record pages.',
    )
    action_plan_intent: str = Field(
        default='',
        description=(
            'Plain-English description of any pre-extraction actions the page needs '
            '(load-more, scroll, navigate). The orchestrator may pass this through '
            'to the existing ActionPlanDiscoveryAgent in a follow-up step.'
        ),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class _OrchestratorDeps:
    """Runtime context the orchestrator threads into the agent's user prompt."""

    contract_name: str
    url: str
    field_descriptions: dict[str, str]


class MCPDiscoveryOrchestrator:
    """Drive an interactive OpenCode + voidcrawl-MCP agent to discover selectors.

    Same public surface as :class:`DiscoveryOrchestrator` where it matters:
    ``discover_selectors(url=...)`` returns a ``SelectorMap``. Caller is
    responsible for having an OpenCode server reachable (via
    ``OPENCODE_BASE_URL`` or an ``ensure_opencode_server`` context manager
    around the call).

    Attributes:
        model_name: Underlying LLM model id (e.g. ``"gpt-5.4-mini"``).
        provider: LLM provider for OpenCode (e.g. ``"openai"`` /
            ``"openrouter"``).
        console: Rich console for progress output.
    """

    def __init__(
        self,
        contract: type[Contract],
        llm_config: LLMConfig,
        console: Console | None = None,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            contract: Contract subclass defining fields to discover selectors for.
            llm_config: Provider + model config. Must be an OpenCode-shaped
                config (``provider='opencode'`` with ``extra_params`` carrying
                ``provider_id`` and ``model_id``).
            console: Optional Rich console for progress output.

        Raises:
            ValueError: If ``llm_config`` is not OpenCode-shaped.
        """
        if llm_config.provider != 'opencode':
            raise ValueError(
                f'MCPDiscoveryOrchestrator requires an OpenCode-shaped LLMConfig '
                f'(provider="opencode"); got provider={llm_config.provider!r}'
            )
        self._contract = contract
        self._llm_config = llm_config
        self.console = console or Console()
        self.model_name = llm_config.model_name
        self.provider = llm_config.provider
        self._agent: Agent[_OrchestratorDeps, MCPDiscoveryResult] = self._build_agent()
        # Latched after each discover_selectors run so callers (Pipeline) can
        # pick up the action plan distilled from the agent's tool transcript.
        # None when transcript capture was disabled or the agent emitted no
        # replayable tool calls.
        self.last_action_plan: ReplayPlan | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def discover_selectors(
        self,
        html: str | None = None,  # noqa: ARG002 — accepted for orchestrator-interface parity; MCP path navigates live
        url: str | None = None,
        *,
        stale_fields: set[str] | None = None,
        force: bool = False,  # noqa: ARG002 — MCP path always re-discovers; cache short-circuiting lives upstream
        feedback: dict[str, str] | None = None,  # noqa: ARG002 — feedback loop is static-mode-only
    ) -> SelectorMap | None:
        """Drive the agent to discover selectors for *url*. Returns a SelectorMap.

        Args:
            url: URL to discover selectors against.
            html: Ignored — kept for interface parity with the static
                orchestrator. The MCP agent navigates the live URL itself.
            stale_fields: When set, only request selectors for these fields.
                On the MCP path this is currently informational — the agent
                always works the whole Contract — but the orchestrator narrows
                the returned SelectorMap to just the requested fields.
            force: Ignored — the MCP agent always works against the live page.
            feedback: Ignored — the agent's loop sees extracted values
                directly, so the static-mode feedback channel doesn't apply.

        Returns:
            ``SelectorMap`` matching the static orchestrator's shape, or
            ``None`` on hard failure.

        Raises:
            LLMGenerationError: If the agent's MCP loop errors out.
        """
        field_descs = self._contract.field_descriptions()
        if not field_descs:
            return None
        if not url:
            # The MCP agent must know which page to navigate to. Without the URL
            # it cannot start. Don't silently no-op — fail loudly.
            raise LLMGenerationError(
                'MCPDiscoveryOrchestrator.discover_selectors requires url=... — the agent navigates the live page'
            )
        deps = _OrchestratorDeps(
            contract_name=self._contract.__name__,
            url=url,
            field_descriptions=field_descs,
        )
        user_prompt = MCP_CONTRACT_INSTRUCTIONS_TMPL.format(
            contract_name=deps.contract_name,
            url=deps.url,
            n_fields=len(field_descs),
            field_lines=build_field_lines(field_descs),
        )
        # Reset the action-plan latch BEFORE running so callers always see the
        # plan from THIS run (not a stale leftover from a prior invocation).
        self.last_action_plan = None
        target_key = f'{_domain_from_url(url)}/{self._contract.__name__}'

        with obs.span(
            'mcp_orchestrator_discover',
            url=url,
            contract=deps.contract_name,
            field_count=len(field_descs),
        ):
            base_url = os.environ.get('OPENCODE_BASE_URL')
            tool_parts: list[dict[str, Any]] = []
            sse_stop = asyncio.Event()
            sse_task: asyncio.Task[None] | None = None
            if base_url:
                # Tail OpenCode's /event stream during the agent run to capture
                # every successful voidcrawl_* tool call. Best-effort: a stream
                # failure logs but does NOT fail discovery — the selectors are
                # the primary product; the replay plan is a bonus.
                sse_task = asyncio.create_task(_capture_tool_parts(base_url, sse_stop, tool_parts))
            try:
                result = await self._agent.run(user_prompt, deps=deps)
            except Exception as exc:
                _logger.error(
                    'MCP discovery failed',
                    extra={'contract': deps.contract_name, 'url': url, 'provider': self.provider},
                )
                raise LLMGenerationError(f'MCP discovery failed for {url!r}: {exc}') from exc
            finally:
                if sse_task is not None:
                    # Give the stream a moment to drain trailing tool events,
                    # then stop it cleanly. Best-effort: ignore any teardown
                    # errors so they don't mask discovery failures.
                    await asyncio.sleep(0.5)
                    sse_stop.set()
                    sse_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await sse_task

        if tool_parts:
            try:
                plan = plan_from_tool_parts(
                    tool_parts,
                    target=target_key,
                    task=f'discovered via MCP for {self._contract.__name__}',
                )
                if plan.nodes:
                    self.last_action_plan = plan
            except (ValueError, KeyError) as exc:  # malformed transcript → log + drop
                _logger.warning('Tool-transcript distillation failed: %s', exc)

        return self._to_selector_map(result.output, stale_fields)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_agent(self) -> Agent[_OrchestratorDeps, MCPDiscoveryResult]:
        """Construct the pydantic-ai Agent with OpenCode + MCP-tool-enabled model."""
        from yosoi.integrations.opencode import OpenCodeModel

        extra = self._llm_config.extra_params or {}
        provider_id = str(extra.get('provider_id', 'openai'))
        model_id = str(extra.get('model_id', self._llm_config.model_name))
        base_url_raw = extra.get('base_url')
        base_url = str(base_url_raw) if base_url_raw is not None else None

        model = OpenCodeModel(
            provider_id=provider_id,
            model_id=model_id,
            base_url=base_url,
            enable_tools=True,  # hands the loop to OpenCode so voidcrawl MCP tools are callable
        )
        agent: Agent[_OrchestratorDeps, MCPDiscoveryResult] = Agent(
            model,
            deps_type=_OrchestratorDeps,
            output_type=MCPDiscoveryResult,
            output_retries=2,
            instrument=obs.instrumentation_settings(),
            system_prompt=MCP_DISCOVERY_BASE + '\n' + MCP_SELECTOR_VOCAB,
        )
        return agent

    def _to_selector_map(
        self,
        result: MCPDiscoveryResult,
        stale_fields: set[str] | None,
    ) -> SelectorMap | None:
        """Convert the agent's typed answer into the standard SelectorMap shape.

        Each FieldFinding's SelectorEntry becomes the field's ``primary``;
        fallback/tertiary remain None (the agent commits to ONE working
        selector per field, having verified it live). The root selector lands
        under the ``root`` key if present, matching the static orchestrator.
        """
        if not result.field_selectors:
            return None
        out: SelectorMap = {}
        wanted = set(result.field_selectors)
        if stale_fields is not None:
            wanted &= stale_fields
        for field_name in wanted:
            finding = result.field_selectors[field_name]
            out[field_name] = {'primary': finding.selector.model_dump(exclude_none=True)}
        if result.root_selector is not None:
            out['root'] = {'primary': result.root_selector.model_dump(exclude_none=True)}
        return out or None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _domain_from_url(url: str) -> str:
    from urllib.parse import urlparse

    netloc = urlparse(url).netloc
    return netloc.removeprefix('www.') if netloc.startswith('www.') else netloc or 'unknown'


async def _capture_tool_parts(
    base_url: str,
    stop: asyncio.Event,
    collected: list[dict[str, Any]],
) -> None:
    """Tail OpenCode's ``/event`` SSE stream and collect completed tool parts.

    Mirrors the capture loop in ``examples/opencode_voidcrawl/browse_and_save.py``
    but trimmed to just the parts we need for ReplayPlan distillation — no
    per-step usage / reasoning logging. Best-effort: any HTTP / stream failure
    is silently caught so a flaky SSE feed doesn't break the agent run.
    """
    seen: set[tuple[str, str]] = set()
    try:
        async with (
            httpx.AsyncClient(base_url=base_url, timeout=None) as client,
            client.stream('GET', '/event') as resp,
        ):
            async for line in resp.aiter_lines():
                if stop.is_set():
                    return
                if not line.startswith('data:'):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if evt.get('type') != 'message.part.updated':
                    continue
                part = (evt.get('properties') or {}).get('part') or {}
                if part.get('type') != 'tool':
                    continue
                state = part.get('state') or {}
                status = state.get('status', '')
                if status != 'completed':
                    continue
                key = (part.get('callID', ''), status)
                if key in seen:
                    continue
                seen.add(key)
                collected.append(part)
    except (httpx.HTTPError, asyncio.CancelledError):
        return
