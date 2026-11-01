"""Explicit network and document-policy API mappings, without scope exceptions.

Only live public Python counterparts produce mappings. Absent methods, constants
or value aliases remain missing for the owner's API review; this module never
approves language-specific dispositions or creates behavioral evidence.
"""

from __future__ import annotations

from typing import Any

import sdk_contract
import seed_ledger

TYPE_TARGETS = {
    **{
        f"yosoi::surface::{name}": f"yosoi.surface.{name}"
        for name in (
            "NetworkSubscription",
            "NetworkWindow",
            "NetworkObservation",
            "NetworkObservationPolicy",
            "NetworkHeader",
            "NetworkPayloadRef",
            "NetworkCoverage",
            "NetworkGap",
            "NetworkInFlight",
            "NetworkEvent",
            "NetworkRetention",
            "NetworkPayload",
            "NetworkPayloadState",
            "NetworkPayloadKind",
            "NetworkProjectionBasis",
            "NetworkProviderClock",
            "NetworkByteProvenance",
            "NetworkPayloadValue",
        )
    },
    "yosoi::surface::NetworkEventKind": "yosoi.surface.NetworkEventDetails",
    "yosoi::surface::DocumentPolicy": "yosoi.DocumentPolicy",
    "yosoi::surface::DocumentPolicies": "yosoi.DocumentPolicies",
    "yosoi::surface::browser::BrowserObservation": "yosoi.surface.BrowserObservation",
    "yosoi::surface::browser::BrowserRepresentation": (
        "yosoi.surface.BrowserRepresentation"
    ),
}
METHOD_TARGETS = {
    "yosoi::surface::NetworkObservationPolicy::validate": (
        "yosoi.surface.NetworkObservationPolicy.validate_policy"
    ),
    "yosoi::surface::NetworkWindow::validate": (
        "yosoi.surface.NetworkWindow.validate_window"
    ),
    "yosoi::surface::NetworkPayloadValue::bytes": "yosoi.surface.network_payload_bytes",
    "yosoi::Surface::with_policy": "yosoi.Surface.with_policy",
    "yosoi::Surface::is_network_observation": "yosoi.Surface.is_network_observation",
    "yosoi::WebSurface::with_policy": "yosoi.WebSurface",
    "yosoi::surface::browser::consume_session": "yosoi.BrowserSurface.consume_session",
    "yosoi::surface::network": "yosoi.surface",
}
BROWSER_METHODS = {
    "subscribe_network",
    "cancel_network",
    "wait_network_event",
    "observe_network",
    "network_payload",
    "consume_session",
    "consume_tab",
    "consume_work",
    "observe",
    "read",
}
CONSTANTS = {
    f"yosoi::surface::{name}": f"yosoi.surface.{name}"
    for name in (
        "NETWORK_OBSERVATION_SCHEMA",
        "NETWORK_PROVIDER_RESOURCE_BUFFER_BYTES",
        "NETWORK_PROVIDER_TOTAL_BUFFER_BYTES",
    )
}
FIELD_ALIASES = {
    "yosoi::surface::NetworkWindow::schema": "schema_id",
    "yosoi::surface::DocumentPolicies::json": "json_document",
}


