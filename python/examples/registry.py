"""Offline Registry SDK example: memory by default, JSONL with an explicit path."""

from __future__ import annotations

import sys

import yosoi as ys

registry = (
    ys.registry.Registry.jsonl(sys.argv[1])
    if len(sys.argv) > 1
    else ys.registry.Registry()
)
before = registry.snapshot()
after = registry.commit(
    before.revision,
    [ys.registry.Put(key="example/state", value={"message": "shared portable DTO"})],
)
print(after.model_dump_json())
