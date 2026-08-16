"""Fail-closed tests for the unwired QA consumer scaffold."""

from __future__ import annotations

import asyncio

import pytest

from yosoi.qa.prompts import QAPromptNotReadyError, build_qa_system_prompt
from yosoi.qa.runtime import QARequest, QARuntime
from yosoi.qa.tools import OverviewArgs, UnwiredQAToolHandler


def test_qa_prompt_is_deliberately_deferred() -> None:
    with pytest.raises(QAPromptNotReadyError, match='intentionally deferred'):
        build_qa_system_prompt()


def test_qa_runtime_fails_closed_until_wired() -> None:
    request = QARequest(url='https://example.com')

    with pytest.raises(NotImplementedError, match='runtime is not wired'):
        asyncio.run(QARuntime().run(request))


def test_qa_tool_handler_fails_closed_until_wired() -> None:
    args = OverviewArgs(snapshot_id='snapshot-1', tokenizer_id='test', token_budget=500)

    with pytest.raises(NotImplementedError, match='overview is not wired'):
        asyncio.run(UnwiredQAToolHandler().overview(args))
