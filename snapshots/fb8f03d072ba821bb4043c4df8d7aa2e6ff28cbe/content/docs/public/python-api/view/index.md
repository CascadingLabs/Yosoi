---
title: "yosoi.view"
description: "Public declarations in yosoi.view."
order: 0
---

`yosoi.view`

Bounded offline DOM inspection using Rust's capture-bound View.

[Source: python/yosoi/view.py:1](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/view.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`DomElementRow`](/yosoi/python-api/view/types/dom-element-row/) | One exact DOM element reference with a bounded descendant text preview. |
| [`View`](/yosoi/python-api/view/types/view/) | One bounded page of captured DOM evidence, independent of a live browser. |
| [`ViewCaptureToken`](/yosoi/python-api/view/types/view-capture-token/) | Capture binding retained by each View and continuation cursor. |
| [`ViewCursor`](/yosoi/python-api/view/types/view-cursor/) | Continuation position that Rust validates against the original capture. |
| [`ViewSource`](/yosoi/python-api/view/types/view-source/) | Provenance of retained evidence, without browser control authority. |
