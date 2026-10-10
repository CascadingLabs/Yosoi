from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT = Path(__file__).with_name("run_sdk_parity.py")
SPEC = importlib.util.spec_from_file_location("run_sdk_parity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class FakeParity:
    def __init__(self) -> None:
        self.loaded_ledger: Path | None = None

    def load_rust_inventory(self, reference: Path) -> dict[str, object]:
        return {"sourceRevision": "a" * 40, "items": []}

    def introspect_python_package(self, package: str) -> dict[str, object]:
        if package != "yosoi":
            raise AssertionError(package)
        return {"runtime": {"version": "3.14.8"}}

    def load_ledger(self, path: Path) -> dict[str, object]:
        self.loaded_ledger = path
        return {"entries": []}


class FakeContract:
    def __init__(self, drift: list[dict[str, object]] | None = None) -> None:
        self.drift = drift or []
        self.baseline: Path | None = None

    def load_contract(self, path: Path) -> dict[str, object]:
        return {"contract": str(path)}

    def prepare_ledger(
        self,
        contract: dict[str, object],
        rust: dict[str, object],
        python: dict[str, object],
        ledger: dict[str, object],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        self.baseline = Path(str(contract["contract"]))
        return ({"schemaVersion": 1, "entries": []}, self.drift)


class SdkParityRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.temp_path = Path(self.temp.name)
        self.source = "a" * 40
        self.reference = self.temp_path / "reference"
        self.reference.mkdir()
        (self.reference / "manifest.json").write_text(
            json.dumps({"source": {"commit": self.source}}), encoding="utf-8"
        )
        self.binary_dir = self.temp_path / "binaries"
        self.binary_dir.mkdir()
        for example, _, _ in runner.EXAMPLES:
            binary = self.binary_dir / example
            binary.write_bytes(example.encode())
            binary.chmod(0o755)
        self.output = self.temp_path / "output"
        self.fake_parity = FakeParity()
        self.fake_contract = FakeContract()
        self.calls: list[list[str]] = []

        def command(
            args: list[str],
            *,
            cwd: Path = runner.ROOT,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            del cwd, env
            call = list(args)
            self.calls.append(call)
            stdout = self.source + "\n" if call[:2] == ["git", "rev-parse"] else ""
            return subprocess.CompletedProcess(call, 0, stdout=stdout, stderr="")

        self.command = command
        self.args = runner.build_parser().parse_args(
            [
                "--source",
                self.source,
                "--rust-reference",
                str(self.reference),
                "--output-dir",
                str(self.output),
            ]
        )

    def run_gate(self) -> int:
        with mock.patch.object(runner, "_binary_dir", return_value=self.binary_dir):
            return runner.run_sdk_parity(
                self.args,
                command=self.command,
                contract_module=self.fake_contract,
                parity_module=self.fake_parity,
                package_probe=lambda: None,
            )

    def test_runs_nine_python_fixtures_in_order_and_uses_sdk_gate(self) -> None:
        self.assertEqual(self.run_gate(), 0)

        runner_calls = [
            call
            for call in self.calls
            if len(call) > 1
            and call[0] == sys.executable
            and call[1].endswith(".py")
            and Path(call[1]).name != "parity.py"
        ]
        self.assertEqual(
            [Path(call[1]).name for call in runner_calls],
            [entry[1] for entry in runner.EXAMPLES],
        )
        for call, (example, _, accepts_python_root) in zip(
            runner_calls, runner.EXAMPLES, strict=True
        ):
            self.assertIn(str(self.binary_dir / example), call)
            if example != "python_map_ordering_conformance":
                self.assertIn(str(self.output / "runtime-ledger.json"), call)
            if accepts_python_root:
                self.assertIn("--python-root", call)
            if example == "python_map_ordering_conformance":
                self.assertNotIn("--ledger", call)

        gate_call = self.calls[-1]
        self.assertEqual(
            gate_call[:4],
            [sys.executable, str(runner.SCRIPT_DIR / "parity.py"), "--gate", "sdk"],
        )
        self.assertIn("--contract", gate_call)
        self.assertIn("--ledger", gate_call)
        self.assertNotIn("--allow-incomplete", gate_call)

        execution = json.loads(
            (self.output / "execution.json").read_text(encoding="utf-8")
        )
        self.assertTrue(execution["binaryBuild"]["freshCurrentHead"])
        self.assertEqual(execution["binaryBuild"]["mode"], "built")
        self.assertEqual(
            execution["fixtureExecutables"]["python_conformance"]["sha256"],
            hashlib.sha256(b"python_conformance").hexdigest(),
        )
        self.assertTrue(any(call and call[0] == "cargo" for call in self.calls))

    def test_selected_source_must_match_build_checkout_before_any_build(self) -> None:
        with mock.patch.object(
            runner, "_git_commit", side_effect=[self.source, "b" * 40]
        ):
            with self.assertRaisesRegex(
                runner.RunnerError, "clean build checkout HEAD"
            ):
                self.run_gate()
        self.assertFalse(any(call[0] in {"cargo", "node"} for call in self.calls))

    def test_dirty_checkout_is_rejected_before_any_build(self) -> None:
        with mock.patch.object(runner, "_git_tree_is_clean", return_value=False):
            with self.assertRaisesRegex(
                runner.RunnerError, "clean build checkout HEAD"
            ):
                self.run_gate()
        self.assertFalse(any(call[0] in {"cargo", "node"} for call in self.calls))

    def test_unverified_reused_fixtures_cannot_pass_release_gate(self) -> None:
        self.args.skip_build = True
        with self.assertRaisesRegex(runner.RunnerError, "reused fixture provenance"):
            self.run_gate()
        self.assertFalse(any(call[0] in {"cargo", "node"} for call in self.calls))

    def test_drift_fails_before_any_fixture_runner_and_preserves_baseline(self) -> None:
        baseline_bytes = runner.BASELINE_LEDGER.read_bytes()
        self.fake_contract = FakeContract([{"kind": "drift", "path": "sample"}])

        with mock.patch.object(runner, "_binary_dir", return_value=self.binary_dir):
            with self.assertRaisesRegex(runner.RunnerError, "drift detected"):
                runner.run_sdk_parity(
                    self.args,
                    command=self.command,
                    contract_module=self.fake_contract,
                    parity_module=self.fake_parity,
                    package_probe=lambda: None,
                )

        self.assertEqual(runner.BASELINE_LEDGER.read_bytes(), baseline_bytes)
        self.assertFalse(
            any(
                call
                and call[0] == sys.executable
                and len(call) > 1
                and call[1].endswith(".py")
                for call in self.calls
            )
        )

    def test_rust_reference_must_match_selected_source(self) -> None:
        (self.reference / "manifest.json").write_text(
            json.dumps({"source": {"commit": "b" * 40}}), encoding="utf-8"
        )

        with self.assertRaisesRegex(runner.RunnerError, "does not match"):
            runner.run_sdk_parity(
                self.args,
                command=self.command,
                contract_module=self.fake_contract,
                parity_module=self.fake_parity,
                package_probe=lambda: None,
            )

        self.assertFalse(any(call and call[0] == "cargo" for call in self.calls))
        self.assertFalse(any(call and call[0] == sys.executable for call in self.calls))

    def test_build_precedes_fixtures_and_marks_clean_head_binaries_fresh(self) -> None:
        self.args = runner.build_parser().parse_args(
            [
                "--source",
                self.source,
                "--rust-reference",
                str(self.reference),
                "--output-dir",
                str(self.output),
            ]
        )

        self.assertEqual(self.run_gate(), 0)

        cargo_index = next(
            index for index, call in enumerate(self.calls) if call[0] == "cargo"
        )
        first_fixture_index = next(
            index
            for index, call in enumerate(self.calls)
            if len(call) > 1
            and call[0] == sys.executable
            and Path(call[1]).name == runner.EXAMPLES[0][1]
        )
        self.assertLess(cargo_index, first_fixture_index)
        execution = json.loads(
            (self.output / "execution.json").read_text(encoding="utf-8")
        )
        self.assertEqual(execution["binaryBuild"]["mode"], "built")
        self.assertTrue(execution["binaryBuild"]["freshCurrentHead"])

    def test_reference_generation_passes_offline_and_exact_source_options(self) -> None:
        captured: list[list[str]] = []

        def command(
            args: list[str],
            *,
            cwd: Path = runner.ROOT,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            del cwd, env
            captured.append(list(args))
            return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")

        output = runner._generate_reference(
            source=self.source,
            output_dir=self.output,
            offline=True,
            command=command,
        )
        call = captured[0]
        self.assertEqual(
            call[:5],
            [
                "node",
                str(runner.REFERENCE_GENERATOR),
                "generate",
                "--source",
                self.source,
            ],
        )
        self.assertIn("CascadingLabs/Yosoi", call)
        self.assertIn("--features", call)
        self.assertIn("browser", call)
        self.assertIn("--preview", call)
        self.assertIn("--offline", call)
        self.assertTrue(output.is_relative_to(self.output / "references"))

    def test_build_uses_one_serial_cargo_invocation_for_all_examples(self) -> None:
        captured: list[list[str]] = []

        def command(
            args: list[str],
            *,
            cwd: Path = runner.ROOT,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            del cwd
            self.assertEqual(env["CARGO_BUILD_JOBS"], "1")
            self.assertEqual(env["RAYON_NUM_THREADS"], "1")
            captured.append(list(args))
            return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")

        runner._build_examples(channel="nightly-pinned", offline=True, command=command)

        self.assertEqual(len(captured), 1)
        command_args = captured[0]
        self.assertEqual(command_args[:2], ["cargo", "+nightly-pinned"])
        self.assertIn("--jobs", command_args)
        self.assertEqual(command_args[command_args.index("--jobs") + 1], "1")
        self.assertIn("--offline", command_args)
        self.assertEqual(
            [
                command_args[index + 1]
                for index, value in enumerate(command_args)
                if value == "--example"
            ],
            [entry[0] for entry in runner.EXAMPLES],
        )

    def test_unknown_positional_command_is_rejected(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            runner.build_parser().parse_args(["build"])

    def test_source_tree_import_is_rejected_for_package_parity(self) -> None:
        source_package = runner.ROOT / "python/yosoi/__init__.py"
        with mock.patch.object(
            runner.importlib.util,
            "find_spec",
            return_value=SimpleNamespace(origin=str(source_package)),
        ):
            with self.assertRaisesRegex(runner.RunnerError, "installed wheel"):
                runner._assert_installed_package()


if __name__ == "__main__":
    unittest.main()
