"""Verify release gates using synthetic packages; no builds or registry writes."""

import io
import os
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY))
import publish  # noqa: E402
import release  # noqa: E402
from archive import cli_archive  # noqa: E402


class IdentityTests(unittest.TestCase):
    def test_rc_versions_use_registry_specific_spelling(self):
        for tag in ("v0.1.0-rc.1", "v0.1.0-rc.2"):
            version = release.release_version(tag)
            self.assertEqual(version, tag[1:])
            self.assertEqual(
                release.python_version(version), version.replace("-rc.", "rc")
            )
        for tag in ("v0.1.0-rc.0", "v0.1.0-rc.01", "v0.1.0-rc", "v0.1.0rc1"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.release_version(tag)

    def test_production_docs_dispatch_guard_and_reusable_release_call(self):
        workflow = DIRECTORY.parents[1] / ".github/workflows/docs-publish.yml"
        section = (
            workflow.read_text()
            .split(
                "      - name: Restrict standalone manual docs publication to main\n", 1
            )[1]
            .split("\n      - ", 1)[0]
        )
        script = textwrap.dedent(section.split("        run: |\n", 1)[1])
        for event, ref, source, expected in (
            ("workflow_dispatch", "refs/heads/main", "", 0),
            ("workflow_dispatch", "refs/heads/feature", "", 1),
            ("workflow_dispatch", "refs/tags/v0.1.0", "a" * 40, 0),
            ("push", "refs/heads/main", "", 0),
        ):
            with self.subTest(event=event, ref=ref, source=source):
                result = subprocess.run(
                    ["bash", "-ec", script],
                    env=dict(
                        os.environ,
                        EVENT_NAME=event,
                        SELECTED_REF=ref,
                        REQUESTED_SOURCE=source,
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_publishing_requires_the_tagged_workflow_revision(self):
        release.verify_workflow_source("a" * 40, "a" * 40, True)
        for workflow in (None, "b" * 40):
            with (
                self.subTest(workflow=workflow),
                self.assertRaisesRegex(ValueError, "workflow revision"),
            ):
                release.verify_workflow_source("a" * 40, workflow, True)

    def test_validation_only_can_use_a_different_workflow_revision(self):
        release.verify_workflow_source("a" * 40, "b" * 40, False)

    def test_beta_version_boundaries(self):
        for valid in ("v0.1.0", "v0.100000.10000"):
            self.assertEqual(release.release_version(valid), valid[1:])
        for invalid in (
            "v1.0.0",
            "v0.0.1",
            "v0.01.0",
            "v0.1.0-beta",
            "v0.100001.0",
            "v0.1.10001",
            "v0.1.0\n",
        ):
            with self.subTest(tag=invalid), self.assertRaises(ValueError):
                release.release_version(invalid)

    def test_python_315_follows_compatibility_range(self):
        old = release.python_abis(">=3.12,<3.15")
        new = release.python_abis(">=3.12,<3.16")
        self.assertEqual([a["python"] for a in old], ["3.12", "3.13", "3.14", "3.14t"])
        self.assertEqual([a["python"] for a in new[-2:]], ["3.15", "3.15t"])
        self.assertEqual(new[-1]["linux_python"], "/opt/python/cp315-cp315t/bin/python")

    def test_unreviewed_python_range_fails(self):
        for requirement in (">=3.12", ">=3.12,<3.17", ">=3.14,<3.13"):
            with self.subTest(requirement=requirement), self.assertRaises(ValueError):
                release.python_abis(requirement)

    def test_native_platforms_are_distinct(self):
        self.assertEqual(len(release.PLATFORMS), 5)
        self.assertEqual(len({p[1] for p in release.PLATFORMS}), 5)
        self.assertNotIn("aarch64-pc-windows-msvc", {p[1] for p in release.PLATFORMS})


class PublicationPlanTests(unittest.TestCase):
    def fixture(self, root, dependency_publish="true", cycle=False):
        (root / "Cargo.toml").write_text("""[workspace]
members = ["crates/application", "crates/substrate"]
[workspace.dependencies]
substrate = { version = "=0.1.0", path = "crates/substrate" }
""")
        for name in ("application", "substrate"):
            path = root / "crates" / name
            path.mkdir(parents=True)
            setting = dependency_publish if name == "substrate" else "true"
            body = (
                f'[package]\nname = "{name}"\nversion = "0.1.0"\npublish = {setting}\n'
            )
            if name == "application":
                body += (
                    "[dependencies]\n"
                    "substrate = { workspace = true, optional = true }\n"
                )
            elif cycle:
                body += (
                    "[dependencies]\n"
                    'application = { version = "=0.1.0", path = "../application" }\n'
                )
            (path / "Cargo.toml").write_text(body)

    def test_dependencies_are_published_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(
                release.publication_plan(root),
                {"crates": ["substrate", "application"], "blockers": []},
            )

    def test_nonpublishable_optional_dependency_blocks_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, "false")
            result = release.publication_plan(root)
            self.assertEqual(result["crates"], ["application"])
            self.assertEqual(
                result["blockers"],
                ["application depends on substrate, which has publish = false"],
            )

    def test_dependency_cycles_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, cycle=True)
            with self.assertRaisesRegex(ValueError, "Cyclic"):
                release.publication_plan(root)


class ArtifactTests(unittest.TestCase):
    def fixture(self, directory, version="0.1.0", abi="cp314t", platform="win_amd64"):
        wheel = directory / f"yosoi-{version}-cp314-{abi}-{platform}.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                f"yosoi-{version}.dist-info/METADATA",
                f"Name: yosoi\nVersion: {version}\n",
            )
            archive.writestr(
                f"yosoi-{version}.dist-info/WHEEL",
                f"Wheel-Version: 1.0\nTag: cp314-{abi}-{platform}\n",
            )
        with tarfile.open(directory / f"yosoi-{version}.tar.gz", "w:gz") as archive:
            metadata = f"Name: yosoi\nVersion: {version}\n".encode()
            info = tarfile.TarInfo(f"yosoi-{version}/PKG-INFO")
            info.size = len(metadata)
            archive.addfile(info, io.BytesIO(metadata))
        return wheel

    def release(self):
        return {
            "version": "0.1.0",
            "wheels": {
                "include": [
                    {
                        "python_tag": "cp314",
                        "abi": "cp314t",
                        "wheel_platform": "win_amd64",
                    }
                ]
            },
        }

    def test_exact_matrix_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            release.verify_wheels(root, self.release())

    def test_rc_matrix_accepts_pep440_and_rejects_final_artifacts(self):
        candidate = self.release() | {"version": "0.1.0-rc.1"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, version="0.1.0rc1")
            release.verify_wheels(root, candidate)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, version="0.1.0")
            with self.assertRaisesRegex(ValueError, "identity"):
                release.verify_wheels(root, candidate)

    def test_missing_or_wrong_platform_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, platform="linux_x86_64")
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                release.verify_wheels(root, self.release())

    def test_wrong_free_threaded_abi_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, abi="cp314")
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                release.verify_wheels(root, self.release())

    def test_wrong_version_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, version="0.2.0")
            with self.assertRaisesRegex(ValueError, "identity"):
                release.verify_wheels(root, self.release())

    def test_duplicate_wheels_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = self.fixture(root)
            (root / "duplicate.whl").write_bytes(wheel.read_bytes())
            with self.assertRaisesRegex(ValueError, "duplicate"):
                release.verify_wheels(root, self.release())

    def test_missing_sdist_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            next(root.glob("*.tar.gz")).unlink()
            with self.assertRaisesRegex(ValueError, "source distribution"):
                release.verify_wheels(root, self.release())

    def test_matching_existing_pypi_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = self.fixture(root)
            existing = {
                "urls": [
                    {
                        "filename": wheel.name,
                        "digests": {"sha256": release.sha256(wheel)},
                    }
                ]
            }
            with patch.object(release, "json_url", return_value=existing):
                release.pypi_pending(root, "0.1.0", root / "pending")
            self.assertEqual(
                [f.name for f in (root / "pending").iterdir()], ["yosoi-0.1.0.tar.gz"]
            )

    def test_different_existing_pypi_bytes_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = self.fixture(root)
            existing = {
                "urls": [{"filename": wheel.name, "digests": {"sha256": "0" * 64}}]
            }
            with (
                patch.object(release, "json_url", return_value=existing),
                self.assertRaisesRegex(ValueError, "different bytes"),
            ):
                release.pypi_pending(root, "0.1.0", root / "pending")


