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
    ActKind,
    DiscoveryLesson,
    LessonKey,
    LessonProvenance,
    LessonValidation,
    ReplayAct,
    ReplayNode,
    ReplayPlan,
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


def _navigate_plan(url: str) -> ReplayPlan:
    """Build the minimal replay plan: navigate to the target page.

    Single-page targets only need the page loaded before extraction; the cached
    selectors do the rest. Richer interaction recording is a separate concern.

    FUTURE(CAS-103): plans are NAVIGATE-only today. The Act/Assert runtime in
    :mod:`yosoi.core.replay.runtime` (``execute_plan``/``verify_plan``) can already
    replay CLICK/SCROLL/WAIT/EVAL, but no learn-time code emits a multi-step plan
    here yet and the replay path (:meth:`_lesson_to_selector_map`) never executes
    the stored plan. That runtime is parked scaffolding awaiting interaction
    capture — intentionally unwired, not dead code. Greps for ``execute_plan``
    callers will come up empty until CAS-103 connects these two halves.
    """
    return ReplayPlan(
        nodes=[ReplayNode(id='navigate', intent='open the target page', act=ReplayAct(kind=ActKind.NAVIGATE, url=url))]
    )


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
        # ``stale_fields`` / ``feedback`` are accepted for call-site parity with
        # the static orchestrator (Pipeline passes them as kwargs). The MCP agent
        # self-corrects in-loop and does whole-page discovery, so neither partial
        # rediscovery nor external feedback applies here. ``html`` IS used — as the
        # independent re-extraction oracle in the validation gate (see _distill).
        del stale_fields, feedback
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
            return await self._discover_fresh(url=url, key=key, html=html)

    async def _discover_fresh(self, *, url: str, key: LessonKey, html: str) -> SelectorMap | None:
        fields = self._contract.field_descriptions()
        draft = await self._agent.discover(url=url, fields=fields, field_rules=self._field_rules)

        merged, snapshots, sample_values, rejected = self._distill(draft, html)

        if not any(name != 'root' for name in merged):
            obs.warning('MCP discovery produced no verified fields', url=url)
            return None

        verified_fields = len(sample_values)
        lesson = DiscoveryLesson(
            key=key,
            # FUTURE(CAS-103): navigate-only plan; multi-step interaction capture pending.
            replay_plan=_navigate_plan(url),
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
        html: str,
    ) -> tuple[SelectorMap, dict[str, SelectorSnapshot], dict[str, Any], int]:
        """Final-gate the draft's findings and build the selector map + snapshots.

        The gate validates an *independently* re-extracted value, not the value
        the model reported: when ``html`` is available the discovered selector is
        re-run against it (via the real :class:`ContentExtractor`) and that value
        is what the :class:`SemanticValidator` checks. This keeps a hallucinated
        ``sample_value`` from ever being cached as a lesson. If cleaned HTML was
        supplied and Yosoi cannot replay the selector locally, the finding is
        rejected even if the live browser observed a plausible value. Only
        replayable, validated findings become snapshot entries.
        """
        now = utc_now()
        merged: SelectorMap = {}
        snapshots: dict[str, SelectorSnapshot] = {}
        sample_values: dict[str, Any] = {}
        rejected = 0

        candidates = {f.field: FieldSelectors(primary=f.selector).model_dump(exclude_none=True) for f in draft.fields}
        replay_candidates = dict(candidates)
        if draft.root is not None:
            root = draft.root.model_dump(exclude_none=True)
            replay_candidates = {name: {**entry, 'root': root} for name, entry in candidates.items()}
        has_replay_html = bool(html.strip())
        reextracted = self._reextract(html, replay_candidates) if has_replay_html else {}

        for finding in draft.fields:
            reext = reextracted.get(finding.field)
            if has_replay_html and reext is None:
                rejected += 1
                logger.info('Rejected MCP finding for %s: selector did not replay against cleaned HTML', finding.field)
                continue
            value = reext if reext is not None else finding.sample_value
            rule = self._field_rules.get(finding.field)
            if rule is not None:
                issues = self._validator.validate({finding.field: value}, {finding.field: rule})
                if issues:
                    rejected += 1
                    logger.info('Rejected MCP finding for %s: %s', finding.field, issues[0].reason)
                    continue
            entry = candidates[finding.field]
            merged[finding.field] = entry
            snapshots[finding.field] = selector_dict_to_snapshot(entry, discovered_at=now)
            sample_values[finding.field] = value

        if draft.root is not None:
            root_entry = {'primary': draft.root.model_dump(exclude_none=True)}
            merged['root'] = root_entry
            snapshots['root'] = selector_dict_to_snapshot(root_entry, discovered_at=now)

        return merged, snapshots, sample_values, rejected

    def _reextract(self, html: str, candidates: SelectorMap) -> dict[str, str]:
        """Independently re-run each discovered selector against the page HTML.

        Returns field -> first extracted value (stringified). Fields whose
        selector matches nothing are omitted; callers decide whether missing
        fields are acceptable for their context.
        """
        from rich.console import Console as _Console

        from yosoi.core.extraction.extractor import ContentExtractor
        from yosoi.models.selectors import SelectorLevel

        extractor = ContentExtractor(console=_Console(quiet=True), contract=self._contract)
        if not candidates:
            return {}
        try:
            extracted = extractor.extract_content_with_html('', html, candidates, max_level=SelectorLevel.VISUAL)
        except Exception as exc:  # noqa: BLE001 — extraction is a best-effort oracle, never fatal
            logger.info('Re-extraction oracle failed, falling back to reported values: %s', exc)
            return {}

        out: dict[str, str] = {}
        for name, raw in (extracted or {}).items():
            value: object = raw[0] if isinstance(raw, list) and raw else raw
            if isinstance(value, dict):
                value = next(iter(value.values()), None)
            if value is not None and not isinstance(value, list) and str(value).strip():
                out[name] = str(value)
        return out

    @staticmethod
    def _lesson_to_selector_map(lesson: DiscoveryLesson) -> SelectorMap:
        """Reconstruct a SelectorMap from a persisted lesson's snapshots.

        Replay is selector-only: ``lesson.replay_plan`` is deliberately NOT executed
        here (see :func:`_navigate_plan`). Wiring ``verify_plan`` in front of this for
        interaction-gated pages is FUTURE(CAS-103).
        """
        merged: SelectorMap = {}
        for name, snap in lesson.selectors.items():
            data = snapshot_to_selector_dict(snap)
            if data:
                merged[name] = data
        return merged
