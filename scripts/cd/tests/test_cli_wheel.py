"""Check native tool packaging and separate SDK/CLI registry retry identities."""

import base64
import csv
import hashlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release  # noqa: E402
from cli_wheel import build_cli_wheel, verify_cli_wheels  # noqa: E402


class CliWheelTests(unittest.TestCase):
    def build(self, root, platform="manylinux_2_39_x86_64", version="0.2.1"):
        executable = root / ("yosoi.exe" if platform == "win_amd64" else "yosoi")
        executable.write_bytes(b"native-cli-fixture")
        license_file = root / "LICENSE"
        license_file.write_text("Apache License, Version 2.0\n")
        return build_cli_wheel(
            executable, root / "dist", version, platform, license_file
        )

    def planned(self, platform="manylinux_2_39_x86_64"):
        return {
            "version": "0.2.1",
            "platforms": {"include": [{"cli_wheel_platform": platform}]},
        }

    def test_platform_matrix_has_no_sdk_dependencies_and_valid_records(self):
        for platform in (
            "manylinux_2_39_x86_64",
            "manylinux_2_39_aarch64",
            "win_amd64",
            "macosx_11_0_arm64",
            "macosx_11_0_x86_64",
        ):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                wheel = self.build(root, platform)
                verify_cli_wheels(root / "dist", self.planned(platform))
                with zipfile.ZipFile(wheel) as archive:
                    metadata = archive.read("yosoi_cli-0.2.1.dist-info/METADATA")
                    self.assertNotIn(b"Requires-Dist:", metadata)
                    records = csv.reader(
                        io.StringIO(
                            archive.read("yosoi_cli-0.2.1.dist-info/RECORD").decode()
                        )
                    )
                    for name, digest, size in records:
                        if not digest:
                            continue
                        content = archive.read(name)
                        actual = (
                            base64.urlsafe_b64encode(hashlib.sha256(content).digest())
                            .rstrip(b"=")
                            .decode()
                        )
                        self.assertEqual(digest, "sha256=" + actual)
                        self.assertEqual(int(size), len(content))
                    binary = "yosoi.exe" if platform == "win_amd64" else "yosoi"
                    member = archive.getinfo(f"yosoi_cli-0.2.1.data/scripts/{binary}")
                    self.assertEqual((member.external_attr >> 16) & 0o777, 0o755)

    def test_packaging_is_deterministic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheel = self.build(root)
            original = wheel.read_bytes()
            with self.assertRaises(FileExistsError):
                self.build(root)
            wheel.unlink()
            self.assertEqual(self.build(root).read_bytes(), original)

    def test_rc_uses_pep440_and_rejects_wrong_version_or_missing_platform(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.build(root, version="0.2.1-rc.1")
            verify_cli_wheels(root / "dist", self.planned() | {"version": "0.2.1-rc.1"})
            with self.assertRaises((KeyError, ValueError)):
                verify_cli_wheels(root / "dist", self.planned())
            with self.assertRaisesRegex(ValueError, "Missing CLI wheels"):
                verify_cli_wheels(
                    root / "dist",
                    {
                        **self.planned(),
                        "version": "0.2.1-rc.1",
                        "platforms": {
                            "include": [
                                {"cli_wheel_platform": "manylinux_2_39_x86_64"},
                                {"cli_wheel_platform": "win_amd64"},
                            ]
                        },
                    },
                )

    def test_renamed_duplicate_or_wrong_platform_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheel = self.build(root)
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                verify_cli_wheels(root / "dist", self.planned("win_amd64"))
            wheel.rename(wheel.with_name("yosoi_cli-duplicate.whl"))
            with self.assertRaisesRegex(ValueError, "filename"):
                verify_cli_wheels(root / "dist", self.planned())

    def test_pypi_retry_uses_each_packages_own_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = self.build(root)
            sdk = cli.parent / "yosoi-0.2.1-py3-none-any.whl"
            sdk.write_bytes(b"sdk")

            def registry(url):
                if "/yosoi-cli/" in url:
                    return {
                        "urls": [
                            {
                                "filename": cli.name,
                                "digests": {"sha256": release.sha256(cli)},
                            }
                        ]
                    }
                return None

            with patch.object(release, "json_url", side_effect=registry) as lookup:
                release.pypi_pending(cli.parent, "0.2.1", root / "pending")
            self.assertEqual(
                sorted(p.name for p in (root / "pending").iterdir()), [sdk.name]
            )
            self.assertEqual(
                {call.args[0] for call in lookup.call_args_list},
                {
                    "https://pypi.org/pypi/yosoi/0.2.1/json",
                    "https://pypi.org/pypi/yosoi-cli/0.2.1/json",
                },
            )


if __name__ == "__main__":
    unittest.main()
