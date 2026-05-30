"""MCP discovery orchestrator: live-browser agent loop → persisted lesson.

Public surface mirrors :class:`~yosoi.core.discovery.orchestrator.DiscoveryOrchestrator`
(``discover_selectors(html, url) -> SelectorMap | None``) so ``Pipeline`` can swap
the two transparently. The differences are internal:

* one stateful agent session explores *all* fields against the live page,
  instead of a blind per-field fan-out over cleaned HTML;
* the durable artifact is a :class:`~yosoi.models.replay.DiscoveryLesson`
  (selectors + replay plan + validation evidence), persisted via
  :class:`~yosoi.storage.lesson.LessonStorage`;
* subsequent runs short-circuit to pure replay — an active lesson is returned
  with no LLM activity ("discover once, replay forever").

The ``html`` argument is advisory here: the agent drives its own browser session
from ``url``.
"""

from __future__ import annotations

import logging
from typing import Any

from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_agent import MCPDiscoveryAgent, MCPDiscoveryDraft
from yosoi.core.verification.semantic import SemanticValidator, field_rules_for_contract
from yosoi.models.contract import Contract
from yosoi.models.replay import (
    DiscoveryLesson,
    LessonKey,
    LessonProvenance,
    LessonValidation,
    VerifyReport,
    utc_now,
)
from yosoi.models.selectors import FieldSelectors
from yosoi.models.snapshot import SelectorSnapshot, selector_dict_to_snapshot, snapshot_to_selector_dict
from yosoi.prompts.discovery import FieldFeedback
from yosoi.storage.lesson import LessonStorage
from yosoi.utils import observability as obs
from yosoi.utils.signatures import contract_signature

# Selector dict: field name → {primary, fallback, tertiary} selectors.
SelectorMap = dict[str, dict[str, Any]]

logger = logging.getLogger(__name__)