class GithubRetryTests(unittest.TestCase):
    def test_partial_draft_retry_uploads_only_missing_assets_then_finalizes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.tar.gz").write_bytes(b"existing")
            (root / "missing.tar.gz").write_bytes(b"missing")

            def download(*args):
                if args[:3] == ("gh", "release", "download"):
                    (Path(args[-1]) / "existing.tar.gz").write_bytes(b"existing")

            with (
                patch.dict(
                    "os.environ",
                    GITHUB_REPOSITORY="owner/repo",
                    GH_TOKEN="fixture-token",
                ),
                patch.object(publish, "plan", return_value={"version": "0.1.0"}),
                patch.object(
                    publish,
                    "json_url",
                    return_value={
                        "draft": True,
                        "assets": [{"name": "existing.tar.gz"}],
                    },
                ),
                patch.object(publish, "run", side_effect=download) as run,
            ):
                publish.publish_github("v0.1.0", root, True)
            commands = [call.args for call in run.call_args_list]
            self.assertEqual(
                [command[2] for command in commands], ["download", "upload", "edit"]
            )
            self.assertEqual(commands[1][-1], str(root / "missing.tar.gz"))

    def test_unexpected_draft_assets_fail_before_upload_or_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "expected.tar.gz").write_bytes(b"expected")

            def download(*args):
                if args[:3] == ("gh", "release", "download"):
                    (Path(args[-1]) / "stale.tar.gz").write_bytes(b"stale")

            with (
                patch.dict(
                    "os.environ",
                    GITHUB_REPOSITORY="owner/repo",
                    GH_TOKEN="fixture-token",
                ),
                patch.object(publish, "plan", return_value={"version": "0.1.0"}),
                patch.object(
                    publish,
                    "json_url",
                    return_value={"draft": True, "assets": [{"name": "stale.tar.gz"}]},
                ),
                patch.object(publish, "run", side_effect=download) as run,
                self.assertRaisesRegex(
                    ValueError, "Unexpected existing release assets"
                ),
            ):
                publish.publish_github("v0.1.0", root, True)
            self.assertEqual(len(run.call_args_list), 1)
            self.assertEqual(run.call_args.args[:3], ("gh", "release", "download"))

    def test_release_lookup_sends_the_token_to_github(self):
        with patch.object(release.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = (
                b'{"draft": true}'
            )
            self.assertEqual(
                release.json_url(
                    "https://api.github.com/repos/owner/repo/releases/tags/v0.1.0",
                    token="fixture-token",
                ),
                {"draft": True},
            )
            request = open_url.call_args.args[0]
            self.assertEqual(
                request.get_header("Authorization"), "Bearer fixture-token"
            )

    def test_existing_draft_is_queried_with_authentication_and_not_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.dict(
                    "os.environ",
                    GITHUB_REPOSITORY="owner/repo",
                    GH_TOKEN="fixture-token",
                ),
                patch.object(publish, "plan", return_value={"version": "0.1.0"}),
                patch.object(
                    publish, "json_url", return_value={"draft": True, "assets": []}
                ) as lookup,
                patch.object(publish, "run") as run,
            ):
                publish.publish_github("v0.1.0", root, False)
                lookup.assert_called_once_with(
                    "https://api.github.com/repos/owner/repo/releases/tags/v0.1.0",
                    token="fixture-token",
                )
                run.assert_not_called()

    def test_missing_github_token_fails_before_release_writes(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(publish, "plan", return_value={"version": "0.1.0"}),
            patch.object(publish, "json_url") as lookup,
            patch.object(publish, "run") as run,
            self.assertRaisesRegex(ValueError, "GH_TOKEN"),
        ):
            publish.publish_github("v0.1.0", Path("unused"), False)
        lookup.assert_not_called()
        run.assert_not_called()

    def test_published_release_cannot_gain_new_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "new.tar.gz").write_bytes(b"artifact")
            with (
                patch.dict(
                    "os.environ",
                    GITHUB_REPOSITORY="owner/repo",
                    GH_TOKEN="fixture-token",
                ),
                patch.object(publish, "plan", return_value={"version": "0.1.0"}),
                patch.object(
                    publish, "json_url", return_value={"draft": False, "assets": []}
                ),
                patch.object(publish, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "already published"):
                    publish.publish_github("v0.1.0", root, False)
                run.assert_not_called()


class ArchiveTests(unittest.TestCase):
    def test_archive_bytes_ignore_source_mtime_and_output_name(self):
        import os

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "yosoi.exe"
            binary.write_bytes(b"compiled executable")
            first, second = root / "first.tar.gz", root / "second.tar.gz"
            cli_archive(binary, first)
            os.utime(binary, (100, 100))
            cli_archive(binary, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as archive:
                entry = archive.getmembers()[0]
                self.assertEqual(entry.name, "yosoi.exe")
                self.assertEqual(entry.mode, 0o755)
                self.assertEqual(entry.mtime, 0)
                self.assertEqual(archive.extractfile(entry).read(), binary.read_bytes())

    def test_existing_archive_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "yosoi"
            binary.write_bytes(b"binary")
            output = root / "cli.tar.gz"
            output.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                cli_archive(binary, output)
            self.assertEqual(output.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
