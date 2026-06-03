"""Discovery mixin — selector discovery, MCP escalation, JS actions, semantic refinement.

Contains: _discover, _discover_via_mcp, _ensure_mcp_discovery, _discover_js_actions,
_resolve_js_scripts, _maybe_escalate, _escalate_to_mcp, _semantic_refine,
_required_discovery_fields, _representative_item, _unsatisfied_required,
_semantic_issues, _selector_values, _js_action_scripts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from rich.console import Console
from tenacity import RetryCallState, RetryError

from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability
from yosoi.utils.retry import get_async_retryer

if TYPE_CHECKING:
    from yosoi.core.discovery import DiscoveryOrchestrator, MCPDiscoveryOrchestrator
    from yosoi.core.fetcher import HTMLFetcher
    from yosoi.core.fetcher.dom.ax import AxSnapshot
    from yosoi.core.verification import FieldSemanticIssue
    from yosoi.models.contract import Contract
    from yosoi.models.results import ContentItems, ContentMap

logger = logging.getLogger(__name__)


class PipelineDiscoveryMixin:
    """Methods for AI selector discovery, MCP escalation, and semantic validation."""

    # Pipeline attributes referenced here
    console: Console
    contract: type[Contract]
    discovery: DiscoveryOrchestrator
    js_storage: Any
    selector_level: SelectorLevel
    debug: Any
    verifier: Any
    semantic_validator: Any
    _field_rules: Any
    _mcp_discovery: MCPDiscoveryOrchestrator | None
    _mcp_llm_config: Any
    _replay_verify_threshold: float
    _force_mcp: bool
    _discovery_strategy: Any
    _contract_sig: str
    _js_discovery_orchestrator: Any

    def _js_action_scripts(self) -> dict[str, str]:
        """Return {field: js_script} for JS action fields with a hand-authored script."""
        return {
            name: cfg['script']
            for name, cfg in self.contract.action_fields().items()
            if cfg.get('type') == 'js' and cfg.get('script')
        }

    async def _resolve_js_scripts(self, domain: str) -> dict[str, str]:
        """Return {field: script} for ALL JS action fields — hand-authored and cached discovered."""
        scripts = dict(self._js_action_scripts())
        undiscovered = self.contract.undiscovered_action_fields()
        if undiscovered:
            cached = await self.js_storage.get_scripts(domain, undiscovered)
            scripts.update(cached)
        return scripts

    async def _discover_js_actions(self, url: str, domain: str, fetcher: HTMLFetcher) -> None:
        """Run JS discovery for action fields that lack a cached script."""
        undiscovered = self.contract.undiscovered_action_fields()
        if not undiscovered:
            return
        cached = await self.js_storage.get_scripts(domain, undiscovered)
        missing = {k: v for k, v in undiscovered.items() if k not in cached}
        if not missing:
            return
        if not fetcher.supports_browse:
            self.console.print(
                '[warning]⚠ JS discovery skipped — fetcher has no live browser tab; '
                'switch to fetcher_type="headless" or "waterfall" for ys.js discovery[/warning]'
            )
            return
        from yosoi.core.discovery.js_orchestrator import JsDiscoveryOrchestrator

        if not hasattr(fetcher, 'browse'):
            logger.debug('JS discovery skipped — fetcher does not implement browse()')
            return
        if self._js_discovery_orchestrator is None:
            self._js_discovery_orchestrator = JsDiscoveryOrchestrator(
                llm_config=self._llm_config,  # type: ignore[attr-defined]
                storage=self.js_storage,
                console=self.console,
            )
        with observability.span('js_discovery', url=url, fields=len(missing)):
            await self._js_discovery_orchestrator.discover(
                url=url,
                domain=domain,
                fields=missing,
                fetcher=fetcher,
                field_coercer=self.contract.coerce_field,
            )

    def _ensure_mcp_discovery(self) -> MCPDiscoveryOrchestrator:
        """Lazily build the interaction-driven MCP discovery orchestrator."""
        from yosoi.core.discovery import MCPDiscoveryOrchestrator

        if self._mcp_discovery is None:
            self._mcp_discovery = MCPDiscoveryOrchestrator(
                contract=self.contract,
                llm_config=self._mcp_llm_config,
                console=self.console,
                verify_threshold=self._replay_verify_threshold,
            )
        return self._mcp_discovery

    async def _discover_via_mcp(
        self, url: str, cleaned_html: str, force: bool = False
    ) -> tuple[dict[str, Any] | None, bool]:
        """Run interaction-driven (MCP) discovery, returning ``(selectors, used_llm)``."""
        self.console.print('[step]Step 2: Interaction-driven discovery — driving a live browser...[/step]')
        overrides = self.contract.get_selector_overrides()
        try:
            selectors = await self._ensure_mcp_discovery().discover_selectors(cleaned_html, url, force=force)
        except Exception as exc:  # noqa: BLE001
            observability.warning('MCP discovery failed', url=url, error=str(exc))
            return None, True
        if selectors:
            selectors.update(overrides)
        return selectors, True

    async def _discover(
        self,
        url: str,
        cleaned_html: str,
        max_retries: int = 3,
        force: bool = False,
        ax_snapshot: AxSnapshot | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Discover CSS selectors with AI, using fallback heuristics if needed."""
        overrides = self.contract.get_selector_overrides()
        if overrides:
            override_fields = ', '.join(f'`{f}`' for f in overrides)
            self.console.print(f'[info]  ↳ Using selector overrides for: {override_fields}[/info]')

        if not self.contract.field_descriptions():
            self.console.print('[step]Step 2: All fields have selector overrides — skipping AI discovery[/step]')
            logger.info('Skipping AI discovery — all fields overridden url=%s', url)
            await self.debug.save_debug_selectors(url, overrides)
            return overrides, False

        def before_ai_sleep_log(retry_state: RetryCallState) -> None:
            attempt = retry_state.attempt_number
            if attempt >= 1:
                self.console.print(f'[warning]AI retry attempt {attempt}/{max_retries}...[/warning]')
                observability.warning('Retrying AI discovery', url=url, attempt=attempt)

        try:
            retryer = get_async_retryer(
                max_attempts=max_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(Exception,),
                log_callback=before_ai_sleep_log,
                reraise=False,
            )

            async for attempt in retryer:
                with attempt:
                    self.console.print(
                        f'[step]Step 2: AI analyzing HTML (attempt {attempt.retry_state.attempt_number}/{max_retries})...[/step]'
                    )

                    selectors = await self.discovery.discover_selectors(
                        cleaned_html, url, force=force, ax_snapshot=ax_snapshot
                    )

                    if selectors:
                        selectors.update(overrides)
                        self.console.print(f'[success]Discovered selectors for {len(selectors)} fields[/success]')
                        await self.debug.save_debug_selectors(url, selectors)

                        if attempt.retry_state.attempt_number > 1:
                            self.console.print(
                                f'[success]AI retry successful on attempt {attempt.retry_state.attempt_number}[/success]'
                            )
                        return selectors, True

                    self.console.print('[danger]AI discovery failed[/danger]')
                    logger.warning('AI discovery failed for %s', url)
                    raise Exception('AI discovery failed')

        except RetryError:
            pass
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            pass

        self.console.print(f'[danger]All {max_retries} AI attempts failed[/danger]')
        observability.warning('All AI attempts failed', url=url)
        return None, False

    def _required_discovery_fields(self) -> set[str]:
        """Flat names of required (no-default) contract discovery fields."""
        from yosoi.models.contract import Contract as _Contract

        required: set[str] = set()
        for name, fi in self.contract.model_fields.items():
            annotation = fi.annotation
            if isinstance(annotation, type) and issubclass(annotation, _Contract):
                for child_name, child_fi in annotation.model_fields.items():
                    if child_fi.is_required():
                        required.add(f'{name}_{child_name}')
            elif fi.is_required():
                required.add(name)
        return required

    @staticmethod
    def _representative_item(extracted: ContentMap | ContentItems) -> ContentMap:
        """Return a representative extracted item (first non-empty for multi-item)."""
        if isinstance(extracted, list):
            return next((item for item in extracted if item), {})
        return extracted or {}

    def _semantic_issues(self, extracted: ContentMap | ContentItems) -> list[FieldSemanticIssue]:
        """Run the type-aware semantic validator on a representative extracted item."""
        if isinstance(extracted, list):
            item = next((i for i in extracted if i), None)
            if item is None:
                return []
        else:
            item = extracted
        return self.semantic_validator.validate(item, self._field_rules)

    def _unsatisfied_required(self, extracted: ContentMap | ContentItems) -> set[str]:
        """Required fields static discovery failed to extract a well-shaped value for."""
        required = self._required_discovery_fields() - set(self.contract.get_selector_overrides())
        if not required:
            return set()
        item = self._representative_item(extracted)
        present = {k for k, v in item.items() if v not in (None, '', [], {})}
        missing = required - present
        bad = {issue.field for issue in self._semantic_issues(extracted)} & required
        return missing | bad

    @staticmethod
    def _selector_values(entry: dict[str, Any] | None) -> tuple[str, ...]:
        """Collect the non-empty primary/fallback/tertiary selector strings from an entry."""
        if not isinstance(entry, dict):
            return ()
        values: list[str] = []
        for key in ('primary', 'fallback', 'tertiary'):
            candidate = entry.get(key)
            if isinstance(candidate, str) and candidate:
                values.append(candidate)
            elif isinstance(candidate, dict):
                value = candidate.get('value')
                if isinstance(value, str) and value:
                    values.append(value)
        return tuple(dict.fromkeys(values))

    async def _semantic_refine(
        self,
        url: str,
        cleaned_html: str,
        raw_html: str,
        verified: dict[str, Any],
        container_selector: str | None,
        extracted: ContentMap | ContentItems,
        max_retries: int,
    ) -> tuple[ContentMap | ContentItems, dict[str, Any]]:
        """Re-discover fields whose extracted values fail type-aware semantic checks."""
        from yosoi.prompts.discovery import FieldFeedback

        for attempt in range(max_retries):
            issues = self._semantic_issues(extracted)
            if not issues:
                return extracted, verified

            feedback = {
                issue.field: FieldFeedback(
                    message=issue.as_feedback(),
                    failed_selectors=self._selector_values(verified.get(issue.field)),
                )
                for issue in issues
            }
            failing = set(feedback)
            self.console.print(
                f'[warning]⚠ Semantic check flagged {", ".join(sorted(failing))} — '
                f're-discovering (attempt {attempt + 1}/{max_retries})[/warning]'
            )

            fresh = await self.discovery.discover_selectors(
                cleaned_html, url, stale_fields=failing, feedback=feedback, force=True
            )
            if not fresh:
                break

            reverified = self._verify(url, cleaned_html, fresh, skip_verification=False)  # type: ignore[attr-defined]
            improved = {k: v for k, v in (reverified or {}).items() if k != 'root'}
            if not improved:
                break

            verified.update(improved)
            re_extracted = self._extract(url, raw_html, verified, container_selector)  # type: ignore[attr-defined]
            if not re_extracted:
                break
            extracted = re_extracted

        remaining = self._semantic_issues(extracted)
        if remaining:
            fields = ', '.join(sorted({issue.field for issue in remaining}))
            self.console.print(f'[warning]⚠ Semantic issues remain after {max_retries} retries: {fields}[/warning]')
        return extracted, verified

    async def _maybe_escalate(
        self,
        url: str,
        domain: str,
        cleaned_html: str,
        raw_html: str,
        verified: dict[str, Any],
        container_selector: str | None,
        root_entry: dict[str, Any] | None,
        extracted: ContentMap | ContentItems | None,
    ) -> tuple[ContentMap | ContentItems, dict[str, Any], dict[str, Any] | None, str | None, bool]:
        """Escalate to MCP discovery when static left a required field unsatisfied."""
        current = extracted or {}
        unmet = self._unsatisfied_required(current)
        if not unmet:
            return current, verified, root_entry, container_selector, False

        with observability.span('discover_escalate', url=url, unmet=len(unmet)):
            self.console.print(
                f'[warning]⚠ Static discovery left required field(s) unmet '
                f'({", ".join(sorted(unmet))}) — escalating to interaction-driven discovery[/warning]'
            )
            current, verified, root_entry, improved = await self._escalate_to_mcp(
                url, cleaned_html, raw_html, verified, container_selector, root_entry, current, unmet
            )
            container_selector = self._root_value(root_entry)  # type: ignore[attr-defined]
            if improved:
                await self._discovery_strategy.save(domain, self._contract_sig, 'mcp')
        return current, verified, root_entry, container_selector, improved

    async def _escalate_to_mcp(
        self,
        url: str,
        cleaned_html: str,
        raw_html: str,
        verified: dict[str, Any],
        container_selector: str | None,
        root_entry: dict[str, Any] | None,
        extracted: ContentMap | ContentItems,
        unmet: set[str],
    ) -> tuple[ContentMap | ContentItems, dict[str, Any], dict[str, Any] | None, bool]:
        """Drive MCP discovery once and merge selectors that improve extraction."""
        try:
            fresh = await self._ensure_mcp_discovery().discover_selectors(cleaned_html, url, force=True)
        except Exception as exc:  # noqa: BLE001
            observability.warning('MCP discovery escalation failed', url=url, error=str(exc))
            return extracted, verified, root_entry, False
        if not fresh:
            return extracted, verified, root_entry, False

        mcp_root = self._resolve_root(fresh)  # type: ignore[attr-defined]
        if mcp_root:
            root_entry = mcp_root
            container_selector = self._root_value(root_entry) or container_selector  # type: ignore[attr-defined]

        reverified = self._verify(url, cleaned_html, fresh, skip_verification=False) or {}  # type: ignore[attr-defined]
        merged = {k: v for k, v in reverified.items() if k != 'root'}
        if merged:
            verified.update(merged)
            re_extracted = self._extract(url, raw_html, verified, container_selector)  # type: ignore[attr-defined]
            if re_extracted:
                extracted = re_extracted

        improved = bool(unmet - self._unsatisfied_required(extracted))
        return extracted, verified, root_entry, improved
