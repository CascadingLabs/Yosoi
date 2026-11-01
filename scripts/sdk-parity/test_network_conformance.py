"""Pure network fixture and declaration-attribution checks; no native SDK runs."""

from __future__ import annotations

import copy
import hashlib
import unittest

import network_conformance as network
import run_sdk_parity
import sdk_contract


def fixture():
    bodies = []
    refs = []
    events = [{"kind": {"kind": "redirect"}}]
    for sequence, kind in enumerate(("html", "json", "file"), 1):
        raw = list(f"actual-{kind}".encode())
        id = f"body-{kind}"
        body = {"id": id, "bytes": raw}
        if kind == "file":
            body.update(
                {
                    "class": "BinaryDocument",
                    "sha256": hashlib.sha256(bytes(raw)).hexdigest(),
                }
            )
        else:
            body.update(
                {
                    "class": "Document",
                    "profile": {
                        "schema": "html5" if kind == "html" else "json_rfc8259"
                    },
                }
            )
        bodies.append(body)
        ref = {
            "id": id,
            "document_id": id,
            "document_kind": kind,
            "request_id": f"request-{kind}",
            "hop": sequence,
            "response_sequence": sequence,
            "retained_bytes": len(raw),
            "sha256": hashlib.sha256(bytes(raw)).hexdigest(),
        }
        refs.append(ref)
        events.append(
            {
                "sequence": sequence,
                "request_id": ref["request_id"],
                "hop": sequence,
                "kind": {"kind": "response_received"},
            }
        )
    retention = {"retained_header_names": ["x-request-id"], "retain_url_query": False}
    window = {
        "schema": "yosoi.network.v1",
        "coverage": {"complete": False},
        "retention": retention,
        "payloads": refs,
        "events": events,
        "gaps": [{"reason": "bounded gap"}],
        "in_flight": [{"request_id": "pending"}],
        "in_flight_at_start": [{"request_id": "prior"}],
    }
    payloads = [
        {
            "class": "NetworkPayload",
            "reference": ref,
            "bytes": body["bytes"],
            "value": body,
        }
        for ref, body in zip(refs, bodies, strict=True)
    ]
    results = {
        "policy-defaults": {"retain_bodies": False, "retain_url_query": False},
        "policy-retention": retention,
        "typed-window": {
            "window": window,
            "document": {"profile": {"schema": "yosoi_network_observation_v1"}},
            "surface": {"coverage": {"complete": False}},
        },
        "ordinary-json": {
            "network": False,
            "surface": {"coverage": {"complete": True}},
        },
        "portable-outcome": {
            "class": "Outcome",
            "source_keys": {
                "source_keys": ["network-window", *[body["id"] for body in bodies]]
            },
            "payloads": payloads,
        },
        **{
            f"payload-{body['id']}": value
            for body, value in zip(bodies, payloads, strict=True)
        },
    }
    return {
        "schemaVersion": 1,
        "kind": network.FIXTURE_KIND,
        "input": {"bodies": bodies, "window": window},
        "cases": [
            {"name": name, "rustPath": path, "input": {}, "rust": results[name]}
            for name, path in network.CASE_PATHS.items()
        ],
        "errorCases": [
            {
                "name": name,
                "rustPath": path,
                "input": {},
                "rust": {"rejected": True},
                "rustFailure": {
                    "rust_type": "yosoi::surface::SurfaceError",
                    "variant": "Invalid",
                    "details": {},
                    "message": "actual authored failure",
                },
            }
            for name, path in network.ERROR_PATHS.items()
        ],
    }


