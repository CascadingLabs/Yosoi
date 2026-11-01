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
    "surface": "surface",
}

MAPPING_RUST_CRATE = "yosoi"
SUPPORTED_RUST_CRATES = {MAPPING_RUST_CRATE, "yosoi_sdk"}


def _rebase_rust_path(path: str, source_crate: str, target_crate: str) -> str:
    if path == source_crate:
        return target_crate
    prefix = f"{source_crate}::"
    if path.startswith(prefix):
        return f"{target_crate}{path[len(source_crate) :]}"
    return path


def _inventory_with_mapping_root(rust: dict[str, Any]) -> dict[str, Any]:
    """Present supported compiler inventories under the canonical mapping root."""
    source_crate = (rust.get("sdk") or {}).get("crate")
    if source_crate not in SUPPORTED_RUST_CRATES:
        raise parity.ParityError(
            f"no Python mapping root is configured for Rust crate {source_crate!r}"
        )
    if source_crate == MAPPING_RUST_CRATE:
        return rust

    rebased = dict(rust)
    items = []
    for original in rust["items"]:
        item = dict(original)
        item["rustPath"] = _rebase_rust_path(
            item["rustPath"], source_crate, MAPPING_RUST_CRATE
        )
        item["aliases"] = [
            _rebase_rust_path(alias, source_crate, MAPPING_RUST_CRATE)
            for alias in item.get("aliases", [])
        ]
        parent = item.get("parentRustPath")
        if parent is not None:
            item["parentRustPath"] = _rebase_rust_path(
                parent, source_crate, MAPPING_RUST_CRATE
            )
        items.append(item)
    rebased["items"] = items
    return rebased


def _ledger_with_mapping_root(ledger: dict[str, Any]) -> dict[str, Any]:
    rebased = dict(ledger)
    entries = []
    for original in ledger["entries"]:
        entry = dict(original)
        entry["rustPath"] = _rebase_rust_path(
            entry["rustPath"], "yosoi_sdk", MAPPING_RUST_CRATE
        )
        entries.append(entry)
    rebased["entries"] = entries
    return rebased


def _matches_prior_mapping(entry: dict[str, Any], item: dict[str, Any]) -> bool:
    selector = entry.get("symbolKey")
    if selector == item["symbolKey"]:
        return True
    if entry["rustPath"] not in {item["rustPath"], *item.get("aliases", [])}:
        return False
    if entry.get("trait") != item.get("trait"):
        return False
    if selector:
        old_signature = re.search(r"@signature:([^@]+)", selector)
        new_signature = re.search(r"@signature:([^@]+)", item["symbolKey"])
        if old_signature and new_signature:
            return old_signature.group(1) == new_signature.group(1)
        if old_signature and item.get("surface") == "item" and not new_signature:
            old_kind = re.match(r"(?:page|member):([^:]+):", selector)
            signature = item.get("signature")
            return (
                old_kind is not None
                and old_kind.group(1) == item.get("kind")
                and isinstance(signature, str)
                and old_signature.group(1)
                == parity.digest_bytes(signature.encode("utf-8"))
            )
    return selector is None


def _ledger_with_source_root(
    ledger: dict[str, Any], source_crate: str
) -> dict[str, Any]:
    rebased = dict(ledger)
    entries = []
    for original in ledger["entries"]:
        entry = dict(original)
        entry["rustPath"] = _rebase_rust_path(
            entry["rustPath"], MAPPING_RUST_CRATE, source_crate
        )
        entries.append(entry)
    rebased["entries"] = entries
    return rebased


ERROR_TARGETS = {
    "ArchiveRefError": "yosoi.errors.ArchiveError",
    "CoordinateError": "yosoi.errors.LocatorError",
    "ContractLocatorError": "yosoi.errors.ContractError",
    "ContractSchemaError": "yosoi.errors.ContractError",
    "DocumentError": "yosoi.errors.DocumentError",
    "FileDocumentError": "yosoi.errors.FileDocumentError",
    "DocumentProfileError": "yosoi.errors.DocumentError",
    "LocatorError": "yosoi.errors.LocatorError",
    "MapError": "yosoi.errors.MapError",
    "OccurrenceIdParseError": "yosoi.errors.RequestError",
    "ParseError": "yosoi.errors.ParseError",
    "PlanError": "yosoi.errors.LocatorError",
    "PolicyError": "yosoi.errors.PolicyError",
    "QueryError": "yosoi.errors.LocatorError",
    "RequestError": "yosoi.errors.RequestError",
    "RequestPreparationError": "yosoi.errors.RequestError",
    "RequestSendError": "yosoi.errors.RequestError",
    "ResourceBudgetError": "yosoi.errors.LocatorError",
    "RuntimeContractError": "yosoi.errors.ContractError",
    "RuntimeContractArchiveError": "yosoi.errors.ContractError",
    "SearchError": "yosoi.errors.SearchError",
    "SearchQueryError": "yosoi.errors.SearchError",
    "SearchReplayError": "yosoi.errors.SearchError",
    "SearchSendError": "yosoi.errors.SearchError",
    "SearchFailure": "yosoi.search.Failed.value",
    "SearchUnavailableReason": "yosoi.search.NotStarted.value",
    "SurfaceError": "yosoi.SurfaceError",
}

