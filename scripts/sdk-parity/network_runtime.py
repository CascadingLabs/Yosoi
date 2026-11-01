"""Observe Rust-authored network journeys through public installed Python APIs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from network_conformance import comparison


def dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json", by_alias=True)


def document(value: Any) -> dict[str, Any]:
    return {
        "class": type(value).__name__,
        "id": str(value.id),
        "bytes": list(value.data),
        "profile": dump(value.profile),
    }


def payload(value: Any, ys: Any) -> dict[str, Any]:
    body = value.value
    if isinstance(body, ys.Document):
        snapshot = document(body)
        raw = body.data
    else:
        raw = body.bytes
        snapshot = {
            "class": type(body).__name__,
            "id": str(body.id),
            "bytes": list(raw),
            "metadata": dump(body.metadata),
            "sha256": body.sha256,
        }
    return {
        "class": type(value).__name__,
        "reference": dump(value.reference),
        "bytes": list(raw),
        "value": snapshot,
    }


def surface(value: Any) -> dict[str, Any]:
    return {
        "identity": value.identity,
        "representation": value.metadata.representation,
        "coverage": dump(value.metadata.coverage),
        "overview": dump(value.overview()),
    }


def outcome_arguments(value: Any) -> dict[str, Any]:
    return {
        "id": str(value.record.id),
        "source_keys": sorted(source.key for source in value.sources),
        "limits": dump(value.limits),
    }


def observe_fixtures(fixtures: dict[str, Any], ys: Any) -> list[dict[str, Any]]:
    """Perform all positive journeys and record actual boundary rejection classes."""
    sf = ys.surface
    source = fixtures["input"]
    policy = sf.NetworkObservationPolicy.model_validate(source["policy"])
    window = sf.NetworkWindow.model_validate(source["window"])
    window_document = window.to_document("network-window")
    index = sf.Surface(window_document)
    ordinary = ys.Document.from_json("ordinary-json", window_document.data)
    values = {}
    for body in source["bodies"]:
        if body["class"] == "Document":
            value = ys.Document.from_profile(
                body["id"],
                ys.documents.DocumentProfile.model_validate(body["profile"]),
                bytes(body["bytes"]),
            )
        else:
            value = ys.file_from_bytes(
                body["id"],
                bytes(body["bytes"]),
                metadata=ys.FileMetadata.model_validate(body["metadata"]),
            )
        values[body["id"]] = value
    outcome = sf.Outcome.new("network-parity-outcome")
    for key, value in values.items():
        retained = (
            sf.ArchivedSource.from_document(key, value)
            if isinstance(value, ys.Document)
            else sf.ArchivedSource.from_file_document(key, value)
        )
        outcome = outcome.with_source(retained)
    outcome = outcome.with_source(
        sf.ArchivedSource.from_document("network-window", window_document, index)
    )
    references = tuple(window.payloads)

    async def portable() -> tuple[dict[str, Any], dict[str, Any]]:
        with TemporaryDirectory(prefix="yosoi-network-parity-") as directory:
            root = Path(directory)
            original = await ys.Archive.open(root / "original")
            reference = await original.write(outcome)
            path = root / "network.yosoi"
            await original.export_file(reference, path)
            fresh = await ys.Archive.open(root / "fresh")
            imported = await fresh.import_file(path)
            loaded = await fresh.read(imported)
            restored = [
                payload(
                    sf.NetworkPayload.from_outcome(loaded, reference, 1_048_576), ys
                )
                for reference in references
            ]
            observed = {
                "class": type(loaded).__name__,
                "record_id": str(loaded.record.id),
                "source_keys": outcome_arguments(loaded),
                "payloads": restored,
                "window_document": document(
                    loaded.source_document("network-window", 1_048_576)
                ),
                "network_surface": surface(loaded.surface("network-window")),
                "complete": loaded.complete,
                "sealed": loaded.sealed,
            }
            return observed, {
                "self": outcome_arguments(loaded),
                "key": "network-window",
                "maximum": 1_048_576,
            }

    comparisons = []
    for case in fixtures["cases"]:
        name = case["name"]
        if name == "policy-defaults":
            observed, arguments = dump(sf.NetworkObservationPolicy()), {}
        elif name == "policy-retention":
            observed, arguments = dump(policy.retention()), {"self": dump(policy)}
        elif name == "typed-window":
            observed = {
                "window": dump(sf.NetworkWindow.from_document(window_document)),
                "document": document(window_document),
                "surface": surface(index),
            }
            arguments = {"self": dump(window), "id": "network-window"}
        elif name == "ordinary-json":
            observed = {
                "network": ordinary.profile.schema_profile
                == "yosoi_network_observation_v1",
                "surface": surface(sf.Surface(ordinary)),
            }
            arguments = {"document": document(ordinary)}
        elif name.startswith("payload-"):
            selected = sf.NetworkPayloadRef.model_validate(case["input"]["reference"])
            observed = payload(
                sf.NetworkPayload.from_outcome(outcome, selected, 1_048_576), ys
            )
            arguments = {
                "outcome": outcome_arguments(outcome),
                "reference": dump(selected),
                "maximum": 1_048_576,
            }
        elif name == "portable-outcome":
            observed, arguments = asyncio.run(portable())
        else:
            raise ValueError(f"unsupported network fixture: {name}")
        comparisons.append(comparison(case, observed, arguments))
    for case in fixtures["errorCases"]:
        args, operation = case["input"], case["operation"]
        arguments = dict(args)
        try:
            if operation == "ordinary-json":
                sf.NetworkWindow.from_document(ordinary)
            elif operation == "policy":
                sf.NetworkObservationPolicy.model_validate(
                    args["self"]
                ).validate_policy()
            elif operation == "window":
                sf.NetworkWindow.model_validate(args["self"])
                arguments["obj"] = args["self"]
            elif operation in {"payload", "missing-body"}:
                selected = sf.NetworkPayloadRef.model_validate(args["reference"])
                selected_outcome = outcome
                if operation == "missing-body":
                    selected_outcome = (
                        sf.Outcome.new("network-missing-body")
                        .model_copy(update={"complete": False})
                        .with_source(
                            sf.ArchivedSource.from_document(
                                "network-window", window_document
                            )
                        )
                    )
                arguments["outcome"] = outcome_arguments(selected_outcome)
                arguments["reference"] = dump(selected)
                sf.NetworkPayload.from_outcome(
                    selected_outcome, selected, args["maximum"]
                )
            elif operation == "surface":
                sf.Surface(
                    window_document, limits=sf.Limits.model_validate(args["limits"])
                )
            else:
                raise RuntimeError(
                    f"unsupported network rejection fixture: {operation}"
                )
        except (ValueError, sf.SurfaceError) as error:
            rejected = True
            failure = {"python_type": type(error).__name__, "message": str(error)}
        else:
            rejected, failure = False, None
        if operation == "window":
            arguments["obj"] = args["self"]
        row = comparison(case, {"rejected": rejected}, arguments)
        row["rustFailure"], row["pythonFailure"] = case["rustFailure"], failure
        comparisons.append(row)
    return comparisons
