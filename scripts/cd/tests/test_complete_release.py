"""Keep metadata repair narrower than a new SDK release."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import complete_release  # noqa: E402
import release  # noqa: E402


class CompletionTests(unittest.TestCase):
    def test_readonly_completion_cannot_publish(self):
        workflow = (
            Path(__file__).resolve().parents[3] / ".github/workflows/release-cd.yml"
        ).read_text()
        publish_steps = workflow.split(
            "      - name: Publish verified Rust packages", 1
        )[1].split("\n  complete-docs:", 1)[0]
        self.assertTrue(
            publish_steps.startswith(
                " and record their packaging source\n        if: inputs.publish"
            )
        )
        for step in publish_steps.split("\n      - ")[1:]:
            self.assertIn("\n        if: inputs.publish", step)
        docs = workflow.split("\n  complete-docs:\n", 1)[1]
        self.assertIn(
            "inputs.publish && needs.complete-verified.result == 'success'", docs
        )

    def test_only_missing_descriptions_can_be_added(self):
        before = {
            "package": {"name": "test-support", "version": "0.1.0"},
            "dependencies": {"serde": "1"},
            "features": {"default": []},
        }
        after = copy.deepcopy(before)
        after["package"]["description"] = "Typed documents for Yosoi."
        self.assertTrue(complete_release.description_only(before, after))
        for key, value in (
            ("version", "0.1.1"),
            ("name", "other"),
            ("description", " "),
            ("license", "MIT"),
        ):
            altered = copy.deepcopy(after)
            altered["package"][key] = value
            self.assertFalse(complete_release.description_only(before, altered))
        for key in ("dependencies", "features"):
            altered = copy.deepcopy(after)
            altered[key]["new"] = []
            self.assertFalse(complete_release.description_only(before, altered))
        original = copy.deepcopy(before)
        original["package"]["description"] = "Existing description"
        self.assertFalse(complete_release.description_only(original, after))

    def test_sdk_code_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(
                    complete_release,
                    "command",
                    side_effect=["", "crates/yosoi/src/lib.rs"],
                ),
                patch.object(complete_release, "registry_manifests", return_value={}),
                self.assertRaisesRegex(ValueError, "SDK input changed"),
            ):
                complete_release.verify_source(root, "a" * 40)

    def test_every_original_gate_must_have_passed(self):
        source = "a" * 40
        run = {
            "head_sha": source,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "path": ".github/workflows/release-cd.yml",
            "status": "completed",
        }
        planned = {
            "platforms": {"include": [{"platform": "linux-x86_64"}]},
            "wheel_tests": {
                "include": [{"platform": "linux-x86_64", "python": "3.15.0t"}]
            },
        }
        names = (
            "identity",
            "source-ci",
            "verify",
            "pypi",
            "Rust artifacts (linux-x86_64)",
            "Build wheels (linux-x86_64)",
            "Installed wheel (linux-x86_64, 3.15.0t)",
            "Published install (linux-x86_64, 3.15.0t)",
        )
        jobs = [
            {
                "name": name,
                "status": "completed",
                "conclusion": "success",
                "databaseId": n,
            }
            for n, name in enumerate(names)
        ]
        complete_release.verify_build(run, jobs, source, planned)
        for index in range(len(jobs)):
            for result in ("failure", "cancelled", "skipped"):
                altered = copy.deepcopy(jobs)
                altered[index]["conclusion"] = result
                with (
                    self.subTest(name=jobs[index]["name"], result=result),
                    self.assertRaises(ValueError),
                ):
                    complete_release.verify_build(run, altered, source, planned)
        for key, value in (
            ("head_sha", "b" * 40),
            ("head_branch", "other"),
            ("event", "pull_request"),
            ("status", "in_progress"),
            ("path", ".github/workflows/other.yml"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                complete_release.verify_build(run | {key: value}, jobs, source, planned)
        with self.assertRaises(ValueError):
            complete_release.verify_build(run, jobs[:-1], source, planned)

    def test_metadata_preflight_checks_description_and_inherited_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text(
                '[workspace.package]\nlicense="Apache-2.0"\n'
            )
            document = {
                "package": {"name": "test-support", "license": {"workspace": True}}
            }
            with (
                patch.object(
                    release,
                    "registry_manifests",
                    return_value={"test-support": (root / "Cargo.toml", document)},
                ),
                patch.object(
                    release,
                    "publication_plan",
                    return_value={"crates": ["test-support"]},
                ),
            ):
                with self.assertRaisesRegex(ValueError, "description"):
                    release.validate_registry_metadata(root)
                document["package"]["description"] = "Release metadata fixture."
                release.validate_registry_metadata(root)
                (root / "Cargo.toml").write_text("[workspace.package]\n")
                with self.assertRaisesRegex(ValueError, "license"):
                    release.validate_registry_metadata(root)

    def test_rust_receipt_records_the_registry_checksum_for_reused_crates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "yosoi-chromiumoxide"
            version = "0.9.1-yosoi.1"
            registry_checksum = "a" * 64
            proof = {"tag": "v0.1.1", "verified_run": 1}
            package = {"package": {"name": name, "version": version}}
            with (
                patch.object(
                    complete_release,
                    "plan",
                    return_value={"publication": {"crates": [name]}},
                ),
                patch.object(
                    complete_release,
                    "registry_manifests",
                    return_value={name: (root / "Cargo.toml", package)},
                ),
                patch.object(
                    complete_release,
                    "json_url",
                    return_value={"version": {"checksum": registry_checksum}},
                ),
                patch.object(
                    complete_release,
                    "verify_existing_crate",
                    return_value=registry_checksum,
                ) as verify,
            ):
                receipt = complete_release.receipts(root, proof)

            self.assertEqual(
                receipt["packages"],
                [{"name": name, "version": version, "sha256": registry_checksum}],
            )
            verify.assert_called_once_with(
                name,
                version,
                root / "target/package" / f"{name}-{version}.crate",
                {"checksum": registry_checksum},
            )


if __name__ == "__main__":
    unittest.main()
