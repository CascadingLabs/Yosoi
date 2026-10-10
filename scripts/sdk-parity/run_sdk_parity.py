#!/usr/bin/env python3
"""Run the fail-closed semantic Rust/Python SDK parity gate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
REFERENCE_GENERATOR = ROOT / "scripts/docs/reference/generate.mjs"
TOOLCHAIN_FILE = ROOT / "scripts/docs/reference/toolchain.json"
BASELINE_LEDGER = ROOT / "python/parity/ledger.json"
SDK_CONTRACT = ROOT / "python/parity/sdk-contract.json"
EXAMPLES: tuple[tuple[str, str, bool], ...] = (
    ("python_conformance", "run_conformance.py", False),
    ("python_diagnostics_conformance", "run_diagnostics_conformance.py", False),
    ("python_schema_errors_conformance", "run_schema_errors_conformance.py", False),
    ("python_value_equality_conformance", "run_value_equality_conformance.py", False),
    ("python_errors_conformance", "run_errors_conformance.py", True),
    ("python_map_ordering_conformance", "run_map_ordering_conformance.py", True),
    ("python_serde_conformance", "run_serde_conformance.py", False),
    ("python_document_errors_conformance", "run_document_errors_conformance.py", True),
    ("python_webtarget_conformance", "run_webtarget_conformance.py", True),
)


class RunnerError(RuntimeError):
    """Raised when the SDK parity orchestration cannot prove its inputs."""


Command = Callable[..., subprocess.CompletedProcess[str]]


def run_command(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one checked command with text output, suitable for mocked tests."""
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = "\n".join(
            (result.stderr or result.stdout or "no command output").splitlines()[-30:]
        )
        raise RunnerError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n{detail}"
        )
    return result


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunnerError(f"cannot read JSON file {path}: {error}") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RunnerError(f"cannot read Rust example binary {path}: {error}") from error
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RunnerError(f"cannot load parity module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _assert_installed_package(package_name: str = "yosoi") -> None:
    spec = importlib.util.find_spec(package_name)
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None:
        raise RunnerError(f"cannot locate installed Python package {package_name!r}")
    source_root = (ROOT / "python").resolve()
    try:
        origin.relative_to(source_root)
    except ValueError:
        return
    raise RunnerError(
        "semantic SDK parity must import the installed wheel; Python resolved "
        f"{package_name!r} from the source tree at {origin}"
    )


def _git_commit(source: str | None, command: Command, repo: Path = ROOT) -> str:
    revision = f"{source}^{{commit}}" if source else "HEAD^{commit}"
    result = command(
        ["git", "rev-parse", "--verify", "--end-of-options", revision], cwd=repo
    )
    commit = result.stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RunnerError("source must resolve to a full 40-character Git commit")
    return commit


def _git_tree_is_clean(command: Command) -> bool:
    result = command(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT
    )
    return not result.stdout.strip()


def _reference_manifest(
    reference_dir: Path,
    *,
    source: str,
    command: Command,
) -> dict[str, Any]:
    command(
        [
            "node",
            str(REFERENCE_GENERATOR),
            "verify",
            "--dir",
            str(reference_dir.resolve()),
        ],
        cwd=ROOT,
    )
    manifest = _read_json(reference_dir / "manifest.json")
    actual_source = (manifest.get("source") or {}).get("commit")
    if actual_source != source:
        raise RunnerError(
            "Rust reference source does not match the selected source commit "
            f"({actual_source!r} != {source!r})"
        )
    return manifest


def _generate_reference(
    *,
    source: str,
    output_dir: Path,
    offline: bool,
    command: Command,
    source_repo: Path = ROOT,
) -> Path:
    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    reference_dir = output_dir / "references" / f"{run_stamp}-{source[:12]}"
    work_dir = output_dir / "reference-work"
    args = [
        "node",
        str(REFERENCE_GENERATOR),
        "generate",
        "--source",
        source,
        "--sdk",
        "yosoi",
        "--repo",
        str(source_repo),
        "--repository",
        "CascadingLabs/Yosoi",
        "--out",
        str(reference_dir),
        "--work",
        str(work_dir),
        "--version",
        f"0.1.0-sdk-parity.{source[:12]}",
        "--features",
        "browser",
        "--preview",
    ]
    if offline:
        args.append("--offline")
    command(args, cwd=ROOT)
    return reference_dir


def _toolchain() -> dict[str, Any]:
    document = _read_json(TOOLCHAIN_FILE)
    channel = document.get("channel")
    compiler_commit = document.get("compilerCommit")
    if not isinstance(channel, str) or not channel:
        raise RunnerError("reference toolchain.json has no pinned compiler channel")
    if not isinstance(compiler_commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}", compiler_commit
    ):
        raise RunnerError("reference toolchain.json has no pinned compiler commit")
    return document


