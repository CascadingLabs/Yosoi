---
title: "View"
description: "yosoi.view.View Python API reference."
order: 0
---

`yosoi.view.View`

```python
class View(ImmutableModel):
```

One bounded page of captured DOM evidence, independent of a live browser.

Attributes:
    source: Captured observation provenance.
    capture: Binding used to reject foreign or changed observations.
    rows: Up to page_size DOM element references and text previews.
    total_rows: Total elements in captured HTML, not the current live DOM.
    page_size: Requested row bound, at most 100.
    next_cursor: Validated continuation position, or None after the last page.

[Source: python/yosoi/view.py:78](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/view.py#L78-L118)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
source: ViewSource
capture: ViewCaptureToken
rows: tuple[DomElementRow, ...]
total_rows: int = Field(strict=True, ge=0, le=2 ** 64 - 1)
page_size: int = Field(strict=True, ge=1, le=100)
next_cursor: ViewCursor | None = None
```

## Methods

### from_observation

```python
@classmethod
def from_observation(cls, observation: Observation, page_size: int=20) -> Self:
```

Inspect captured HTML with 1–100 rows; ArchiveError reports invalid input.

This parses retained evidence only. It does not fetch the recorded URL or
prove current visibility. Cursors use an advisory fingerprint; Archive
independently verifies stored payload integrity.

[Source: python/yosoi/view.py:98](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/view.py#L98-L109)

### continue_from

```python
@classmethod
def continue_from(cls, observation: Observation, cursor: ViewCursor) -> Self:
```

Read the next page; ArchiveError rejects foreign or stale cursors.

[Source: python/yosoi/view.py:112](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/view.py#L112-L118)
