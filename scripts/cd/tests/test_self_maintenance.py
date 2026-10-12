"""Exercise maintenance through a disposable copy of the exact built CLI."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.environ.get("YOSOI_TEST_CLI"), "requires YOSOI_TEST_CLI")
class SelfMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = Path(os.environ["YOSOI_TEST_CLI"]).resolve()
        self.version = (
            subprocess.check_output([str(self.binary), "--version"], text=True)
            .strip()
            .removeprefix("yosoi ")
        )
        self.name = "yosoi.exe" if os.name == "nt" else "yosoi"
        with self.binary.open("rb") as stream:
            self.sha = hashlib.file_digest(stream, "sha256").hexdigest()
        self.env = os.environ | {"UV_TOOL_DIR": str(self.root / "tools")}

    def standalone(self, directory=None):
        directory = directory or self.root / "install with spaces"
        directory.mkdir(parents=True)
        executable = directory / self.name
        try:
            os.link(self.binary, executable)
        except OSError:
            shutil.copy2(self.binary, executable)
        receipt = {
            "schema": 1,
            "method": "standalone",
            "version": self.version,
            "sha256": self.sha,
            "path_added": False,
        }
        (directory / ".yosoi-install.json").write_text(json.dumps(receipt))
        return executable

    def run_cli(self, executable, *args):
        return subprocess.run(
            [str(executable), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_no_prompt_requires_yes_and_preserves_files(self):
        executable = self.standalone()
        for args in [
            ("self", "uninstall"),
            ("self", "update", "--target-version", "0.100000.0"),
        ]:
            result = self.run_cli(executable, *args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--yes", result.stderr)
            self.assertTrue(executable.exists())
            self.assertTrue((executable.parent / ".yosoi-install.json").exists())

    def test_unknown_or_stale_receipt_is_left_unchanged(self):
        executable = self.standalone()
        receipt_path = executable.parent / ".yosoi-install.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt))
        result = self.run_cli(executable, "self", "uninstall", "--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match", result.stderr)
        receipt_path.unlink()
        result = self.run_cli(executable, "self", "uninstall", "--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("receipt missing", result.stderr)
        self.assertTrue(executable.exists())

    def test_package_managers_take_precedence_and_keep_custom_root(self):
        executable = self.standalone(self.root / "cargo root" / "bin")
        metadata = {
            "installs": {f"yosoi {self.version} (registry)": {"bins": [self.name]}}
        }
        (executable.parent.parent / ".crates2.json").write_text(json.dumps(metadata))
        for action in ("update", "uninstall"):
            result = self.run_cli(executable, "self", action, "--yes")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("cargo", result.stdout)
            self.assertIn("--root", result.stdout)
            self.assertIn("cargo root", result.stdout)
            self.assertTrue(executable.exists())

    def test_uv_export_uses_tool_receipt_including_windows_copies(self):
        directory = self.root / "tools" / "yosoi-cli"
        source = self.standalone(directory / ("Scripts" if os.name == "nt" else "bin"))
        (directory / "pyvenv.cfg").write_text("home = python\n")
        exported = self.root / "exported" / self.name
        exported.parent.mkdir()
        if os.name == "nt":
            shutil.copy2(source, exported)
        else:
            exported.symlink_to(source)
        # JSON strings are valid TOML basic strings, including Windows escaping.
        (directory / "uv-receipt.toml").write_text(
            '[tool]\nentrypoints = [{ name = "yosoi", install-path = '
            + json.dumps(str(exported))
            + " }]\n"
        )
        for action in ("update", "uninstall"):
            result = self.run_cli(exported, "self", action, "--yes")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("uv tool", result.stdout)
            self.assertIn("UV_TOOL_DIR", result.stdout)
            self.assertIn("UV_TOOL_BIN_DIR", result.stdout)
            self.assertTrue(source.exists())

    def test_uninstall_yes_removes_only_owned_files(self):
        executable = self.standalone()
        evidence = executable.parent / "saved-document.json"
        evidence.write_text("saved evidence")
        result = self.run_cli(executable, "self", "uninstall", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        if os.name == "nt":
            outcome = Path(result.stdout.split(" at ", 1)[1].strip().removesuffix("."))
            pending = json.loads(outcome.read_text(encoding="utf-8-sig"))
            if pending["status"] == "pending":
                subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        f"Wait-Process -Id {int(pending['helper_id'])} "
                        "-Timeout 70 -ErrorAction SilentlyContinue",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=75,
                )
            terminal = json.loads(outcome.read_text(encoding="utf-8-sig"))
            self.assertEqual(terminal["status"], "success", terminal)
            outcome.unlink()
        self.assertFalse(executable.exists())
        self.assertFalse((executable.parent / ".yosoi-install.json").exists())
        self.assertEqual(evidence.read_text(), "saved evidence")

    @unittest.skipIf(os.name == "nt", "PTY confirmation is POSIX")
    def test_interactive_defaults_and_declining_update(self):
        import pty
        import select
        import time

        executable = self.standalone()
        for args, expected_prompt, answer, expected_result in [
            (("self", "uninstall"), b"[y/N]", b"\n", "Uninstall cancelled."),
            (
                ("self", "update", "--target-version", "0.100000.0"),
                b"[Y/n]",
                b"n\n",
                "Update cancelled.",
            ),
        ]:
            master, slave = pty.openpty()
            try:
                process = subprocess.Popen(
                    [str(executable), *args],
                    env=self.env,
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                )
                # Keep the parent slave descriptor open until output is drained.
                # Closing every slave on macOS can discard buffered final output.
                data = b""
                deadline = time.monotonic() + 15
                while expected_prompt not in data:
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, data)
                    readable, _, _ = select.select([master], [], [], remaining)
                    self.assertTrue(readable, data)
                    data += os.read(master, 65536)
                os.write(master, answer)
                process.wait(timeout=15)
                while select.select([master], [], [], 0)[0]:
                    try:
                        chunk = os.read(master, 65536)
                        if not chunk:
                            break
                        data += chunk
                    except OSError:
                        break
                self.assertEqual(process.returncode, 0, data)
                self.assertIn(expected_result, data.decode())
                self.assertTrue(executable.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if slave is not None:
                    os.close(slave)
                os.close(master)