def _build_examples(*, channel: str, offline: bool, command: Command) -> None:
    args = [
        "cargo",
        f"+{channel}",
        "build",
        "--locked",
        "--package",
        "yosoi",
        "--features",
        "browser",
        "--jobs",
        "1",
    ]
    if offline:
        args.append("--offline")
    for example, _, _ in EXAMPLES:
        args.extend(("--example", example))
    env = os.environ.copy()
    env.update(
        CARGO_BUILD_JOBS="1",
        RAYON_NUM_THREADS="1",
        CARGO_INCREMENTAL="0",
    )
    command(args, cwd=ROOT, env=env)


def _binary_dir() -> Path:
    configured = os.environ.get("CARGO_TARGET_DIR")
    target_dir = Path(configured) if configured else ROOT / "target"
    if not target_dir.is_absolute():
        target_dir = ROOT / target_dir
    return target_dir / "debug" / "examples"


def _sdk_contract_module() -> Any:
    path = SCRIPT_DIR / "sdk_contract.py"
    if not path.is_file():
        raise RunnerError(f"SDK contract tooling is missing: {path}")
    return _load_module("sdk_contract", path)


def _parity_module() -> Any:
    return _load_module("sdk_parity", SCRIPT_DIR / "parity.py")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def run_sdk_parity(
    args: argparse.Namespace,
    *,
    command: Command = run_command,
    contract_module: Any | None = None,
    parity_module: Any | None = None,
    package_probe: Callable[[], None] = _assert_installed_package,
) -> int:
    package_probe()
    source_repo = (getattr(args, "source_repo", None) or ROOT).resolve()
    source = _git_commit(args.source, command, source_repo)
    current_head = _git_commit(None, command)
    clean_tree = _git_tree_is_clean(command)
    if source != current_head or not clean_tree:
        raise RunnerError(
            "SDK parity requires the selected source to match the clean build "
            "checkout HEAD; commit changes and run from that checkout."
        )
    if args.skip_build:
        raise RunnerError(
            "SDK parity cannot verify reused fixture provenance; --skip-build "
            "is not accepted by the release gate."
        )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    toolchain = _toolchain()

    if args.rust_reference is None:
        reference_dir = _generate_reference(
            source=source,
            output_dir=output_dir,
            offline=args.offline,
            command=command,
            source_repo=source_repo,
        )
    else:
        reference_dir = args.rust_reference.resolve()

    manifest = _reference_manifest(reference_dir, source=source, command=command)
    _build_examples(channel=toolchain["channel"], offline=args.offline, command=command)
    if _git_commit(None, command) != source or not _git_tree_is_clean(command):
        raise RunnerError("Build checkout changed while producing SDK parity fixtures")

    binary_dir = _binary_dir()
    binaries: dict[str, Path] = {}
    binary_pins: dict[str, str] = {}
    for example, _, _ in EXAMPLES:
        path = binary_dir / example
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RunnerError(f"missing executable Rust example binary: {path}")
        binaries[example] = path.resolve()
        binary_pins[example] = _sha256_file(path)

    parity = parity_module or _parity_module()
    contract_tools = contract_module or _sdk_contract_module()
    rust = parity.load_rust_inventory(reference_dir)
    python = parity.introspect_python_package("yosoi")
    contract = contract_tools.load_contract(SDK_CONTRACT)
    baseline = parity.load_ledger(BASELINE_LEDGER)
    runtime_ledger, drift = contract_tools.prepare_ledger(
        contract,
        rust,
        python,
        baseline,
    )
    runtime_ledger_path = output_dir / "runtime-ledger.json"
    _write_json(runtime_ledger_path, runtime_ledger)
    if drift:
        detail = json.dumps(drift, indent=2, ensure_ascii=False)
        raise RunnerError(f"SDK structural/runtime contract drift detected:\n{detail}")

    evidence_dir = output_dir / "evidence"
    python_root = output_dir / "installed-python-root"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    python_root.mkdir(parents=True, exist_ok=True)
    evidence_paths: list[Path] = []
    for example, runner_name, accepts_python_root in EXAMPLES:
        evidence_path = evidence_dir / f"{example}.json"
        runner = SCRIPT_DIR / runner_name
        runner_args = [
            sys.executable,
            str(runner),
            "--rust-executable",
            str(binaries[example]),
            "--rust-reference",
            str(reference_dir.resolve()),
        ]
        if runner_name != "run_map_ordering_conformance.py":
            runner_args.extend(("--ledger", str(runtime_ledger_path.resolve())))
        runner_args.extend(("--output", str(evidence_path.resolve())))
        if accepts_python_root:
            runner_args.extend(("--python-root", str(python_root.resolve())))
        command(runner_args, cwd=ROOT)
        evidence_paths.append(evidence_path.resolve())

    run_dir = output_dir / "execution.json"
    execution = {
        "schemaVersion": 1,
        "kind": "yosoi-python-sdk-parity-execution",
        "sourceRevision": source,
        "referenceSourceRevision": manifest["source"]["commit"],
        "referencePath": str(reference_dir.resolve()),
        "toolchain": toolchain,
        "python": {
            key: python.get(key)
            for key in ("runtime", "surfaceDigest", "implementationDigest")
        },
        "inventoryPins": {
            key: rust.get(key)
            for key in (
                "sourceRevision",
                "inventorySignature",
                "featureProfileDigest",
            )
        },
        "runtimeLedgerSha256": _sha256_file(runtime_ledger_path),
        "fixtureExecutables": {
            name: {"path": str(path), "sha256": binary_pins[name]}
            for name, path in binaries.items()
        },
        "binaryBuild": {
            "mode": "built",
            "freshCurrentHead": True,
        },
        "evidence": [str(path) for path in evidence_paths],
    }
    _write_json(run_dir, execution)

    report_path = output_dir / "report.json"
    summary_path = output_dir / "summary.json"
    gate_args = [
        sys.executable,
        str(SCRIPT_DIR / "parity.py"),
        "--gate",
        "sdk",
        "--contract",
        str(SDK_CONTRACT),
        "--ledger",
        str(runtime_ledger_path.resolve()),
        "--rust-reference",
        str(reference_dir.resolve()),
        "--python-root",
        str(python_root.resolve()),
        "--output",
        str(report_path.resolve()),
        "--summary-output",
        str(summary_path.resolve()),
    ]
    for evidence_path in evidence_paths:
        gate_args.extend(("--evidence", str(evidence_path)))
    command(gate_args, cwd=ROOT)
    print(f"SDK semantic parity report: {report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", help="full Git commit/tag; defaults to repository HEAD"
    )
    parser.add_argument(
        "--source-repo",
        type=Path,
        help="authoritative Git object store checkout for JJ workspaces",
    )
    parser.add_argument(
        "--rust-reference",
        type=Path,
        help="existing compiler-generated reference to verify and reuse",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".generated/python-parity"),
        help="directory for the ephemeral ledger, evidence, and report",
    )
    parser.add_argument(
        "--offline", action="store_true", help="forward offline mode to Rust tooling"
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="release parity requires fresh fixtures; reuse is not supported",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_sdk_parity(args)
    except (OSError, ValueError, RunnerError, subprocess.CalledProcessError) as error:
        print(f"SDK parity failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
