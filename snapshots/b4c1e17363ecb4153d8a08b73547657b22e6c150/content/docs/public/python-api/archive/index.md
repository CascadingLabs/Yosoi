---
title: "yosoi.archive"
description: "Public declarations in yosoi.archive."
order: 0
---

`yosoi.archive`

Immutable local evidence storage backed by Rust's validated Archive format.

[Source: python/yosoi/archive.py:1](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/archive.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`Archive`](/yosoi/python-api/archive/types/archive/) | Local Unix Archive handle with no open files between operations. |
| [`AutomationContext`](/yosoi/python-api/archive/types/automation-context/) | Recorded provenance supplied by the application, without live authority. |
| [`AutomationRecord`](/yosoi/python-api/archive/types/automation-record/) | Bounded observations and receipts validated by the Rust record contract. |
| [`AutomationRecordRef`](/yosoi/python-api/archive/types/automation-record-ref/) | Portable handle naming one immutable automation record Document. |
| [`DocumentArchiveRef`](/yosoi/python-api/archive/types/document-archive-ref/) | Immutable reference to one exact Document occurrence. |
| [`PlanArchiveRef`](/yosoi/python-api/archive/types/plan-archive-ref/) | Immutable reference to one compiled locator Plan. |
