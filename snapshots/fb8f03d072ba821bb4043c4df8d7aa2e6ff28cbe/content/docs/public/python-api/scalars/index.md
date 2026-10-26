---
title: "yosoi.scalars"
description: "Public declarations in yosoi.scalars."
order: 0
---

`yosoi.scalars`

Validated Python values for the public Rust SDK's scalar newtypes.

[Source: python/yosoi/scalars.py:1](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`AccessibilityNodeLimit`](/yosoi/python-api/scalars/types/accessibility-node-limit/) | Positive addressable u32 bound on accessibility snapshot nodes. |
| [`AddressableByteLimit`](/yosoi/python-api/scalars/types/addressable-byte-limit/) | Positive u64 byte bound that also fits the Rust platform address size. |
| [`Budget`](/yosoi/python-api/scalars/types/budget/) | Positive u32 Map discovery budget; zero never means unlimited. |
| [`ByteLimit`](/yosoi/python-api/scalars/types/byte-limit/) | Positive byte limit returned by a policy conversion; units are bytes. |
| [`CaptureDeadline`](/yosoi/python-api/scalars/types/capture-deadline/) | Positive capture deadline represented in microseconds. |
| [`CaptureDuration`](/yosoi/python-api/scalars/types/capture-duration/) | Elapsed duration represented in microseconds. |
| [`ContractId`](/yosoi/python-api/scalars/types/contract-id/) | Authored nonblank identity distinguishing portable Contract schemas. |
| [`CountLimit`](/yosoi/python-api/scalars/types/count-limit/) | Positive u64 document or locator count; zero does not mean unlimited. |
| [`DocumentEpoch`](/yosoi/python-api/scalars/types/document-epoch/) | Positive u64 document-local generation for DOM and accessibility snapshots. |
| [`DocumentId`](/yosoi/python-api/scalars/types/document-id/) | Authored nonblank document identity, independent of an acquisition URL. |
| [`DomNodeId`](/yosoi/python-api/scalars/types/dom-node-id/) | Positive u64 node identity meaningful only within its snapshot epoch. |
| [`EventLimit`](/yosoi/python-api/scalars/types/event-limit/) | Positive addressable u64 count of admitted browser capture events. |
| [`FieldId`](/yosoi/python-api/scalars/types/field-id/) | Authored nonblank field identity matching Contract output evidence. |
| [`JsonCoordinate`](/yosoi/python-api/scalars/types/json-coordinate/) | Validated JSON Pointer spelling without checking document resolution. |
| [`MaximumElapsed`](/yosoi/python-api/scalars/types/maximum-elapsed/) | Positive u64 elapsed budget measured in microseconds, not a timestamp. |
| [`NonZeroU32`](/yosoi/python-api/scalars/types/non-zerou32/) | Positive 32-bit value returned by Rust policy conversions. |
| [`OutputId`](/yosoi/python-api/scalars/types/output-id/) | Authored nonblank locator-output identity for ordered findings. |
| [`ProviderDefaultsVersion`](/yosoi/python-api/scalars/types/provider-defaults-version/) | Positive u16 version selecting certified provider-default metadata. |
| [`RedirectHopLimit`](/yosoi/python-api/scalars/types/redirect-hop-limit/) | Positive u32 bound on Direct HTTP redirect transitions. |
| [`RegionId`](/yosoi/python-api/scalars/types/region-id/) | Authored nonblank repeated-region identity for finding lineage. |
| [`ResourceLimit`](/yosoi/python-api/scalars/types/resource-limit/) | Positive addressable u32 count of browser resources admitted to a capture. |
| [`StepLimit`](/yosoi/python-api/scalars/types/step-limit/) | Positive u32 locator step count; zero does not mean unlimited. |
| [`ValidatedInteger`](/yosoi/python-api/scalars/types/validated-integer/) | Integer scalar with the width and constructor rules of its Rust type. |
| [`ValidatedString`](/yosoi/python-api/scalars/types/validated-string/) | String scalar constructed and checked by its Rust SDK type. |

## Constants

| Name | Summary |
| --- | --- |
| [`RUST_DOMAIN_VALIDATED`](/yosoi/python-api/scalars/constants/rust-domain-validated/) | Internal reconstruction context for data already checked by Rust. |