VALUE_TARGETS = {
    "yosoi::Continuation": "yosoi.policy.Continuation",
    "yosoi::FlowPolicy": "yosoi.policy.FlowPolicy",
    "yosoi::StopScope": "yosoi.policy.StopScope",
    "yosoi::CountLimit": "yosoi.scalars.CountLimit",
    "yosoi::DocumentId": "yosoi.scalars.DocumentId",
    "yosoi::DocumentProfile": "yosoi.documents.DocumentProfile",
    "yosoi::documents::DEFAULT_FILE_MAX_BYTES": "yosoi.documents.DEFAULT_FILE_MAX_BYTES",
    "yosoi::documents::MAX_FILE_BYTES": "yosoi.documents.MAX_FILE_BYTES",
    "yosoi::policy::observe::MAX_RECORDING_DURATION_MS": "yosoi.policy.MAX_RECORDING_DURATION_MS",
    "yosoi::DocumentProfileError": "yosoi.errors.DocumentError",
    "yosoi::documents::FileDocument": "yosoi.documents.FileDocument",
    "yosoi::documents::ImageDocument": "yosoi.documents.ImageDocument",
    "yosoi::documents::VideoDocument": "yosoi.documents.VideoDocument",
    "yosoi::documents::AudioDocument": "yosoi.documents.AudioDocument",
    "yosoi::documents::BinaryDocument": "yosoi.documents.BinaryDocument",
    "yosoi::documents::FileLimits": "yosoi.documents.FileLimits",
    "yosoi::documents::FileMetadata": "yosoi.documents.FileMetadata",
    "yosoi::documents::FileDocumentError": "yosoi.errors.FileDocumentError",
    "yosoi::documents::DEFAULT_FILE_MAX_BYTES": "yosoi.documents.FileLimits.max_bytes",
    "yosoi::documents::MAX_FILE_BYTES": "yosoi.documents.FileLimits.max_bytes",
    "yosoi::documents::MAX_SOURCE_BYTES": "yosoi.documents.FileMetadata.source",
    "yosoi::documents::file_from_bytes": "yosoi.documents.file_from_bytes",
    "yosoi::documents::read_file": "yosoi.documents.read_file",
    "yosoi::EffectivePolicyIdentity": "yosoi.policy.PolicyIdentity",
    "yosoi::LocateOutcome": "yosoi.outcomes.LocateOutcome",
    "yosoi::PolicyError": "yosoi.errors.PolicyError",
    "yosoi::ResponseTermination": "yosoi.request.Response.termination",
    "yosoi::contracts::ContractId": "yosoi.scalars.ContractId",
    "yosoi::contracts::ContractLocatorError": "yosoi.errors.ContractError",
    "yosoi::contracts::ContractSchemaError": "yosoi.contracts.ContractSchemaFailure",
    "yosoi::contracts::ExtractionFailure": "yosoi.contracts.RuntimeExtractionFailure",
    "yosoi::contracts::ValidationFailure": "yosoi.contracts.RuntimeValidationFailure",
    "yosoi::contracts::FieldId": "yosoi.scalars.FieldId",
    "yosoi::contracts::ExtractionLimit": "yosoi.runtime_contracts.ExtractionLimitName",
    "yosoi::contracts::RecordScope": "yosoi.contracts.ContractSchema.scope",
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
    "yosoi::map::Rejection": "yosoi.map.Rejection",
    "yosoi::map::SkipReason": "yosoi.map.SkipReason",
    "yosoi::map::SourceSkipReason": "yosoi.map.SourceSkipReason",
    "yosoi::policy::Limits": "yosoi.policy.MapLimits",
    "yosoi::request::ActivityId": "yosoi.request.ActivityId",
    "yosoi::request::CaptureId": "yosoi.request.CaptureId",
    "yosoi::request::RequestId": "yosoi.request.RequestId",
    "yosoi::policy::DiscoveryDocuments": "yosoi.policy.DiscoveryDocuments",
    "yosoi::map::HostVerification": "yosoi.map.HostEntry.verification",
    "yosoi::map::LimitReached": "yosoi.map.MapTermination.value",
    "yosoi::map::PendingReason": "yosoi.map.FrontierEntry.reason",
    "yosoi::map::RelationshipKind": "yosoi.map.RelationshipKind",
    "yosoi::map::SupportDocumentKind": "yosoi.map.SupportDocument.kind",
    "yosoi::policy::search::ProfileSelectionKind": "yosoi.policy.ProfileSelection.kind",
    "yosoi::request::AttemptDiagnostic": "yosoi.request.AttemptDiagnostic",
    "yosoi::request::AttemptFailureKind": "yosoi.diagnostics.AttemptFailureKind",
    "yosoi::request::AttemptState": "yosoi.request.Attempt.state",
    "yosoi::request::NotStartedReason": "yosoi.diagnostics.NotStartedReason",
    "yosoi::request::PartialReason": "yosoi.request.PartialReason",
    "yosoi::request::BrowserFailureReason": "yosoi.diagnostics.BrowserFailureReason",
    "yosoi::request::DecodingErrorCode": "yosoi.diagnostics.DecodingErrorCode",
    "yosoi::request::DirectHttpRedirectErrorKind": "yosoi.diagnostics.DirectHttpRedirectErrorKind",
    "yosoi::request::DirectHttpTransportErrorKind": "yosoi.diagnostics.TransportDiagnostic",
    "yosoi::request::UnknownReason": "yosoi.diagnostics.UnknownReason",
    "yosoi::request::WebArtifactFamily": "yosoi.diagnostics.WebArtifactFamily",
    "yosoi::request::UnavailableReason": "yosoi.request.UnavailableReason",
    "yosoi::request::UnprojectableReason": "yosoi.request.UnprojectableReason",
    "yosoi::search::RequestAttemptTerminal": "yosoi.search.RequestAttemptSummary.terminal",
    "yosoi::search::SearchAttemptDiagnostic": "yosoi.search.SearchAttemptDiagnostic",
    "yosoi::search::SearchCaptureRetention": "yosoi.search.SearchCaptureRetention",
    "yosoi::search::SearchParserDiagnostic": "yosoi.search.SearchParserDiagnostic",
    "yosoi::search::SearchParserStatus": "yosoi.search.SearchParserStatus",
    "yosoi::search::SearchIssueKind": "yosoi.search.SearchIssueKind",
    "yosoi::documents::AccessibilityCompleteness": "yosoi.outcomes.Completeness",
    "yosoi::documents::DocumentEpoch": "yosoi.scalars.DocumentEpoch",
    "yosoi::documents::DocumentError": "yosoi.errors.DocumentError",
    "yosoi::documents::DocumentRepresentation": "yosoi.documents.DocumentProfile.representation",
    "yosoi::documents::DocumentSchemaProfile": "yosoi.documents.DocumentProfile.schema_profile",
    "yosoi::documents::ParseError": "yosoi.errors.ParseError",
    "yosoi::locators::AccessibilityStateName": "yosoi.locators.AccessibilityStateName",
    "yosoi::locators::CoordinateError": "yosoi.errors.LocatorError",
    "yosoi::locators::DomNodeId": "yosoi.scalars.DomNodeId",
    "yosoi::locators::JsonCoordinate": "yosoi.scalars.JsonCoordinate",
    "yosoi::locators::JsonQuerySyntaxError": "yosoi.locators.JsonQuerySyntaxError",
    "yosoi::locators::LocateFailure": "yosoi.outcomes.Failure",
    "yosoi::locators::NamedOutput": "yosoi.locators.Output",
    "yosoi::locators::OutputPlan": "yosoi.locators.Locator",
    "yosoi::locators::RegionPlan": "yosoi.locators.Region",
    "yosoi::locators::OutputId": "yosoi.scalars.OutputId",
    "yosoi::locators::PlanError": "yosoi.errors.LocatorError",
    "yosoi::locators::QueryError": "yosoi.errors.LocatorError",
    "yosoi::locators::RegionId": "yosoi.scalars.RegionId",
    "yosoi::locators::ResourceLimit": "yosoi.outcomes.ResourceLimit",
    "yosoi::map::MapError": "yosoi.errors.MapError",
    "yosoi::map::PolicySnapshot": "yosoi.policy.PolicySnapshot",
    "yosoi::policy::AccessibilityNodeLimit": "yosoi.scalars.AccessibilityNodeLimit",
    "yosoi::policy::AddressableByteLimit": "yosoi.scalars.AddressableByteLimit",
    "yosoi::policy::BrowserMode": "yosoi.policy.BrowserMode",
    "yosoi::policy::Budget": "yosoi.scalars.Budget",
    "yosoi::policy::DirectHttpRedirectTargets": "yosoi.policy.DirectHttpRedirectTargets",
    "yosoi::policy::DirectHttpRedirects": "yosoi.policy.Redirects",
    "yosoi::policy::DocumentRequest": "yosoi.policy.DocumentRequest",
    "yosoi::policy::DocumentSelectionKind": "yosoi.policy.DocumentSelectionKind",
    "yosoi::policy::EventLimit": "yosoi.scalars.EventLimit",
    "yosoi::policy::HostScope": "yosoi.policy.HostScope",
    "yosoi::policy::MaximumElapsed": "yosoi.scalars.MaximumElapsed",
    "yosoi::policy::PageDiscovery": "yosoi.policy.PageDiscovery",
    "yosoi::policy::PathScope": "yosoi.policy.PathScope",
    "yosoi::policy::ProviderDefaultsVersion": "yosoi.scalars.ProviderDefaultsVersion",
    "yosoi::policy::RedirectHopLimit": "yosoi.scalars.RedirectHopLimit",
    "yosoi::policy::ResourceLimit": "yosoi.scalars.ResourceLimit",
    "yosoi::policy::Robots": "yosoi.policy.Robots",
    "yosoi::policy::Subdomains": "yosoi.policy.Subdomains",
    "yosoi::policy::TuningMode": "yosoi.policy.TuningMode",
    "yosoi::policy::search::Provider": "yosoi.policy.Provider",
    "yosoi::StepLimit": "yosoi.scalars.StepLimit",
    "yosoi::request::RequestPreparationError": "yosoi.errors.RequestError",
    "yosoi::request::RequestSendError": "yosoi.errors.RequestError",
    "yosoi::request::WebTarget": "yosoi.request.WebTarget",
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
    "yosoi::documents::FileDocument": (
        "Python exposes the Rust media enum as the union of concrete immutable "
        "ImageDocument, VideoDocument, AudioDocument, and BinaryDocument classes; "
        "native Rust performs classification."
    ),
    "yosoi::documents::ImageDocument": (
        "Python ImageDocument retains the same exact image bytes and native "
        "signature-checked metadata."
    ),
    "yosoi::documents::VideoDocument": (
        "Python VideoDocument retains the same exact video bytes and native "
        "signature-checked metadata."
    ),
    "yosoi::documents::AudioDocument": (
        "Python AudioDocument retains the same exact audio bytes and native "
        "signature-checked metadata."
    ),
    "yosoi::documents::BinaryDocument": (
        "Python BinaryDocument retains opaque bytes even when a media signature "
        "is recognized."
    ),
    "yosoi::documents::FileLimits": (
        "Python FileLimits uses byte units with the same 64 MiB default and "
        "256 MiB hard cap."
    ),
    "yosoi::documents::FileMetadata": (
        "Python FileMetadata keeps declared MIME, detected MIME, exact source "
        "provenance, and computed digest separate."
    ),
    "yosoi::documents::FileDocumentError": (
        "Python raises the dedicated native FileDocumentError and "
        "rust_error_details retains Rust variants and payload fields."
    ),
    "yosoi::documents::DEFAULT_FILE_MAX_BYTES": (
        "Python FileLimits.max_bytes exposes the same 64 MiB default through its "
        "model-field default."
    ),
    "yosoi::documents::MAX_FILE_BYTES": (
        "Python FileLimits.max_bytes enforces the same 256 MiB hard maximum while "
        "Rust revalidates it at operation time."
    ),
    "yosoi::documents::MAX_SOURCE_BYTES": (
        "Python FileMetadata.source uses the same 1 MiB source bound; Rust checks "
        "UTF-8 byte length and the public constant is re-exported for callers."
    ),
    "yosoi::documents::file_from_bytes": (
        "The Python factory passes exact payload bytes, metadata, and byte limits "
        "to the same Rust signature classifier; it performs no media decoding."
    ),
    "yosoi::documents::read_file": (
        "The Python async factory delegates bounded regular-file reads to Rust and "
        "retains only the basename as filename metadata."
    ),
}

# These Default counterparts are exercised by independent Rust Default versus
# Python authoring-default workflows. Other traits retain proposed status.
DEFAULT_EQUIVALENTS = {
    "yosoi::map::Summary": "yosoi.map.Summary",
    "yosoi::search::SearchHitMetadata": "yosoi.search.SearchHitMetadata",
    "yosoi::Policy": "yosoi.Policy",
    "yosoi::documents::FileLimits": "yosoi.documents.FileLimits",
    "yosoi::documents::FileMetadata": "yosoi.documents.FileMetadata",
    "yosoi::policy::Page": "yosoi.policy.Page",
    "yosoi::policy::Request": "yosoi.policy.Request",
    "yosoi::policy::SourceLimits": "yosoi.policy.SourceLimits",
    "yosoi::policy::BrowserLimits": "yosoi.policy.BrowserLimits",
    "yosoi::policy::DirectHttpRedirects": "yosoi.policy.Redirects.default",
    "yosoi::policy::Documents": "yosoi.policy.Documents",
    "yosoi::policy::Locators": "yosoi.policy.Locators",
    "yosoi::policy::Map": "yosoi.policy.Map",
    "yosoi::policy::Limits": "yosoi.policy.MapLimits",
    "yosoi::policy::Filters": "yosoi.policy.Filters",
    "yosoi::policy::Scope": "yosoi.policy.Scope",
    "yosoi::policy::Tuning": "yosoi.policy.Tuning",
    "yosoi::policy::ObserveLimits": "yosoi.policy.ObserveLimits",
    "yosoi::policy::ObservePolicy": "yosoi.policy.ObservePolicy",
    "yosoi::policy::RecordingRule": "yosoi.policy.RecordingRule",
    "yosoi::policy::ScreenshotPolicy": "yosoi.policy.ScreenshotPolicy",
    "yosoi::policy::search::Search": "yosoi.policy.Search",
    "yosoi::policy::EventLimit": "yosoi.policy.EventLimit.default",
    "yosoi::policy::MaximumElapsed": "yosoi.policy.MaximumElapsed.default",
    "yosoi::policy::RedirectHopLimit": "yosoi.policy.RedirectHopLimit.default",
    "yosoi::documents::FileLimits": "yosoi.documents.FileLimits",
    "yosoi::documents::FileMetadata": "yosoi.documents.FileMetadata",
}

