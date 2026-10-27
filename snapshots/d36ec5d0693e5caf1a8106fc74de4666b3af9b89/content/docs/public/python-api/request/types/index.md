---
title: "Types"
description: "Types declared in yosoi.request."
order: 0
---

| Name | Summary |
| --- | --- |
| [`Attempt`](/yosoi/python-api/request/types/attempt/) | Typed acquisition outcome retained in authored policy order. |
| [`AttemptDocument`](/yosoi/python-api/request/types/attempt-document/) | One authored document request and its typed production outcome. |
| [`BoundPageRequest`](/yosoi/python-api/request/types/bound-page-request/) | A page request bound to a serialized policy snapshot. |
| [`BoundSessionRequest`](/yosoi/python-api/request/types/bound-session-request/) | A page request retaining a caller-owned browser Session or Work. |
| [`DocumentMetadata`](/yosoi/python-api/request/types/document-metadata/) | Source document identity, representation, and byte accounting. |
| [`PageRequest`](/yosoi/python-api/request/types/page-request/) | Authored page acquisition intent, independent of policy binding. |
| [`PartialDocument`](/yosoi/python-api/request/types/partial-document/) | Document production retained incomplete evidence or omitted a document. |
| [`Produced`](/yosoi/python-api/request/types/produced/) | Requested document representation was produced with retained ownership. |
| [`Response`](/yosoi/python-api/request/types/response/) | Completed and failed acquisition evidence with retained native ownership. |
| [`Unavailable`](/yosoi/python-api/request/types/unavailable/) | Requested evidence was unavailable from the acquisition. |
| [`Unprojectable`](/yosoi/python-api/request/types/unprojectable/) | Available acquisition evidence cannot produce the requested representation. |
| [`WebTarget`](/yosoi/python-api/request/types/web-target/) | Authored request target; Rust defers URL validation until preparation. |
