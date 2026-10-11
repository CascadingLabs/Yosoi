"""Exercise the actual shell installer offline, including failure preservation."""

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[2] / "install/install.sh"


@unittest.skipIf(os.name == "nt", "POSIX installer")
class InstallerTests(unittest.TestCase):
    def fixture(
        self,
        root,
        *,
        system="Linux",
        arch="x86_64",
        version="0.2.1",
        member="yosoi",
        content=None,
    ):
        mocks = root / "mocks"
        mocks.mkdir()
        fixtures = root / "fixtures"
        fixtures.mkdir()
        (fixtures / "release-plan.json").write_text(
            json.dumps({"version": version}, indent=2) + "\n"
        )
        os_tag = "linux" if system == "Linux" else "macos"
        cpu_tag = "aarch64" if arch in ("aarch64", "arm64") else "x86_64"
        asset = f"yosoi-v{version}-{os_tag}-{cpu_tag}.tar.gz"
        if content is None:
            content = f"#!/bin/sh\nprintf 'yosoi {version}\\n'\n".encode()
        with tarfile.open(fixtures / asset, "w:gz") as archive:
            info = tarfile.TarInfo(member)
            info.size = len(content)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(content))
        checksum = hashlib.sha256((fixtures / asset).read_bytes()).hexdigest()
        (fixtures / "SHA256SUMS").write_text(f"{checksum}  {asset}\n")
        scripts = {
            "uname": (
                '#!/bin/sh\ncase "$1" in '
                f"-s) echo {system} ;; -m) echo {arch} ;; esac\n"
            ),
            "getconf": '#!/bin/sh\necho "${FIXTURE_LIBC:-glibc 2.39}"\n',
            "sw_vers": '#!/bin/sh\necho "${FIXTURE_MACOS:-11.0}"\n',
            "curl": """#!/bin/sh
while [ "$#" -gt 0 ]; do
case "$1" in
https://*) url=$1; shift ;;
-o) output=$2; shift 2 ;;
--proto|--proto-redir|--tlsv1.2|--retry|--connect-timeout|--max-time) shift 2 ;;
*) shift ;;
esac
done
cp "$FIXTURE_ROOT/${url##*/}" "$output"
""",
        }
        for name, script in scripts.items():
            file = mocks / name
            file.write_text(script)
            file.chmod(0o755)
        return os.environ | {
            "PATH": f"{mocks}:{os.environ['PATH']}",
            "FIXTURE_ROOT": str(fixtures),
            "YOSOI_INSTALL_DIR": str(root / "install with spaces"),
            "YOSOI_VERSION": "",
        }

    def run_installer(self, env, *args):
        return subprocess.run(
            ["sh", str(INSTALLER), *args],
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_latest_pinned_and_rc_install_and_upgrade(self):
        for system, arch, version in (
            ("Linux", "x86_64", "0.2.1"),
            ("Linux", "aarch64", "0.2.1"),
            ("Darwin", "arm64", "0.2.1"),
            ("Darwin", "x86_64", "0.2.1-rc.1"),
        ):
            with (
                self.subTest(system=system, arch=arch),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                env = self.fixture(root, system=system, arch=arch, version=version)
                for args in ((), ("--version", version)):
                    result = self.run_installer(env, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    installed = Path(env["YOSOI_INSTALL_DIR"]) / "yosoi"
                    self.assertEqual(
                        subprocess.check_output(
                            [str(installed), "--version"], text=True
                        ).strip(),
                        f"yosoi {version}",
                    )
                    self.assertIn("Installed Yosoi", result.stdout)

    def test_bad_checksum_and_archive_members_preserve_existing_binary(self):
        for failure in ("checksum", "missing-checksum", "traversal", "wrong-version"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                env = self.fixture(
                    root,
                    member="../yosoi" if failure == "traversal" else "yosoi",
                    content=b"#!/bin/sh\necho 'yosoi 0.1.0'\n"
                    if failure == "wrong-version"
                    else None,
                )
                if failure in ("checksum", "missing-checksum"):
                    sums = root / "fixtures/SHA256SUMS"
                    sums.write_text(
                        sums.read_text().replace(sums.read_text()[:64], "0" * 64)
                        if failure == "checksum"
                        else ""
                    )
                installed = Path(env["YOSOI_INSTALL_DIR"]) / "yosoi"
                installed.parent.mkdir()
                installed.write_bytes(b"previous-install")
                result = self.run_installer(env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(installed.read_bytes(), b"previous-install")

    def test_unsupported_platform_baseline_and_invalid_version_fail(self):
        for changes in (
            {"FIXTURE_LIBC": "glibc 2.38"},
            {"FIXTURE_LIBC": "musl 1.2"},
            {"YOSOI_VERSION": "../../bad"},
            {"YOSOI_INSTALL_DIR": "relative"},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temp:
                env = self.fixture(Path(temp)) | changes
                result = self.run_installer(env)
                self.assertNotEqual(result.returncode, 0, result.stdout)
        for system, arch in (("FreeBSD", "x86_64"), ("Linux", "riscv64")):
            with tempfile.TemporaryDirectory() as temp:
                result = self.run_installer(
                    self.fixture(Path(temp), system=system, arch=arch)
                )
                self.assertNotEqual(result.returncode, 0)

    def test_symlink_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = self.fixture(root)
            target = root / "uv-managed-cli"
            target.write_bytes(b"old-cli")
            installed = Path(env["YOSOI_INSTALL_DIR"]) / "yosoi"
            installed.parent.mkdir()
            installed.symlink_to(target)
            result = self.run_installer(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uv tool uninstall yosoi", result.stderr)
            self.assertTrue(installed.is_symlink())
            self.assertEqual(target.read_bytes(), b"old-cli")

    def test_release_executable_when_supplied(self):
        executable = os.environ.get("YOSOI_TEST_EXECUTABLE")
        if not executable:
            self.skipTest("Native build supplied only by artifact validation")
        version = (
            subprocess.check_output([executable, "--version"], text=True)
            .strip()
            .removeprefix("yosoi ")
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = self.fixture(
                root, version=version, content=Path(executable).read_bytes()
            )
            result = self.run_installer(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = Path(env["YOSOI_INSTALL_DIR"]) / "yosoi"
            subprocess.run(
                [str(installed), "request", "--help"], check=True, capture_output=True
            )


if __name__ == "__main__":
    unittest.main()
