# Read-only QA index

Yosoi's QA index is a bounded, provider-neutral view over observation snapshots and indexes that
already exist. It does not capture a page, start a browser, call a model, or sanitize evidence.
Use it to expose the same overview, inspection, expansion, and diff semantics through Python or an
injected MCP server without duplicating pruning rules.

## Security boundary

An `IndexSession` accepts only index source artifacts marked `model_safe`. It refuses restricted or
ephemeral-secret sources, and its inspection APIs reject `allow_restricted=True`. A `model_safe`
label is still an upstream assertion, not a sanitizer: only pass public or pre-sanitized artifacts.
Authenticated HTML, DOM, AX, network, and screenshots remain blocked on the CAS-269 sanitization
boundary.

## Python API

This complete example constructs one static-HTML artifact and production index before opening the
read-only session:

```python
import asyncio

import yosoi as ys
from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.models import CaptureProfile, EvidenceKind, ObservationSnapshot
from yosoi.observations.pruning import BodyPruner, PruningInput, PruningPolicy
from yosoi.qa.tools import InspectArgs, OverviewArgs


async def main() -> None:
    data = b'<html><body><main id="content"><h1>Example</h1><p>Evidence</p></main></body></html>'
    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id='example-1',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=data,
    )
    snapshot = ObservationSnapshot(
        run_id='example',
        episode_id='example',
        snapshot_id='example-1',
        requested_profile=CaptureProfile.HTTP_STATIC,
        artifacts=(artifact,),
    )
    view = BodyPruner().prune(PruningInput(source=artifact, data=data), PruningPolicy())
    observation_index = ObservationIndexCompiler().compile(snapshot, (view,))

    session = await ys.index(store=store, snapshot=snapshot, observation_index=observation_index)
    print((await session.status()).model_dump_json(indent=2))
    overview = await session.overview(OverviewArgs(snapshot_id=snapshot.snapshot_id))
    print(overview.text)
    if overview.included_refs:
        detail = await session.inspect(InspectArgs(ref=overview.included_refs[0]))
        print(detail.content.decode('utf-8'))


asyncio.run(main())
```

`OverviewArgs` defaults to the deterministic `estimate/chars-per-token-4` tokenizer and a 1,000-token
budget. The hard session ceiling is 3,000 tokens. Inspection and expansion have separate server-side
byte, item, and summary ceilings. Expansion reports the serialized member bytes it consumed.

For related snapshots, pass a mapping when constructing the session and call `session.diff(...)`.
References remain snapshot-local; ordinals are resolved only within the index named by the request.

## MCP embedding

The standalone launcher intentionally has no artifact persistence or capture wiring and therefore
reports `ready=false`. A host with an in-process `IndexSession` injects the same typed handler:

```python
from yosoi.integrations.qa_index_mcp import build_server
from yosoi.qa.tools import IndexQAToolHandler

server = build_server(IndexQAToolHandler(session))
server.run('stdio')
```

The MCP tools are `capabilities`, `status`, `overview`, `inspect`, `expand`, and `diff`. Restricted
inspection is not present in their schemas. The console entry point is `yosoi-qa-index-mcp`; use it
only as a fail-closed transport check until a reviewed persistence/capture adapter exists.

## CLI and packaged skill

```bash
uvx yosoi qa status --json
uvx yosoi agents install --target pi
```

`yosoi qa mcp` launches the same fail-closed standalone transport. The installed
`yosoi-qa-index` skill teaches agents to check capabilities first, navigate by exact references, and
state unavailable modalities rather than inferring their absence. It does not grant evidence access
by itself.