ITEM_SEMANTIC_EQUIVALENTS = {
    "yosoi::contracts::ContractValue": (
        "The structural Python ContractValue protocol exposes TYPE_ID; "
        "value_type_id returns the same identity. This trait supplies schema "
        "identity only, not a custom extraction or validation converter."
    ),
    "yosoi::locators::NamedOutput": "Python Output(id, locator) represents the Rust named output.",
    "yosoi::locators::OutputPlan": "Python Locator is the Rust output selection before Plan compilation.",
    "yosoi::locators::RegionPlan": "Python Region represents the Rust region id/query and find operation.",
    "yosoi::documents::FileDocument": (
        "Signature classification selects one concrete Python union member, with "
        "all variants retaining the same opaque bytes and provenance semantics "
        "as the Rust enum."
    ),
    "yosoi::documents::ImageDocument": (
        "The Python concrete class is backed by the same Rust image document; "
        "signatures are checked without decoding pixels."
    ),
    "yosoi::documents::VideoDocument": (
        "The Python concrete class is backed by the same Rust video document; "
        "signatures are checked without codec or frame decoding."
    ),
    "yosoi::documents::AudioDocument": (
        "The Python concrete class is backed by the same Rust audio document; "
        "signatures are checked without decoding tracks."
    ),
    "yosoi::documents::BinaryDocument": (
        "The Python concrete class retains arbitrary exact bytes; detected media "
        "metadata remains separate from the caller-selected binary family."
    ),
    "yosoi::documents::FileLimits": (
        "Python and Rust limits count payload bytes and enforce the same default "
        "and hard maximum."
    ),
    "yosoi::documents::FileMetadata": (
        "Declared and detected media types remain distinct. Rust computes the "
        "payload digest, and source provenance preserves the exact value within "
        "its UTF-8 bound."
    ),
    "yosoi::documents::FileDocumentError": (
        "Both interfaces retain typed invalid-size, type-mismatch, metadata, "
        "source, and unavailable-body failures."
    ),
    "yosoi::documents::DEFAULT_FILE_MAX_BYTES": (
        "Rust's 64 MiB default equals the default value of Python FileLimits.max_bytes."
    ),
    "yosoi::documents::MAX_FILE_BYTES": (
        "Rust and Python FileLimits enforce the same 256 MiB hard cap."
    ),
    "yosoi::documents::MAX_SOURCE_BYTES": (
        "Rust checks the UTF-8 byte size of source metadata; Python exposes the "
        "same 1 MiB MAX_SOURCE_BYTES value and applies it to FileMetadata.source."
    ),
    "yosoi::documents::file_from_bytes": (
        "Both factories retain exact bytes and classify by signature without "
        "invoking a decoder; unknown and non-media bytes remain BinaryDocument."
    ),
    "yosoi::documents::read_file": (
        "Both operations perform bounded regular-file reads through Rust, classify "
        "the retained bytes, and keep only the basename as filename metadata."
    ),
}

MEMBER_TARGETS = {
    "yosoi::search::ProviderResult::captures": "yosoi.search.ProviderResult.diagnostic_captures",
    "yosoi::request::DocumentOutcome::document": "yosoi.request.DocumentOutcome.document",
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
    "yosoi::request::Attempt::body_bytes": "yosoi.request.Attempt.body",
    "yosoi::request::Attempt::content_type": "yosoi.request.Attempt.content_type",
    "yosoi::request::Attempt::file_document": "yosoi.request.Attempt.file_document",
    "yosoi::contracts::Contract::schema": "yosoi.contracts.Contract.contract_schema",
    "yosoi::contracts::CandidateField::id": "yosoi.contracts.CandidateField.field_id",
    "yosoi::contracts::CandidateField::len": "yosoi.contracts.CandidateField.__len__",
    "yosoi::policy::Acquisition::documents": "yosoi.policy.Acquisition.with_documents",
    "yosoi::policy::Filters::validate": "yosoi.policy.Filters.check",
    "yosoi::policy::Map::validate": "yosoi.policy.Map.check",
    "yosoi::locators::AccessibilityStateName::as_str": "yosoi.locators.AccessibilityStateName",
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
    "yosoi::contracts::RuntimeContractOutcome::to_archived": "yosoi.contracts.RuntimeContractOutcome.to_archived",
    "yosoi::request::WebTarget::as_str": "yosoi.request.WebTarget.as_str",
    "yosoi::documents::FileDocument::id": "yosoi.documents.FileDocument.id",
    "yosoi::documents::FileDocument::metadata": "yosoi.documents.FileDocument.metadata",
    "yosoi::documents::FileDocument::bytes": "yosoi.documents.FileDocument.bytes",
    "yosoi::documents::FileDocument::byte_len": "yosoi.documents.FileDocument.byte_len",
    "yosoi::documents::FileDocument::sha256": "yosoi.documents.FileDocument.sha256",
    "yosoi::documents::VideoDocument::copy_with_metadata": (
        "yosoi.documents.VideoDocument.copy_with_metadata"
    ),
    "yosoi::documents::FileLimits::max_bytes": "yosoi.documents.FileLimits.max_bytes",
    "yosoi::documents::FileMetadata::filename": "yosoi.documents.FileMetadata.filename",
    "yosoi::documents::FileMetadata::declared_media_type": (
        "yosoi.documents.FileMetadata.declared_media_type"
    ),
    "yosoi::documents::FileMetadata::detected_media_type": (
        "yosoi.documents.FileMetadata.detected_media_type"
    ),
    "yosoi::documents::FileMetadata::source": "yosoi.documents.FileMetadata.source",
    "yosoi::documents::FileMetadata::capture_id": (
        "yosoi.documents.FileMetadata.capture_id"
    ),
    "yosoi::documents::FileMetadata::session_id": (
        "yosoi.documents.FileMetadata.session_id"
    ),
    "yosoi::documents::FileMetadata::tab_id": "yosoi.documents.FileMetadata.tab_id",
    "yosoi::documents::FileMetadata::download_id": (
        "yosoi.documents.FileMetadata.download_id"
    ),
    "yosoi::documents::FileMetadata::probe_validated_video_container": (
        "yosoi.documents.FileMetadata.probe_validated_video_container"
    ),
    "yosoi::documents::FileMetadata::sha256": "yosoi.documents.FileMetadata.sha256",
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
    **{
        f"yosoi::documents::{document}::{method}": (
            f"yosoi.documents.{document}.from_bytes"
        )
        for document in (
            "ImageDocument",
            "VideoDocument",
            "AudioDocument",
            "BinaryDocument",
        )
        for method in ("from_bytes_with_limits", "from_bytes_with_metadata")
    },
}

for _media_document_type in (
    "ImageDocument",
    "VideoDocument",
    "AudioDocument",
    "BinaryDocument",
):
    for _media_document_member in ("id", "metadata", "bytes", "byte_len", "sha256"):
        MEMBER_TARGETS[
            f"yosoi::documents::{_media_document_type}::{_media_document_member}"
        ] = f"yosoi.documents.{_media_document_type}.{_media_document_member}"
    for _constructor in (
        "from_bytes",
        "from_bytes_with_limits",
        "from_bytes_with_metadata",
    ):
        MEMBER_TARGETS[f"yosoi::documents::{_media_document_type}::{_constructor}"] = (
            f"yosoi.documents.{_media_document_type}.from_bytes"
        )

FILE_DOCUMENT_VARIANT_TARGETS = {
    "yosoi::documents::FileDocument": {
        "Image": "yosoi.ImageDocument",
        "Video": "yosoi.VideoDocument",
        "Audio": "yosoi.AudioDocument",
        "Binary": "yosoi.BinaryDocument",
    }
}

FILE_DOCUMENT_ERROR_VARIANT_FIELDS = {
    "TooLarge": {
        "maximum": "details.maximum",
        "observed": "details.observed",
    },
    "LimitExceedsHardMaximum": {
        "configured": "details.configured",
        "maximum": "details.maximum",
    },
    "MetadataTooLong": {
        "field": "details.field",
        "maximum": "details.maximum",
        "observed": "details.observed",
    },
    "TypeMismatch": {
        "expected": "details.expected",
        "detected": "details.detected",
    },
    "BodyUnavailable": {},
    "ArchivedMetadataMismatch": {},
    "NotRegularFile": {"0": "details.path"},
    "Document": {
        "0": "details.message",
    },
    "Io": {
        "path": "details.path",
        "source": "source_chain.[*]",
    },
}

FILE_DOCUMENT_ERROR_SOURCE_FIELDS = {
    "Document": {
        "0": "source_chain.[*]",
    }
}

FILE_METADATA_BUILDER_FIELDS = {
    "with_filename": "filename",
    "with_declared_media_type": "declared_media_type",
    "with_source": "source",
    "with_capture_id": "capture_id",
    "with_session_id": "session_id",
    "with_tab_id": "tab_id",
    "with_download_id": "download_id",
}

MEMBER_MAPPING_RATIONALES = {
    "yosoi::Archive::write": (
        "Rust Archive writes each sealed value through its typed ArchiveValue; "
        "Python dispatches media subclasses at runtime and returns the exact "
        "typed reference."
    ),
    "yosoi::Archive::read": (
        "Rust Archive reads through the supplied typed ArchiveReference; Python "
        "dispatches typed media references and restores the matching concrete class."
    ),
    "yosoi::request::Attempt::file_document": (
        "Python converts only this Attempt's complete retained Direct HTTP body "
        "through the same Rust media factory; no second request is issued."
    ),
    **{
        f"yosoi::documents::FileMetadata::{builder}": (
            f"Rust FileMetadata::{builder} returns immutable metadata with the "
            f"{field} value set; Python's immutable FileMetadata constructor exposes "
            "that same field in its authoring model."
        )
        for builder, field in FILE_METADATA_BUILDER_FIELDS.items()
    },
}

