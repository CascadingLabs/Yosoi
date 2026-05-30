"""JS action script discovery — iterative LLM-driven generation with live DOM access."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig, create_model
from yosoi.prompts.js_discovery import (
    PRE_PROBE_JS,
    SYSTEM_PROMPT,
    JsDiscoveryDeps,
    build_user_prompt,
)
from yosoi.storage.js_scripts import JsScriptEntry, JsScriptStorage
from yosoi.utils import observability as obs

if TYPE_CHECKING:
    from yosoi.core.fetcher.voiddriver import _VoidCrawlFetcher

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_REPR_MAX = 200  # max chars when showing eval output in feedback


def _repr(value: Any) -> str:
    """Short human-readable repr of a JS eval result for LLM feedback."""
    raw = repr(value)
    return raw if len(raw) <= _REPR_MAX else raw[:_REPR_MAX] + '…'


class JsDiscoveryOrchestrator:
    """Discovers and caches JS extraction scripts for action fields.

    For each contract field annotated with ``ys.js(description=...)`` but
    no pre-authored script, this orchestrator:

    1. Opens a live browser tab via the fetcher's ``browse()`` context manager.
    2. Runs a pre-probe eval to collect DOM context (script srcs, window keys, …).
    3. Calls the LLM to generate a JS IIFE expression for the field.
    4. Executes the generated script on the live tab to verify it returns a
       non-null, non-error result.
    5. If verification fails, feeds the error/output back to the LLM and retries
       (up to ``max_attempts`` times).
    6. Caches verified scripts in ``.yosoi/js_scripts/`` so replay never calls
       the LLM again for that domain+contract pair.
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        storage: JsScriptStorage,
        console: Console | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            llm_config: LLM provider and model configuration.
            storage: JS script cache storage.
            console: Optional Rich console for output.
            max_attempts: Maximum LLM+verify iterations per field.

        """
        self._llm_config = llm_config
        self._storage = storage
        self._console = console or Console()
        self._max_attempts = max_attempts
        self.model_name = llm_config.model_name

        model = create_model(llm_config)
        self._agent: Agent[JsDiscoveryDeps, str] = Agent(
            model,
            deps_type=JsDiscoveryDeps,
            output_type=str,
            system_prompt=SYSTEM_PROMPT,
            instrument=obs.instrumentation_settings(),
        )

    async def discover(
        self,
        url: str,
        domain: str,
        contract_sig: str,
        fields: dict[str, str],  # {field_name: description}
        fetcher: _VoidCrawlFetcher,
    ) -> dict[str, str]:
        """Discover JS scripts for all undiscovered action fields.

        Opens one browser tab for the whole batch (one page load, N fields).

        Args:
            url: URL to open in the browser tab.
            domain: Bare domain string for cache keying.
            contract_sig: Contract signature for cache keying.
            fields: Mapping of {field_name: description} for undiscovered fields.
            fetcher: An L2 fetcher whose browser pool is already started.

        Returns:
            Mapping of {field_name: verified_script} for successfully discovered fields.
            Fields that could not be discovered after max_attempts are omitted.

        """
        if not fields:
            return {}

        self._console.print(f'[dim]  ↻ JS discovery: {len(fields)} field(s) on {domain}[/dim]')

        discovered: dict[str, str] = {}

        async with fetcher.browse(url) as tab:
            dom_context = await self._pre_probe(tab)
            if dom_context is None:
                self._console.print('[warning]  ✗ JS discovery: pre-probe eval failed[/warning]')
                return {}

            for field_name, description in fields.items():
                script = await self._discover_field(tab, field_name, description, dom_context)
                if script:
                    discovered[field_name] = script
                    self._console.print(f'[success]  ✓ JS discovery: {field_name}[/success]')
                else:
                    self._console.print(
                        f'[warning]  ✗ JS discovery: {field_name} — no valid script after '
                        f'{self._max_attempts} attempts[/warning]'
                    )

        if discovered:
            await self._cache(domain, contract_sig, fields, discovered)

        return discovered

    async def _pre_probe(self, tab: Any) -> dict[str, Any] | None:
        """Run the pre-probe eval to collect live DOM context."""
        try:
            result = await tab.eval_js(PRE_PROBE_JS)
            if isinstance(result, dict):
                return result
            logger.warning('JS discovery pre-probe returned non-dict: %r', result)
            return {}
        except Exception as exc:  # noqa: BLE001
            logger.warning('JS discovery pre-probe failed: %s', exc)
            return None

    async def _discover_field(
        self,
        tab: Any,
        field_name: str,
        description: str,
        dom_context: dict[str, Any],
    ) -> str | None:
        """Run the iterative LLM + verify loop for one field."""
        previous_script: str | None = None
        previous_result: str | None = None

        for attempt in range(1, self._max_attempts + 1):
            deps = JsDiscoveryDeps(
                field_name=field_name,
                field_description=description,
                dom_context=dom_context,
                previous_attempt=previous_script,
                previous_result=previous_result,
            )

            with obs.span(
                f'js_discovery[{field_name}]',
                field=field_name,
                attempt=attempt,
            ):
                script = await self._call_llm(deps, field_name, attempt)

            if not script:
                continue

            script = script.strip()
            verified, output = await self._verify(tab, script, field_name)
            if verified:
                return script

            previous_script = script
            previous_result = output

        return None

    async def _call_llm(self, deps: JsDiscoveryDeps, field_name: str, attempt: int) -> str | None:
        """Call the LLM agent and return the generated script string."""
        try:
            result = await self._agent.run(
                build_user_prompt(deps),
                deps=deps,
            )
            script = result.output.strip()
            # Strip accidental markdown code fences
            if script.startswith('```'):
                lines = script.splitlines()
                script = '\n'.join(ln for ln in lines if not ln.startswith('```')).strip()
            return script or None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'JS discovery LLM call failed (field=%s attempt=%d): %s',
                field_name,
                attempt,
                exc,
            )
            return None

    async def _verify(self, tab: Any, script: str, field_name: str) -> tuple[bool, str | None]:
        """Execute the script on the live tab and check the result.

        Returns:
            (verified, repr_of_output) — verified is True if the script ran
            without error and returned a non-null, non-undefined value.

        """
        try:
            output = await tab.eval_js(script)
            if output is None:
                return False, 'null'
            return True, _repr(output)
        except Exception as exc:  # noqa: BLE001
            logger.debug('JS script verification failed (field=%s): %s', field_name, exc)
            return False, str(exc)[:_REPR_MAX]

    async def _cache(
        self,
        domain: str,
        contract_sig: str,
        descriptions: dict[str, str],
        discovered: dict[str, str],
    ) -> None:
        """Persist verified scripts to the JS script cache."""
        entries = {
            field: JsScriptEntry(
                script=script,
                description=descriptions.get(field, ''),
                discovered_at=_utc_now(),
                verified=True,
                model=self.model_name,
                attempts=self._max_attempts,
            )
            for field, script in discovered.items()
        }
        await self._storage.save_entries(domain, contract_sig, entries)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
