---
title: "MapOutcome"
description: "yosoi.map.MapOutcome Python API reference."
order: 0
---

`yosoi.map.MapOutcome`

```python
class MapOutcome(ImmutableModel):
```

Bounded discovery evidence with retained acquisition owners.

Attributes:
    policy_snapshot: Resolved policy snapshot used for execution.
    hosts: Admitted hostnames with explicit reachability evidence.
    pages: Retained normalized pages and exploration states.
    relationships: Directed links, redirects, and canonical hints retained as
        evidence.
    frontier: Unfinished work, not a promise of later execution.
    support_documents: Robots and sitemap sources with processing states.
    sources: Selected sources, including disabled, failed, sampled, and unstarted
        slots.
    tree: Deterministic rooted forest; unattached evidence has unknown depth.
    captures: Retained acquisition responses keeping native document owners alive.
    wildcard_names: Observed wildcard patterns, without concrete-host expansion.
    wildcards: Wildcard patterns with retained provenance observations.
    request_trace: Acquisition accounting; target strings can contain user-sensitive
        data.
    termination: Why execution stopped; exhaustion alone does not prove complete
        coverage.
    omissions: Counted omission categories, not all undiscovered site items.
    summary: Charged resources, retained evidence counts, and concurrency peaks.

[Source: python/yosoi/map.py:591](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/map.py#L591-L640)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
policy_snapshot: PolicySnapshot
hosts: tuple[HostEntry, ...]
pages: tuple[PageEntry, ...]
relationships: tuple[Relationship, ...]
frontier: tuple[FrontierEntry, ...]
support_documents: tuple[SupportDocument, ...]
sources: tuple[SourceOutcome, ...]
tree: tuple[TreeEntry, ...]
captures: tuple[RetainedCapture, ...]
wildcard_names: tuple[str, ...]
wildcards: tuple[WildcardEntry, ...]
request_trace: tuple[RequestTrace, ...]
termination: MapTermination
omissions: tuple[Omission, ...]
summary: Summary
```
