#!/usr/bin/env python3
"""Create and validate installed-wheel browser behavior evidence."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tomllib
import zipfile
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "python/parity/browser-behavior-contract.json"
SCHEMA_VERSION = 1
REPORT_KIND = "yosoi-python-browser-behavior-evidence"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
CHROME_VERSION_RE = re.compile(r"^Google Chrome (\d+\.\d+\.\d+\.\d+)$")


class BrowserEvidenceError(ValueError):
    """Evidence was incomplete, malformed, or not tied to the selected artifacts."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise BrowserEvidenceError(f"cannot read file {path}: {error}") from error
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _contract(path: Path = CONTRACT_PATH) -> tuple[dict[str, Any], str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BrowserEvidenceError(
            f"cannot read browser behavior contract: {error}"
        ) from error

    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != SCHEMA_VERSION
        or document.get("kind") != "yosoi-python-browser-behavior-contract"
        or document.get("sdkVersionSource") != "workspace.package.version"
        or "sdkVersion" in document
        or document.get("testModule") != "python/tests/test_browser_beta.py"
    ):
        raise BrowserEvidenceError("unsupported browser behavior contract")
    try:
        workspace = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
        version = workspace["workspace"]["package"]["version"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise BrowserEvidenceError("cannot resolve workspace SDK version") from error
    if not isinstance(version, str) or not re.fullmatch(
        r"0\.[1-9][0-9]*\.(0|[1-9][0-9]*)(?:-rc\.[1-9][0-9]*)?", version
    ):
        raise BrowserEvidenceError("unsupported workspace SDK version")
    # Bind the effective contract digest to the selected release. Rust and
    # Python spell numbered release candidates differently.
    document["nativeVersion"] = version
    document["sdkVersion"] = version.replace("-rc.", "rc")
    profiles = document.get("modeProfiles")
    if not isinstance(profiles, dict) or set(profiles) != {"headless", "headful"}:
        raise BrowserEvidenceError(
            "browser contract must define headless and headful profiles"
        )
    for mode, profile in profiles.items():
        if (
            not isinstance(profile, dict)
            or profile.get("managedSession") != "headless"
            or profile.get("borrowedSession") != mode
            or profile.get("browserFree") != "mode-independent"
        ):
            raise BrowserEvidenceError(f"invalid {mode} browser coverage profile")

    stories = document.get("stories")
    if not isinstance(stories, list) or not stories:
        raise BrowserEvidenceError("browser contract has no supported stories")
    story_ids: set[str] = set()
    for story in stories:
        if not isinstance(story, dict):
            raise BrowserEvidenceError("browser contract stories must be objects")
        story_id = story.get("id")
        cases = story.get("testCases")
        if (
            not isinstance(story_id, str)
            or not story_id
            or story_id in story_ids
            or not isinstance(cases, list)
            or not cases
            or not all(
                isinstance(case, str) and case.startswith("test_") for case in cases
            )
            or not isinstance(story.get("description"), str)
            or not story["description"].strip()
        ):
            raise BrowserEvidenceError("invalid or duplicate browser behavior story")
        story_ids.add(story_id)

    browser = document.get("browser")
    if (
        not isinstance(browser, dict)
        or browser.get("distribution") != "Google Chrome Stable"
        or type(browser.get("admittedStableMajorVersion")) is not int
        or browser["admittedStableMajorVersion"] <= 0
        or not isinstance(browser.get("versionPattern"), str)
    ):
        raise BrowserEvidenceError(
            "browser contract must require regular Chrome Stable"
        )
    return document, _digest_json(document)


def _run_git(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BrowserEvidenceError(
            f"cannot inspect source checkout: {error}"
        ) from error
    if result.returncode != 0:
        raise BrowserEvidenceError(
            "cannot inspect source checkout: "
            + (result.stderr.strip() or result.stdout.strip() or "git command failed")
        )
    return result.stdout.strip()


def _require_clean_source(source: str) -> None:
    if REVISION_RE.fullmatch(source) is None:
        raise BrowserEvidenceError("source must be a full lowercase Git commit")
    actual = _run_git(["rev-parse", "--verify", "HEAD^{commit}"]).lower()
    if actual != source:
        raise BrowserEvidenceError(
            f"selected source does not match checkout HEAD ({source} != {actual})"
        )
    if _run_git(["status", "--porcelain", "--untracked-files=all"]):
        raise BrowserEvidenceError("browser evidence requires a clean source checkout")


def _read_wheel_members(wheel_path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    wheel_path = wheel_path.resolve()
    if not wheel_path.is_file() or wheel_path.suffix != ".whl":
        raise BrowserEvidenceError("--wheel must name an existing .whl file")
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            names = archive.namelist()
            metadata_paths = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1:
                raise BrowserEvidenceError(
                    "wheel must contain exactly one dist-info METADATA"
                )
            metadata_path = metadata_paths[0]
            metadata = Parser().parsestr(archive.read(metadata_path).decode("utf-8"))
            name = re.sub(r"[-_.]+", "-", (metadata.get("Name") or "").strip()).lower()
            version = (metadata.get("Version") or "").strip()
            if name != "yosoi" or not version:
                raise BrowserEvidenceError(
                    "selected wheel metadata is not a Yosoi distribution"
                )

            record_path = metadata_path.removesuffix("METADATA") + "RECORD"
            raw_record = archive.read(record_path)
            record_bytes = raw_record.decode("utf-8")
            record_rows = list(csv.reader(record_bytes.splitlines()))
            record: dict[str, tuple[str, str]] = {}
            for row in record_rows:
                if len(row) != 3 or row[0] in record:
                    raise BrowserEvidenceError(
                        "wheel RECORD has a malformed or duplicate row"
                    )
                record[row[0]] = (row[1], row[2])

            native_members = [
                entry
                for entry in record
                if entry.startswith("yosoi/_native.")
                and entry.endswith((".so", ".pyd"))
            ]
            required = ["yosoi/__init__.py", *native_members]
            if len(native_members) != 1 or any(path not in names for path in required):
                raise BrowserEvidenceError(
                    "wheel must contain one native extension and yosoi/__init__.py"
                )

            contents: dict[str, bytes] = {}
            for path in required:
                payload = archive.read(path)
                encoded_hash, encoded_size = record[path]
                _verify_record_entry(path, payload, encoded_hash, encoded_size)
                contents[path] = payload
    except (
        OSError,
        UnicodeDecodeError,
        zipfile.BadZipFile,
        KeyError,
        csv.Error,
    ) as error:
        raise BrowserEvidenceError(f"cannot inspect selected wheel: {error}") from error

    return {
        "version": version,
        "nativeMember": native_members[0],
        "recordSha256": hashlib.sha256(raw_record).hexdigest(),
        "pythonInitSha256": hashlib.sha256(contents["yosoi/__init__.py"]).hexdigest(),
        "nativeExtensionSha256": hashlib.sha256(
            contents[native_members[0]]
        ).hexdigest(),
    }, contents


def _verify_record_entry(
    path: str, payload: bytes, encoded_hash: str, encoded_size: str
) -> None:
    algorithm, separator, expected = encoded_hash.partition("=")
    if algorithm != "sha256" or not separator or not expected:
        raise BrowserEvidenceError(f"wheel RECORD has no SHA-256 digest for {path}")
    actual = (
        base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
        .decode("ascii")
        .rstrip("=")
    )
    if expected.rstrip("=") != actual:
        raise BrowserEvidenceError(f"wheel RECORD digest does not match {path}")
    if (
        not encoded_size
        or not encoded_size.isdecimal()
        or int(encoded_size) != len(payload)
    ):
        raise BrowserEvidenceError(f"wheel RECORD size does not match {path}")


def _outside_python_source(path: Path) -> bool:
    try:
        path.resolve().relative_to((ROOT / "python").resolve())
    except ValueError:
        return True
    return False


def _installed_package(
    wheel_path: Path, *, expected_version: str, expected_native_version: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    wheel_info, wheel_files = _read_wheel_members(wheel_path)
    if wheel_info["version"] != expected_version:
        raise BrowserEvidenceError(
            "selected wheel is not the browser contract SDK version "
            f"({wheel_info['version']} != {expected_version})"
        )
    try:
        package = importlib.import_module("yosoi")
        native = package._native
        init_path = Path(package.__file__).resolve(strict=True)
        native_path = Path(native.__file__).resolve(strict=True)
        installed_version = importlib.metadata.version("yosoi")
        native_version = native.__version__
        init_bytes = init_path.read_bytes()
        native_bytes = native_path.read_bytes()
    except (
        ImportError,
        AttributeError,
        OSError,
        importlib.metadata.PackageNotFoundError,
    ) as error:
        raise BrowserEvidenceError(
            f"cannot inspect installed Yosoi wheel: {error}"
        ) from error

    native_member = wheel_info["nativeMember"]
    if not _outside_python_source(init_path) or not _outside_python_source(native_path):
        raise BrowserEvidenceError(
            "Yosoi imports resolve inside the Python source tree"
        )
    if installed_version != wheel_info["version"]:
        raise BrowserEvidenceError(
            "installed Yosoi version does not match selected wheel "
            f"({installed_version} != {wheel_info['version']})"
        )
    if native_version != expected_native_version:
        raise BrowserEvidenceError(
            "installed native extension version does not match selected wheel "
            f"({native_version} != {expected_native_version})"
        )
    if (
        init_path.name != "__init__.py"
        or native_path.name != PurePosixPath(native_member).name
    ):
        raise BrowserEvidenceError(
            "installed package files do not match wheel member names"
        )
    if init_bytes != wheel_files["yosoi/__init__.py"]:
        raise BrowserEvidenceError(
            "installed Python package file differs from selected wheel"
        )
    if native_bytes != wheel_files[native_member]:
        raise BrowserEvidenceError(
            "installed native extension differs from selected wheel"
        )

    return (
        {
            "version": installed_version,
            "nativeVersion": native_version,
            "pythonInit": {
                "path": str(init_path),
                "sha256": hashlib.sha256(init_bytes).hexdigest(),
                "wheelMember": "yosoi/__init__.py",
            },
            "nativeExtension": {
                "path": str(native_path),
                "sha256": hashlib.sha256(native_bytes).hexdigest(),
                "wheelMember": native_member,
            },
        },
        wheel_info,
    )


def _python_runtime() -> dict[str, Any]:
    gil_disabled = sysconfig.get_config_var("Py_GIL_DISABLED")
    is_free_threaded = gil_disabled in (1, True, "1")
    gil_enabled = getattr(sys, "_is_gil_enabled", None)
    return {
        "implementation": sys.implementation.name,
        "version": ".".join(str(part) for part in sys.version_info[:3]),
        "abi": getattr(sys, "abiflags", ""),
        "freeThreaded": is_free_threaded,
        "gilEnabled": bool(gil_enabled()) if callable(gil_enabled) else None,
        "executable": str(Path(sys.executable).resolve()),
    }


def _chrome_executable(value: str | None) -> Path:
    if not value:
        raise BrowserEvidenceError(
            "set CHROME or pass --chrome to select regular Chrome Stable"
        )
    candidate = Path(value).expanduser()
    if candidate.is_file():
        resolved = candidate.resolve()
    else:
        found = shutil.which(value)
        if found is None:
            raise BrowserEvidenceError(f"Chrome executable does not exist: {value}")
        resolved = Path(found).resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise BrowserEvidenceError(f"Chrome executable is not executable: {resolved}")
    return resolved


def _chrome_identity(value: str | None, expected_major: int) -> dict[str, str]:
    executable = _chrome_executable(value)
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BrowserEvidenceError(
            f"cannot identify Chrome executable: {error}"
        ) from error
    output = (result.stdout or result.stderr).strip()
    match = CHROME_VERSION_RE.fullmatch(output)
    if result.returncode != 0 or match is None:
        raise BrowserEvidenceError(
            "selected browser is not an identifiable regular Google Chrome Stable "
            f"distribution: {output!r}"
        )
    if int(match.group(1).split(".", 1)[0]) != expected_major:
        raise BrowserEvidenceError(
            "selected Chrome Stable milestone is outside the admitted contract "
            f"({match.group(1)} vs {expected_major})"
        )
    return {
        "channel": "stable",
        "distribution": "Google Chrome Stable",
        "version": match.group(1),
        "executable": str(executable),
        "executableSha256": _digest_file(executable),
    }


def _junit_case_statuses(path: Path, contract: dict[str, Any]) -> dict[str, str]:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise BrowserEvidenceError(f"cannot parse JUnit XML: {error}") from error

    if root.tag.split("}")[-1] not in {"testsuite", "testsuites"}:
        raise BrowserEvidenceError("JUnit root must be testsuite or testsuites")
    required = {
        test_name for story in contract["stories"] for test_name in story["testCases"]
    }
    found: dict[str, list[str]] = {name: [] for name in required}
    for testcase in root.iter():
        if testcase.tag.split("}")[-1] != "testcase":
            continue
        classname = testcase.get("classname", "")
        module_name = classname.rsplit(".", 1)[-1].removesuffix(".py")
        if module_name != "test_browser_beta":
            continue
        name = testcase.get("name")
        if not isinstance(name, str) or not name:
            raise BrowserEvidenceError("JUnit test_browser_beta case has no name")
        if name not in required:
            continue
        statuses = {child.tag.split("}")[-1] for child in testcase}
        if "error" in statuses:
            status = "error"
        elif "failure" in statuses:
            status = "failed"
        elif "skipped" in statuses:
            status = "skipped"
        else:
            status = "passed"
        found[name].append(status)

    result: dict[str, str] = {}
    for name in sorted(required):
        values = found[name]
        if not values:
            result[name] = "missing"
        elif len(values) != 1:
            raise BrowserEvidenceError(f"JUnit contains duplicate case {name}")
        else:
            result[name] = values[0]
    return result


def _required_stories(
    contract: dict[str, Any], case_statuses: dict[str, str]
) -> list[dict[str, Any]]:
    not_passed = [
        f"{name}: {status}"
        for name, status in sorted(case_statuses.items())
        if status != "passed"
    ]
    if not_passed:
        raise BrowserEvidenceError(
            "required browser acceptance tests did not all pass: "
            + "; ".join(not_passed)
        )
    return [
        {
            "id": story["id"],
            "status": "passed",
            "testCases": list(story["testCases"]),
        }
        for story in contract["stories"]
    ]


def create_evidence(
    *,
    junit_path: Path,
    source_revision: str,
    wheel_path: Path,
    output_path: Path,
    mode: str,
    chrome: str | None = None,
    contract_path: Path = CONTRACT_PATH,
    require_clean_checkout: bool = True,
) -> dict[str, Any]:
    """Validate provenance and passing named tests, then write one evidence record."""
    if mode not in {"headless", "headful"}:
        raise BrowserEvidenceError("mode must be headless or headful")
    selected_yield_mode = os.environ.get("YOSOI_YIELD_MODE", "headless")
    if selected_yield_mode != mode:
        raise BrowserEvidenceError(
            "--mode must match YOSOI_YIELD_MODE used by browser test fixtures "
            f"({mode!r} != {selected_yield_mode!r})"
        )
    if require_clean_checkout:
        _require_clean_source(source_revision)
    elif REVISION_RE.fullmatch(source_revision) is None:
        raise BrowserEvidenceError("source must be a full lowercase Git commit")

    contract, contract_sha256 = _contract(contract_path)
    case_statuses = _junit_case_statuses(junit_path, contract)
    stories = _required_stories(contract, case_statuses)
    installed, wheel_info = _installed_package(
        wheel_path,
        expected_version=contract["sdkVersion"],
        expected_native_version=contract["nativeVersion"],
    )
    browser = _chrome_identity(
        chrome or os.environ.get("CHROME"),
        contract["browser"]["admittedStableMajorVersion"],
    )
    profile = contract["modeProfiles"][mode]

    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sourceRevision": source_revision,
        "mode": mode,
        "modeCoverage": profile,
        "contractSha256": contract_sha256,
        "testModule": contract["testModule"],
        "junitSha256": _digest_file(junit_path),
        "wheel": {
            "path": str(wheel_path.resolve()),
            "sha256": _digest_file(wheel_path.resolve()),
            "version": installed["version"],
            "nativeWheelMember": wheel_info["nativeMember"],
            "recordSha256": wheel_info["recordSha256"],
            "pythonInitSha256": wheel_info["pythonInitSha256"],
            "nativeExtensionSha256": wheel_info["nativeExtensionSha256"],
        },
        "installedPackage": installed,
        "python": _python_runtime(),
        "browser": browser,
        "testCases": [
            {"name": name, "status": status}
            for name, status in sorted(case_statuses.items())
        ],
        "stories": stories,
    }
    validate_browser_evidence_document(report, contract, contract_sha256)
    _write_json(output_path, report)
    return report


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def validate_browser_evidence_document(
    report: Any,
    contract: dict[str, Any],
    contract_sha256: str,
) -> dict[str, Any]:
    """Validate report schema essentials and exact contract story coverage."""
    if (
        not isinstance(report, dict)
        or report.get("schemaVersion") != SCHEMA_VERSION
        or report.get("kind") != REPORT_KIND
    ):
        raise BrowserEvidenceError("unsupported browser behavior evidence schema")
    if (
        not isinstance(report.get("sourceRevision"), str)
        or REVISION_RE.fullmatch(report["sourceRevision"]) is None
    ):
        raise BrowserEvidenceError("browser evidence has an invalid source revision")
    generated_at = report.get("generatedAt")
    if not isinstance(generated_at, str):
        raise BrowserEvidenceError("browser evidence has no generation timestamp")
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise BrowserEvidenceError(
            "browser evidence has an invalid generation timestamp"
        ) from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise BrowserEvidenceError(
            "browser evidence generation timestamp must include a timezone"
        )
    if report.get("mode") not in {"headless", "headful"}:
        raise BrowserEvidenceError("browser evidence has an invalid mode")
    if report.get("modeCoverage") != contract["modeProfiles"][report["mode"]]:
        raise BrowserEvidenceError(
            "browser evidence mode coverage does not match its contract"
        )
    if report.get("contractSha256") != contract_sha256:
        raise BrowserEvidenceError("browser evidence contract digest is stale")
    if report.get("testModule") != contract["testModule"]:
        raise BrowserEvidenceError("browser evidence names the wrong test module")
    for field in ("junitSha256",):
        if not _is_sha256(report.get(field)):
            raise BrowserEvidenceError(f"browser evidence has an invalid {field}")

    wheel = report.get("wheel")
    if (
        not isinstance(wheel, dict)
        or not isinstance(wheel.get("path"), str)
        or not Path(wheel["path"]).is_absolute()
        or not _is_sha256(wheel.get("sha256"))
        or not isinstance(wheel.get("version"), str)
        or wheel["version"] != contract["sdkVersion"]
        or not isinstance(wheel.get("nativeWheelMember"), str)
        or not wheel["nativeWheelMember"].startswith("yosoi/_native.")
        or not _is_sha256(wheel.get("recordSha256"))
        or not _is_sha256(wheel.get("pythonInitSha256"))
        or not _is_sha256(wheel.get("nativeExtensionSha256"))
    ):
        raise BrowserEvidenceError("browser evidence has incomplete wheel provenance")

    installed = report.get("installedPackage")
    if (
        not isinstance(installed, dict)
        or installed.get("version") != wheel["version"]
        or installed.get("nativeVersion") != contract["nativeVersion"]
        or not isinstance(installed.get("pythonInit"), dict)
        or not isinstance(installed.get("nativeExtension"), dict)
    ):
        raise BrowserEvidenceError(
            "browser evidence has incomplete installed-package provenance"
        )
    init = installed["pythonInit"]
    native = installed["nativeExtension"]
    for item, member in (
        (init, "yosoi/__init__.py"),
        (native, wheel["nativeWheelMember"]),
    ):
        path = item.get("path")
        if (
            not isinstance(path, str)
            or not Path(path).is_absolute()
            or not _outside_python_source(Path(path))
            or not _is_sha256(item.get("sha256"))
            or item.get("wheelMember") != member
        ):
            raise BrowserEvidenceError(
                "installed package file does not match wheel provenance"
            )
    if (
        init["sha256"] != wheel["pythonInitSha256"]
        or native["sha256"] != wheel["nativeExtensionSha256"]
    ):
        raise BrowserEvidenceError(
            "installed file hashes do not match wheel RECORD members"
        )
    if init["path"] == native["path"]:
        raise BrowserEvidenceError(
            "Python package and native extension provenance are invalid"
        )

    python_runtime = report.get("python")
    if (
        not isinstance(python_runtime, dict)
        or python_runtime.get("implementation") != "cpython"
        or not isinstance(python_runtime.get("version"), str)
        or not isinstance(python_runtime.get("freeThreaded"), bool)
        or not isinstance(python_runtime.get("executable"), str)
        or not Path(python_runtime["executable"]).is_absolute()
    ):
        raise BrowserEvidenceError(
            "browser evidence has incomplete Python runtime identity"
        )

    browser = report.get("browser")
    if (
        not isinstance(browser, dict)
        or browser.get("channel") != "stable"
        or browser.get("distribution") != "Google Chrome Stable"
        or not isinstance(browser.get("version"), str)
        or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", browser["version"])
        or int(browser["version"].split(".", 1)[0])
        != contract["browser"]["admittedStableMajorVersion"]
        or not isinstance(browser.get("executable"), str)
        or not Path(browser["executable"]).is_absolute()
        or not _is_sha256(browser.get("executableSha256"))
    ):
        raise BrowserEvidenceError(
            "browser evidence has incomplete Chrome Stable identity"
        )

    statuses = report.get("testCases")
    if not isinstance(statuses, list):
        raise BrowserEvidenceError("browser evidence has no test case results")
    expected_cases = {
        test_case for story in contract["stories"] for test_case in story["testCases"]
    }
    actual_cases: dict[str, str] = {}
    for item in statuses:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or item.get("name") in actual_cases
            or item.get("status")
            not in {"passed", "skipped", "failed", "error", "missing"}
        ):
            raise BrowserEvidenceError("browser evidence has malformed test results")
        actual_cases[item["name"]] = item["status"]
    if set(actual_cases) != expected_cases:
        raise BrowserEvidenceError(
            "browser evidence test names do not match contract stories"
        )
    if any(status != "passed" for status in actual_cases.values()):
        raise BrowserEvidenceError(
            "browser evidence contains a missing, skipped, or failed test"
        )

    stories = report.get("stories")
    expected_stories = [
        {"id": story["id"], "status": "passed", "testCases": story["testCases"]}
        for story in contract["stories"]
    ]
    if stories != expected_stories:
        raise BrowserEvidenceError(
            "browser evidence stories do not match passing contract tests"
        )
    return report


def verify_browser_evidence(
    path: Path | str,
    source_revision: str,
    native_path: Path | str | None = None,
    *,
    contract_path: Path = CONTRACT_PATH,
) -> dict[str, Any]:
    """Validate evidence against current source, contract, and native bytes."""
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BrowserEvidenceError(
            f"cannot read browser behavior evidence: {error}"
        ) from error
    contract, contract_sha256 = _contract(contract_path)
    validate_browser_evidence_document(report, contract, contract_sha256)
    if report["sourceRevision"] != source_revision:
        raise BrowserEvidenceError("browser behavior evidence source revision is stale")
    installed = report["installedPackage"]
    installed_paths: dict[str, Path] = {}
    for key in ("pythonInit", "nativeExtension"):
        item = installed[key]
        try:
            current = Path(item["path"]).resolve(strict=True)
        except OSError as error:
            raise BrowserEvidenceError(
                f"cannot read installed package file {key}: {error}"
            ) from error
        if not _outside_python_source(current):
            raise BrowserEvidenceError(
                f"installed package file {key} resolves inside Python source"
            )
        if _digest_file(current) != item["sha256"]:
            label = (
                "native extension"
                if key == "nativeExtension"
                else "Python package file"
            )
            raise BrowserEvidenceError(f"installed {label} hash is stale")
        installed_paths[key] = current
    if native_path is not None:
        try:
            native_file = Path(native_path).resolve(strict=True)
        except OSError as error:
            raise BrowserEvidenceError(
                f"cannot read current native extension: {error}"
            ) from error
        if native_file != installed_paths["nativeExtension"]:
            raise BrowserEvidenceError(
                "browser evidence points to a different native import path"
            )
    try:
        wheel_path = Path(report["wheel"]["path"]).resolve(strict=True)
    except OSError as error:
        raise BrowserEvidenceError(f"cannot read selected wheel: {error}") from error
    if _digest_file(wheel_path) != report["wheel"]["sha256"]:
        raise BrowserEvidenceError("selected wheel hash is stale")
    wheel_info, _wheel_contents = _read_wheel_members(wheel_path)
    if (
        wheel_info["version"] != report["wheel"]["version"]
        or wheel_info["nativeMember"] != report["wheel"]["nativeWheelMember"]
        or wheel_info["recordSha256"] != report["wheel"]["recordSha256"]
        or wheel_info["pythonInitSha256"] != report["wheel"]["pythonInitSha256"]
        or wheel_info["nativeExtensionSha256"]
        != report["wheel"]["nativeExtensionSha256"]
    ):
        raise BrowserEvidenceError(
            "selected wheel RECORD no longer matches browser evidence"
        )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("headless", "headful"), required=True)
    parser.add_argument("--chrome", default=os.environ.get("CHROME"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        create_evidence(
            junit_path=args.junit.resolve(),
            source_revision=args.source,
            wheel_path=args.wheel.resolve(),
            output_path=args.output.resolve(),
            mode=args.mode,
            chrome=args.chrome,
        )
    except (OSError, BrowserEvidenceError) as error:
        print(f"browser behavior evidence failed: {error}", file=sys.stderr)
        return 1
    print(f"Browser behavior evidence: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
