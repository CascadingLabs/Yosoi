---
title: "Types"
description: "Types declared in yosoi.runtime_contracts."
order: 0
---

| Name | Summary |
| --- | --- |
| [`ArchivedContractCandidateField`](/yosoi/python-api/runtime-contracts/types/archived-contract-candidate-field/) | Store portable evidence for one archived candidate field. |
| [`ArchivedContractField`](/yosoi/python-api/runtime-contracts/types/archived-contract-field/) | Pair an archived schema field ID with its accepted value. |
| [`ArchivedContractOutcome`](/yosoi/python-api/runtime-contracts/types/archived-contract-outcome/) | Inspect a portable Contract outcome without a live Rust handle. |
| [`ArchivedContractRecordIssue`](/yosoi/python-api/runtime-contracts/types/archived-contract-record-issue/) | Retain a rejected portable candidate with its field issues. |
| [`ArchivedContractString`](/yosoi/python-api/runtime-contracts/types/archived-contract-string/) | Store a validated string in the portable archive format. |
| [`ArchivedValidatedContractRecord`](/yosoi/python-api/runtime-contracts/types/archived-validated-contract-record/) | Retain accepted portable values together with source evidence. |
| [`RuntimeCandidate`](/yosoi/python-api/runtime-contracts/types/runtime-candidate/) | Retain raw findings for every field of one runtime candidate. |
| [`RuntimeContract`](/yosoi/python-api/runtime-contracts/types/runtime-contract/) | Author a Contract schema for extraction and validation in Rust. |
| [`RuntimeContractOutcome`](/yosoi/python-api/runtime-contracts/types/runtime-contract-outcome/) | Inspect runtime validation results while retaining the Rust handle. |
| [`RuntimeExactlyOne`](/yosoi/python-api/runtime-contracts/types/runtime-exactly-one/) | Carry the single value accepted for a required field. |
| [`RuntimeExtracted`](/yosoi/python-api/runtime-contracts/types/runtime-extracted/) | Inspect runtime extraction results while retaining the Rust handle. |
| [`RuntimeMany`](/yosoi/python-api/runtime-contracts/types/runtime-many/) | Carry all accepted values for a repeated field. |
| [`RuntimeRecordIssue`](/yosoi/python-api/runtime-contracts/types/runtime-record-issue/) | Retain a rejected candidate and its field validation issues. |
| [`RuntimeString`](/yosoi/python-api/runtime-contracts/types/runtime-string/) | Carry a string accepted by runtime Contract validation. |
| [`RuntimeValidatedRecord`](/yosoi/python-api/runtime-contracts/types/runtime-validated-record/) | Pair accepted field values with their original candidate evidence. |
| [`RuntimeZeroOrOne`](/yosoi/python-api/runtime-contracts/types/runtime-zero-or-one/) | Carry an optional field after cardinality and conversion checks. |
