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
from types import SimpleNamespace
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY))
import publish  # noqa: E402
import release  # noqa: E402
from archive import cli_archive  # noqa: E402


class IdentityTests(unittest.TestCase):
    def test_interpreter_resolution_installs_first_and_propagates_failures(self):
        workflow = (
            DIRECTORY.parents[1] / ".github/workflows/release-cd.yml"
        ).read_text()
        sections = workflow.split(
            "      - name: Resolve the managed interpreter path\n"
        )[1:]
        self.assertEqual(len(sections), 2)
        for section in sections:
            script = textwrap.dedent(
                section.split("\n      - ", 1)[0].split("        run: |\n", 1)[1]
            )
            for fail in ("", "install", "find"):
                with (
                    self.subTest(fail=fail),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    executable = root / "uv"
                    executable.write_text("""#!/usr/bin/env bash
set -e
if [ "$2" = install ]; then
  test "$FAIL_AT" != install
  touch "$MARKER"
elif [ "$2" = find ]; then
  test -f "$MARKER"
  test "$FAIL_AT" != find
  echo '/managed Python/3.15t/bin/python'
else
  exit 2
fi
""")
                    executable.chmod(0o755)
                    output = root / "environment"
                    result = subprocess.run(
                        ["bash", "-ec", script],
                        env=dict(
                            os.environ,
                            PATH=f"{root}:/usr/bin:/bin",
                            SELECTED_PYTHON="3.15.0t",
                            FAIL_AT=fail,
                            MARKER=str(root / "installed"),
                            GITHUB_ENV=str(output),
                        ),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 1 if fail else 0, result.stderr)
                    if fail:
                        self.assertFalse(output.exists())
                    else:
                        self.assertEqual(
                            output.read_text(),
                            "RELEASE_PYTHON=/managed Python/3.15t/bin/python\n",
                        )

    def test_batch_interpreters_preserve_paths_and_fail_on_resolution_errors(self):
        workflow = (
            DIRECTORY.parents[1] / ".github/workflows/release-cd.yml"
        ).read_text()
        section = workflow.split(
            "      - name: Resolve managed interpreters for the wheel batch\n", 1
        )[1]
        script = textwrap.dedent(
            section.split("\n      - ", 1)[0].split("        run: |\n", 1)[1]
        )
        for fail in ("", "3.12", "3.14t", "3.15.0t"):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                executable = root / "uv"
                executable.write_text("""#!/usr/bin/env bash
set -e
if [ "$2" = install ]; then
  touch "$MARKER-$3"
elif [ "$2" = find ]; then
  test -f "$MARKER-$4"
  test "$FAIL_VERSION" != "$4"
  echo "/managed Python/$4/bin/python"
else
  exit 2
fi
""")
                executable.chmod(0o755)
                output = root / "environment"
                result = subprocess.run(
                    ["bash", "-ec", script],
                    capture_output=True,
                    text=True,
                    env=dict(
                        os.environ,
                        PATH=f"{root}:/usr/bin:/bin",
                        BUILD_ABI3="3.12",
                        BUILD_CP314T="3.14t",
                        BUILD_ABI3T="3.15.0t",
                        FAIL_VERSION=fail,
                        MARKER=str(root / "installed"),
                        GITHUB_ENV=str(output),
                    ),
                )
                self.assertEqual(result.returncode, 1 if fail else 0, result.stderr)
                if not fail:
                    self.assertEqual(
                        output.read_text().splitlines(),
                        [
                            "RELEASE_PYTHON_ABI3=/managed Python/3.12/bin/python",
                            "RELEASE_PYTHON=/managed Python/3.12/bin/python",
                            "RELEASE_PYTHON_CP314T=/managed Python/3.14t/bin/python",
                            "RELEASE_PYTHON_ABI3T=/managed Python/3.15.0t/bin/python",
                        ],
                    )

    def test_actual_publication_conditions_keep_final_registry_gates(self):
        workflow = (
            DIRECTORY.parents[1] / ".github/workflows/release-cd.yml"
        ).read_text()
        github = workflow.split("\n  github:\n", 1)[1].split("    runs-on:", 1)[0]
        github_if = " ".join(github.split("    if: >-\n", 1)[1].split())
        registry = workflow.split("\n  publication-ready:\n", 1)[1].split(
            "    runs-on:", 1
        )[0]
        registry_if = registry.split("    if: ", 1)[1].strip()
        for (
            candidate,
            verify,
            installed,
            event,
            publish_requested,
            github_expected,
            registry_expected,
        ) in (
            (True, "success", "skipped", "push", False, False, False),
            (True, "success", "success", "push", False, True, False),
            (True, "failure", "skipped", "push", False, False, False),
            (False, "success", "failure", "push", False, False, True),
            (False, "success", "success", "push", False, True, True),
            (True, "success", "skipped", "workflow_dispatch", False, False, False),
            (True, "success", "success", "workflow_dispatch", True, True, False),
        ):
            with self.subTest(
                candidate=candidate,
                verify=verify,
                installed=installed,
                event=event,
                publish=publish_requested,
            ):
                context = dict(
                    needs=SimpleNamespace(
                        identity=SimpleNamespace(
                            result="success",
                            outputs=SimpleNamespace(candidate=str(candidate).lower()),
                        ),
                        verify=SimpleNamespace(result=verify),
                        installed=SimpleNamespace(result=installed),
                        container_publish=SimpleNamespace(result="success"),
                    ),
                    github=SimpleNamespace(event_name=event),
                    inputs=SimpleNamespace(publish=publish_requested),
                )
                for condition, expected in (
                    (github_if, github_expected),
                    (registry_if, registry_expected),
                ):
                    expression = (
                        condition.replace("always()", "True")
                        .replace("!cancelled()", "True")
                        .replace("&&", " and ")
                        .replace("||", " or ")
                    )
                    self.assertEqual(
                        eval(expression, {"__builtins__": {}}, context), expected
                    )
                    if condition == github_if:
                        context["needs"].container_publish.result = "failure"
                        self.assertFalse(
                            eval(expression, {"__builtins__": {}}, context)
                        )
                        context["needs"].container_publish.result = "success"

    def test_python_rc_publication_is_independent_and_final_publication_keeps_rust_gate(
        self,
    ):
        workflow = (
            DIRECTORY.parents[1] / ".github/workflows/release-cd.yml"
        ).read_text()
        conditions = {}
        for job in ("pypi", "container_publish"):
            section = workflow.split(f"\n  {job}:\n", 1)[1].split("    runs-on:", 1)[0]
            conditions[job] = " ".join(section.split("    if: >-\n", 1)[1].split())
        for candidate in (False, True):
            for requested in (False, True):
                for canceled in (False, True):
                    for gate in (
                        "identity",
                        "verify",
                        "installed",
                        "publication_ready",
                        "crates",
                    ):
                        for result in ("success", "failure", "skipped", "cancelled"):
                            with self.subTest(
                                candidate=candidate,
                                requested=requested,
                                canceled=canceled,
                                gate=gate,
                                result=result,
                            ):
                                states = {
                                    name: "success"
                                    for name in (
                                        "identity",
                                        "verify",
                                        "installed",
                                        "publication_ready",
                                        "crates",
                                    )
                                }
                                states[gate] = result
                                context = dict(
                                    needs=SimpleNamespace(
                                        **{
                                            name: SimpleNamespace(result=value)
                                            for name, value in states.items()
                                        }
                                    ),
                                    github=SimpleNamespace(
                                        event_name="workflow_dispatch"
                                    ),
                                    inputs=SimpleNamespace(publish=requested),
                                )
                                context["needs"].identity.outputs = SimpleNamespace(
                                    candidate=str(candidate).lower()
                                )
                                common = (
                                    requested
                                    and not canceled
                                    and states["identity"] == "success"
                                    and states["verify"] == "success"
                                )
                                expected = {
                                    "pypi": common
                                    and (
                                        candidate
                                        or states["publication_ready"] == "success"
                                    ),
                                    "container_publish": common
                                    and states["installed"] == "success"
                                    and (candidate or states["crates"] == "success"),
                                }
                                for job, condition in conditions.items():
                                    expression = (
                                        condition.replace("always()", "True")
                                        .replace("!cancelled()", str(not canceled))
                                        .replace(
                                            "publication-ready", "publication_ready"
                                        )
                                        .replace("&&", " and ")
                                        .replace("||", " or ")
                                    )
                                    self.assertEqual(
                                        eval(expression, {"__builtins__": {}}, context),
                                        expected[job],
                                    )

    def test_registry_install_gate_overrides_skipped_ancestors_but_requires_pypi(self):
        workflow = (
            DIRECTORY.parents[1] / ".github/workflows/release-cd.yml"
        ).read_text()
        section = workflow.split("\n  installed:\n", 1)[1].split("    name:", 1)[0]
        condition = " ".join(section.split("    if: >-\n", 1)[1].split())
        self.assertIn("always()", condition)
        self.assertIn("!cancelled()", condition)
        for identity in ("success", "failure", "skipped", "cancelled"):
            for pypi in ("success", "failure", "skipped", "cancelled"):
                for cancelled in (False, True):
                    with self.subTest(
                        identity=identity, pypi=pypi, cancelled=cancelled
                    ):
                        # The Rust-only ancestors are intentionally skipped for RCs.
                        context = dict(
                            needs=SimpleNamespace(
                                identity=SimpleNamespace(result=identity),
                                pypi=SimpleNamespace(result=pypi),
                                crates=SimpleNamespace(result="skipped"),
                            ),
                        )
                        expression = (
                            condition.replace("always()", "True")
                            .replace("!cancelled()", str(not cancelled))
                            .replace("&&", " and ")
                        )
                        self.assertEqual(
                            eval(expression, {"__builtins__": {}}, context),
                            not cancelled
                            and identity == "success"
                            and pypi == "success",
                        )

    def test_docs_version_guard_accepts_rc_and_rejects_invalid_versions(self):
        workflow = DIRECTORY.parents[1] / ".github/workflows/docs-publish.yml"
        line = next(
            line.strip()
            for line in workflow.read_text().splitlines()
            if "node --input-type=module -e" in line
        )
        script = line.split(" -e '", 1)[1].removesuffix("'")
        for version, expected in (
            ("0.1.0-rc.2", 0),
            ("0.1.0", 0),
            ("0.1.0-rc.0", 1),
            ("0.01.0", 1),
            ("0.100001.0", 1),
        ):
            with (
                self.subTest(version=version),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "environment"
                result = subprocess.run(
                    ["node", "--input-type=module", "-e", script],
                    env=dict(
                        os.environ,
                        SELECTED_VERSION=version,
                        SELECTED_SOURCE="",
                        BUNDLE_ARTIFACT="",
                        GITHUB_OUTPUT=str(output),
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected == 0:
                    publish = str("-rc." not in version).lower()
                    self.assertEqual(
                        output.read_text(), f"version={version}\npublish={publish}\n"
                    )
                else:
                    self.assertFalse(output.exists())

    def test_rc_docs_require_explicit_identity_and_verified_release_bundle(self):
        workflow = DIRECTORY.parents[1] / ".github/workflows/docs-publish.yml"
        line = next(
            line.strip()
            for line in workflow.read_text().splitlines()
            if "node --input-type=module -e" in line
        )
        script = line.split(" -e '", 1)[1].removesuffix("'")
        for version, source, bundle, tag, allowed, expected in (
            ("0.1.0-rc.2", "a" * 40, "release-docs", "", True, 0),
            ("0.1.0-rc.2", "", "release-docs", "", False, 0),
            ("", "a" * 40, "release-docs", "", False, 0),
            ("0.1.0-rc.2", "a" * 40, "unverified-docs", "", False, 0),
            ("", "", "", "v0.1.0-rc.2", True, 0),
            ("", "", "", "v0.1.0-rc.3", False, 1),
        ):
            with (
                self.subTest(version=version, source=source, bundle=bundle),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / "Cargo.toml").write_text(
                    '[workspace.package]\nversion = "0.1.0-rc.2"\n'
                )
                output = root / "output"
                result = subprocess.run(
                    ["node", "--input-type=module", "-e", script],
                    cwd=root,
                    env=dict(
                        os.environ,
                        SELECTED_VERSION=version,
                        SELECTED_SOURCE=source,
                        BUNDLE_ARTIFACT=bundle,
                        RELEASE_TAG=tag,
                        GITHUB_OUTPUT=str(output),
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertFalse(output.exists())
                else:
                    self.assertIn(
                        f"publish={str(allowed).lower()}\n", output.read_text()
                    )

    def test_docs_replay_rejects_drafts_missing_releases_and_invalid_tags(self):
        workflow = DIRECTORY.parents[1] / ".github/workflows/docs-publish.yml"
        section = workflow.read_text().split(
            "      - name: Require a published release for docs replay\n", 1
        )[1]
        script = textwrap.dedent(
            section.split("\n      - ", 1)[0].split("        run: |\n", 1)[1]
        )
        for tag, published, api_exit, allowed in (
            ("v0.1.0-rc.4", "true", 0, True),
            ("v0.1.0", "true", 0, True),
            ("v0.1.0-rc.4", "false", 0, False),
            ("v0.1.0-rc.4", "", 1, False),
            ("main", "true", 0, False),
            ("v0.1.0-rc.0", "true", 0, False),
        ):
            with self.subTest(tag=tag, published=published, api_exit=api_exit):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    gh = root / "gh"
                    gh.write_text(
                        '#!/bin/sh\nprintf "%s\\n" "$PUBLISHED"\nexit "$API_EXIT"\n'
                    )
                    gh.chmod(0o755)
                    result = subprocess.run(
                        ["bash", "-ec", script],
                        env=dict(
                            os.environ,
                            PATH=f"{root}:/usr/bin:/bin",
                            RELEASE_TAG=tag,
                            PUBLISHED=published,
                            API_EXIT=str(api_exit),
                            GITHUB_REPOSITORY="example/repo",
                        ),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, allowed, result.stderr)

    def test_actual_sdist_extraction_avoids_python_directory_collision(self):
        workflow = DIRECTORY.parents[1] / ".github/workflows/release-cd.yml"
        section = (
            workflow.read_text()
            .split("      - name: Extract the exact source distribution\n", 1)[1]
            .split("\n      - ", 1)[0]
        )
        script = textwrap.dedent(section.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "python").mkdir()
            (root / "source-distribution").mkdir()
            data = b"candidate source"
            with tarfile.open(
                root / "source-distribution/yosoi.tar.gz", "w:gz"
            ) as archive:
                entry = tarfile.TarInfo("yosoi/test.txt")
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            result = subprocess.run(
                ["bash", "-ec", script],
                cwd=root,
                env=dict(os.environ, RELEASE_PYTHON=sys.executable),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "sdist-source/test.txt").read_bytes(), data)

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
        self.assertEqual([a["python"] for a in new[-2:]], ["3.15.0", "3.15.0t"])
        self.assertEqual(new[-1]["linux_python"], "/opt/python/cp315-cp315t/bin/python")

    def test_unreviewed_python_range_fails(self):
        for requirement in (">=3.12", ">=3.12,<3.17", ">=3.14,<3.13"):
            with self.subTest(requirement=requirement), self.assertRaises(ValueError):
                release.python_abis(requirement)

    def test_native_platforms_are_distinct(self):
        self.assertEqual(len(release.PLATFORMS), 5)
        self.assertEqual(len({p[1] for p in release.PLATFORMS}), 5)
        self.assertNotIn("aarch64-pc-windows-msvc", {p[1] for p in release.PLATFORMS})

    def test_stable_builds_cover_every_interpreter_without_recompilation(self):
        abis = release.python_abis(">=3.12,<3.16")
        builds = release.wheel_builds(abis)
        self.assertEqual(
            [(row["python_tag"], row["abi"]) for row in builds],
            [("cp312", "abi3"), ("cp314", "cp314t"), ("cp315", "abi3.abi3t")],
        )
        self.assertEqual(builds[0]["features"], "browser,pyo3/abi3-py312")
        self.assertEqual(builds[-1]["features"], "browser,pyo3/abi3t-py315")
        for row in abis:
            self.assertEqual(
                len([build for build in builds if build["abi"] == row["wheel_abi"]]),
                1,
            )
        self.assertEqual(abis[3]["wheel_abi"], "cp314t")
        self.assertEqual(abis[-1]["wheel_abi"], "abi3.abi3t")

    def test_real_release_matrix_halves_builds_and_keeps_all_tests(self):
        root = DIRECTORY.parents[1]
        version = release.read_toml(root / "Cargo.toml")["workspace"]["package"][
            "version"
        ]
        planned = release.plan(root, f"v{version}")
        self.assertEqual(len(planned["wheels"]["include"]), 15)
        self.assertEqual(len(planned["wheel_tests"]["include"]), 30)
        self.assertEqual(len(planned["wheel_platforms"]["include"]), 5)
        for batch in planned["wheel_platforms"]["include"]:
            self.assertEqual(batch["abi3_features"], "browser,pyo3/abi3-py312")
            self.assertEqual(batch["cp314t_features"], "browser")
            self.assertEqual(batch["abi3t_features"], "browser,pyo3/abi3t-py315")
            self.assertEqual(batch["cp314t_python"], "3.14t")
        for row in planned["wheel_tests"]["include"]:
            matching = [
                build
                for build in planned["wheels"]["include"]
                if build["platform"] == row["platform"]
                and build["abi"] == row["wheel_abi"]
            ]
            self.assertEqual(len(matching), 1)

    def test_python_ci_uses_shared_matrix_without_losing_interpreters(self):
        import json

        root = DIRECTORY.parents[1]
        workflow = (root / ".github/workflows/python-ci.yml").read_text()
        script = textwrap.dedent(
            workflow.split("python - <<'PY_MATRIX'\n", 1)[1].split(
                "          PY_MATRIX", 1
            )[0]
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            subprocess.run(
                [sys.executable, "-c", script],
                cwd=root,
                env=dict(os.environ, GITHUB_OUTPUT=str(output)),
                check=True,
            )
            matrices = dict(
                line.split("=", 1) for line in output.read_text().splitlines()
            )
            builds = json.loads(matrices["builds"])["include"]
            tests = json.loads(matrices["tests"])["include"]
        self.assertEqual(len(builds), 3)
        self.assertEqual(
            [row["python"] for row in tests],
            ["3.12", "3.13", "3.14", "3.14t", "3.15.0", "3.15.0t"],
        )
        for row in tests:
            self.assertEqual(
                len([build for build in builds if build["abi"] == row["wheel_abi"]]), 1
            )


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

    def test_reviewed_browser_forks_publish_in_order_with_independent_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            application = root / "crates/application/Cargo.toml"
            application.write_text(
                application.read_text()
                + 'controller = { package = "yosoi-chromiumoxide", '
                'version = "=0.9.1-yosoi.1", '
                'path = "../../vendor/chromiumoxide" }\n'
            )
            for path, name, version in (
                ("vendor/chromiumoxide", "yosoi-chromiumoxide", "0.9.1-yosoi.1"),
                (
                    "vendor/chromiumoxide_cdp",
                    "yosoi-chromiumoxide-cdp",
                    "0.10.0-yosoi.m153.1",
                ),
            ):
                folder = root / path
                folder.mkdir(parents=True)
                text = f'[package]\nname = "{name}"\nversion = "{version}"\n'
                if name == "yosoi-chromiumoxide":
                    text += (
                        "[dependencies]\nschema = { "
                        'package = "yosoi-chromiumoxide-cdp", '
                        'version = "=0.10.0-yosoi.m153.1", '
                        'path = "../chromiumoxide_cdp" }\n'
                    )
                (folder / "Cargo.toml").write_text(text)
            publication = release.publication_plan(root)
            self.assertEqual(publication["blockers"], [])
            order = publication["crates"]
            self.assertLess(
                order.index("yosoi-chromiumoxide-cdp"),
                order.index("yosoi-chromiumoxide"),
            )
            self.assertLess(
                order.index("yosoi-chromiumoxide"), order.index("application")
            )
            manifest, document = release.registry_manifests(root)["yosoi-chromiumoxide"]
            self.assertEqual(release.package_version(root, document), "0.9.1-yosoi.1")
            document["package"]["name"] = "chromiumoxide"
            manifest.write_text(
                '[package]\nname = "chromiumoxide"\nversion = "0.9.1"\n'
            )
            self.assertIn(
                "application depends on vendored chromiumoxide; "
                "approve its registry distribution first",
                release.publication_plan(root)["blockers"],
            )

    def test_crate_publisher_uses_fork_version_and_manifest_in_shared_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            folder = root / "vendor/chromiumoxide"
            folder.mkdir(parents=True)
            (folder / "Cargo.toml").write_text(
                '[package]\nname = "yosoi-chromiumoxide"\nversion = "0.9.1-yosoi.1"\n'
            )
            archive = root / "target/package/yosoi-chromiumoxide-0.9.1-yosoi.1.crate"
            calls = []
            uploaded = False

            def command(*args):
                nonlocal uploaded
                calls.append(args)
                if args[1] == "package":
                    archive.parent.mkdir(parents=True)
                    archive.write_bytes(b"verified fork archive")
                elif args[1] == "publish":
                    uploaded = True

            def registry(url):
                self.assertTrue(url.endswith("/yosoi-chromiumoxide/0.9.1-yosoi.1"))
                return (
                    {"version": {"checksum": release.sha256(archive)}}
                    if uploaded
                    else None
                )

            with (
                patch.object(publish.Path, "cwd", return_value=root),
                patch.object(
                    publish,
                    "plan",
                    return_value={
                        "version": "0.1.0",
                        "publication": {
                            "crates": ["yosoi-chromiumoxide"],
                            "blockers": [],
                        },
                    },
                ),
                patch.object(publish, "run", side_effect=command),
                patch.object(publish, "json_url", side_effect=registry),
                patch.dict(os.environ, {"CARGO_REGISTRY_TOKEN": "fixture"}),
            ):
                publish.publish_crates("v0.1.0")
            self.assertEqual([call[1] for call in calls], ["package", "publish"])
            for call in calls:
                self.assertIn(str(folder / "Cargo.toml"), call)
                self.assertIn(str(root / "target"), call)


class ArtifactTests(unittest.TestCase):
    def fixture(
        self,
        directory,
        version="0.1.0",
        abi="cp314t",
        platform="win_amd64",
        python_tag="cp314",
        license_file="LICENSE",
        include_license=True,
    ):
        wheel = directory / f"yosoi-{version}-{python_tag}-{abi}-{platform}.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                f"yosoi-{version}.dist-info/METADATA",
                f"Name: yosoi\nVersion: {version}\n",
            )
            archive.writestr(
                f"yosoi-{version}.dist-info/WHEEL",
                "Wheel-Version: 1.0\n"
                + "".join(
                    f"Tag: {python_tag}-{tag}-{platform}\n" for tag in abi.split(".")
                ),
            )
        with tarfile.open(directory / f"yosoi-{version}.tar.gz", "w:gz") as archive:
            metadata = (
                f"Name: yosoi\nVersion: {version}\nLicense-File: {license_file}\n"
            ).encode()
            info = tarfile.TarInfo(f"yosoi-{version}/PKG-INFO")
            info.size = len(metadata)
            archive.addfile(info, io.BytesIO(metadata))
            if include_license:
                content = b"Apache License, Version 2.0\n"
                info = tarfile.TarInfo(f"yosoi-{version}/{license_file}")
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
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

    def test_sdist_declared_license_must_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, include_license=False)
            with self.assertRaisesRegex(ValueError, "missing license file: LICENSE"):
                release.verify_wheels(root, self.release())

    def test_sdist_license_cannot_escape_archive_root(self):
        for path in ("../LICENSE", "/LICENSE"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root, license_file=path, include_license=False)
                with self.assertRaisesRegex(ValueError, "Invalid.*license path"):
                    release.verify_wheels(root, self.release())

    def test_stable_wheel_tags_are_verified_exactly(self):
        for python_tag, abi in (("cp312", "abi3"), ("cp315", "abi3.abi3t")):
            with self.subTest(abi=abi), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root, python_tag=python_tag, abi=abi)
                planned = self.release()
                planned["wheels"]["include"][0].update(python_tag=python_tag, abi=abi)
                release.verify_wheels(root, planned)
                planned["wheels"]["include"][0]["abi"] = "cp315t"
                with self.assertRaisesRegex(ValueError, "Unexpected"):
                    release.verify_wheels(root, planned)

    def test_unrelated_multiple_abis_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = self.fixture(root, abi="cp314t.abi3")
            with self.assertRaisesRegex(ValueError, "Unexpected wheel ABI"):
                release.wheel_identity(wheel, "0.1.0")

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
    def test_candidate_and_final_release_flags(self):
        for version, prerelease, latest in (
            ("0.1.0-rc.7", "true", "false"),
            ("0.1.0", "false", "true"),
        ):
            with (
                self.subTest(version=version),
                tempfile.TemporaryDirectory() as directory,
            ):
                with (
                    patch.dict(
                        "os.environ",
                        GITHUB_REPOSITORY="owner/repo",
                        GH_TOKEN="fixture-token",
                    ),
                    patch.object(publish, "plan", return_value={"version": version}),
                    patch.object(
                        publish, "json_url", return_value={"draft": True, "assets": []}
                    ),
                    patch.object(publish, "run") as run,
                ):
                    publish.publish_github(f"v{version}", Path(directory), True)
                self.assertEqual(
                    run.call_args.args,
                    (
                        "gh",
                        "release",
                        "edit",
                        f"v{version}",
                        "--draft=false",
                        f"--prerelease={prerelease}",
                        f"--latest={latest}",
                    ),
                )

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
