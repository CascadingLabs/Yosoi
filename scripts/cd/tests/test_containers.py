"""Publication must preserve smoke-tested bytes and immutable release tags."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import containers  # noqa: E402


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for mode, arch in containers.ROWS:
            (self.directory / f"{mode}-{arch}.json").write_text(
                json.dumps(
                    dict(
                        image=f"local:{mode}-{arch}",
                        image_id="sha256:tested",
                        mode=mode,
                    )
                )
            )
            (self.directory / f"{mode}-{arch}.tar").touch()

    def publish(self):
        containers.publish(
            self.directory, "0.1.0-rc.3", "ghcr.io/cascadinglabs/chromium-cdp"
        )

    def test_mismatched_archive_never_pushes(self):
        with patch.object(containers, "run", return_value="sha256:other") as run:
            with self.assertRaisesRegex(ValueError, "Archive differs"):
                self.publish()
            self.assertFalse(any("push" in call.args for call in run.call_args_list))

    def test_existing_different_image_never_overwrites(self):
        existing = SimpleNamespace(
            returncode=0, stdout=json.dumps(dict(config=dict(digest="sha256:other")))
        )
        with patch.object(containers, "run", return_value="sha256:tested") as run:
            with patch.object(containers.subprocess, "run", return_value=existing):
                with self.assertRaisesRegex(ValueError, "different bytes"):
                    self.publish()
            self.assertFalse(any("push" in call.args for call in run.call_args_list))

    def test_existing_different_index_never_overwrites(self):
        image = SimpleNamespace(
            returncode=0, stdout=json.dumps(dict(config=dict(digest="sha256:tested")))
        )
        index = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(dict(manifests=[dict(digest="sha256:other")])),
        )
        with patch.object(containers, "run", return_value="sha256:tested") as run:
            with patch.object(
                containers.subprocess, "run", side_effect=[image, image, image, index]
            ):
                with self.assertRaisesRegex(ValueError, "Existing index"):
                    self.publish()
            self.assertFalse(any("create" in call.args for call in run.call_args_list))

    def test_idempotent_rerun_still_requires_anonymous_visibility(self):
        image = SimpleNamespace(
            returncode=0, stdout=json.dumps(dict(config=dict(digest="sha256:tested")))
        )
        index = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(dict(manifests=[dict(digest="sha256:tested")])),
        )
        with patch.object(containers, "run", return_value="sha256:tested") as run:
            with patch.object(
                containers.subprocess,
                "run",
                side_effect=[image, image, image, index, index],
            ):
                self.publish()
            calls = run.call_args_list
            self.assertFalse(
                any("push" in call.args or "create" in call.args for call in calls)
            )
            self.assertEqual(sum("--config" in call.args for call in calls), 2)

    def test_registry_errors_do_not_count_as_missing_tags(self):
        error = SimpleNamespace(returncode=1, stderr="unauthorized")
        with patch.object(containers, "run", return_value="sha256:tested") as run:
            with patch.object(containers.subprocess, "run", return_value=error):
                with self.assertRaisesRegex(RuntimeError, "unauthorized"):
                    self.publish()
            self.assertFalse(any("push" in call.args for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
