"""LLM-driven A3Node action plan discovery — the navigation/interaction analog of FieldDiscoveryAgent.

Where ``FieldDiscoveryAgent`` answers "given this rendered page, where do my contract
fields live?", this agent answers "given this rendered page and what the user wants
to extract, what *actions* must I perform first to make the data available?"

The output is a sequence of :class:`yosoi.models.replay.A3Node` — typically a
``click_until(load_more, expect=selector_absent(...))`` with the structural
termination — that the headless fetcher runs after navigate and before extraction.

This is what makes reddit's lazy comment expansion automagic. The user's contract
says ``RedditComment`` (multi-item), the system infers "load every comment", the
agent picks the load-more trigger and termination for the rendered DOM, the plan
is cached per domain via :class:`yosoi.storage.action_plan.ActionPlanStorage`, and
every subsequent visit replays without invoking the LLM.

The agent is gated by the same observability + retry layer as field discovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic_ai import Agent
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig, create_model
from yosoi.models.replay import A3Node, ReplayPlan
from yosoi.prompts.action_plan import (
    ActionPlanDiscoveryDeps,
    action_plan_base_instructions,
    action_plan_intent_instructions,
    action_plan_primitives_guide,
    build_action_plan_user_prompt,
)
from yosoi.utils import observability as obs
from yosoi.utils.exceptions import LLMGenerationError

_logger = logging.getLogger(__name__)


@dataclass
class _PlanCandidate:
    """The agent's structured output — a list of A3Nodes to run post-navigate.

    Kept as a thin wrapper around ``list[A3Node]`` (rather than ``ReplayPlan``)
    because the agent doesn't know the target/task strings — those are owned by
    the caller. The caller stitches the agent's nodes into a full ``ReplayPlan``.
    """

    nodes: list[A3Node]


class ActionPlanDiscoveryAgent:
    """Discovers post-navigate actions for a (rendered HTML, intent) pair.

    Typical intent strings derived by the system:
      * ``"load every item on this listing"`` — when the contract is multi-item
        and the page has lazy/infinite content.
      * ``"open every collapsed thread"`` — when the contract is multi-item and
        the page has expand-more / load-more triggers (reddit comments).
      * ``""`` — when the contract is single-item and the page renders eagerly;
        the agent should return an empty plan.

    Attributes:
        model_name: Name of the underlying LLM model.
        provider: LLM provider name.
        console: Rich console for output.
    """

    def __init__(self, llm_config: LLMConfig, console: Console | None = None):
        """Initialize the action-plan discovery agent.

        Args:
            llm_config: LLM provider and model configuration.
            console: Optional Rich console for output.
        """
        model = create_model(llm_config)
        self.model_name = llm_config.model_name
        self.provider = llm_config.provider
        self.console = console or Console()

        self._agent: Agent[ActionPlanDiscoveryDeps, _PlanCandidate] = Agent(
            model,
            deps_type=ActionPlanDiscoveryDeps,
            output_type=_PlanCandidate,
            output_retries=3,
            instrument=obs.instrumentation_settings(),
        )
        self._agent.system_prompt(action_plan_base_instructions)
        self._agent.system_prompt(action_plan_intent_instructions)
        self._agent.system_prompt(action_plan_primitives_guide)

    async def discover_plan(
        self,
        target: str,
        intent: str,
        html: str,
    ) -> ReplayPlan:
        """Ask the LLM to emit a list of post-navigate actions for the given intent.

        Args:
            target: Stable key identifying the page kind (e.g. domain or
                ``domain/section``). Used as the cache key downstream.
            intent: One-sentence description of what state the page must be in
                BEFORE extraction runs (e.g. "load every public comment").
            html: Rendered HTML of the page in its just-navigated state.

        Returns:
            A ``ReplayPlan`` whose nodes are the agent-emitted A3Nodes. May be
            empty when the page needs no pre-extraction interaction.

        Raises:
            LLMGenerationError: If the LLM call fails.
        """
        deps = ActionPlanDiscoveryDeps(target=target, intent=intent, html=html)

        with obs.span('action_plan_agent', target=target, intent=intent[:80], source='agent'):
            try:
                result = await self._agent.run(build_action_plan_user_prompt(deps), deps=deps)
                candidate: _PlanCandidate = result.output
            except Exception as exc:
                _logger.error(
                    'Action plan discovery failed',
                    extra={'target': target, 'intent': intent, 'provider': self.provider},
                )
                raise LLMGenerationError(f'Action plan discovery failed for {target!r}: {exc}') from exc

        plan = ReplayPlan(
            target=target,
            task=intent,
            source='scripted',  # LLM-emitted plans behave like scripted plans at the executor
            nodes=list(candidate.nodes),
        )
        _logger.info(
            'Action plan discovered',
            extra={'target': target, 'intent': intent, 'nodes': len(plan.nodes)},
        )
        return plan
