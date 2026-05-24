"""Behavior tree base classes.

Pure tree logic — no browser knowledge. Conditions and actions
import from here, not the other way around.

Status:
    SUCCESS — the node completed successfully, something happened
    FAILURE — the node could not complete, nothing happened

Nodes:
    Node      — base class, all nodes implement tick()
    Selector  — tries children in order, returns SUCCESS on first success
    Sequence  — runs children in order, returns FAILURE on first failure
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Any


class Status(Enum):
    """Result of a single node tick."""

    SUCCESS = auto()
    FAILURE = auto()


class Node(ABC):
    """Base class for all behavior tree nodes."""

    @abstractmethod
    async def tick(self, tab: Any) -> Status:
        """Evaluate this node against the current page state.

        Args:
            tab: Live browser tab.

        Returns:
            SUCCESS if the node completed, FAILURE otherwise.
        """


class Selector(Node):
    """Tries children in order, returns SUCCESS on the first that succeeds.

    If all children fail, returns FAILURE. Analogous to a logical OR.
    """

    def __init__(self, *children: Node) -> None:
        """Initialise with one or more child nodes."""
        self._children = children

    async def tick(self, tab: Any) -> Status:
        """Tick each child in order until one succeeds."""
        for child in self._children:
            if await child.tick(tab) == Status.SUCCESS:
                return Status.SUCCESS
        return Status.FAILURE


class Sequence(Node):
    """Runs children in order, returns FAILURE if any child fails.

    Returns SUCCESS only if all children succeed. Analogous to a logical AND.
    """

    def __init__(self, *children: Node) -> None:
        """Initialise with one or more child nodes."""
        self._children = children

    async def tick(self, tab: Any) -> Status:
        """Tick each child in order, stopping on first failure."""
        for child in self._children:
            if await child.tick(tab) == Status.FAILURE:
                return Status.FAILURE
        return Status.SUCCESS
