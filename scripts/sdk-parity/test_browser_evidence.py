"""Focused tests for browser behavior evidence validation."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree

SCRIPT = Path(__file__).with_name("browser_evidence.py")
SPEC = importlib.util.spec_from_file_location("browser_evidence", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load browser_evidence.py")
browser_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = browser_evidence
SPEC.loader.exec_module(browser_evidence)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _record_digest(value: bytes) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(value).digest())
        .decode("ascii")
        .rstrip("=")
    )


def _case_names(contract: dict[str, object]) -> list[str]:
    return sorted(
        {
            name
            for story in contract["stories"]  # type: ignore[index]
            for name in story["testCases"]
        }
    )


def _junit(
    path: Path, statuses: dict[str, str] | None = None, *, omit: str | None = None
) -> None:
    contract, _ = browser_evidence._contract()
    statuses = statuses or {}
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(root, "testsuite", name="browser-beta")
    for name in _case_names(contract):
        if name == omit:
            continue
        case = ElementTree.SubElement(
            suite,
            "testcase",
            classname="python.tests.test_browser_beta",
            name=name,
        )
        status = statuses.get(name, "passed")
        if status != "passed":
            ElementTree.SubElement(case, status, message=f"{status} fixture")
    path.write_bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))


def _synthetic_wheel(
    root: Path, native_bytes: bytes = b"native extension fixture"
) -> tuple[Path, Path, Path, dict[str, str]]:
    init_bytes = b"# installed wheel init\n"
    init_member = "yosoi/__init__.py"
    native_member = "yosoi/_native.cpython-314-x86_64-linux-gnu.so"
    metadata_member = "yosoi-0.2.0.dist-info/METADATA"
    record_member = "yosoi-0.2.0.dist-info/RECORD"
    metadata_bytes = b"Metadata-Version: 2.4\nName: yosoi\nVersion: 0.2.0\n\n"
    rows = [
        [init_member, f"sha256={_record_digest(init_bytes)}", str(len(init_bytes))],
        [
            native_member,
            f"sha256={_record_digest(native_bytes)}",
            str(len(native_bytes)),
        ],
        [
            metadata_member,
            f"sha256={_record_digest(metadata_bytes)}",
            str(len(metadata_bytes)),
        ],
        [record_member, "", ""],
    ]
    record_output = StringIO()
    csv.writer(record_output).writerows(rows)
    wheel_path = root / "yosoi-0.2.0-cp314-cp314-linux_x86_64.whl"
    with zipfile.ZipFile(wheel_path, "w") as archive:
        archive.writestr(init_member, init_bytes)
        archive.writestr(native_member, native_bytes)
        archive.writestr(metadata_member, metadata_bytes)
        archive.writestr(record_member, record_output.getvalue())
    package_dir = root / "site-packages" / "yosoi"
    package_dir.mkdir(parents=True)
    init_path = package_dir / "__init__.py"
    init_path.write_bytes(init_bytes)
    native_path = package_dir / Path(native_member).name
    native_path.write_bytes(native_bytes)
    wheel_info, _members = browser_evidence._read_wheel_members(wheel_path)
    return wheel_path, init_path, native_path, wheel_info


def _valid_report(
    init_path: Path,
    native_path: Path,
    wheel_path: Path,
    wheel_info: dict[str, str],
) -> dict[str, object]:
    contract, contract_digest = browser_evidence._contract()
    test_cases = [{"name": name, "status": "passed"} for name in _case_names(contract)]
    stories = [
        {"id": story["id"], "status": "passed", "testCases": story["testCases"]}
        for story in contract["stories"]
    ]
    return {
        "schemaVersion": 1,
        "kind": browser_evidence.REPORT_KIND,
        "generatedAt": "2026-10-11T00:00:00Z",
        "sourceRevision": "a" * 40,
        "mode": "headful",
        "modeCoverage": contract["modeProfiles"]["headful"],
        "contractSha256": contract_digest,
        "testModule": contract["testModule"],
        "junitSha256": "b" * 64,
        "wheel": {
            "path": str(wheel_path),
            "sha256": _sha(wheel_path.read_bytes()),
            "version": wheel_info["version"],
            "nativeWheelMember": wheel_info["nativeMember"],
            "recordSha256": wheel_info["recordSha256"],
            "pythonInitSha256": wheel_info["pythonInitSha256"],
            "nativeExtensionSha256": wheel_info["nativeExtensionSha256"],
        },
        "installedPackage": {
            "version": "0.2.0",
            "nativeVersion": "0.2.0",
            "pythonInit": {
                "path": str(init_path),
                "sha256": wheel_info["pythonInitSha256"],
                "wheelMember": "yosoi/__init__.py",
            },
            "nativeExtension": {
                "path": str(native_path),
                "sha256": _sha(native_path.read_bytes()),
                "wheelMember": wheel_info["nativeMember"],
            },
        },
        "python": {
            "implementation": "cpython",
            "version": "3.14.0",
            "abi": "",
            "freeThreaded": False,
            "gilEnabled": True,
            "executable": "/usr/bin/python3",
        },
        "browser": {
            "channel": "stable",
            "distribution": "Google Chrome Stable",
            "version": "155.0.6490.0",
            "executable": "/usr/bin/google-chrome-stable",
            "executableSha256": "e" * 64,
        },
        "testCases": test_cases,
        "stories": stories,
    }


class BrowserEvidenceTests(unittest.TestCase):
    def test_passing_junit_names_map_to_contract_stories_without_fake_comparisons(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            junit_path = Path(temporary) / "results.xml"
            _junit(junit_path)
            contract, _ = browser_evidence._contract()
            statuses = browser_evidence._junit_case_statuses(junit_path, contract)

        self.assertEqual(set(statuses), set(_case_names(contract)))
        self.assertEqual(set(statuses.values()), {"passed"})
        stories = browser_evidence._required_stories(contract, statuses)
        self.assertEqual(
            [item["id"] for item in stories],
            [item["id"] for item in contract["stories"]],
        )
        self.assertTrue(all(item["status"] == "passed" for item in stories))
        self.assertTrue(all("comparisons" not in item for item in stories))

    def test_missing_required_junit_case_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            junit_path = Path(temporary) / "results.xml"
            missing = _case_names(browser_evidence._contract()[0])[0]
            _junit(junit_path, omit=missing)
            contract, _ = browser_evidence._contract()
            statuses = browser_evidence._junit_case_statuses(junit_path, contract)

        self.assertEqual(statuses[missing], "missing")
        with self.assertRaisesRegex(browser_evidence.BrowserEvidenceError, "missing"):
            browser_evidence._required_stories(contract, statuses)

    def test_skipped_failed_and_error_cases_are_rejected(self) -> None:
        contract, _ = browser_evidence._contract()
        selected = _case_names(contract)[0]
        for status in ("skipped", "failure", "error"):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                junit_path = Path(temporary) / "results.xml"
                expected_status = "failed" if status == "failure" else status
                _junit(junit_path, {selected: status})
                statuses = browser_evidence._junit_case_statuses(junit_path, contract)
                self.assertEqual(statuses[selected], expected_status)
                with self.assertRaises(browser_evidence.BrowserEvidenceError):
                    browser_evidence._required_stories(contract, statuses)

    def test_malformed_junit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            junit_path = Path(temporary) / "malformed.xml"
            junit_path.write_text("<testsuites><testsuite>", encoding="utf-8")
            with self.assertRaisesRegex(browser_evidence.BrowserEvidenceError, "JUnit"):
                browser_evidence._junit_case_statuses(
                    junit_path, browser_evidence._contract()[0]
                )

    def test_valid_report_passes_and_stale_source_or_native_bytes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            wheel_path, init_path, native_path, wheel_info = _synthetic_wheel(
                temporary_path
            )
            report_path = temporary_path / "browser-report.json"
            report = _valid_report(init_path, native_path, wheel_path, wheel_info)
            report_path.write_text(json.dumps(report), encoding="utf-8")

            verified = browser_evidence.verify_browser_evidence(
                report_path, "a" * 40, native_path
            )
            self.assertEqual(verified["sourceRevision"], "a" * 40)
            with self.assertRaisesRegex(
                browser_evidence.BrowserEvidenceError, "source"
            ):
                browser_evidence.verify_browser_evidence(
                    report_path, "f" * 40, native_path
                )

            native_path.write_bytes(b"replaced native bytes")
            with self.assertRaisesRegex(
                browser_evidence.BrowserEvidenceError, "native extension"
            ):
                browser_evidence.verify_browser_evidence(
                    report_path, "a" * 40, native_path
                )

    def test_stale_contract_digest_and_schema_errors_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            wheel_path, init_path, native_path, wheel_info = _synthetic_wheel(
                temporary_path
            )
            report_path = temporary_path / "browser-report.json"
            report = _valid_report(init_path, native_path, wheel_path, wheel_info)

            report["contractSha256"] = "f" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(
                browser_evidence.BrowserEvidenceError, "contract"
            ):
                browser_evidence.verify_browser_evidence(
                    report_path, "a" * 40, native_path
                )

            report = _valid_report(init_path, native_path, wheel_path, wheel_info)
            del report["stories"]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(
                browser_evidence.BrowserEvidenceError, "stories"
            ):
                browser_evidence.verify_browser_evidence(
                    report_path, "a" * 40, native_path
                )

    def test_selected_wheel_record_hashes_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel_path, _init_path, _native_path, _wheel_info = _synthetic_wheel(
                Path(temporary)
            )
            wheel, members = browser_evidence._read_wheel_members(wheel_path)

        self.assertEqual(wheel["version"], "0.2.0")
        self.assertEqual(
            wheel["nativeMember"], "yosoi/_native.cpython-314-x86_64-linux-gnu.so"
        )
        self.assertEqual(members["yosoi/__init__.py"], b"# installed wheel init\n")
        self.assertEqual(members[wheel["nativeMember"]], b"native extension fixture")

    def test_selected_wheel_record_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel_path, _init_path, _native_path, _wheel_info = _synthetic_wheel(root)
            with zipfile.ZipFile(wheel_path) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            record_name = "yosoi-0.2.0.dist-info/RECORD"
            rows = list(csv.reader(members[record_name].decode("utf-8").splitlines()))
            native_row = next(
                row for row in rows if row[0].startswith("yosoi/_native.")
            )
            native_row[1] = (
                "sha256="
                + ("A" if native_row[1][7] != "A" else "B")
                + native_row[1][8:]
            )
            record_output = StringIO()
            csv.writer(record_output).writerows(rows)
            members[record_name] = record_output.getvalue().encode("utf-8")

            bad_wheel = root / "bad-yosoi.whl"
            with zipfile.ZipFile(bad_wheel, "w") as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)

            with self.assertRaisesRegex(
                browser_evidence.BrowserEvidenceError, "RECORD digest"
            ):
                browser_evidence._read_wheel_members(bad_wheel)


if __name__ == "__main__":
    unittest.main()
