"""Injectable FastMCP transport for the read-only QA index surface."""

from __future__ import annotations

import shutil
from typing import Annotated, Any

from pydantic import Field

from yosoi.observations.models.view import RegionRef
from yosoi.qa.index import DEFAULT_QA_OVERVIEW_TOKENS, DEFAULT_QA_TOKENIZER_ID, QA_INDEX_LIMITS
from yosoi.qa.tools import (
    DiffArgs,
    ExpandArgs,
    InspectArgs,
    OverviewArgs,
    QAToolHandler,
    UnwiredQAToolHandler,
)

QA_INDEX_SERVER_NAME = 'yosoi_qa_index'
QA_INDEX_TOOL_NAMES = ('capabilities', 'status', 'overview', 'inspect', 'expand', 'diff')
QA_INDEX_TOOL_IDS = tuple(f'mcp__{QA_INDEX_SERVER_NAME}__{name}' for name in QA_INDEX_TOOL_NAMES)

SnapshotId = Annotated[str, Field(min_length=1)]
Ordinal = Annotated[int, Field(ge=0)]
Offset = Annotated[int, Field(ge=0)]
OverviewTokens = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.overview_tokens)]
InspectBytes = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.inspect_bytes)]
InspectItems = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.inspect_items)]
InspectSummaryChars = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.inspect_summary_chars)]
ExpandBytes = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.expand_bytes)]
ExpandItems = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.expand_items)]
ExpandSummaryChars = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.expand_summary_chars)]
DiffItems = Annotated[int, Field(gt=0, le=QA_INDEX_LIMITS.diff_page_items)]


def build_server(handler: QAToolHandler | None = None) -> object:
    """Build an MCP server over one handler; no pruning or provider logic lives here."""
    from mcp.server.fastmcp import FastMCP

    service = handler or UnwiredQAToolHandler()
    server = FastMCP('yosoi-qa-index')

    @server.tool()
    async def capabilities() -> dict[str, Any]:
        """Return actual QA-index capabilities."""
        return (await service.capabilities()).model_dump(mode='json')

    @server.tool()
    async def status() -> dict[str, Any]:
        """Return readiness without starting capture or a provider."""
        return (await service.status()).model_dump(mode='json')

    @server.tool()
    async def overview(
        snapshot_id: SnapshotId,
        tokenizer_id: Annotated[str, Field(min_length=1)] = DEFAULT_QA_TOKENIZER_ID,
        token_budget: OverviewTokens = DEFAULT_QA_OVERVIEW_TOKENS,
    ) -> dict[str, Any]:
        """Render a bounded overview of an existing snapshot index."""
        result = await service.overview(
            OverviewArgs(snapshot_id=snapshot_id, tokenizer_id=tokenizer_id, token_budget=token_budget)
        )
        return result.model_dump(mode='json')

    @server.tool()
    async def inspect(
        ref: RegionRef | None = None,
        snapshot_id: SnapshotId | None = None,
        ordinal: Ordinal | None = None,
        max_bytes: InspectBytes = QA_INDEX_LIMITS.inspect_bytes,
        max_items: InspectItems = QA_INDEX_LIMITS.inspect_items,
        max_summary_chars: InspectSummaryChars = QA_INDEX_LIMITS.inspect_summary_chars,
    ) -> dict[str, Any]:
        """Inspect one exact evidence reference or overview ordinal under hard limits."""
        result = await service.inspect(
            InspectArgs(
                ref=ref,
                snapshot_id=snapshot_id,
                ordinal=ordinal,
                budget={'max_bytes': max_bytes, 'max_items': max_items, 'max_summary_chars': max_summary_chars},
            )
        )
        return result.model_dump(mode='json')

    @server.tool()
    async def expand(
        snapshot_id: SnapshotId,
        ordinal: Ordinal | None = None,
        ref: RegionRef | None = None,
        offset: Offset = 0,
        max_items: ExpandItems = QA_INDEX_LIMITS.expand_items,
        max_bytes: ExpandBytes = QA_INDEX_LIMITS.expand_bytes,
        max_summary_chars: ExpandSummaryChars = QA_INDEX_LIMITS.expand_summary_chars,
    ) -> dict[str, Any]:
        """Expand one overview ordinal or exact region reference."""
        result = await service.expand(
            ExpandArgs(
                snapshot_id=snapshot_id,
                ordinal=ordinal,
                ref=ref,
                offset=offset,
                budget={'max_items': max_items, 'max_bytes': max_bytes, 'max_summary_chars': max_summary_chars},
            )
        )
        return result.model_dump(mode='json')

    @server.tool()
    async def diff(
        before_snapshot_id: SnapshotId,
        after_snapshot_id: SnapshotId,
        offset: Offset = 0,
        limit: DiffItems = QA_INDEX_LIMITS.diff_page_items,
    ) -> dict[str, Any]:
        """Compare related snapshot indexes by durable identity."""
        result = await service.diff(
            DiffArgs(
                before_snapshot_id=before_snapshot_id,
                after_snapshot_id=after_snapshot_id,
                offset=offset,
                limit=limit,
            )
        )
        return result.model_dump(mode='json')

    return server


def qa_index_server_command() -> tuple[str, tuple[str, ...]]:
    """Prefer the console script, with the validator-style module fallback."""
    script = shutil.which('yosoi-qa-index-mcp')
    if script is not None:
        return script, ()
    import sys

    return sys.executable, ('-m', 'yosoi.integrations.qa_index_mcp')


def qa_index_server_spec() -> dict[str, object]:
    """Return a provider-neutral stdio server description for host adapters."""
    command, args = qa_index_server_command()
    return {
        'name': QA_INDEX_SERVER_NAME,
        'command': command,
        'args': args,
        'tools': QA_INDEX_TOOL_NAMES,
        'allowed_tools': QA_INDEX_TOOL_IDS,
    }


def qa_index_toolset(*, command: str | None = None, env: dict[str, str] | None = None) -> object:
    """Build a PydanticAI MCP toolset using the robust stdio launcher."""
    from yosoi.core.discovery.mcp_client import stdio_toolset

    fallback, args = qa_index_server_command()
    return stdio_toolset(command or fallback, args if command is None else (), env=env, id=QA_INDEX_SERVER_NAME)


def main() -> None:
    """Launch a fail-closed stdio server when no injected evidence handler exists."""
    build_server().run('stdio')  # type: ignore[attr-defined]


if __name__ == '__main__':
    main()


__all__ = [
    'QA_INDEX_SERVER_NAME',
    'QA_INDEX_TOOL_IDS',
    'QA_INDEX_TOOL_NAMES',
    'build_server',
    'main',
    'qa_index_server_command',
    'qa_index_server_spec',
    'qa_index_toolset',
]
