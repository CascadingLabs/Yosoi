---
title: "yosoi.documents"
description: "Public declarations in yosoi.documents."
order: 0
---

`yosoi.documents`

Immutable Pydantic documents with Rust-owned parse and locate operations.

[Source: python/yosoi/documents.py:1](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`BoundDocument`](/yosoi/python-api/documents/types/bound-document/) | Retained document paired with a serialized policy snapshot. |
| [`Document`](/yosoi/python-api/documents/types/document/) | Immutable document bytes with retained native parse ownership. |
| [`DocumentProfile`](/yosoi/python-api/documents/types/document-profile/) | Validated representation and schema for retained payload bytes. |
| [`ParsedDocument`](/yosoi/python-api/documents/types/parsed-document/) | A reusable Rust parse; close explicitly or use it as a context manager. |

## Aliases

| Name | Summary |
| --- | --- |
| [`DocumentClass`](/yosoi/python-api/documents/aliases/document-class/) | Native capability classes; source, rendered DOM, and accessibility evidence are not interchangeable. |
| [`SourceFormat`](/yosoi/python-api/documents/aliases/source-format/) | Payload syntax accepted by source profiles: HTML, XML, JSON, or UTF-8 text. |
