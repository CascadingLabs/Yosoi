---
title: "yosoi.identities"
description: "Public declarations in yosoi.identities."
order: 0
---

`yosoi.identities`

Public activity/capture identities backed by Rust generation and parsing.

[Source: python/yosoi/identities.py:1](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/identities.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`ActivityId`](/yosoi/python-api/identities/types/activity-id/) | Canonical random UUID v4 identity for one activity occurrence. |
| [`CaptureId`](/yosoi/python-api/identities/types/capture-id/) | An activity identity designated as a capture by its Python type. |
| [`ContractIdentity`](/yosoi/python-api/identities/types/contract-identity/) | The hexadecimal representation of a Rust-computed 32-byte identity. |
| [`RequestId`](/yosoi/python-api/identities/types/request-id/) | A validated activity UUID used to correlate one authored request. |
