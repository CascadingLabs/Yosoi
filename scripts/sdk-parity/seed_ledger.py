#!/usr/bin/env python3
"""Seed conservative source-backed mappings from the rustdoc and Python inventories.

The seed contains mappings only when the live Python surface has a concrete
target. Language-specific proposals stay ``proposed`` and therefore remain
missing in the parity report until an owner reviews them. No evidence is created.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import parity


ROOT_MODULES = {
    "contracts": "contracts",
    "documents": "documents",
    "locators": "locators",
    "map": "map",
    "policy": "policy",
    "request": "request",
    "search": "search",
}

ERROR_TARGETS = {
    "CoordinateError": "yosoi.errors.LocatorError",
    "ContractLocatorError": "yosoi.errors.ContractError",
    "ContractSchemaError": "yosoi.errors.ContractError",
    "DocumentError": "yosoi.errors.DocumentError",
    "DocumentProfileError": "yosoi.errors.DocumentError",
    "LocatorError": "yosoi.errors.LocatorError",
    "MapError": "yosoi.errors.MapError",
    "ParseError": "yosoi.errors.ParseError",
    "PlanError": "yosoi.errors.LocatorError",
    "PolicyError": "yosoi.errors.PolicyError",
    "QueryError": "yosoi.errors.LocatorError",
    "RequestError": "yosoi.errors.RequestError",
    "RequestPreparationError": "yosoi.errors.RequestError",
    "RequestSendError": "yosoi.errors.RequestError",
    "ResourceBudgetError": "yosoi.errors.LocatorError",
    "RuntimeContractError": "yosoi.errors.ContractError",
    "SearchError": "yosoi.errors.SearchError",
    "SearchQueryError": "yosoi.errors.SearchError",
    "SearchSendError": "yosoi.errors.SearchError",
    "SearchFailure": "yosoi.search.Failed.value",
    "SearchUnavailableReason": "yosoi.search.NotStarted.value",
}

VALUE_TARGETS = {
    "yosoi::CountLimit": "yosoi.scalars.CountLimit",
    "yosoi::DocumentId": "yosoi.scalars.DocumentId",
    "yosoi::DocumentProfile": "yosoi.documents.DocumentProfile",
    "yosoi::DocumentProfileError": "yosoi.errors.DocumentError",
    "yosoi::EffectivePolicyIdentity": "yosoi.policy.PolicyIdentity",
    "yosoi::LocateOutcome": "yosoi.outcomes.LocateOutcome",
    "yosoi::PolicyError": "yosoi.errors.PolicyError",
    "yosoi::ResponseTermination": "yosoi.request.Response.termination",
    "yosoi::StepLimit": "yosoi.scalars.StepLimit",
    "yosoi::contracts::ContractId": "yosoi.scalars.ContractId",
    "yosoi::contracts::ContractLocatorError": "yosoi.errors.ContractError",
    "yosoi::contracts::ContractSchemaError": "yosoi.errors.ContractError",
    "yosoi::contracts::ExtractionFailure": "yosoi.contracts.TerminalFailure",
    "yosoi::contracts::ValidationFailure": "yosoi.contracts.TerminalFailure",
    "yosoi::contracts::Currency": "yosoi.contracts.Money.currency",
    "yosoi::contracts::FieldId": "yosoi.scalars.FieldId",
    "yosoi::contracts::ExtractionLimit": "yosoi.runtime_contracts.ExtractionLimitName",
    "yosoi::contracts::RecordScope": "yosoi.contracts.ContractSchema.scope",
    "yosoi::contracts::ValidationCode": "yosoi.contracts.FieldIssueKind.code",
    "yosoi::locators::AccessibilityCoordinate": "yosoi.outcomes.AccessibilityCoordinate",
    "yosoi::locators::ByteRange": "yosoi.outcomes.ByteRange",
    "yosoi::locators::Completeness": "yosoi.outcomes.Completeness",
    "yosoi::locators::DecodedTextCoordinate": "yosoi.outcomes.DecodedTextCoordinate",
    "yosoi::locators::DomCoordinate": "yosoi.outcomes.DomCoordinate",
    "yosoi::locators::ExpandedNamePathSegment": "yosoi.outcomes.ExpandedNamePathSegment",
    "yosoi::locators::Finding": "yosoi.outcomes.Finding",
    "yosoi::locators::IncompleteEvidence": "yosoi.outcomes.IncompleteEvidence",
    "yosoi::locators::LocateResult": "yosoi.outcomes.LocateResult",
    "yosoi::locators::NativeCoordinate": "yosoi.outcomes.NativeCoordinate",
    "yosoi::locators::NodeReference": "yosoi.outcomes.NodeReference",
    "yosoi::locators::ProjectedValue": "yosoi.outcomes.ProjectedValue",
    "yosoi::locators::RegionLineage": "yosoi.outcomes.RegionLineage",
    "yosoi::locators::TextRange": "yosoi.outcomes.TextRange",
    "yosoi::locators::TreeCoordinate": "yosoi.outcomes.TreeCoordinate",
    "yosoi::map::MapError": "yosoi.errors.MapError",
    "yosoi::map::Rejection": "yosoi.map.Rejection",
    "yosoi::map::SkipReason": "yosoi.map.SkipReason",
    "yosoi::map::SourceSkipReason": "yosoi.map.SourceSkipReason",
    "yosoi::policy::Limits": "yosoi.policy.MapLimits",
    "yosoi::request::RequestPreparationError": "yosoi.errors.RequestError",
    "yosoi::request::RequestSendError": "yosoi.errors.RequestError",
    "yosoi::request::ActivityId": "yosoi.request.ActivityId",
    "yosoi::request::CaptureId": "yosoi.request.CaptureId",
    "yosoi::request::RequestId": "yosoi.request.RequestId",
    "yosoi::policy::DiscoveryDocuments": "yosoi.policy.DocumentSelection.documents",
    "yosoi::map::HostVerification": "yosoi.map.HostEntry.verification",
    "yosoi::map::LimitReached": "yosoi.map.MapTermination.value",
    "yosoi::map::PendingReason": "yosoi.map.FrontierEntry.reason",
    "yosoi::map::RelationshipKind": "yosoi.map.Relationship.kind",
    "yosoi::map::SupportDocumentKind": "yosoi.map.SupportDocument.kind",
    "yosoi::policy::search::ProfileSelectionKind": "yosoi.policy.ProfileSelection.kind",
    "yosoi::request::AttemptDiagnostic": "yosoi.request.Diagnostic.kind",
    "yosoi::request::AttemptFailureKind": "yosoi.request.Attempt.failure_kind",
    "yosoi::request::AttemptState": "yosoi.request.Attempt.state",
    "yosoi::request::NotStartedReason": "yosoi.request.Attempt.not_started_reason",
    "yosoi::request::PartialReason": "yosoi.request.ProjectionReason.kind",
    "yosoi::request::UnavailableReason": "yosoi.request.ProjectionReason.kind",
    "yosoi::request::UnprojectableReason": "yosoi.request.ProjectionReason.kind",
    "yosoi::search::RequestAttemptTerminal": "yosoi.search.RequestAttemptSummary.terminal",
    "yosoi::search::SearchAttemptDiagnostic": "yosoi.search.RequestAttemptSummary.diagnostic",
    "yosoi::search::SearchIssueKind": "yosoi.search.SearchIssue.kind",
    "yosoi::documents::AccessibilityCompleteness": "yosoi.outcomes.Completeness",
    "yosoi::documents::DocumentEpoch": "yosoi.scalars.DocumentEpoch",
    "yosoi::documents::DocumentError": "yosoi.errors.DocumentError",
    "yosoi::documents::DocumentRepresentation": "yosoi.documents.DocumentProfile.representation",
    "yosoi::documents::DocumentSchemaProfile": "yosoi.documents.DocumentProfile.schema_profile",
    "yosoi::documents::ParseError": "yosoi.errors.ParseError",
    "yosoi::locators::AccessibilityStateName": "yosoi.locators.Query.state",
    "yosoi::locators::CoordinateError": "yosoi.errors.LocatorError",
    "yosoi::locators::DomNodeId": "yosoi.scalars.DomNodeId",
    "yosoi::locators::JsonCoordinate": "yosoi.scalars.JsonCoordinate",
    "yosoi::locators::LocateFailure": "yosoi.outcomes.Failure",
    "yosoi::locators::NamedOutput": "yosoi.locators.Output",
    "yosoi::locators::OutputPlan": "yosoi.locators.Locator",
    "yosoi::locators::RegionPlan": "yosoi.locators.Region",
    "yosoi::locators::OutputId": "yosoi.scalars.OutputId",
    "yosoi::locators::PlanError": "yosoi.errors.LocatorError",
    "yosoi::locators::QueryError": "yosoi.errors.LocatorError",
    "yosoi::locators::RegionId": "yosoi.scalars.RegionId",
    "yosoi::locators::ResourceLimit": "yosoi.outcomes.Failure",
    "yosoi::map::MapError": "yosoi.errors.MapError",
    "yosoi::map::PolicySnapshot": "yosoi.policy.PolicySnapshot",
    "yosoi::policy::AccessibilityNodeLimit": "yosoi.scalars.AccessibilityNodeLimit",
    "yosoi::policy::AddressableByteLimit": "yosoi.scalars.AddressableByteLimit",
    "yosoi::policy::BrowserMode": "yosoi.policy.Acquisition.mode",
    "yosoi::policy::Budget": "yosoi.scalars.Budget",
    "yosoi::policy::DirectHttpRedirectTargets": "yosoi.policy.Redirects.targets",
    "yosoi::policy::DirectHttpRedirects": "yosoi.policy.Request.direct_http_redirects",
    "yosoi::policy::DocumentRequest": "yosoi.policy.DocumentSelection.documents",
    "yosoi::policy::DocumentSelectionKind": "yosoi.policy.DocumentSelection.kind",
    "yosoi::policy::EventLimit": "yosoi.scalars.EventLimit",
    "yosoi::policy::HostScope": "yosoi.policy.Scope.hosts",
    "yosoi::policy::MaximumElapsed": "yosoi.scalars.MaximumElapsed",
    "yosoi::policy::PageDiscovery": "yosoi.policy.Map.pages",
    "yosoi::policy::PathScope": "yosoi.policy.Scope.paths",
    "yosoi::policy::ProviderDefaultsVersion": "yosoi.scalars.ProviderDefaultsVersion",
    "yosoi::policy::RedirectHopLimit": "yosoi.scalars.RedirectHopLimit",
    "yosoi::policy::ResourceLimit": "yosoi.scalars.ResourceLimit",
    "yosoi::policy::Robots": "yosoi.policy.Map.robots",
    "yosoi::policy::Subdomains": "yosoi.policy.Map.subdomains",
    "yosoi::policy::TuningMode": "yosoi.policy.Tuning.mode",
    "yosoi::policy::search::Provider": "yosoi.search.Provider",
    "yosoi::StepLimit": "yosoi.scalars.StepLimit",
    "yosoi::request::RequestPreparationError": "yosoi.errors.RequestError",
    "yosoi::request::RequestSendError": "yosoi.errors.RequestError",
    "yosoi::request::WebTarget": "yosoi.request.PageRequest.target",
    "yosoi::search::FeatureCoverage": "yosoi.search.SearchCoverage.rich_features",
    "yosoi::search::SearchFailure": "yosoi.search.Failed.value",
    "yosoi::search::SearchQueryError": "yosoi.errors.SearchError",
    "yosoi::search::SearchRequestId": "yosoi.search.SearchRequest.id",
    "yosoi::search::SearchSendError": "yosoi.errors.SearchError",
    "yosoi::search::SearchTermination": "yosoi.search.SearchResponse.termination",
    "yosoi::search::SearchUnavailableReason": "yosoi.search.NotStarted.value",
    "yosoi::search::WebCoverage": "yosoi.search.SearchCoverage.web",
    "yosoi::request::Response": "yosoi.request.Response",
}

ITEM_MAPPING_RATIONALES = {
    "yosoi::locators::NamedOutput": "Rust NamedOutput is the named projected output value; Python Output carries the validated id and Locator.",
    "yosoi::locators::OutputPlan": "Rust OutputPlan maps to the Python Locator model; Rust compiles the same query, projection, captures, and optional region into Plan.",
    "yosoi::locators::RegionPlan": "Rust RegionPlan maps to the Python Region model, which carries a native-validated id and query and supports find().",
}

ITEM_SEMANTIC_EQUIVALENTS = {
    "yosoi::locators::NamedOutput": "Python Output(id, locator) represents the Rust named output.",
    "yosoi::locators::OutputPlan": "Python Locator is the Rust output selection before Plan compilation.",
    "yosoi::locators::RegionPlan": "Python Region represents the Rust region id/query and find operation.",
}

MEMBER_TARGETS = {
    "yosoi::Document::bytes": "yosoi.documents.Document.data",
    "yosoi::Document::class": "yosoi.documents.Document.document_class",
    "yosoi::Document::json": "yosoi.documents.Document.from_json",
    "yosoi::DocumentProfile::accessibility_tree_v1": "yosoi.documents.DocumentProfile.accessibility_tree",
    "yosoi::DocumentProfile::schema": "yosoi.documents.DocumentProfile.schema_profile",
    "yosoi::DocumentProfile::class": "yosoi.documents.DocumentProfile.document_class",
    "yosoi::Policy::effective_identity": "yosoi.policy.Policy.identity",
    "yosoi::Policy::to_canonical_json": "yosoi.policy.Policy.to_json",
    "yosoi::Policy::validate": "yosoi.policy.Policy.check",
    "yosoi::EffectivePolicyIdentity::digest": "yosoi.policy.PolicyIdentity.sha256",
    "yosoi::request::Attempt::status": "yosoi.request.Attempt.http_status",
    "yosoi::contracts::Contract::schema": "yosoi.contracts.Contract.contract_schema",
    "yosoi::contracts::CandidateField::id": "yosoi.contracts.CandidateField.field_id",
    "yosoi::contracts::CandidateField::len": "yosoi.contracts.CandidateField.__len__",
    "yosoi::contracts::RuntimeExtracted::validate_with_limits": "yosoi.contracts.RuntimeExtracted.validate",
    "yosoi::locators::Plan::new": "yosoi.locators.Plan",
    "yosoi::locators::PinnedLocator::attribute": "yosoi.locators.Query.attribute",
    "yosoi::locators::PinnedLocator::text": "yosoi.locators.Query.text",
    "yosoi::locators::QuerySpec::attribute": "yosoi.locators.Query.attribute",
    "yosoi::locators::QuerySpec::captures": "yosoi.locators.Query.captures",
    "yosoi::locators::QuerySpec::each_as_region": "yosoi.locators.Query.each_as_region",
    "yosoi::locators::QuerySpec::name": "yosoi.locators.Query.name",
    "yosoi::locators::QuerySpec::node": "yosoi.locators.Query.node",
    "yosoi::locators::QuerySpec::text": "yosoi.locators.Query.text",
    "yosoi::locators::QuerySpec::value": "yosoi.locators.Query.value",
    "yosoi::locators::QuerySpec::with_default_namespace": "yosoi.locators.QuerySpec.with_default_namespace",
    "yosoi::locators::QuerySpec::with_namespace": "yosoi.locators.QuerySpec.with_namespace",
    "yosoi::documents::Document::bytes": "yosoi.documents.Document.data",
    "yosoi::documents::Document::class": "yosoi.documents.Document.document_class",
    "yosoi::map::MapRequest::validate": "yosoi.map.MapRequest.check",
    "yosoi::map::MapRequest::send_cancellable": "yosoi.map.MapRequest.send",
    "yosoi::policy::Policy::to_canonical_json": "yosoi.policy.Policy.to_json",
    "yosoi::policy::Policy::effective_identity": "yosoi.policy.Policy.identity",
    "yosoi::policy::Policy::validate": "yosoi.policy.Policy.check",
    "yosoi::request::BoundPageRequest::validate": "yosoi.request.BoundPageRequest.check",
    "yosoi::request::BoundPageRequest::send_cancellable": "yosoi.request.BoundPageRequest.send",
    "yosoi::request::PageRequest::validate": "yosoi.request.PageRequest.check",
    "yosoi::request::PageRequest::send_cancellable": "yosoi.request.PageRequest.send",
    "yosoi::request::ActivityId::from_str": "yosoi.request.ActivityId.from_str",
    "yosoi::search::BoundSearchRequest::validate": "yosoi.search.BoundSearchRequest.check",
    "yosoi::search::BoundSearchRequest::send_cancellable": "yosoi.search.BoundSearchRequest.send",
    "yosoi::search::SearchRequest::validate": "yosoi.search.SearchRequest.check",
    "yosoi::search::SearchRequest::send_cancellable": "yosoi.search.SearchRequest.send",
    "yosoi::search::SearchRequestId::activity_id": "yosoi.request.RequestId.activity_id",
    "yosoi::contracts::RuntimeContract::schema": "yosoi.contracts.RuntimeContract.contract_schema",
    "yosoi::contracts::RuntimeContract::extract_with_limits": "yosoi.contracts.RuntimeContract.extract",
    "yosoi::locators::accessibility_text": "yosoi.locators.accessibility_text",
    "yosoi::locators::accessible_name": "yosoi.locators.accessible_name",
    "yosoi::locators::css": "yosoi.locators.css",
    "yosoi::locators::json_path": "yosoi.locators.json_path",
    "yosoi::locators::json_pointer": "yosoi.locators.json_pointer",
    "yosoi::locators::output": "yosoi.locators.output",
    "yosoi::locators::regex": "yosoi.locators.regex",
    "yosoi::locators::role": "yosoi.locators.role",
    "yosoi::locators::text_literal": "yosoi.locators.text_literal",
    "yosoi::locators::tree_text_contains": "yosoi.locators.tree_text_contains",
    "yosoi::locators::xpath": "yosoi.locators.xpath",
}

VARIANT_PARENT_TARGETS = {
    "yosoi::LocateOutcome": {
        "Failed": "yosoi.outcomes.LocateFailed",
    },
    "yosoi::locators::NativeCoordinate": {
        "SourceTree": "yosoi.outcomes.SourceTreeLocation",
        "Json": "yosoi.outcomes.JsonLocation",
        "RenderedDom": "yosoi.outcomes.RenderedDomLocation",
        "Accessibility": "yosoi.outcomes.AccessibilityLocation",
        "DecodedText": "yosoi.outcomes.DecodedTextLocation",
    },
    "yosoi::request::DocumentOutcome": {
        "Produced": "yosoi.request.Produced",
        "Partial": "yosoi.request.PartialDocument",
        "Unavailable": "yosoi.request.Unavailable",
        "Unprojectable": "yosoi.request.Unprojectable",
    },
}

VARIANT_MODEL_PARENTS = {
    "yosoi::map::DiscoverySource",
    "yosoi::map::Exploration",
    "yosoi::map::MapTermination",
    "yosoi::map::OmissionReason",
    "yosoi::map::SourceFailure",
    "yosoi::map::SourceStatus",
    "yosoi::policy::AcquisitionKind",
    "yosoi::policy::ProviderDefaultsStatus",
    "yosoi::search::ProviderCharge",
}

VARIANT_MEMBER_ALIASES = {
    ("yosoi::contracts::RuntimeValue", "String"): "RuntimeString",
    ("yosoi::contracts::RuntimeValue", "MoneyUsd"): "RuntimeMoneyUsd",
    ("yosoi::contracts::RuntimeFieldValue", "ExactlyOne"): "RuntimeExactlyOne",
    ("yosoi::contracts::RuntimeFieldValue", "ZeroOrOne"): "RuntimeZeroOrOne",
    ("yosoi::contracts::RuntimeFieldValue", "Many"): "RuntimeMany",
}

WRAPPED_OUTCOME_ENUMS = {
    "yosoi::contracts::ContractOutcome": "yosoi.contracts.ContractOutcome",
    "yosoi::contracts::ExtractionFailure": "yosoi.contracts.TerminalFailure",
    "yosoi::contracts::ValidationFailure": "yosoi.contracts.TerminalFailure",
    "yosoi::contracts::RuntimeExtractionFailure": "yosoi.runtime_contracts.RuntimeExtractionFailure",
    "yosoi::contracts::RuntimeValidationFailure": "yosoi.runtime_contracts.RuntimeValidationFailure",
    "yosoi::contracts::RuntimeContractOutcome": "yosoi.contracts.RuntimeContractOutcome",
    "yosoi::contracts::RuntimeExtracted": "yosoi.contracts.RuntimeExtracted",
}

VARIANT_ARGUMENT_ALIASES = {
    ("yosoi::search::ProviderOutcome::Results", "0"): "value",
    ("yosoi::search::ProviderOutcome::Failed", "0"): "value",
    ("yosoi::search::ProviderOutcome::NotStarted", "0"): "value",
    ("yosoi::request::DocumentOutcome::Produced", "0"): "document",
    ("yosoi::request::DocumentOutcome::Unavailable", "0"): "reason",
    ("yosoi::request::DocumentOutcome::Unprojectable", "0"): "reason",
    ("yosoi::contracts::RuntimeValue::String", "0"): "value",
    ("yosoi::contracts::RuntimeValue::MoneyUsd", "0"): "value",
    ("yosoi::contracts::RuntimeFieldValue::ExactlyOne", "0"): "value",
    ("yosoi::contracts::RuntimeFieldValue::ZeroOrOne", "0"): "value",
    ("yosoi::contracts::RuntimeFieldValue::Many", "0"): "values",
    ("yosoi::map::Exploration::Failed", "0"): "value",
    ("yosoi::map::SourceStatus::Failed", "0"): "value",
    ("yosoi::map::MapTermination::Limit", "0"): "value",
    ("yosoi::policy::Acquisition::Browser", "0"): "mode",
}

SERDE_EQUIVALENTS = {
    ("yosoi::locators::Plan", "Serialize"): {
        "pythonTarget": "yosoi.locators.Plan.compiled",
        "pythonEquivalent": "Plan.compiled() returns the Rust-compiled portable plan value.",
        "rationale": "Rust Plan serde output is represented by the portable compiled plan view, not the Pydantic authoring DSL; owner review and executed wire comparisons are required.",
        "conversion": "Rust serializer output maps to the Python compiled plan mapping.",
    },
    ("yosoi::locators::Plan", "Deserialize"): {
        "pythonTarget": "yosoi.locators.Plan.from_compiled",
        "pythonEquivalent": "Plan.from_compiled(value) imports and Rust-validates the portable plan.",
        "rationale": "Rust Plan serde input maps to the compiled-plan importer; Pydantic DSL JSON is not the Rust plan wire form. Owner review and executed wire comparisons are required.",
        "conversion": "Rust deserializer input maps to Plan.from_compiled(value).",
    },
    ("yosoi::contracts::RuntimeExtracted", "Serialize"): {
        "pythonTarget": "yosoi.contracts.RuntimeExtracted.model_dump_json",
        "pythonEquivalent": "RuntimeExtracted.model_dump_json() returns the retained raw Rust JSON.",
        "rationale": "The Python wrapper serializes its retained native Rust result directly; owner review and executed wire comparisons are required.",
        "conversion": "Rust serializer output maps to the native result JSON.",
    },
    ("yosoi::contracts::RuntimeContractOutcome", "Serialize"): {
        "pythonTarget": "yosoi.contracts.RuntimeContractOutcome.model_dump_json",
        "pythonEquivalent": "RuntimeContractOutcome.model_dump_json() returns the retained raw Rust JSON.",
        "rationale": "The Python wrapper serializes its retained native Rust result directly; owner review and executed wire comparisons are required.",
        "conversion": "Rust serializer output maps to the native result JSON.",
    },
}

ENUM_VALUE_FIELDS = {
    "yosoi::ResponseTermination": "yosoi.request.Response.termination",
    "yosoi::contracts::Cardinality": "yosoi.contracts.FieldSchema.cardinality",
    "yosoi::contracts::Currency": "yosoi.contracts.Money.currency",
    "yosoi::contracts::RecordScope": "yosoi.contracts.ContractSchema.scope",
    "yosoi::documents::DocumentClass": "yosoi.documents.DocumentProfile.document_class",
    "yosoi::documents::DocumentRepresentation": "yosoi.documents.DocumentProfile.representation",
    "yosoi::documents::DocumentSchemaProfile": "yosoi.documents.DocumentProfile.schema_profile",
    "yosoi::documents::SourceFormat": "yosoi.documents.DocumentProfile.source_format",
    "yosoi::map::DiscoverySource": "yosoi.map.DiscoverySource.kind",
    "yosoi::map::Exploration": "yosoi.map.Exploration.kind",
    "yosoi::map::MapTermination": "yosoi.map.MapTermination.kind",
    "yosoi::map::OmissionReason": "yosoi.map.OmissionReason.kind",
    "yosoi::map::SourceStatus": "yosoi.map.SourceStatus.kind",
    "yosoi::map::SourceFailure": "yosoi.map.SourceFailure.kind",
    "yosoi::map::HostVerification": "yosoi.map.HostEntry.verification",
    "yosoi::map::LimitReached": "yosoi.map.MapTermination.value",
    "yosoi::map::PendingReason": "yosoi.map.FrontierEntry.reason",
    "yosoi::map::RelationshipKind": "yosoi.map.Relationship.kind",
    "yosoi::map::SupportDocumentKind": "yosoi.map.SupportDocument.kind",
    "yosoi::policy::BrowserMode": "yosoi.policy.Acquisition.mode",
    "yosoi::policy::AcquisitionKind": "yosoi.policy.Acquisition.kind",
    "yosoi::policy::DirectHttpRedirectTargets": "yosoi.policy.Redirects.targets",
    "yosoi::policy::DirectHttpRedirects": "yosoi.policy.Redirects.kind",
    "yosoi::policy::DocumentRequest": "yosoi.policy.DocumentSelection.documents",
    "yosoi::policy::DocumentSelectionKind": "yosoi.policy.DocumentSelection.kind",
    "yosoi::policy::DiscoveryDocuments": "yosoi.policy.DocumentSelection.documents",
    "yosoi::policy::ProfileSelectionKind": "yosoi.policy.ProfileSelection.kind",
    "yosoi::policy::HostScope": "yosoi.policy.Scope.hosts",
    "yosoi::policy::PathScope": "yosoi.policy.Scope.paths",
    "yosoi::policy::ProviderDefaultsStatus": "yosoi.policy.ProviderDefaultsStatus.status",
    "yosoi::policy::search::ProfileSelectionKind": "yosoi.policy.ProfileSelection.kind",
    "yosoi::policy::PageDiscovery": "yosoi.policy.Map.pages",
    "yosoi::policy::Robots": "yosoi.policy.Map.robots",
    "yosoi::policy::Subdomains": "yosoi.policy.Map.subdomains",
    "yosoi::request::AttemptState": "yosoi.request.Attempt.state",
    "yosoi::request::AttemptFailureKind": "yosoi.request.Attempt.failure_kind",
    "yosoi::request::AttemptDiagnostic": "yosoi.request.Diagnostic.kind",
    "yosoi::request::NotStartedReason": "yosoi.request.Attempt.not_started_reason",
    "yosoi::request::PartialReason": "yosoi.request.ProjectionReason.kind",
    "yosoi::request::UnavailableReason": "yosoi.request.ProjectionReason.kind",
    "yosoi::request::UnprojectableReason": "yosoi.request.ProjectionReason.kind",
    "yosoi::search::FeatureCoverage": "yosoi.search.SearchCoverage.rich_features",
    "yosoi::search::ProviderCharge": "yosoi.search.ProviderCharge.status",
    "yosoi::search::RequestAttemptTerminal": "yosoi.search.RequestAttemptSummary.terminal",
    "yosoi::search::SearchIssueKind": "yosoi.search.SearchIssue.kind",
    "yosoi::search::SearchFailure": "yosoi.search.Failed.value",
    "yosoi::search::SearchUnavailableReason": "yosoi.search.NotStarted.value",
    "yosoi::search::SearchTermination": "yosoi.search.SearchResponse.termination",
    "yosoi::search::WebCoverage": "yosoi.search.SearchCoverage.web",
}

BORROWED_VIEW_EQUIVALENTS = {
    "yosoi::documents::DocumentRef": "Python returns an owning yosoi.Document wrapper that keeps the native document alive; the Rust borrow is not exposed.",
    "yosoi::request::ResponseRef": "Python returns an owning yosoi.request.Response wrapper that keeps the native response alive; the Rust borrow is not exposed.",
}

LANGUAGE_SPECIFIC_ITEMS = {
    "yosoi::contracts::ContractIdentity": {
        "pythonTarget": "yosoi.contracts.ContractSchema.identity",
        "pythonEquivalent": "ContractSchema.identity() returns the canonical SHA-256 identity as lowercase hexadecimal text.",
        "rationale": "Rust exposes a 32-byte identity value while Python exposes its canonical hexadecimal form from the schema; owner review must decide whether the omitted bytes wrapper is acceptable.",
    },
    "yosoi::locators::PinnedLocator": {
        "pythonTarget": "yosoi.locators.Query",
        "pythonEquivalent": "Query authoring plus text() or attribute() declares a pinned locator.",
        "rationale": "Python Query represents the static CSS/text-literal query and projections, while Rust pins expressions to static lifetimes. Owner review must accept the lifetime/authoring difference.",
    },
    "yosoi::locators::PinnedOutputLocator": {
        "pythonTarget": "yosoi.locators.Locator",
        "pythonEquivalent": "Locator carries the query and output projection declared by a pinned output locator.",
        "rationale": "Python Locator represents the resulting text or attribute projection. Owner review and compiled-plan comparisons are required.",
    },
}

BORROWED_VIEW_METHODS = {
    "yosoi::documents::Document::as_ref": "Python Document itself is the owning view of the native document.",
    "yosoi::documents::DocumentRef::id": "Python Document.id reads the identity from its retained native handle.",
    "yosoi::documents::DocumentRef::class": "Python Document.document_class reads the validated native profile.",
    "yosoi::documents::DocumentRef::profile": "Python Document.profile owns the same immutable profile value.",
    "yosoi::documents::DocumentRef::bytes": "Python Document.data returns owned bytes rather than a borrowed Rust slice.",
    "yosoi::documents::DocumentRef::byte_len": "Python Document.byte_len reads the native byte count.",
    "yosoi::documents::DocumentRef::parse": "Python Document.parse returns an owning ParsedDocument handle.",
    "yosoi::documents::DocumentRef::locate": "Python Document.locate retains the native document for the operation.",
    "yosoi::documents::DocumentRef::bind": "Python Document.bind retains the document and policy in BoundDocument.",
    "yosoi::documents::DocumentRef::to_owned": "Python document wrappers already own the native document value.",
    "yosoi::documents::Document::as_ref": "Python Document itself is the owning view of the native document.",
    "yosoi::request::Response::as_ref": "Python Response itself is the owning view of the native response.",
    "yosoi::request::ResponseRef::request_id": "Python Response.request_id is read from its retained native response.",
    "yosoi::request::ResponseRef::requested_target": "Python Response.requested_target is read from its retained native response.",
    "yosoi::request::ResponseRef::policy_snapshot": "Python Response.policy_snapshot owns the snapshot model.",
    "yosoi::request::ResponseRef::attempts": "Python Response.attempts exposes immutable attempt models.",
    "yosoi::request::ResponseRef::termination": "Python Response.termination is read from its retained native response.",
    "yosoi::Document::as_ref": "Python Document is the owning wrapper around the native document.",
}

BORROWED_VIEW_TARGETS = {
    "yosoi::documents::DocumentRef": "yosoi.documents.Document",
    "yosoi::documents::Document::as_ref": "yosoi.documents.Document",
    "yosoi::documents::DocumentRef::id": "yosoi.documents.Document.id",
    "yosoi::documents::DocumentRef::class": "yosoi.documents.Document.document_class",
    "yosoi::documents::DocumentRef::profile": "yosoi.documents.Document.profile",
    "yosoi::documents::DocumentRef::bytes": "yosoi.documents.Document.data",
    "yosoi::documents::DocumentRef::byte_len": "yosoi.documents.Document.byte_len",
    "yosoi::documents::DocumentRef::parse": "yosoi.documents.Document.parse",
    "yosoi::documents::DocumentRef::locate": "yosoi.documents.Document.locate",
    "yosoi::documents::DocumentRef::bind": "yosoi.documents.Document.bind",
    "yosoi::documents::DocumentRef::to_owned": "yosoi.documents.Document",
    "yosoi::request::Response::as_ref": "yosoi.request.Response",
    "yosoi::request::ResponseRef::request_id": "yosoi.request.Response.request_id",
    "yosoi::request::ResponseRef::requested_target": "yosoi.request.Response.requested_target",
    "yosoi::request::ResponseRef::policy_snapshot": "yosoi.request.Response.policy_snapshot",
    "yosoi::request::ResponseRef::attempts": "yosoi.request.Response.attempts",
    "yosoi::request::ResponseRef::termination": "yosoi.request.Response.termination",
    "yosoi::Document::as_ref": "yosoi.documents.Document",
    "yosoi::request::ResponseRef": "yosoi.request.Response",
}

ARGUMENT_ALIASES = {
    ("yosoi::Document::html", "bytes"): "content",
    ("yosoi::Document::xml", "bytes"): "content",
    ("yosoi::Document::json", "bytes"): "content",
    ("yosoi::request::ActivityId::from_str", "s"): "value",
    ("yosoi::locators::JsonCoordinate::try_new", "pointer"): "value",
    ("yosoi::locators::Finding::try_new", "value"): "projected",
    ("yosoi::policy::ProviderDefaultsVersion::try_new", "version"): "value",
    ("yosoi::Document::text", "bytes"): "content",
    ("yosoi::Document::rendered_dom", "bytes"): "content",
    ("yosoi::Document::accessibility_tree", "bytes"): "content",
    ("yosoi::Document::from_profile", "bytes"): "content",
    ("yosoi::Document::json", "bytes"): "content",
    ("yosoi::locators::output", "value"): "locator",
    ("yosoi::locators::accessibility_text", "value"): "expression",
    ("yosoi::locators::accessible_name", "value"): "expression",
    ("yosoi::locators::css", "value"): "expression",
    ("yosoi::locators::json_path", "value"): "expression",
    ("yosoi::locators::json_pointer", "value"): "expression",
    ("yosoi::locators::regex", "value"): "expression",
    ("yosoi::locators::role", "value"): "expression",
    ("yosoi::locators::text_literal", "value"): "expression",
    ("yosoi::locators::tree_text_contains", "value"): "expression",
    ("yosoi::locators::xpath", "value"): "expression",
    ("yosoi::locators::QuerySpec::with_namespace", "namespace_uri"): "uri",
    ("yosoi::locators::QuerySpec::with_default_namespace", "namespace_uri"): "uri",
    (
        "yosoi::contracts::RuntimeContract::extract_with_limits",
        "located",
    ): "located",
    ("yosoi::contracts::RuntimeContract::extract_with_limits", "limits"): "limits",
    **VARIANT_ARGUMENT_ALIASES,
}


def _python_module(rust_path: str, *, module_item: bool = False) -> str | None:
    parts = rust_path.removeprefix("yosoi::").split("::")
    if parts == ["prelude"]:
        return None
    root = parts[0]
    if root not in ROOT_MODULES:
        return "yosoi-engine"
    module = f"yosoi.{ROOT_MODULES[root]}"
    return module


def _target_for_page(item: dict[str, Any], python: dict[str, Any]) -> str | None:
    rust_path = item["rustPath"]
    override = VALUE_TARGETS.get(rust_path)
    if override in python["targets"]:
        return override
    name = rust_path.split("::")[-1]
    if item["kind"] == "module":
        if name == "prelude":
            return None
        module = _python_module(rust_path, module_item=True)
        if len(rust_path.split("::")) == 2:
            module = f"yosoi.{name}" if name in ROOT_MODULES else module
        if module and module in python["targets"]:
            return module
        return None
    if rust_path.startswith("yosoi::policy::search::"):
        module = "yosoi.policy"
    elif rust_path.startswith("yosoi::locators::locator::"):
        module = "yosoi.locators"
    else:
        module = _python_module(rust_path)
    candidate = f"{module}.{name}" if module else None
    if candidate in python["targets"]:
        return candidate
    error_target = ERROR_TARGETS.get(name)
    if error_target in python["targets"]:
        return error_target
    return None


def _container_target(rust_path: str, pages: dict[str, dict[str, Any]]) -> str | None:
    return pages.get(rust_path)


def _field_target(
    parent_target: str, rust_field: str, python: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None]:
    parent = python["targets"].get(parent_target) or {}
    for field in parent.get("fields", []):
        names = {
            field.get("name"),
            field.get("alias"),
            field.get("validationAlias"),
            field.get("serializationAlias"),
        }
        if rust_field in names:
            target = f"{parent_target}.{field['name']}"
            return (target, python["targets"].get(target))
    target = f"{parent_target}.{rust_field}"
    return (target, python["targets"].get(target))


def _snake_case(value: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _variant_literal_target(
    parent: dict[str, Any],
    member_name: str,
    parent_target: str,
    python: dict[str, Any],
) -> tuple[str | None, str | None]:
    wire_name = _snake_case(member_name)
    parent_info = python["targets"].get(parent_target) or {}
    alias = parent_info.get("alias") or {}
    if wire_name in alias.get("choices", []):
        return parent_target, wire_name
    direct_field = (parent_info.get("field") or {}).get("literalChoices", [])
    if wire_name in direct_field:
        return parent_target, wire_name
    field_target = ENUM_VALUE_FIELDS.get(parent["rustPath"])
    field_info = python["targets"].get(field_target) if field_target else None
    choices = (field_info or {}).get("field", {}).get("literalChoices", [])
    if wire_name in choices:
        return field_target, wire_name
    return None, None


def _variant_tag_defaults(
    target: dict[str, Any], member_name: str
) -> list[dict[str, Any]]:
    wire_name = _snake_case(member_name)
    fields = target.get("fields", [])
    if target.get("kind") == "field":
        fields = [target.get("field") or {}]
    for field in fields:
        if wire_name in field.get("literalChoices", []):
            return [
                {
                    "id": f"variant-tag:{field['name']}",
                    "rust": f"variant {member_name}",
                    "python": f"{field['name']}={wire_name}",
                }
            ]
    return []


def _variant_argument_aliases(
    item: dict[str, Any], target: dict[str, Any], member_name: str
) -> dict[tuple[str, str], str]:
    fields = target.get("fields", [])
    wire_name = _snake_case(member_name)
    tag_fields = {
        field.get("name")
        for field in fields
        if wire_name in field.get("literalChoices", [])
    }
    payload_fields = [
        field.get("name") for field in fields if field.get("name") not in tag_fields
    ]
    arguments = [
        argument
        for argument in item.get("rustArguments", [])
        if not argument.get("receiver")
    ]
    aliases = {}
    for index, argument in enumerate(arguments):
        rust_name = argument["name"]
        if rust_name in payload_fields:
            continue
        if rust_name.isdecimal() and len(arguments) == len(payload_fields):
            aliases[(item["rustPath"], rust_name)] = payload_fields[index]
    return aliases


def _conversion(rust_type: str, python_parameter: dict[str, Any]) -> str:
    python_type = str(python_parameter.get("annotation") or "")
    if "String" in rust_type or "str" in rust_type:
        return "Rust string-like input maps to Python str"
    if "Vec<u8>" in rust_type or "[u8]" in rust_type:
        return "Python str is UTF-8 encoded; bytes are preserved"
    if "CancellationToken" in rust_type:
        return "Python CancellationToken forwards its native handle"
    if "Policy" in rust_type:
        return "Python Policy serializes to the native Rust policy value"
    if "Plan" in rust_type:
        return "Python Plan forwards the compiled native plan"
    if "WebTarget" in rust_type:
        return "Python str is converted to the Rust WebTarget wrapper"
    if "DocumentRef" in rust_type:
        return "Python Document wraps the native document value"
    if "Duration" in rust_type:
        return "Python Duration serializes seconds and nanoseconds"
    if "AddressableByteLimit" in rust_type or "ByteLimit" in rust_type:
        return "positive Rust byte limit maps to a positive Python byte count"
    if rust_type.startswith("u") or rust_type.startswith("i"):
        return f"checked Rust integer maps to Python {python_type or 'int'}"
    return f"Python {python_type or 'value'} converts to the Rust parameter type"


def _argument_mappings(
    item: dict[str, Any],
    target: dict[str, Any] | None,
    argument_aliases: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, str]] | None:
    if item["kind"] not in {"function", "variant"}:
        return []
    if not target:
        return None
    signature = target.get("signature") or {}
    parameters = signature.get("parameters") or []
    by_name = {parameter.get("name"): parameter for parameter in parameters}
    mappings = []
    for argument in item.get("rustArguments", []):
        if argument.get("receiver"):
            continue
        rust_name = argument["name"]
        python_name = (argument_aliases or {}).get(
            (item["rustPath"], rust_name),
            ARGUMENT_ALIASES.get((item["rustPath"], rust_name), rust_name),
        )
        python_parameter = by_name.get(python_name)
        if python_parameter is None and rust_name.isdecimal() and len(parameters) == 1:
            python_parameter = parameters[0]
            python_name = python_parameter.get("name")
        if python_parameter is None:
            return None
        mappings.append(
            {
                "rustArgument": rust_name,
                "pythonArgument": str(python_name),
                "conversion": _conversion(argument["type"], python_parameter),
            }
        )
    return mappings


def _detail_rows(
    item: dict[str, Any],
    target: dict[str, Any] | None,
    *,
    rust_type: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    defaults: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    cardinality: list[dict[str, Any]] = []
    signature = item["signature"]
    rust_types = [rust_type or signature]
    rust_types.extend(argument["type"] for argument in item.get("rustArguments", []))
    joined = " ".join(rust_types)
    leaf = item["rustPath"].split("::")[-1]
    if "MaximumElapsed" in joined:
        units.append(
            {
                "id": f"elapsed-unit:{leaf}",
                "rust": "microseconds",
                "python": "microseconds",
            }
        )
    if "Duration" in joined:
        units.append(
            {
                "id": f"duration-unit:{leaf}",
                "rust": "seconds and nanoseconds",
                "python": "Duration.seconds and Duration.nanoseconds",
            }
        )
    if any(token in joined for token in ("Vec<", "&[", "impl ExactSizeIterator")):
        python_type = str((target or {}).get("annotation") or "")
        if not python_type:
            python_type = str((target or {}).get("signature") or {})
        if "tuple" in python_type or "list" in python_type or "Tuple" in python_type:
            cardinality.append(
                {
                    "id": f"sequence:{leaf}",
                    "rust": "ordered sequence",
                    "python": "ordered tuple/list",
                }
            )
    if "Option<" in joined and target:
        default = target.get("field", {}).get("default")
        if default and default.get("kind") == "value" and default.get("value") is None:
            defaults.append(
                {
                    "id": f"optional-default:{leaf}",
                    "rust": "optional value; no constructor default",
                    "python": "None default",
                }
            )
    signature_info = (target or {}).get("signature") or {}
    python_parameters = {
        parameter.get("name"): parameter
        for parameter in signature_info.get("parameters", [])
    }
    for argument in item.get("rustArguments", []):
        if argument.get("receiver"):
            continue
        rust_name = argument["name"]
        python_name = ARGUMENT_ALIASES.get((item["rustPath"], rust_name), rust_name)
        parameter = python_parameters.get(python_name)
        if parameter and parameter.get("hasDefault"):
            defaults.append(
                {
                    "id": f"python-default:{rust_name}",
                    "rust": "no explicit default on this Rust parameter",
                    "python": f"Python default {parameter.get('default')!r}",
                }
            )
    return defaults, units, cardinality


def _entry(
    item: dict[str, Any],
    target: str,
    target_info: dict[str, Any],
    python: dict[str, Any],
    rationale: str,
    *,
    rust_type: str | None = None,
    semantic_equivalent: str | None = None,
    argument_aliases: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any] | None:
    arguments = _argument_mappings(item, target_info, argument_aliases)
    if arguments is None:
        return None
    defaults, units, cardinality = _detail_rows(item, target_info, rust_type=rust_type)
    result = {
        "rustPath": item["rustPath"],
        "symbolKey": item["symbolKey"],
        "decision": "mapped",
        "pythonTarget": target,
        "argumentMappings": arguments,
        "defaults": defaults,
        "units": units,
        "cardinality": cardinality,
        "rationale": rationale,
    }
    if item.get("trait"):
        result["trait"] = item["trait"]
    if semantic_equivalent:
        result["semanticEquivalent"] = semantic_equivalent
    return result


def _language_proposal(
    item: dict[str, Any],
    python_equivalent: str,
    rationale: str,
    *,
    argument_mappings: list[dict[str, str]] | None = None,
    defaults: list[dict[str, Any]] | None = None,
    units: list[dict[str, Any]] | None = None,
    cardinality: list[dict[str, Any]] | None = None,
    python_target: str | None = None,
) -> dict[str, Any]:
    result = {
        "rustPath": item["rustPath"],
        "symbolKey": item["symbolKey"],
        "decision": "language-specific",
        "argumentMappings": argument_mappings or [],
        "defaults": defaults or [],
        "units": units or [],
        "cardinality": cardinality or [],
        "rationale": rationale,
        "review": {
            "status": "proposed",
            "rationale": rationale,
            "pythonEquivalent": python_equivalent,
        },
        **({"trait": item["trait"]} if item.get("trait") else {}),
    }
    if python_target:
        result["pythonTarget"] = python_target
    return result


def _proposal_argument_mappings(
    item: dict[str, Any], trait: str
) -> list[dict[str, str]]:
    mappings = []
    for argument in item.get("rustArguments", []):
        if argument.get("receiver"):
            continue
        name = argument["name"]
        if trait == "Serialize" and name == "serializer":
            python_argument = "Pydantic model_dump/model_dump_json serializer"
            conversion = "Python serialization selects its serializer through Pydantic configuration"
        elif trait == "Deserialize" and name == "deserializer":
            python_argument = "Pydantic model_validate/model_validate_json input"
            conversion = "Rust deserializer input maps to Python validation input"
        else:
            python_argument = name
            conversion = (
                f"Language-specific {trait} input {name} needs owner-reviewed semantics"
            )
        mappings.append(
            {
                "rustArgument": name,
                "pythonArgument": python_argument,
                "conversion": conversion,
            }
        )
    return mappings


def _mapped_error_target(item: dict[str, Any], python: dict[str, Any]) -> str | None:
    name = item["rustPath"].split("::")[-1]
    if item["kind"] == "assoc_type" and name == "Error":
        match = re.search(
            r"type\s+Error\s*=\s*([A-Za-z_][A-Za-z0-9_:]*)", item["signature"]
        )
        if match:
            name = match.group(1).split("::")[-1]
    if name not in ERROR_TARGETS:
        return None
    target = ERROR_TARGETS[name]
    return target if target in python["targets"] else None


def seed_entries(
    rust: dict[str, Any], python: dict[str, Any], existing: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries_by_identity: dict[str, dict[str, Any]] = {}
    existing_by_path = {entry["rustPath"]: entry for entry in existing["entries"]}
    page_targets: dict[str, str] = {}
    items_by_key = {item["symbolKey"]: item for item in rust["items"]}

    # Keep explicit, source-reviewed mappings already in the seed ledger.
    for entry in existing["entries"]:
        item = next(
            (
                candidate
                for candidate in rust["items"]
                if entry.get("symbolKey") == candidate["symbolKey"]
                or (entry["rustPath"] in {candidate["rustPath"], *candidate["aliases"]})
            ),
            None,
        )
        if item is not None:
            copied = dict(entry)
            copied["rustPath"] = item["rustPath"]
            copied["symbolKey"] = item["symbolKey"]
            preferred_target = VALUE_TARGETS.get(item["rustPath"])
            if preferred_target in python["targets"]:
                copied["pythonTarget"] = preferred_target
            entries_by_identity[item["symbolKey"]] = copied
            if (
                item["surface"] == "item"
                and copied.get("decision") == "mapped"
                and copied.get("pythonTarget") in python["targets"]
            ):
                page_targets[item["rustPath"]] = copied["pythonTarget"]

    for item in rust["items"]:
        if item["surface"] != "item":
            continue
        if item["symbolKey"] in entries_by_identity:
            continue
        leaf = item["rustPath"].split("::")[-1]
        if item["kind"] == "proc_macro" and leaf == "Contract":
            entries_by_identity[item["symbolKey"]] = _language_proposal(
                item,
                "Python Contract subclasses with annotated fields declared through yosoi.Field.",
                "The Rust derive macro generates a static Contract implementation; Python declares the same schema on a Contract subclass. Owner review is required.",
            )
            continue
        target = _target_for_page(item, python)
        if target is None and item["rustPath"] in BORROWED_VIEW_EQUIVALENTS:
            equivalent = BORROWED_VIEW_EQUIVALENTS[item["rustPath"]]
            entries_by_identity[item["symbolKey"]] = _language_proposal(
                item,
                equivalent,
                f"Rust exposes a borrowed view while Python retains an owning native wrapper. {equivalent} Owner review is required.",
                python_target=BORROWED_VIEW_TARGETS.get(item["rustPath"]),
            )
            continue
        if target is None and item["rustPath"] in LANGUAGE_SPECIFIC_ITEMS:
            proposal = LANGUAGE_SPECIFIC_ITEMS[item["rustPath"]]
            target = proposal["pythonTarget"]
            if target not in python["targets"]:
                continue
            entries_by_identity[item["symbolKey"]] = _language_proposal(
                item,
                proposal["pythonEquivalent"],
                proposal["rationale"],
                python_target=target,
            )
            page_targets[item["rustPath"]] = target
            continue
        if target is None and item["kind"] in {"trait", "proc_macro"}:
            if leaf == "ContractValue":
                entries_by_identity[item["symbolKey"]] = _language_proposal(
                    item,
                    "Python Contract fields use str or yosoi.Money annotations.",
                    "The Rust value trait has no named Python union; Python field annotations select the supported scalar values. Owner review is required.",
                )
            continue
        if target is None:
            continue
        target_info = python["targets"].get(target)
        if target_info is None:
            continue
        page_targets[item["rustPath"]] = target
        if (
            item["kind"] == "trait"
            and item["rustPath"] == "yosoi::contracts::Contract"
        ):
            row = _entry(
                item,
                target,
                target_info,
                python,
                "Rust Contract implementors map to Python subclasses of yosoi.Contract with fields declared using yosoi.Field.",
                semantic_equivalent="Python Contract subclass and Field declarations; extraction and validation remain Rust-owned.",
            )
        else:
            rationale = ITEM_MAPPING_RATIONALES.get(
                item["rustPath"],
                f"The live Python surface exposes the corresponding public target {target}.",
            )
            row = _entry(
                item,
                target,
                target_info,
                python,
                rationale,
                semantic_equivalent=ITEM_SEMANTIC_EQUIVALENTS.get(item["rustPath"]),
            )
        if row is not None:
            entries_by_identity[item["symbolKey"]] = row

    # Public member mappings use the owning Rust page's mapped Python target.
    for item in rust["items"]:
        if item["surface"] != "member" or item["symbolKey"] in entries_by_identity:
            continue
        if item["rustPath"] in BORROWED_VIEW_METHODS:
            target = BORROWED_VIEW_TARGETS.get(item["rustPath"])
            target_info = python["targets"].get(target) if target else None
            arguments = (
                _argument_mappings(item, target_info)
                if target_info
                else _proposal_argument_mappings(item, "ownership")
            )
            defaults, units, cardinality = _detail_rows(item, target_info)
            entries_by_identity[item["symbolKey"]] = _language_proposal(
                item,
                f"{BORROWED_VIEW_METHODS[item['rustPath']]} Owner review is required.",
                f"{BORROWED_VIEW_METHODS[item['rustPath']]} This preserves the value while making Python ownership explicit.",
                argument_mappings=arguments or [],
                defaults=defaults,
                units=units,
                cardinality=cardinality,
                python_target=target,
            )
            continue
        parent_target = page_targets.get(item["parentRustPath"])
        if not parent_target:
            continue
        member_name = item["rustPath"].split("::")[-1]
        target = None
        rust_type = None
        rationale = ""
        if item["kind"] == "struct_field":
            target, target_info = _field_target(parent_target, member_name, python)
            if not target or not target_info:
                continue
            field_info = next(
                (
                    field
                    for field in (python["targets"].get(parent_target) or {}).get(
                        "fields", []
                    )
                    if target.endswith(f".{field.get('name')}")
                ),
                None,
            )
            rust_type = item["signature"].split(":", 1)[-1].strip()
            rationale = (
                f"Rust field {member_name} maps to Python field "
                f"{target.rsplit('.', 1)[-1]}"
                + (
                    f" with serialization alias {field_info['alias']}"
                    if field_info and field_info.get("alias")
                    else ""
                )
                + "."
            )
        elif item["kind"] == "function" and not item.get("trait"):
            target = MEMBER_TARGETS.get(
                item["rustPath"], f"{parent_target}.{member_name}"
            )
            target_info = python["targets"].get(target)
            if (
                target_info is None
                and member_name in {"new", "try_new"}
                and not any(
                    argument.get("receiver")
                    for argument in item.get("rustArguments", [])
                )
            ):
                target = parent_target
                target_info = python["targets"].get(target)
            if target_info is None:
                continue
            rationale = (
                f"Rust method maps to the matching Python method/property {target}."
            )
        elif item["kind"] == "variant":
            parent = next(
                (
                    page
                    for page in rust["items"]
                    if page["surface"] == "item"
                    and page["rustPath"] == item["parentRustPath"]
                ),
                None,
            )
            if parent is None:
                continue
            wrapped_target = WRAPPED_OUTCOME_ENUMS.get(parent["rustPath"])
            if wrapped_target and wrapped_target in python["targets"]:
                equivalent = (
                    f"Python {wrapped_target} exposes the Rust {member_name} variant "
                    "through its read-only status/view attributes."
                )
                defaults, units, cardinality = _detail_rows(
                    item, python["targets"][wrapped_target]
                )
                entries_by_identity[item["symbolKey"]] = _language_proposal(
                    item,
                    equivalent,
                    f"The Python outcome wrapper owns the tagged Rust outcome; owner review is required for {member_name} payload details.",
                    argument_mappings=_proposal_argument_mappings(item, "outcome-view"),
                    defaults=defaults,
                    units=units,
                    cardinality=cardinality,
                    python_target=wrapped_target,
                )
                continue
            wire_value = None
            target = VARIANT_PARENT_TARGETS.get(parent["rustPath"], {}).get(member_name)
            if target is None:
                parent_type = python["targets"].get(parent_target) or {}
                variant_alias = VARIANT_MEMBER_ALIASES.get(
                    (parent["rustPath"], member_name), member_name
                )
                union_members = (parent_type.get("alias") or {}).get("unionMembers", [])
                target = next(
                    (
                        member["target"]
                        for member in union_members
                        if member.get("name") == variant_alias
                        and member.get("target") in python["targets"]
                    ),
                    None,
                )
                if target is None:
                    parent_module = parent_target.rsplit(".", 1)[0]
                    alias_targets = [
                        name
                        for name in python["targets"]
                        if name.startswith(f"{parent_module}.")
                        and name.rsplit(".", 1)[-1] == variant_alias
                        and python["targets"][name].get("kind") == "class"
                    ]
                    union_display = str(
                        (parent_type.get("signature") or {}).get("display", "")
                    )
                    target = next(
                        (name for name in alias_targets if name in union_display),
                        None,
                    )
                if target is None and parent["rustPath"] in VARIANT_MODEL_PARENTS:
                    candidate = python["targets"].get(parent_target)
                    if candidate and candidate.get("kind") == "class":
                        target = parent_target
                if target is None:
                    target, wire_value = _variant_literal_target(
                        parent, member_name, parent_target, python
                    )
                else:
                    wire_value = None
                if target is None and parent_type.get("enumValues"):
                    wire_value = _snake_case(member_name)
                    enum_value = next(
                        (
                            value
                            for value in parent_type["enumValues"]
                            if value["name"] == member_name
                            or value["value"] == wire_value
                        ),
                        None,
                    )
                    if enum_value is not None:
                        enum_member_name = enum_value["name"]
                        possible = f"{parent_target}.{enum_member_name}"
                        if possible in python["targets"]:
                            target = possible
                            wire_value = enum_value["value"]
                if target is None:
                    error_target = _mapped_error_target(parent, python)
                    if error_target:
                        target = error_target
                        wire_value = None
            if target is None:
                continue
            target_info = python["targets"].get(target)
            if target_info is None:
                continue
            rationale = f"Rust variant {member_name} maps to the corresponding Python tagged value {target}."
            if wire_value is None:
                tag_defaults = _variant_tag_defaults(target_info, member_name)
                if tag_defaults:
                    wire_value = tag_defaults[0]["python"]
            if wire_value is not None:
                rationale += f" The Python discriminator value is {wire_value!r}."
            variant_argument_aliases = _variant_argument_aliases(
                item, target_info, member_name
            )
        elif item["kind"] == "assoc_type":
            assoc = item["rustPath"].split("::")[-1]
            if assoc == "Error":
                target = _mapped_error_target(item, python)
                target_info = python["targets"].get(target) if target else None
                rationale = "Rust associated error type maps to the public Python SDK exception."
            elif (
                assoc == "Candidate"
                and "yosoi.contracts.Candidate" in python["targets"]
            ):
                target = "yosoi.contracts.Candidate"
                target_info = python["targets"][target]
                rationale = "The Python Contract subclass uses the public Candidate model and derives its typed field view per subclass."
            else:
                continue
        else:
            continue

        row = _entry(
            item,
            target,
            target_info,
            python,
            rationale,
            rust_type=rust_type,
            argument_aliases=(
                variant_argument_aliases if item["kind"] == "variant" else None
            ),
        )
        if row is not None:
            if item["kind"] == "variant":
                row["defaults"].extend(_variant_tag_defaults(target_info, member_name))
            entries_by_identity[item["symbolKey"]] = row

    # Proposed ownership/serialization mappings are explicit but remain missing
    # until an owner reviews them. Unsupported Rust-only traits stay unmapped.
    for item in rust["items"]:
        if (
            item["surface"] != "member"
            or not item.get("trait")
            or item["symbolKey"] in entries_by_identity
        ):
            continue
        parent_target = page_targets.get(item["parentRustPath"])
        if not parent_target:
            continue
        trait = item["trait"].split("::")[-1]
        leaf = item["rustPath"].split("::")[-1]
        proposal = None
        proposal_target = parent_target
        proposal_arguments = None
        parent_info = python["targets"].get(parent_target) or {}
        target_kind = parent_info.get("kind")
        serde = SERDE_EQUIVALENTS.get((item["parentRustPath"], trait))
        if serde and leaf in {"serialize", "deserialize"}:
            proposal = (serde["pythonEquivalent"], serde["rationale"])
            proposal_target = serde["pythonTarget"]
            proposal_arguments = [
                {
                    "rustArgument": argument["name"],
                    "pythonArgument": proposal_target,
                    "conversion": serde["conversion"],
                }
                for argument in item.get("rustArguments", [])
                if not argument.get("receiver")
            ]
        elif (
            trait == "Clone"
            and leaf == "clone"
            and target_kind == "class"
            and parent_info.get("fields")
        ):
            proposal = (
                "Pydantic model_copy() on the corresponding Python model.",
                "Rust Clone returns an owned copy; Python exposes immutable Pydantic models and model_copy. Owner review and per-symbol conformance are required.",
            )
        elif (
            trait == "Default"
            and leaf == "default"
            and target_kind == "class"
            and parent_info.get("fields")
        ):
            proposal = (
                "Construct the Python model with its declared Pydantic defaults.",
                "Rust Default maps to Python constructor defaults; owner review must compare every field value and default factory.",
            )
        elif (
            trait in {"PartialEq", "Eq"}
            and leaf == "eq"
            and target_kind == "class"
            and parent_info.get("fields")
        ):
            proposal = (
                "Python equality on the corresponding immutable Pydantic model.",
                f"Rust {trait} compares the public value fields; Python model equality is a candidate semantic equivalent requiring owner review and per-symbol conformance.",
            )
        elif (
            trait in {"Debug", "Display", "ToString"}
            and leaf in {"fmt", "to_string"}
            and target_kind == "class"
        ):
            operation = "repr(value)" if trait == "Debug" else "str(value)"
            proposal = (
                f"Python {operation} for the corresponding public value.",
                f"Rust {trait} formatting and Python formatting are language-specific; owner review may accept the inspection behavior, but exact string equality is not claimed.",
            )
        elif (
            trait == "Hash"
            and leaf in {"hash", "hash_slice"}
            and target_kind == "class"
        ):
            proposal = (
                "Python hash(value) for the corresponding immutable public value.",
                "Rust Hash and Python hashing can differ in representation and runtime stability; owner review must decide whether value-level hash semantics are part of the parity contract.",
            )
        if proposal:
            defaults, units, cardinality = _detail_rows(item, parent_info)
            entries_by_identity[item["symbolKey"]] = _language_proposal(
                item,
                proposal[0],
                proposal[1],
                argument_mappings=proposal_arguments
                if proposal_arguments is not None
                else _proposal_argument_mappings(item, trait),
                defaults=defaults,
                units=units,
                cardinality=cardinality,
                python_target=proposal_target,
            )

    # Preserve any remaining explicit source mappings, including rows for APIs
    # outside the current compiler feature inventory so strict mode marks them stale.
    for entry in existing["entries"]:
        selector = entry.get("symbolKey")
        if selector and selector not in entries_by_identity:
            entries_by_identity[selector] = dict(entry)
        elif not selector and not any(
            candidate["rustPath"] == entry["rustPath"]
            for candidate in entries_by_identity.values()
        ):
            entries_by_identity[f"legacy:{entry['rustPath']}"] = dict(entry)

    result = dict(existing)
    result["entries"] = sorted(
        entries_by_identity.values(),
        key=lambda entry: (
            entry["rustPath"],
            entry.get("trait", ""),
            entry.get("symbolKey", ""),
        ),
    )
    report = parity.build_report(rust, python, result)
    return result, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference", type=Path, default=Path(".local/sdk-parity-reference")
    )
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument(
        "--python-root",
        type=Path,
        default=Path("python"),
        help="inspect this source package instead of an installed distribution",
    )
    parser.add_argument(
        "--write", action="store_true", help="write the seeded mappings to the ledger"
    )
    args = parser.parse_args(argv)

    rust = parity.load_rust_inventory(args.reference)
    python = parity.introspect_python_package("yosoi-engine", args.python_root)
    existing = parity.load_ledger(args.ledger)
    ledger, report = seed_entries(rust, python, existing)
    counts = report["coverage"]["counts"]
    print(
        f"seeded {len(ledger['entries'])} ledger rows for {report['coverage']['denominator']} Rust items: "
        f"{counts['mapped']} mapped, {counts['language-specific']} reviewed language-specific, "
        f"{counts['missing']} missing, {counts['stale']} stale"
    )
    if args.write:
        args.ledger.write_text(
            json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