def _payload_variant(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Describe the actual Document or FileDocument view returned by a payload."""
    leaf = item["rustPath"].rsplit("::", 1)[-1]
    arguments = [
        arg for arg in item.get("rustArguments", []) if not arg.get("receiver")
    ]
    if len(arguments) != 1 or leaf not in {"Document", "File"}:
        return None
    target = "yosoi.Document" if leaf == "Document" else "yosoi.surface.NetworkPayload"
    if target not in python["targets"]:
        return None
    binding: dict[str, Any] = {
        "kind": "concrete-model" if leaf == "Document" else "outcome-view",
        "schemaTarget": target,
        "discriminator": "python_class"
        if leaf == "Document"
        else "reference.document_kind",
        "tag": "Document" if leaf == "Document" else "file",
        "pythonFields": [
            {
                "rustArgument": arguments[0]["name"],
                "pythonFieldPath": "$" if leaf == "Document" else "value",
                "conversion": (
                    "Retain the complete native Document or FileDocument body; "
                    "response provenance remains in NetworkPayload.reference."
                ),
            }
        ],
    }
    if leaf == "Document":
        binding["rustType"] = arguments[0]["type"]
        binding["behaviorEvidence"] = [
            {
                "path": "python/tests/test_surface_network.py",
                "test": "test_offline_network_payload_accepts_exact_owned_reference",
            },
            {
                "path": "crates/yosoi/tests/surface_network.rs",
                "test": (
                    "cli_restores_network_payloads_from_portable_outcomes_"
                    "without_a_browser"
                ),
            },
        ]
    return {
        "rustPath": item["rustPath"],
        "symbolKey": item["symbolKey"],
        "decision": "mapped",
        "pythonTarget": target,
        "mappingDirection": "output",
        "outputBinding": binding,
        "argumentMappings": [],
        "defaults": [],
        "units": [],
        "cardinality": [],
        "rationale": (
            "Rust NetworkPayloadValue returns the existing typed Python body. "
            "File bodies retain their concrete class and metadata in the "
            "owning NetworkPayload value field."
        ),
        "semanticEquivalent": (
            "Document bytes remain a Document; file bytes retain the native "
            "FileDocument classification. The Python file branch is identified "
            "by its exact response reference document_kind=file."
        ),
    }


def network_mapping(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Map explicitly owned network APIs against actual Python target shapes."""
    if sdk_contract._expected_classification(item) != "sdk":
        return None
    path = item["rustPath"]
    parent, _, leaf = path.rpartition("::")
    if parent == "yosoi::surface::NetworkPayloadValue" and item["kind"] == "variant":
        return _payload_variant(item, python)
    target = CONSTANTS.get(path) or METHOD_TARGETS.get(path) or TYPE_TARGETS.get(path)
    if target is None and parent in TYPE_TARGETS:
        target = f"{TYPE_TARGETS[parent]}.{FIELD_ALIASES.get(path, leaf)}"
    if target is None and parent == "yosoi::BrowserSurface" and leaf in BROWSER_METHODS:
        target = f"yosoi.BrowserSurface.{leaf}"
    if target is None and path in {
        "yosoi::SurfacePolicy::documents",
        "yosoi::SurfacePolicy::network_observation",
    }:
        target = path.replace("::", ".")
    if item["kind"] == "variant" and parent in TYPE_TARGETS:
        target = TYPE_TARGETS[parent]
    info = python["targets"].get(target) if target else None
    if info is None:
        return None
    entry = seed_ledger._entry(
        item,
        target,
        info,
        python,
        "Python preserves the same bounded network evidence, typed payload, "
        "explicit document policy and native ownership boundary.",
    )
    if entry is None:
        return None
    if item["kind"] == "variant" and not item.get("rustArguments"):
        tag = seed_ledger._snake_case(leaf)
        entry["defaults"] = [
            {
                "id": "variant-tag:value",
                "rust": f"{leaf} serializes as {tag}",
                "python": f"Literal {tag}",
            }
        ]
    if path == "yosoi::surface::NetworkPayloadValue::bytes":
        entry["receiverMapping"] = {
            "rustArgument": "self",
            "pythonArgument": "value",
            "conversion": (
                "The typed Document/FileDocument value supplies the Rust "
                "enum payload receiver."
            ),
        }
    for argument in item.get("rustArguments", []):
        name = argument["name"]
        if name in {"maximum", "chunk_bytes", "timeout_ms", "after_sequence"}:
            unit = (
                "milliseconds"
                if name == "timeout_ms"
                else "event sequence"
                if name == "after_sequence"
                else "retained body bytes"
            )
            entry["units"].append(
                {"id": f"network-unit:{name}", "rust": unit, "python": unit}
            )
    return entry
