---
title: "yosoi.view"
description: "Public declarations in yosoi.view."
order: 0
---

`yosoi.view`

Bounded offline DOM inspection using Rust's capture-bound View.

[Source: python/yosoi/view.py:1](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/view.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`DomElementRow`](/yosoi/python-api/view/types/dom-element-row/) | One exact DOM element reference with a bounded descendant text preview. |
| [`View`](/yosoi/python-api/view/types/view/) | One bounded page of captured DOM evidence, independent of a live browser. |
| [`ViewCaptureToken`](/yosoi/python-api/view/types/view-capture-token/) | Capture binding retained by each View and continuation cursor. |
| [`ViewCursor`](/yosoi/python-api/view/types/view-cursor/) | Continuation position that Rust validates against the original capture. |
| [`ViewSource`](/yosoi/python-api/view/types/view-source/) | Provenance of retained evidence, without browser control authority. |
