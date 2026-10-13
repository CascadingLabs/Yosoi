---
title: "yosoi.runtime_contracts"
description: "Public declarations in yosoi.runtime_contracts."
order: 0
---

`yosoi.runtime_contracts`

Runtime-authored Rust Contracts over arbitrary public schemas.

[Source: python/yosoi/runtime_contracts.py:1](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`ArchivedContractCandidateField`](/yosoi/python-api/runtime-contracts/types/archived-contract-candidate-field/) | Store portable evidence for one archived candidate field. |
| [`ArchivedContractField`](/yosoi/python-api/runtime-contracts/types/archived-contract-field/) | Pair an archived schema field ID with its accepted value. |
| [`ArchivedContractMoneyUsd`](/yosoi/python-api/runtime-contracts/types/archived-contract-money-usd/) | Store USD money as a portable signed minor-unit amount. |
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
| [`RuntimeMoneyUsd`](/yosoi/python-api/runtime-contracts/types/runtime-money-usd/) | Carry a USD amount accepted by runtime Contract validation. |
| [`RuntimeRecordIssue`](/yosoi/python-api/runtime-contracts/types/runtime-record-issue/) | Retain a rejected candidate and its field validation issues. |
| [`RuntimeString`](/yosoi/python-api/runtime-contracts/types/runtime-string/) | Carry a string accepted by runtime Contract validation. |
| [`RuntimeValidatedRecord`](/yosoi/python-api/runtime-contracts/types/runtime-validated-record/) | Pair accepted field values with their original candidate evidence. |
| [`RuntimeZeroOrOne`](/yosoi/python-api/runtime-contracts/types/runtime-zero-or-one/) | Carry an optional field after cardinality and conversion checks. |

## Aliases

| Name | Summary |
| --- | --- |
| [`ArchivedContractFieldValue`](/yosoi/python-api/runtime-contracts/aliases/archived-contract-field-value/) | Portable field value tagged as required, optional, or repeated. |
| [`ArchivedContractOutcomeData`](/yosoi/python-api/runtime-contracts/aliases/archived-contract-outcome-data/) | Portable outcome variants tagged by evaluation or phase-failure status. |
| [`ArchivedContractValue`](/yosoi/python-api/runtime-contracts/aliases/archived-contract-value/) | Portable string or signed USD minor-unit value tagged by type. |
| [`ArchivedExtractionFailure`](/yosoi/python-api/runtime-contracts/aliases/archived-extraction-failure/) | Portable schema, counting, grouping, or extraction-budget rejection. |
| [`ArchivedExtractionLimitName`](/yosoi/python-api/runtime-contracts/aliases/archived-extraction-limit-name/) | Names of bounded extraction counters recorded in portable failures. |
| [`ArchivedValidationFailure`](/yosoi/python-api/runtime-contracts/aliases/archived-validation-failure/) | Portable schema, counting, or validation-budget rejection. |
| [`ContractSchemaFailure`](/yosoi/python-api/runtime-contracts/aliases/contract-schema-failure/) | Structured Rust schema error tagged by its variant and typed details. |
| [`ExtractionLimitName`](/yosoi/python-api/runtime-contracts/aliases/extraction-limit-name/) | Names of Rust extraction budgets reported by runtime rejection details. |
| [`RuntimeContractOutcomeData`](/yosoi/python-api/runtime-contracts/aliases/runtime-contract-outcome-data/) | Validation variants retaining accepted records, issues, or phase failures. |
| [`RuntimeExtractedData`](/yosoi/python-api/runtime-contracts/aliases/runtime-extracted-data/) | Extraction variants distinguishing candidates from incomplete or failed work. |
| [`RuntimeExtractionFailure`](/yosoi/python-api/runtime-contracts/aliases/runtime-extraction-failure/) | Typed schema, counting, grouping, or extraction-budget rejection. |
| [`RuntimeFieldValue`](/yosoi/python-api/runtime-contracts/aliases/runtime-field-value/) | Validated runtime field value tagged by its declared cardinality. |
| [`RuntimeValidationFailure`](/yosoi/python-api/runtime-contracts/aliases/runtime-validation-failure/) | Typed schema, counting, or validation-budget rejection. |
| [`RuntimeValue`](/yosoi/python-api/runtime-contracts/aliases/runtime-value/) | String or USD Money value tagged by its runtime wire type. |