MEMBER_SEMANTIC_EQUIVALENTS = {
    "yosoi::Archive::write": (
        "Both write paths retain the concrete document type, exact bytes, and "
        "metadata; "
        "the Python overloads return ImageDocumentArchiveRef, VideoDocumentArchiveRef, "
        "AudioDocumentArchiveRef, or BinaryDocumentArchiveRef for media values."
    ),
    "yosoi::Archive::read": (
        "Both read paths use typed references and restore the corresponding concrete "
        "file-document class with the same identity, metadata, and payload."
    ),
    "yosoi::request::Attempt::file_document": (
        "Both conversions require a complete retained HTTP body, reuse the original "
        "native payload, retain status and declared MIME separately, and raise a "
        "typed BodyUnavailable failure for incomplete or omitted bytes."
    ),
    "yosoi::documents::FileDocument::bytes": (
        "Rust lends the exact byte slice; Python returns a bytes copy from the same "
        "Rust-owned immutable payload."
    ),
    **{
        f"yosoi::documents::{media_type}::bytes": (
            "Rust lends the exact media payload bytes; Python returns a bytes copy "
            "from the same Rust-owned immutable payload."
        )
        for media_type in (
            "ImageDocument",
            "VideoDocument",
            "AudioDocument",
            "BinaryDocument",
        )
    },
    "yosoi::documents::FileLimits::max_bytes": (
        "Both accessors expose the configured payload limit in bytes."
    ),
    "yosoi::documents::FileMetadata::sha256": (
        "Both metadata values expose no digest before payload construction and the "
        "canonical SHA-256 hex string after construction."
    ),
    "yosoi::documents::FileMetadata::probe_validated_video_container": (
        "Both metadata views expose the FFprobe-confirmed Ogg or MPEG-TS container "
        "only for decoder-validated typed video sources. Rust populates the field; "
        "authored metadata cannot create this classification basis."
    ),
    "yosoi::documents::VideoDocument::copy_with_metadata": (
        "Both copies retain the same immutable payload and concrete video family. "
        "A decoder-confirmed Ogg or MPEG-TS source keeps its existing provenance "
        "basis while detector MIME and payload digest remain Rust-computed."
    ),
    **{
        f"yosoi::documents::FileMetadata::{builder}": (
            f"The Rust builder value and Python FileMetadata.{field} field produce "
            "the same retained metadata value; Rust enforces UTF-8 byte limits "
            "before a file document retains it."
        )
        for builder, field in FILE_METADATA_BUILDER_FIELDS.items()
    },
}

REFRESH_EXISTING_MEMBER_MAPPINGS = {
    "yosoi::Archive::read",
    "yosoi::Archive::write",
}

for _media_type in (
    "ImageDocument",
    "VideoDocument",
    "AudioDocument",
    "BinaryDocument",
):
    for _member in ("id", "metadata", "bytes", "byte_len", "sha256"):
        MEMBER_TARGETS[f"yosoi::documents::{_media_type}::{_member}"] = (
            f"yosoi.documents.{_media_type}.{_member}"
        )