class NetworkFixtureTests(unittest.TestCase):
    def test_complete_actual_fixture_contract(self):
        self.assertEqual(len(network.validate_fixture_set(fixture())["cases"]), 8)

    def test_all_twelve_prior_suites_are_preserved(self):
        self.assertEqual(
            tuple(name for name, _, _ in run_sdk_parity.EXAMPLES[:12]),
            (
                "python_conformance",
                "python_diagnostics_conformance",
                "python_schema_errors_conformance",
                "python_value_equality_conformance",
                "python_errors_conformance",
                "python_map_ordering_conformance",
                "python_serde_conformance",
                "python_document_errors_conformance",
                "python_webtarget_conformance",
                "media_documents_conformance",
                "surface_conformance",
                "image_surface_conformance",
            ),
        )
        self.assertEqual(
            run_sdk_parity.EXAMPLES[12],
            ("network_conformance", "run_network_conformance.py", True),
        )
        self.assertEqual(len(sdk_contract.REQUIRED_SUITES), 14)
        self.assertEqual(sdk_contract.REQUIRED_SUITES[12], "run_network_conformance.py")

    def test_metadata_only_and_tampered_bodies_are_rejected(self):
        for mode in ("missing-bytes", "wrong-digest", "wrong-profile"):
            value = copy.deepcopy(fixture())
            if mode == "missing-bytes":
                del value["input"]["bodies"][0]["bytes"]
            elif mode == "wrong-digest":
                value["input"]["window"]["payloads"][0]["sha256"] = "0" * 64
            else:
                value["input"]["bodies"][0]["profile"]["schema"] = "json_rfc8259"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                network.validate_fixture_set(value)

    def test_foreign_hop_and_missing_portable_dependency_are_rejected(self):
        value = copy.deepcopy(fixture())
        value["input"]["window"]["payloads"][0]["hop"] = 99
        with self.assertRaisesRegex(ValueError, "response/hop"):
            network.validate_fixture_set(value)
        value = copy.deepcopy(fixture())
        next(row for row in value["cases"] if row["name"] == "portable-outcome")[
            "rust"
        ]["payloads"] = []
        with self.assertRaisesRegex(ValueError, "dependency closure"):
            network.validate_fixture_set(value)

    def test_duplicate_names_and_unexecuted_paths_cannot_pass(self):
        for mode in ("duplicate", "path"):
            value = fixture()
            if mode == "duplicate":
                value["cases"].append(value["cases"][0])
            else:
                value["cases"][0]["rustPath"] = (
                    "yosoi::surface::NetworkWindow::unexecuted"
                )
            with self.assertRaises(ValueError):
                network.validate_fixture_set(value)

    def test_ordinary_json_and_complete_network_claims_are_rejected(self):
        value = copy.deepcopy(fixture())
        value["input"]["window"]["coverage"]["complete"] = True
        with self.assertRaisesRegex(ValueError, "partial network"):
            network.validate_fixture_set(value)
        value = fixture()
        next(row for row in value["cases"] if row["name"] == "ordinary-json")["rust"][
            "network"
        ] = True
        with self.assertRaisesRegex(ValueError, "ordinary JSON"):
            network.validate_fixture_set(value)

    def test_evidence_requires_reviewed_source_and_actual_arguments(self):
        path = network.CASE_PATHS["typed-window"]
        case = {
            "name": "typed-window",
            "rustPath": path,
            "input": {"id": "fixture"},
            "rust": {"actual": 1},
        }
        row = network.comparison(case, {"actual": 1}, {"id": "fixture"})
        rust = {"items": [{"rustPath": path, "symbolKey": "typed-window"}]}
        entry = {
            "rustPath": path,
            "symbolKey": "typed-window",
            "decision": "mapped",
            "pythonTarget": "yosoi.surface.NetworkWindow.to_document",
            "argumentMappings": [{"rustArgument": "id", "pythonArgument": "id"}],
        }
        self.assertEqual(
            network.evidence_cases([row], rust, {"entries": [entry]})[0]["outcome"],
            "passed",
        )
        with self.assertRaisesRegex(ValueError, "pinned mapping"):
            network.evidence_cases([row], rust, {"entries": []})
        row["mappingValues"]["python"]["id"] = "different"
        self.assertEqual(
            network.evidence_cases([row], rust, {"entries": [entry]})[0]["outcome"],
            "failed",
        )


if __name__ == "__main__":
    unittest.main()
