"""YosoiAgent: typed wrapper around a pydantic-ai Agent for selector discovery."""

import asyncio
from typing import Any

from pydantic_ai import Agent

from yosoi.models.contract import Contract
from yosoi.prompts.discovery import DiscoveryInput


class YosoiAgent:
    """A Yosoi-managed agent for custom selector discovery.

    Wraps a pydantic-ai Agent internally, deriving the output type from the
    contract so callers only need to supply a model and optional system prompt.

    Example::

        agent = YosoiAgent(model, contract=MyContract, system_prompt="Find selectors.")
        discovery = SelectorDiscovery(contract=MyContract, agent=agent)
    """

    def __init__(
        self,
        model: Any,
        contract: type[Contract],
        system_prompt: str | None = None,
    ):
        """Initialise YosoiAgent, deriving the output type from the contract.

        Args:
            model: Any pydantic-ai compatible model (e.g. ``TestModel``, ``GroqModel``).
            contract: Contract subclass whose selector model is used as the agent output type.
            system_prompt: Optional static system prompt for the inner agent.

        """
        self._contract = contract
        output_model = contract.to_selector_model()
        if system_prompt is not None:
            self._agent: Agent[None, Any] = Agent(model, output_type=output_model, system_prompt=system_prompt)
        else:
            self._agent = Agent(model, output_type=output_model)

    async def run(self, discovery_input: DiscoveryInput, **kwargs: Any) -> Any:
        """Run the agent with a JSON-serialised DiscoveryInput prompt."""
        prompt = discovery_input.model_dump_json()
        return await self._agent.run(prompt, **kwargs)

    def run_sync(self, discovery_input: DiscoveryInput, **kwargs: Any) -> Any:
        """Synchronous convenience wrapper around :meth:`run`."""
        return asyncio.run(self.run(discovery_input, **kwargs))

    @property
    def inner(self) -> Agent[None, Any]:
        """The underlying pydantic-ai Agent."""
        return self._agent