VARIANT_PARENT_TARGETS = {
    "yosoi::Continuation": {
        "Continue": "yosoi.policy.Continue",
        "Stop": "yosoi.policy.Stop",
    },
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


FILE_DOCUMENT_ERROR_OUTPUT_FIELDS = {
    "TooLarge": [
        ("maximum", "details.maximum", "Exact native file-size limit in bytes."),
        ("observed", "details.observed", "Exact observed payload size in bytes."),
    ],
    "LimitExceedsHardMaximum": [
        ("configured", "details.configured", "Exact configured file limit in bytes."),
        ("maximum", "details.maximum", "Exact native file-size hard cap in bytes."),
    ],
    "MetadataTooLong": [
        ("field", "details.field", "Exact metadata field name."),
        ("maximum", "details.maximum", "Exact UTF-8 byte bound."),
        ("observed", "details.observed", "Exact observed UTF-8 byte length."),
    ],
    "TypeMismatch": [
        ("expected", "details.expected", "Requested media family."),
        ("detected", "details.detected", "Detected MIME family or null."),
    ],
    "BodyUnavailable": [],
    "ArchivedMetadataMismatch": [],
    "NotRegularFile": [
        (
            "0",
            "details.path",
            "PathBuf rendered as the native error's lossy path string.",
        ),
    ],
    "Document": [
        (
            "0",
            "details.message",
            "Nested DocumentError Display text; source_chain is preserved separately.",
        ),
    ],
    "Io": [
        (
            "path",
            "details.path",
            "PathBuf rendered as the native error's lossy path string.",
        ),
        ("source", "source_chain[*]", "Underlying filesystem error Display text."),
    ],
}

POLICY_ERROR_OUTPUT_FIELDS = {
    "ObservationRulesExceedRecordingLimit": [
        (
            "configured",
            "details.configured",
            "Exact number of configured recording rules.",
        ),
        ("maximum", "details.maximum", "Exact configured maximum recording count."),
    ],
}

VARIANT_MODEL_PARENTS = {
    "yosoi::contracts::FieldIssueKind",
    "yosoi::contracts::ExtractionDiagnostic",
    "yosoi::locators::LocateFailure",
    "yosoi::policy::Acquisition",
    "yosoi::policy::ProfileSelection",
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
    "yosoi::policy::IpFamily": "yosoi.policy.Network.ip_family",
    "yosoi::policy::BrowserMode": "yosoi.policy.Acquisition.mode",
    "yosoi::policy::AcquisitionKind": "yosoi.policy.Acquisition.kind",
    "yosoi::policy::DirectHttpRedirectTargets": "yosoi.policy.Redirects.targets",
    "yosoi::policy::DirectHttpRedirects": "yosoi.policy.Redirects.kind",
    "yosoi::policy::DocumentRequest": "yosoi.policy.DocumentSelection.documents",
    "yosoi::policy::DocumentSelectionKind": "yosoi.policy.DocumentSelection.kind",
    "yosoi::policy::DiscoveryDocuments": "yosoi.policy.DiscoveryDocuments",
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
    "yosoi::request::AttemptDiagnostic": "yosoi.request.AttemptDiagnostic",
    "yosoi::request::NotStartedReason": "yosoi.request.Attempt.not_started_reason",
    "yosoi::request::PartialReason": "yosoi.request.PartialReason",
    "yosoi::request::UnavailableReason": "yosoi.request.UnavailableReason",
    "yosoi::request::UnprojectableReason": "yosoi.request.UnprojectableReason",
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

REVIEWED_MEDIA_TRAIT_DISPOSITIONS: dict[tuple[str, str], dict[str, str]] = {}
for _media_type in (
    "AudioDocument",
    "BinaryDocument",
    "ImageDocument",
    "VideoDocument",
):
    _media_target = f"yosoi.documents.{_media_type}"
    REVIEWED_MEDIA_TRAIT_DISPOSITIONS[
        (f"yosoi::documents::{_media_type}::eq", "PartialEq")
    ] = {
        "pythonTarget": _media_target,
        "pythonEquivalent": (
            "Python == delegates to the native concrete-value comparison, which "
            "compares family, id, metadata, and exact bytes while ignoring shared "
            "handles and acquisition limits."
        ),
        "rationale": (
            "Rust PartialEq and Python equality use the same Rust-backed value "
            "comparison for this concrete document; acquisition limits and handle "
            "identity do not affect equality."
        ),
    }
    REVIEWED_MEDIA_TRAIT_DISPOSITIONS[
        (f"yosoi::documents::{_media_type}::fmt", "Debug")
    ] = {
        "pythonTarget": _media_target,
        "pythonEquivalent": (
            "Python repr(value) is the diagnostic view; callers use explicit "
            "properties for id, metadata, byte length, digest, and payload."
        ),
        "rationale": (
            "Rust Debug formatter flags and wrapper syntax have no Python protocol "
            "equivalent. The immutable Python model repr is diagnostic, and exact "
            "formatter text is not part of parity."
        ),
    }

REVIEWED_MEDIA_TRAIT_DISPOSITIONS.update(
    {
        ("yosoi::documents::FileDocument::clone", "Clone"): {
            "pythonTarget": "yosoi.documents.FileDocument",
            "pythonEquivalent": (
                "Clone the concrete Python document with value.clone(); it keeps "
                "the same concrete family, id, metadata, and bytes while sharing "
                "the immutable native payload handle."
            ),
            "rationale": (
                "Rust FileDocument::clone preserves its concrete variant and the "
                "same immutable inner value. Python exposes clone on each concrete "
                "file model, not on the union alias."
            ),
        },
        ("yosoi::documents::FileDocument::eq", "PartialEq"): {
            "pythonTarget": "yosoi.documents.FileDocument",
            "pythonEquivalent": (
                "Python == on the concrete union member delegates to native value "
                "equality and returns false for different document families."
            ),
            "rationale": (
                "Rust FileDocument equality compares the concrete variant and "
                "retained value. Python returns the concrete immutable class, whose "
                "equality uses the same native value comparison."
            ),
        },
        ("yosoi::documents::FileDocument::fmt", "Debug"): {
            "pythonTarget": "yosoi.documents.FileDocument",
            "pythonEquivalent": (
                "Python repr(value) identifies the concrete model; explicit model "
                "properties expose its family and retained values."
            ),
            "rationale": (
                "Rust Debug formats the enum variant while Python exposes the "
                "corresponding concrete class. The Python repr is diagnostic; exact "
                "enum formatter text is not part of parity."
            ),
        },
        ("yosoi::documents::FileDocumentError::fmt", "Display"): {
            "pythonTarget": "yosoi.errors.FileDocumentError",
            "pythonEquivalent": (
                "str(error) returns the native user-facing error message; "
                "rust_error_details(error) exposes its Rust variant and payload."
            ),
            "rationale": (
                "Rust Display and Python exception strings expose the same native "
                "error message. Python exception formatting punctuation is not a "
                "Rust formatter protocol."
            ),
        },
        ("yosoi::documents::FileDocumentError::fmt", "Debug"): {
            "pythonTarget": "yosoi.errors.FileDocumentError",
            "pythonEquivalent": (
                "Python repr(error) is diagnostic; rust_error_details(error) "
                "provides the Rust variant, structured payload, and source chain."
            ),
            "rationale": (
                "Rust Debug enum syntax differs from Python exception repr. The "
                "Python exception and rust_error_details preserve diagnostic "
                "identity without claiming textual formatter equality."
            ),
        },
        ("yosoi::documents::FileDocumentError::from", "From"): {
            "pythonTarget": "yosoi.errors.FileDocumentError",
            "pythonEquivalent": (
                "When a DocumentError reaches file conversion, Python raises "
                "FileDocumentError with variant Document and the original source "
                "message in rust_error_details(error).source_chain."
            ),
            "rationale": (
                "Rust From<DocumentError> wraps the error in FileDocumentError::Document. "
                "The native Python adapter preserves that variant and source chain; "
                "Python exposes no enum constructor or From trait API."
            ),
        },
        ("yosoi::documents::FileDocumentError::source", "Error"): {
            "pythonTarget": "yosoi.errors.FileDocumentError",
            "pythonEquivalent": (
                "rust_error_details(error).source_chain exposes nested Rust source "
                "display messages from the Python exception."
            ),
            "rationale": (
                "Rust Error::source participates in Rust error chaining. The Python "
                "exception keeps the native source chain available through "
                "rust_error_details rather than a source() trait method."
            ),
        },
    }
)

for _trait in ("Serialize", "Deserialize"):
    _verb = "serializes" if _trait == "Serialize" else "deserializes"
    REVIEWED_MEDIA_TRAIT_DISPOSITIONS[
        (f"yosoi::documents::FileLimits::{_trait.lower()}", _trait)
    ] = {
        "pythonTarget": "yosoi.documents.FileLimits",
        "pythonEquivalent": (
            "Python model_dump_json/model_validate_json expose the supported JSON "
            "model boundary; native operations enforce the authoritative byte limits."
        ),
        "rationale": (
            f"Rust serde {_verb} the FileLimits value at the JSON boundary. Python "
            "uses ordinary Pydantic JSON serialization/validation and may reject "
            "invalid bounds earlier; native operations remain authoritative."
        ),
    }
    REVIEWED_MEDIA_TRAIT_DISPOSITIONS[
        (f"yosoi::documents::FileMetadata::{_trait.lower()}", _trait)
    ] = {
        "pythonTarget": "yosoi.documents.FileMetadata",
        "pythonEquivalent": (
            "Python model_dump_json/model_validate_json expose the supported JSON "
            "metadata model; native operations enforce the authoritative UTF-8 bounds."
        ),
        "rationale": (
            f"Rust serde {_verb} FileMetadata at the JSON boundary. Python uses "
            "ordinary Pydantic JSON serialization/validation and may reject invalid "
            "metadata earlier; native operations remain authoritative."
        ),
    }

for _model_type, _target in (
    ("FileLimits", "yosoi.documents.FileLimits"),
    ("FileMetadata", "yosoi.documents.FileMetadata"),
):
    REVIEWED_MEDIA_TRAIT_DISPOSITIONS[
        (f"yosoi::documents::{_model_type}::eq", "PartialEq")
    ] = {
        "pythonTarget": _target,
        "pythonEquivalent": (
            "Python equality compares the same immutable model field values."
        ),
        "rationale": (
            f"Rust PartialEq compares the {_model_type} values; Python frozen "
            "Pydantic model equality compares the corresponding authoring fields."
        ),
    }
    REVIEWED_MEDIA_TRAIT_DISPOSITIONS[
        (f"yosoi::documents::{_model_type}::fmt", "Debug")
    ] = {
        "pythonTarget": _target,
        "pythonEquivalent": (
            "Python repr(value) is diagnostic; public fields remain directly readable."
        ),
        "rationale": (
            f"Rust Debug formatter syntax differs from Python repr for {_model_type}. "
            "The immutable model repr is diagnostic, with exact formatter text "
            "outside the parity contract."
        ),
    }

BORROWED_VIEW_METHODS = {
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
    **{
        (f"yosoi::documents::{document}::{method}", "bytes"): "content"
        for document in (
            "ImageDocument",
            "VideoDocument",
            "AudioDocument",
            "BinaryDocument",
        )
        for method in (
            "from_bytes",
            "from_bytes_with_limits",
            "from_bytes_with_metadata",
        )
    },
    ("yosoi::documents::file_from_bytes", "bytes"): "content",
    ("yosoi::Document::html", "bytes"): "content",
    ("yosoi::Document::xml", "bytes"): "content",
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

for _media_document_type in (
    "ImageDocument",
    "VideoDocument",
    "AudioDocument",
    "BinaryDocument",
):
    for _constructor in (
        "from_bytes",
        "from_bytes_with_limits",
        "from_bytes_with_metadata",
    ):
        ARGUMENT_ALIASES[
            (f"yosoi::documents::{_media_document_type}::{_constructor}", "bytes")
        ] = "content"
ARGUMENT_ALIASES[("yosoi::documents::file_from_bytes", "bytes")] = "content"
for _argument in ("id", "metadata", "limits"):
    ARGUMENT_ALIASES[
        ("yosoi::documents::VideoDocument::copy_with_metadata", _argument)
    ] = _argument

for _builder, _field in FILE_METADATA_BUILDER_FIELDS.items():
    MEMBER_TARGETS[f"yosoi::documents::FileMetadata::{_builder}"] = (
        "yosoi.documents.FileMetadata"
    )
    ARGUMENT_ALIASES[(f"yosoi::documents::FileMetadata::{_builder}", "value")] = _field

ARGUMENT_CONVERSIONS = {
    (
        f"yosoi::documents::FileMetadata::{builder}",
        "value",
    ): (
        f"The Rust builder value initializes Python FileMetadata.{field}; Rust "
        "rechecks the documented UTF-8 byte bound when the metadata is retained."
    )
    for builder, field in FILE_METADATA_BUILDER_FIELDS.items()
}
ARGUMENT_CONVERSIONS.update(
    {
        ("yosoi::documents::VideoDocument::copy_with_metadata", "id"): (
            "Both APIs revalidate the replacement stable document identity."
        ),
        ("yosoi::documents::VideoDocument::copy_with_metadata", "metadata"): (
            "Both APIs accept optional FileMetadata; omission retains the source values, "
            "while Rust recomputes detector MIME, digest and probe provenance."
        ),
        ("yosoi::documents::VideoDocument::copy_with_metadata", "limits"): (
            "Both APIs accept optional FileLimits; omission uses the 64 MiB default."
        ),
    }
)


def _python_module(rust_path: str, *, module_item: bool = False) -> str | None:
    parts = rust_path.removeprefix("yosoi::").split("::")
    if parts == ["prelude"]:
        return None
    root = parts[0]
    if root not in ROOT_MODULES:
        return "yosoi"
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
    for tag in (wire_name, member_name):
        if tag in alias.get("choices", []):
            return parent_target, tag
    for tag in (wire_name, member_name):
        if any(
            tag in member.get("discriminatorValues", [])
            for member in alias.get("unionMembers", [])
        ):
            return parent_target, tag
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
        normalized_python_type = python_type.replace("builtins.", "")
        accepts_bytes = re.search(r"(?<![\w])bytes(?![\w])", normalized_python_type)
        accepts_str = re.search(r"(?<![\w])str(?![\w])", normalized_python_type)
        if accepts_bytes and accepts_str:
            return "Python str is UTF-8 encoded; bytes are preserved"
        if accepts_bytes:
            return "Python bytes are preserved exactly; str is rejected"
        if accepts_str:
            return "Python str is UTF-8 encoded to Rust bytes; bytes are rejected"
        return (
            f"Python {python_type or 'value'} converts to Rust bytes according to "
            "its declared parameter type"
        )
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
                "conversion": ARGUMENT_CONVERSIONS.get(
                    (item["rustPath"], rust_name),
                    _conversion(argument["type"], python_parameter),
                ),
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
    variant_binding = None
    if arguments is None and item["kind"] == "variant":
        alias = target_info.get("alias") or {}
        leaf = item["rustPath"].rsplit("::", 1)[-1]
        tag = next(
            (
                candidate
                for candidate in (_snake_case(leaf), leaf)
                if any(
                    candidate in member.get("discriminatorValues", [])
                    for member in alias.get("unionMembers", [])
                )
            ),
            None,
        )
        members = [
            member
            for member in alias.get("unionMembers", [])
            if tag in member.get("discriminatorValues", [])
        ]
        if alias.get("kind") == "discriminated-union" and len(members) == 1:
            fields = parity.variant_payload_fields(members[0], alias["discriminator"])
            derived = []
            if item["rustPath"] in {
                "yosoi::contracts::ExtractionFailure::InvalidContractSchema",
                "yosoi::contracts::ValidationFailure::InvalidContractSchema",
            }:
                derived = ["message"]
                fields = [field for field in fields if field["name"] not in derived]
            given = [
                argument
                for argument in item.get("rustArguments", [])
                if not argument.get("receiver")
            ]
            if len(fields) == len(given) and all(
                argument["name"] in {field["rustName"] for field in fields}
                or (argument["name"] == "0" and len(fields) == 1)
                for argument in given
            ):
                arguments = [
                    {
                        "rustArgument": argument["name"],
                        "pythonArgument": fields[0]["name"]
                        if argument["name"] == "0"
                        else next(
                            field["name"]
                            for field in fields
                            if field["rustName"] == argument["name"]
                        ),
                        "conversion": "Rust enum payload maps to the typed dictionary field validated by Pydantic TypeAdapter",
                    }
                    for argument in given
                ]
                variant_binding = {
                    "discriminator": alias["discriminator"],
                    "tag": tag,
                    "input": "TypeAdapter.validate_python",
                }
                if derived:
                    variant_binding["derivedFields"] = derived
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
    if variant_binding:
        result["variantBinding"] = variant_binding
        result["semanticEquivalent"] = (
            "TypeAdapter(public_union).validate_python accepts a tagged dictionary; "
            "the alias is not a callable constructor."
        )
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


def _reviewed_media_trait_entry(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Record an owner-approved, language-specific media trait disposition."""
    disposition = REVIEWED_MEDIA_TRAIT_DISPOSITIONS.get(
        (item["rustPath"], item.get("trait") or "")
    )
    if disposition is None:
        return None
    target = disposition["pythonTarget"]
    entry = _language_proposal(
        item,
        disposition["pythonEquivalent"],
        disposition["rationale"],
        python_target=target if target in python["targets"] else None,
    )
    entry["review"].update(
        {
            "status": "reviewed",
            "reviewer": "Codex owner",
            "reviewedAt": "2026-11-01T03:15:08Z",
        }
    )
    return entry


def _error_details_output_entry(
    item: dict[str, Any],
    *,
    python_target: str,
    rust_type: str,
    fields: list[tuple[str, str, str]],
    rationale: str,
) -> dict[str, Any]:
    """Map one Rust error variant to the native Python exception metadata."""
    variant = item["rustPath"].rsplit("::", 1)[-1]
    return {
        "rustPath": item["rustPath"],
        "symbolKey": item["symbolKey"],
        "decision": "mapped",
        "pythonTarget": python_target,
        "argumentMappings": [],
        "defaults": [],
        "units": [],
        "cardinality": [],
        "mappingDirection": "output",
        "outputBinding": {
            "kind": "error-details",
            "schemaTarget": "yosoi.errors.RustErrorDetails",
            "discriminator": "variant",
            "tag": variant,
            "rustType": rust_type,
            "pythonFields": [
                {
                    "rustArgument": rust_argument,
                    "pythonFieldPath": python_path,
                    "conversion": conversion,
                }
                for rust_argument, python_path, conversion in fields
            ],
        },
        "semanticEquivalent": (
            "The native Python exception preserves the Rust variant, structured "
            "details and source chain through rust_error_details()."
        ),
        "rationale": rationale,
    }


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
    if item["kind"] == "assoc_type" and name in {"Error", "Err"}:
        match = re.search(
            r"type\s+(?:Error|Err)\s*=\s*([A-Za-z_][A-Za-z0-9_:]*)", item["signature"]
        )
        if match:
            name = match.group(1).split("::")[-1]
    if name not in ERROR_TARGETS:
        return None
    target = ERROR_TARGETS[name]
    return target if target in python["targets"] else None


REVIEWED_CONVERSION_ASSOCIATED_TYPES = {
    (f"yosoi::archive::{reference}::Err", "FromStr")
    for reference in (
        "AudioDocumentArchiveRef",
        "BinaryDocumentArchiveRef",
        "DocumentArchiveRef",
        "FileDocumentArchiveRef",
        "ImageDocumentArchiveRef",
        "PlanArchiveRef",
        "VideoDocumentArchiveRef",
    )
} | {
    (f"yosoi::surface::model::{value}::Error", "TryFrom")
    for value in (
        "AddressToken",
        "ContinuationToken",
        "ObservationId",
        "SourceId",
        "SurfaceId",
    )
}


def _conversion_error_type_entry(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Map standard conversion error types only when Python exposes an exception."""
    trait = item.get("trait")
    if item.get("kind") != "assoc_type" or trait not in {
        "FromStr",
        "TryFrom",
        "TryInto",
    }:
        return None
    expected_name = "Err" if trait == "FromStr" else "Error"
    if item["rustPath"].rsplit("::", 1)[-1] != expected_name:
        return None

    target = _mapped_error_target(item, python)
    target_info = python["targets"].get(target) if target else None
    if target and target_info:
        return _entry(
            item,
            target,
            target_info,
            python,
            "Rust FromStr::Err maps to the corresponding public Python SDK exception.",
        )

    associated_type = item["signature"].split("=", 1)[-1].strip()
    if trait == "FromStr":
        python_equivalent = (
            "Python checked construction reports invalid text through its public "
            "validation exception."
        )
        rationale = (
            "Rust FromStr::Err is a trait-associated type, not a callable SDK member. "
            "Python has no matching associated type; its checked constructor or model "
            "validation exposes failures through Python's exception boundary."
        )
    elif "Infallible" in associated_type:
        python_equivalent = (
            "The Rust conversion has no error value; Python model construction "
            "uses its own public validation boundary."
        )
        rationale = (
            f"Rust {trait}::Error = Infallible is compile-time trait metadata, not a "
            "callable SDK member. Python has no associated error type; its typed "
            "constructor validates authoring inputs at the Python boundary."
        )
    else:
        python_equivalent = (
            "Python checked construction reports invalid values through its public "
            "validation exception."
        )
        rationale = (
            f"Rust {trait}::Error is a trait-associated type, not a callable SDK "
            "member. Python has no matching associated type; its checked constructor "
            "or model validation exposes failures through Python's exception boundary."
        )
    entry = _language_proposal(
        item,
        python_equivalent,
        rationale,
    )
    if (item["rustPath"], trait) in REVIEWED_CONVERSION_ASSOCIATED_TYPES:
        entry["review"].update(
            {
                "status": "reviewed",
                "reviewer": "Codex owner",
                "reviewedAt": "2026-11-01T03:15:08Z",
            }
        )
    return entry


def _file_document_variant_entry(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Bind one whole Rust enum payload to its concrete Python model class."""
    parent_path = item.get("parentRustPath")
    variant = item["rustPath"].rsplit("::", 1)[-1]
    target = FILE_DOCUMENT_VARIANT_TARGETS.get(parent_path, {}).get(variant)
    target_info = python["targets"].get(target) if target else None
    if (
        target_info is None
        or target_info.get("kind") != "class"
        or target_info.get("canonicalTarget", target) != target
    ):
        return None
    rust_arguments = [
        argument
        for argument in item.get("rustArguments", [])
        if not argument.get("receiver")
    ]
    if len(rust_arguments) != 1:
        return None
    type_name = target.rsplit(".", 1)[-1]
    rust_type = rust_arguments[0].get("type", "")
    rust_type_name = re.sub(r"[&*\s]", "", rust_type).rsplit("::", 1)[-1]
    if rust_type_name != type_name:
        return None
    return {
        "rustPath": item["rustPath"],
        "symbolKey": item["symbolKey"],
        "decision": "mapped",
        "pythonTarget": target,
        "argumentMappings": [],
        "defaults": [],
        "units": [],
        "cardinality": [],
        "mappingDirection": "output",
        "outputBinding": {
            "kind": "concrete-model",
            "schemaTarget": target,
            "discriminator": "python_class",
            "tag": type_name,
            "rustType": f"yosoi::documents::{type_name}",
            "pythonFields": [
                {
                    "rustArgument": rust_arguments[0]["name"],
                    "pythonFieldPath": "$",
                    "conversion": (
                        "The Rust enum payload is the same complete native value; "
                        "Python returns its corresponding concrete class instance."
                    ),
                }
            ],
            "behaviorEvidence": [
                {
                    "path": "python/tests/test_media_documents.py",
                    "test": "test_media_factory_classifies_and_redacts_payload",
                },
                {
                    "path": "crates/yosoi/src/internal/media_documents/tests.rs",
                    "test": "file_factory_classifies_signatures_without_decoding",
                },
            ],
        },
        "rationale": (
            f"Rust FileDocument::{variant} owns an already-built {type_name}; Python "
            "exposes that payload directly as the same concrete immutable model."
        ),
        "semanticEquivalent": (
            f"The Rust {variant} variant is returned as a Python {type_name} "
            "instance with the same native bytes and metadata. No separate tagged "
            "Python constructor is exposed."
        ),
    }


def _file_document_error_variant_entry(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Map typed file errors to Python details and source-chain fields."""
    target = ERROR_TARGETS["FileDocumentError"]
    if target not in python["targets"]:
        return None
    variant = item["rustPath"].rsplit("::", 1)[-1]
    detail_paths = FILE_DOCUMENT_ERROR_VARIANT_FIELDS.get(variant)
    if detail_paths is None:
        return None
    source_paths = FILE_DOCUMENT_ERROR_SOURCE_FIELDS.get(variant, {})
    arguments = [
        argument
        for argument in item.get("rustArguments", [])
        if not argument.get("receiver")
    ]
    if {argument["name"] for argument in arguments} != set(detail_paths):
        return None
    python_fields = []
    for argument in arguments:
        name = argument["name"]
        python_fields.append(
            {
                "rustArgument": name,
                "pythonFieldPath": detail_paths[name],
                "conversion": (
                    "The native FileDocumentError adapter preserves this exact "
                    "structured detail through rust_error_details."
                ),
            }
        )
        source_path = source_paths.get(name)
        if source_path is not None:
            python_fields.append(
                {
                    "rustArgument": name,
                    "pythonFieldPath": source_path,
                    "conversion": (
                        "The nested Rust error Display chain is retained in the "
                        "Python source_chain sequence."
                    ),
                }
            )
    return {
        "rustPath": item["rustPath"],
        "symbolKey": item["symbolKey"],
        "decision": "mapped",
        "pythonTarget": target,
        "argumentMappings": [],
        "defaults": [],
        "units": [],
        "cardinality": [],
        "mappingDirection": "output",
        "outputBinding": {
            "kind": "error-details",
            "schemaTarget": "yosoi.errors.RustErrorDetails",
            "discriminator": "variant",
            "tag": variant,
            "rustType": "yosoi::documents::FileDocumentError",
            "pythonFields": python_fields,
        },
        "semanticEquivalent": (
            "Python raises FileDocumentError; rust_error_details retains the "
            "Rust variant, structured detail fields, and nested source messages."
        ),
        "rationale": (
            "The PyO3 FileDocumentError adapter sets this variant tag and payload "
            "without rebuilding an arbitrary Rust error in Python."
        ),
    }


def seed_entries(
    rust: dict[str, Any], python: dict[str, Any], existing: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_rust = rust
    source_crate = (rust.get("sdk") or {}).get("crate")
    rust = _inventory_with_mapping_root(rust)
    existing = _ledger_with_mapping_root(existing)
    entries_by_identity: dict[str, dict[str, Any]] = {}
    page_targets: dict[str, str] = {}
    migrated_selectors: set[str] = set()

    # Keep explicit, source-reviewed mappings already in the seed ledger.
    for entry in existing["entries"]:
        item = next(
            (
                candidate
                for candidate in rust["items"]
                if _matches_prior_mapping(entry, candidate)
            ),
            None,
        )
        if item is not None:
            conversion_error = _conversion_error_type_entry(item, python)
            if conversion_error is not None:
                preserved = None
                if (
                    conversion_error["decision"] == "mapped"
                    and entry.get("decision") == "mapped"
                    and entry.get("pythonTarget") == conversion_error["pythonTarget"]
                ) or (
                    conversion_error["decision"] == "language-specific"
                    and entry.get("decision") == "language-specific"
                    and (entry.get("review") or {}).get("status") == "reviewed"
                ):
                    preserved = dict(entry)
                    preserved["rustPath"] = item["rustPath"]
                    preserved["symbolKey"] = item["symbolKey"]
                entries_by_identity[item["symbolKey"]] = (
                    preserved if preserved is not None else conversion_error
                )
                continue
            if entry.get("symbolKey"):
                migrated_selectors.add(entry["symbolKey"])
            copied = dict(entry)
            copied["rustPath"] = item["rustPath"]
            copied["symbolKey"] = item["symbolKey"]
            if item.get("kind") == "variant" and item.get("parentRustPath") in {
                "yosoi::contracts::ContractSchemaError",
                "yosoi::contracts::ExtractionFailure",
                "yosoi::contracts::ValidationFailure",
            }:
                target = VALUE_TARGETS[item["parentRustPath"]]
                info = python["targets"].get(target)
                if info:
                    updated = _entry(
                        item,
                        target,
                        info,
                        python,
                        "The typed Contract schema-error union preserves this Rust variant and its structured details.",
                    )
                    if updated:
                        copied = updated
            if item.get("parentRustPath") == "yosoi::documents::FileDocument":
                updated = _file_document_variant_entry(item, python)
                if updated is not None:
                    copied = updated
            preferred_target = VALUE_TARGETS.get(item["rustPath"])
            if preferred_target in python["targets"]:
                if copied.get("pythonTarget") != preferred_target:
                    copied["rationale"] = (
                        "The live Python surface exposes the corresponding public "
                        f"target {preferred_target}."
                    )
                copied["pythonTarget"] = preferred_target
            if item["rustPath"] in REFRESH_EXISTING_MEMBER_MAPPINGS:
                target = MEMBER_TARGETS.get(
                    item["rustPath"], copied.get("pythonTarget")
                )
                target_info = python["targets"].get(target) if target else None
                if target and target_info:
                    refreshed = _entry(
                        item,
                        target,
                        target_info,
                        python,
                        MEMBER_MAPPING_RATIONALES[item["rustPath"]],
                        semantic_equivalent=MEMBER_SEMANTIC_EQUIVALENTS.get(
                            item["rustPath"]
                        ),
                    )
                    if refreshed is not None:
                        copied = refreshed
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
            target = BORROWED_VIEW_TARGETS.get(item["rustPath"])
            target_info = python["targets"].get(target) if target else None
            if not target or not target_info:
                continue
            entries_by_identity[item["symbolKey"]] = _entry(
                item,
                target,
                target_info,
                python,
                f"{equivalent} Owner accepted the Python owning-view mapping; the wrapper retains the same native value and extends its lifetime.",
                semantic_equivalent="Python Document/Response owns the same native value that Rust exposes through a borrowed view.",
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
                    "Python Contract fields use Pydantic annotations; native transport retains raw strings.",
                    "The Rust value trait has no named Python union; Python field annotations select the supported scalar values. Owner review is required.",
                )
            continue
        if target is None:
            continue
        target_info = python["targets"].get(target)
        if target_info is None:
            continue
        page_targets[item["rustPath"]] = target
        if item["kind"] == "trait" and item["rustPath"] == "yosoi::contracts::Contract":
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
        conversion_error = _conversion_error_type_entry(item, python)
        if conversion_error is not None:
            entries_by_identity[item["symbolKey"]] = conversion_error
            continue
        if item["rustPath"] == "yosoi::contracts::ContractValue::TYPE_ID":
            target = "yosoi.contracts.value_type_id"
            target_info = python["targets"].get(target)
            if target_info:
                entries_by_identity[item["symbolKey"]] = _entry(
                    item,
                    target,
                    target_info,
                    python,
                    "The helper reads the scalar type's ContractValue TYPE_ID; "
                    "str uses the compiled Rust String identity.",
                    semantic_equivalent="Associated type identity maps to value_type_id(type).",
                )
            continue
        if item["parentRustPath"] == "yosoi::request::WebTarget" and (
            (item.get("trait"), item["rustPath"].rsplit("::", 1)[-1])
            in {("From", "from"), ("AsRef", "as_ref")}
        ):
            borrowed = item.get("trait") == "AsRef"
            target = (
                "yosoi.request.WebTarget.as_str"
                if borrowed
                else "yosoi.request.WebTarget.new"
            )
            target_info = python["targets"].get(target)
            if not target_info:
                continue
            row = _entry(
                item,
                target,
                target_info,
                python,
                "Rust string ownership forms preserve the authored target text; "
                "Python uses its immutable string scalar and the native SDK constructor.",
                semantic_equivalent=(
                    "AsRef<str> maps to as_str() on the same authored target."
                    if borrowed
                    else "From<&str/String/&String/Box<str>/Cow<str>> maps to "
                    "WebTarget.new(value); construction preserves text without URL preparation."
                ),
            )
            if row:
                entries_by_identity[item["symbolKey"]] = row
            continue
        if item["rustPath"] in BORROWED_VIEW_METHODS:
            target = BORROWED_VIEW_TARGETS.get(item["rustPath"])
            target_info = python["targets"].get(target) if target else None
            if not target_info:
                continue
            entries_by_identity[item["symbolKey"]] = _entry(
                item,
                target,
                target_info,
                python,
                f"{BORROWED_VIEW_METHODS[item['rustPath']]} Python retains the same native value through its owning wrapper.",
                semantic_equivalent="Python owns the same native value that Rust exposes through a borrowed view.",
            )
            continue
        parent_target = page_targets.get(item["parentRustPath"])
        if not parent_target:
            continue
        member_name = item["rustPath"].split("::")[-1]
        target = None
        rust_type = None
        rationale = ""
        semantic_equivalent = None
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
            rationale = MEMBER_MAPPING_RATIONALES.get(
                item["rustPath"],
                f"Rust method maps to the matching Python method/property {target}.",
            )
            semantic_equivalent = MEMBER_SEMANTIC_EQUIVALENTS.get(item["rustPath"])
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
            if parent["rustPath"] in FILE_DOCUMENT_VARIANT_TARGETS:
                row = _file_document_variant_entry(item, python)
                if row is not None:
                    entries_by_identity[item["symbolKey"]] = row
                continue
            if parent["rustPath"] == "yosoi::documents::FileDocumentError":
                row = _file_document_error_variant_entry(item, python)
                if row is not None:
                    entries_by_identity[item["symbolKey"]] = row
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
            if assoc in {"Error", "Err"}:
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
        elif item["kind"] == "assoc_const":
            target = f"{parent_target}.{member_name}"
            target_info = python["targets"].get(target)
            if not target_info or target_info.get("kind") != "class-constant":
                continue
            rationale = "Rust associated constant maps to the Rust-backed Python class constant."
        else:
            continue

        row = _entry(
            item,
            target,
            target_info,
            python,
            rationale,
            rust_type=rust_type,
            semantic_equivalent=semantic_equivalent,
            argument_aliases=(
                variant_argument_aliases if item["kind"] == "variant" else None
            ),
        )
        if row is not None:
            if item["kind"] == "variant":
                row["defaults"].extend(_variant_tag_defaults(target_info, member_name))
            entries_by_identity[item["symbolKey"]] = row

    for item in rust["items"]:
        if item.get("trait") != "Default":
            continue
        target = DEFAULT_EQUIVALENTS.get(item.get("parentRustPath"))
        info = python["targets"].get(target) if target else None
        if not info:
            continue
        row = _entry(
            item,
            target,
            info,
            python,
            "Rust Default maps to this Python constructor or Rust-backed default helper; "
            "independent default-model conformance compares the resulting values.",
            rust_type=item.get("parentRustPath"),
            semantic_equivalent="Rust Default value and Python authoring default value.",
        )
        if row is not None:
            entries_by_identity[item["symbolKey"]] = row

    # Checked scalar conversions use the same Rust constructor as Python's
    # inherited helper. Rust's trait dispatch is represented by that method.
    for item in rust["items"]:
        trait = item.get("trait")
        leaf = item["rustPath"].rsplit("::", 1)[-1]
        helper = {
            ("TryFrom", "try_from"): "try_new",
            ("FromStr", "from_str"): "from_str",
        }.get((trait, leaf))
        parent_target = page_targets.get(item.get("parentRustPath"))
        if not helper or not parent_target:
            continue
        target = f"{parent_target}.{helper}"
        info = python["targets"].get(target)
        if not info:
            continue
        row = _entry(
            item,
            target,
            info,
            python,
            "Rust checked conversion maps to this Rust-backed Python scalar helper.",
            semantic_equivalent="Python helper validates and constructs the same Rust scalar value.",
        )
        if row is not None:
            entries_by_identity[item["symbolKey"]] = row

    for item in rust["items"]:
        if (
            item.get("trait") != "Clone"
            or item["rustPath"].rsplit("::", 1)[-1] != "clone"
        ):
            continue
        parent_target = page_targets.get(item.get("parentRustPath"))
        target = f"{parent_target}.clone" if parent_target else None
        info = python["targets"].get(target) if target else None
        if not info:
            continue
        row = _entry(
            item,
            target,
            info,
            python,
            "The explicit SDK clone operation detaches mutable Python values while retaining immutable native ownership.",
            semantic_equivalent="Rust Clone and Python clone() return an independently editable logical value.",
        )
        if row is not None:
            entries_by_identity[item["symbolKey"]] = row

    for item in rust["items"]:
        if (
            item.get("parentRustPath") != "yosoi::locators::ProjectedValue"
            or item.get("trait") != "PartialEq"
        ):
            continue
        method = item["rustPath"].rsplit("::", 1)[-1]
        target = {
            "eq": "yosoi.outcomes.projected_values_equal",
            "ne": "yosoi.outcomes.projected_values_not_equal",
        }.get(method)
        info = python["targets"].get(target) if target else None
        if not info:
            continue
        row = _entry(
            item,
            target,
            info,
            python,
            "The typed comparison helper delegates complete projection equality to Rust.",
            argument_aliases={(item["rustPath"], "other"): "right"},
            semantic_equivalent="The helper's left argument supplies Rust self; right supplies the other projected value.",
        )
        if row:
            row["receiverMapping"] = {
                "rustArgument": "self",
                "pythonArgument": "left",
                "conversion": "Typed owning Python value supplies the borrowed Rust receiver",
            }
            entries_by_identity[item["symbolKey"]] = row

    map_ordering_types = {
        "DiscoverySource": "discovery_source",
        "Observation": "observation",
        "OmissionReason": "omission_reason",
        "PublicProvider": "public_provider",
        "Rejection": "rejection",
        "Relationship": "relationship",
        "RelationshipKind": "relationship_kind",
    }
    for item in rust["items"]:
        parent = item.get("parentRustPath") or ""
        if item.get("trait") not in {"Ord", "PartialOrd"} or not parent.startswith(
            "yosoi::map::"
        ):
            continue
        kind = map_ordering_types.get(parent.rsplit("::", 1)[-1])
        target = "yosoi.map.compare_values"
        info = python["targets"].get(target)
        if not kind or not info:
            continue
        row = _entry(
            item,
            target,
            info,
            python,
            "This fixed Map type dispatch uses the public Rust ordering implementation.",
            argument_aliases={(item["rustPath"], "other"): "right"},
            semantic_equivalent="Python returns the Rust total ordering sign; partial_cmp is always Some for these Ord types.",
        )
        if row:
            row["receiverMapping"] = {
                "rustArgument": "self",
                "pythonArgument": "left",
                "conversion": "Typed owning view supplies the borrowed Rust ordering receiver",
            }
            row["fixedArguments"] = {"kind": kind}
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

    # The owner approved only these newly scoped media standard-trait semantics.
    # Keep other generic trait proposals unreviewed until their own disposition.
    for item in rust["items"]:
        reviewed = _reviewed_media_trait_entry(item, python)
        if reviewed is not None:
            entries_by_identity[item["symbolKey"]] = reviewed

    # Preserve any remaining explicit source mappings, including rows for APIs
    # outside the current compiler feature inventory so strict mode marks them stale.
    for entry in existing["entries"]:
        selector = entry.get("symbolKey")
        if (
            selector
            and selector not in entries_by_identity
            and selector not in migrated_selectors
        ):
            entries_by_identity[selector] = dict(entry)
        elif not selector and not any(
            candidate["rustPath"] == entry["rustPath"]
            for candidate in entries_by_identity.values()
        ):
            entries_by_identity[f"legacy:{entry['rustPath']}"] = dict(entry)

    # FileDocument error values surface as the native exception category plus the
    # exact Rust variant, structured details, and source chain.
    for item in rust["items"]:
        if (
            item.get("surface") != "member"
            or item.get("kind") != "variant"
            or item.get("parentRustPath") != "yosoi::documents::FileDocumentError"
        ):
            continue
        variant = item["rustPath"].rsplit("::", 1)[-1]
        fields = FILE_DOCUMENT_ERROR_OUTPUT_FIELDS.get(variant)
        target = "yosoi.errors.FileDocumentError"
        if fields is None or target not in python["targets"]:
            continue
        entries_by_identity[item["symbolKey"]] = _error_details_output_entry(
            item,
            python_target=target,
            rust_type="yosoi::documents::FileDocumentError",
            fields=fields,
            rationale=(
                "The PyO3 media error adapter maps this Rust variant to the native "
                "FileDocumentError exception and retains its listed detail fields "
                "plus the source chain."
            ),
        )

    # This native policy failure carries a meaningful payload through
    # rust_error_details() and has a Python regression for both counts.
    for item in rust["items"]:
        if (
            item["rustPath"]
            != "yosoi::PolicyError::ObservationRulesExceedRecordingLimit"
        ):
            continue
        target = "yosoi.errors.PolicyError"
        if target not in python["targets"]:
            continue
        entries_by_identity[item["symbolKey"]] = _error_details_output_entry(
            item,
            python_target=target,
            rust_type="yosoi_policy::PolicyError",
            fields=POLICY_ERROR_OUTPUT_FIELDS["ObservationRulesExceedRecordingLimit"],
            rationale=(
                "The native PolicyError preserves configured and maximum recording "
                "counts in RustErrorDetails; test_observation_recording_limit_error_"
                "preserves_configured_counts checks both values."
            ),
        )

    # These are returned native failures, not Python exception constructors.
    # The adapter preserves the enum tag and its version/source-message payload.
    replay_payloads = {
        "UnsupportedVersion": (
            "details.version",
            "exact unsupported u16 manifest version",
        ),
        "Archive": (
            "details.source.message",
            "ArchiveError Display message; arbitrary Rust error reconstruction is not claimed",
        ),
        "Metadata": (
            "details.source.message",
            "serde_json::Error Display message; arbitrary Rust error reconstruction is not claimed",
        ),
        "InvalidBounds": None,
    }
    for item in rust["items"]:
        if (
            item.get("kind") != "variant"
            or item.get("parentRustPath") != "yosoi::search::SearchReplayError"
        ):
            continue
        variant = item["rustPath"].rsplit("::", 1)[-1]
        payload = replay_payloads.get(variant)
        entries_by_identity[item["symbolKey"]] = {
            "rustPath": item["rustPath"],
            "symbolKey": item["symbolKey"],
            "decision": "mapped",
            "pythonTarget": "yosoi.errors.SearchError",
            "argumentMappings": [],
            "defaults": [],
            "units": [],
            "cardinality": [],
            "mappingDirection": "output",
            "outputBinding": {
                "kind": "error-details",
                "schemaTarget": "yosoi.errors.RustErrorDetails",
                "discriminator": "variant",
                "tag": variant,
                "rustType": "yosoi::search::SearchReplayError",
                "pythonFields": []
                if payload is None
                else [
                    {
                        "rustArgument": "0",
                        "pythonFieldPath": payload[0],
                        "conversion": payload[1],
                    }
                ],
            },
            "semanticEquivalent": "Native Search replay raises SearchError; rust_error_details preserves the Rust variant and declared diagnostic payload without constructing a Rust error object in Python.",
            "rationale": "The native search_replay_error adapter retains version values and nested source Display messages; source chains remain separately available.",
        }

    result = dict(existing)
    result["entries"] = sorted(
        entries_by_identity.values(),
        key=lambda entry: (
            entry["rustPath"],
            entry.get("trait", ""),
            entry.get("symbolKey", ""),
        ),
    )
    result = _ledger_with_source_root(result, source_crate)
    report = parity.build_report(source_rust, python, result)
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
        "--package",
        default="yosoi",
        help="Python import package to inspect (defaults to the public SDK package)",
    )
    parser.add_argument(
        "--write", action="store_true", help="write the seeded mappings to the ledger"
    )
    args = parser.parse_args(argv)

    rust = parity.load_rust_inventory(args.reference)
    python = parity.introspect_python_package(args.package, args.python_root)
    stored = parity.read_json(args.ledger)
    existing = parity.load_ledger(args.ledger)
    ledger, report = seed_entries(rust, python, existing)
    counts = report["coverage"]["counts"]
    print(
        f"seeded {len(ledger['entries'])} ledger rows for {report['coverage']['denominator']} Rust items: "
        f"{counts['mapped']} mapped, {counts['language-specific']} reviewed language-specific, "
        f"{counts['missing']} missing, {counts['stale']} stale"
    )
    if args.write:
        if stored.get("surfaceContract") is not None:
            from sdk_contract import _surface_path

            ledger["entries"] = [
                entry
                for entry in ledger["entries"]
                if not _surface_path(entry["rustPath"])
            ]
            ledger["surfaceContract"] = stored["surfaceContract"]
        args.ledger.write_text(
            json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