class MCPDiscoveryOrchestrator:
    """Drives an MCP discovery session and persists the result as a lesson.

    Attributes:
        model_name: LLM model name.
        provider: LLM provider name.
        console: Rich console for output.

    """

    def __init__(
        self,
        contract: type[Contract],
        llm_config: LLMConfig,
        console: Console | None = None,
        *,
        lesson_storage: LessonStorage | None = None,
        verify_threshold: float = 1.0,
        agent: MCPDiscoveryAgent | None = None,
    ):
        """Initialise the orchestrator.

        Args:
            contract: Contract subclass defining the fields to discover.
            llm_config: LLM provider and model configuration.
            console: Optional Rich console for output.
            lesson_storage: Lesson cache (read for replay, written after discovery).
            verify_threshold: Minimum validation pass-ratio for a lesson to be
                considered active. Defaults to 1.0.
            agent: Optional pre-built MCP agent (injected in tests).

        """
        self._contract = contract
        self._agent = agent if agent is not None else MCPDiscoveryAgent(llm_config, console=console)
        self._lessons = lesson_storage if lesson_storage is not None else LessonStorage()
        self._validator = SemanticValidator()
        self._field_rules = field_rules_for_contract(contract)
        self._threshold = verify_threshold
        self.console = console or Console()
        self.model_name = llm_config.model_name
        self.provider = llm_config.provider

    async def discover_selectors(
        self,
        html: str,
        url: str | None = None,
        *,
        stale_fields: set[str] | None = None,
        feedback: dict[str, FieldFeedback] | None = None,
        force: bool = False,
    ) -> SelectorMap | None:
        """Discover selectors by driving the live page, or replay a cached lesson.

        Args:
            html: Advisory only — the agent drives its own browser from ``url``.
            url: Target page URL (required for MCP discovery).
            stale_fields: Accepted for signature parity with the static
                orchestrator; partial rediscovery is not used by the MCP path.
            feedback: Accepted for parity; the agent self-corrects in-loop via
                the ``check_value`` tool, so external feedback is unused.
            force: Force fresh discovery, ignoring any cached lesson.

        Returns:
            SelectorMap with discovered selectors, or None if discovery failed.

        """
        # Accepted for call-site parity with the static orchestrator (Pipeline
        # passes these as args/kwargs). ``html`` is advisory — the agent drives
        # its own browser from ``url`` — and the agent self-corrects in-loop with
        # whole-page discovery, so partial rediscovery / external feedback do not
        # apply here.
        del html, stale_fields, feedback
        if not url:
            logger.warning('MCP discovery requires a URL; none provided')
            return None

        domain = obs.normalize_user_id(url) or 'unknown'
        key = LessonKey(domain=domain, contract_signature=contract_signature(self._contract))

        if not force:
            cached = await self._lessons.load_active(key)
            if cached is not None:
                self.console.print('[success]Replaying cached MCP lesson (no LLM)[/success]')
                logger.info('MCP replay-first hit url=%s domain=%s', url, domain)
                return self._lesson_to_selector_map(cached)

        with obs.span('mcp_orchestrator_discover_selectors', url=url, domain=domain):
            return await self._discover_fresh(url=url, key=key)

    async def _discover_fresh(self, *, url: str, key: LessonKey) -> SelectorMap | None:
        fields = self._contract.field_descriptions()
        draft = await self._agent.discover(url=url, fields=fields, field_rules=self._field_rules)

        merged, snapshots, sample_values, rejected = self._distill(draft)

        if not any(name != 'root' for name in merged):
            obs.warning('MCP discovery produced no verified fields', url=url)
            return None

        verified_fields = len(sample_values)
        lesson = DiscoveryLesson(
            key=key,
            replay_plan=draft.replay_plan,
            selectors=snapshots,
            validation=LessonValidation(
                report=VerifyReport(passed=verified_fields, failed=rejected),
                threshold=self._threshold,
                sample_values=sample_values,
            ),
            provenance=LessonProvenance(model_name=self.model_name, provider=self.provider),
        )
        await self._lessons.save(lesson)

        self.console.print(
            f'[success]MCP discovery verified {verified_fields} fields (rejected={rejected}) — lesson saved[/success]'
        )
        logger.info('MCP discovery complete url=%s verified=%d rejected=%d', url, verified_fields, rejected)
        return merged

    def _distill(
        self,
        draft: MCPDiscoveryDraft,
    ) -> tuple[SelectorMap, dict[str, SelectorSnapshot], dict[str, Any], int]:
        """Final-gate the draft's findings and build the selector map + snapshots.

        Each finding's observed value is re-checked against its semantic rule as a
        backstop on the agent's in-loop ``check_value`` calls — only validated
        extractions become snapshot entries.
        """
        now = utc_now()
        merged: SelectorMap = {}
        snapshots: dict[str, SelectorSnapshot] = {}
        sample_values: dict[str, Any] = {}
        rejected = 0

        for finding in draft.fields:
            rule = self._field_rules.get(finding.field)
            if rule is not None:
                issues = self._validator.validate({finding.field: finding.sample_value}, {finding.field: rule})
                if issues:
                    rejected += 1
                    logger.info('Rejected MCP finding for %s: %s', finding.field, issues[0].reason)
                    continue
            entry = FieldSelectors(primary=finding.selector).model_dump(exclude_none=True)
            merged[finding.field] = entry
            snapshots[finding.field] = selector_dict_to_snapshot(entry, discovered_at=now)
            sample_values[finding.field] = finding.sample_value

        if draft.root is not None:
            root_entry = {'primary': draft.root.model_dump(exclude_none=True)}
            merged['root'] = root_entry
            snapshots['root'] = selector_dict_to_snapshot(root_entry, discovered_at=now)

        return merged, snapshots, sample_values, rejected

    @staticmethod
    def _lesson_to_selector_map(lesson: DiscoveryLesson) -> SelectorMap:
        """Reconstruct a SelectorMap from a persisted lesson's snapshots."""
        merged: SelectorMap = {}
        for name, snap in lesson.selectors.items():
            data = snapshot_to_selector_dict(snap)
            if data:
                merged[name] = data
        return merged
