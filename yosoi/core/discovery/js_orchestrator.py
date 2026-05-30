"""JS action script discovery — iterative LLM-driven generation with live DOM access."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from rich.console import Console
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_none

from yosoi.core.discovery.config import LLMConfig, create_model
from yosoi.core.replay.runtime import _eval as _tab_eval
from yosoi.prompts.js_discovery import (
    PRE_PROBE_JS,
    SYSTEM_PROMPT,
    JsDiscoveryDeps,
    build_user_prompt,
)
from yosoi.storage.js_scripts import JsScriptEntry, JsScriptStorage
from yosoi.utils import observability as obs

if TYPE_CHECKING:
    from yosoi.core.fetcher.base import HTMLFetcher

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_REPR_MAX = 200  # max chars when showing eval output in LLM feedback


def _repr(value: Any) -> str:
    """Short human-readable repr of a JS eval result for LLM feedback."""
    raw = repr(value)
    return raw if len(raw) <= _REPR_MAX else raw[:_REPR_MAX] + '…'


class _VerificationFailed(Exception):
    """Raised inside the tenacity retry loop when a script fails live-DOM verification."""

    def __init__(self, script: str | None, output: str | None) -> None:
        self.script = script
        self.output = output


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
       (managed by tenacity, up to ``max_attempts`` times, no sleep between attempts).
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
        fetcher: HTMLFetcher,
    ) -> dict[str, str]:
        """Discover JS scripts for all undiscovered action fields.

        Opens one browser tab for the whole batch (one page load, N fields).

        Args:
            url: URL to open in the browser tab.
            domain: Bare domain string for cache keying.
            contract_sig: Contract signature for cache keying.
            fields: Mapping of {field_name: description} for undiscovered fields.
            fetcher: An L2 fetcher that implements ``browse()`` (supports_browse=True).

        Returns:
            Mapping of {field_name: verified_script} for successfully discovered fields.
            Fields that could not be discovered after max_attempts are omitted.

        """
        if not fields:
            return {}

        self._console.print(f'[dim]  ↻ JS discovery: {len(fields)} field(s) on {domain}[/dim]')

        discovered: dict[str, str] = {}
        attempt_counts: dict[str, int] = {}

        async with fetcher.browse(url) as tab:  # type: ignore[attr-defined]
            dom_context = await self._pre_probe(tab)
            if dom_context is None:
                self._console.print('[warning]  ✗ JS discovery: pre-probe eval failed[/warning]')
                return {}

            for field_name, description in fields.items():
                result = await self._discover_field(tab, field_name, description, dom_context)
                if result is not None:
                    script, attempts = result
                    discovered[field_name] = script
                    attempt_counts[field_name] = attempts
                    self._console.print(
                        f'[success]  ✓ JS discovery: {field_name} (attempt {attempts}/{self._max_attempts})[/success]'
                    )
                else:
                    self._console.print(
                        f'[warning]  ✗ JS discovery: {field_name} — no valid script after '
                        f'{self._max_attempts} attempts[/warning]'
                    )

        if discovered:
            await self._cache(domain, contract_sig, fields, discovered, attempt_counts)

        return discovered

    async def _pre_probe(self, tab: Any) -> dict[str, Any] | None:
        """Run the pre-probe eval to collect live DOM context."""
        try:
            result = await _tab_eval(tab, PRE_PROBE_JS)
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
    ) -> tuple[str, int] | None:
        """Run the tenacity-managed LLM+verify loop for one field.

        Returns:
            ``(verified_script, attempt_count)`` on success, ``None`` after exhausting
            all attempts without a verified script.

        """
        state: dict[str, str | None] = {'script': None, 'result': None}

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_none(),  # LLM generation loop — no sleep needed between attempts
                retry=retry_if_exception_type(_VerificationFailed),
                reraise=True,
            ):
                with attempt:
                    attempt_num = attempt.retry_state.attempt_number
                    deps = JsDiscoveryDeps(
                        field_name=field_name,
                        field_description=description,
                        dom_context=dom_context,
                        previous_attempt=state['script'],
                        previous_result=state['result'],
                    )
                    with obs.span(
                        f'js_discovery[{field_name}]',
                        field=field_name,
                        attempt=attempt_num,
                    ) as js_span:
                        obs.annotate_llm(js_span, provider=self._llm_config.provider, model=self.model_name)
                        script = await self._call_llm(deps, field_name, attempt_num)

                    if not script:
                        raise _VerificationFailed(None, 'LLM returned empty script')

                    script = script.strip()
                    verified, output = await self._verify(tab, script, field_name)
                    if not verified:
                        state['script'] = script
                        state['result'] = output
                        raise _VerificationFailed(script, output)

                    return script, attempt_num

        except (_VerificationFailed, RetryError):
            pass

        return None

    async def _call_llm(self, deps: JsDiscoveryDeps, field_name: str, attempt: int) -> str | None:
        """Call the LLM agent and return the generated script string."""
        try:
            result = await self._agent.run(build_user_prompt(deps), deps=deps)
            script = result.output.strip()
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

        A script is considered verified when it runs without exception AND
        returns a non-None value.  Note that ``False``, ``[]``, ``""``, and
        ``0`` are all valid return values (e.g. "no Alita on this page" or
        "empty competitor list") and are treated as verified — they are
        semantically meaningful results, not failures.  Only JavaScript
        ``null`` (Python ``None``) is treated as "not found / failed".

        Returns:
            ``(True, repr_of_output)`` if verified, ``(False, error_or_null)`` otherwise.

        """
        try:
            output = await _tab_eval(tab, script)
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
        attempt_counts: dict[str, int],
    ) -> None:
        """Persist verified scripts to the JS script cache."""
        # FUTURE: this save_entries is the write end of the JS-discovery
        # read-modify-write race. When the per-domain ``write_lock`` is threaded
        # in (see Pipeline._discover_js_actions), serialise this write under it so
        # concurrent same-domain workers can't clobber each other's cache entries —
        # mirroring DiscoveryOrchestrator's locked selector snapshot save.
        now = datetime.now(timezone.utc).isoformat()
        entries = {
            field: JsScriptEntry(
                script=script,
                description=descriptions.get(field, ''),
                discovered_at=now,
                verified=True,
                model=self.model_name,
                attempts=attempt_counts.get(field, self._max_attempts),
            )
            for field, script in discovered.items()
        }
        await self._storage.save_entries(domain, contract_sig, entries)
