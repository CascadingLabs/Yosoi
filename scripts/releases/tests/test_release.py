from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path


RELEASE_TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_TOOL_DIR))

import release  # noqa: E402


GITHUB_NOTES = (
    "## What's Changed\n"
    "* Keep source links in the generated notes.\n"
    "\n"
    "## New Contributors\n"
    "* @sample-user made their first contribution.\n"
    "\n"
    "**Full Changelog**: [v0.1.0...v0.2.0](https://github.com/example/yosoi/compare/v0.1.0...v0.2.0)\n"
)


class ReleaseToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.release_dir = self.root / "docs/public/releases"
        self.release_dir.mkdir(parents=True)
        self.notes_path = self.root / "github-notes.md"
        self.notes_path.write_text(GITHUB_NOTES, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                status = release.main(["--root", str(self.root), *arguments])
            except SystemExit as error:
                status = error.code if isinstance(error.code, int) else 2
        return status, stdout.getvalue(), stderr.getvalue()

    def prepare(self, version: str = "0.2.0", previous: str | None = "0.1.0") -> Path:
        arguments = [
            "prepare",
            version,
            "--date",
            "2026-10-04",
            "--channel",
            "preview",
            "--github-notes",
            str(self.notes_path),
        ]
        if previous is not None:
            arguments[6:6] = ["--previous", previous]
        status, _, error = self.invoke(*arguments)
        self.assertEqual(status, 0, error)
        return self.release_dir / (version.replace(".", "-") + ".md")

    def snapshot(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }

    def finalize(
        self,
        page: Path,
        date: str = "2026-10-04",
        channel: str = "preview",
        include_highlights: bool = False,
    ) -> None:
        rendered = page.read_text(encoding="utf-8")
        rendered = rendered.replace("draft: true", "draft: false", 1)
        rendered = rendered.replace('date: "2026-10-04"', f'date: "{date}"', 1)
        rendered = rendered.replace('channel: "preview"', f'channel: "{channel}"', 1)
        rendered = rendered.replace(
            "TODO: Describe the main value in a few clear sentences.",
            "Fixed redirect timeout handling.",
        )
        if include_highlights:
            rendered = rendered.replace(
                "## Highlights\n\n### TODO: Name this highlight\n\nTODO: Explain who benefits and how. Include a concrete example when it helps readers understand the change.\n\n",
                "## Highlights\n\n- Redirects retain the original request deadline.\n\n",
            )
        else:
            rendered = rendered.replace(
                "## Highlights\n\n### TODO: Name this highlight\n\nTODO: Explain who benefits and how. Include a concrete example when it helps readers understand the change.\n\n",
                "",
            )
        rendered = rendered.replace(
            "TODO: Explain required actions, compatibility changes, or state that no action is required.",
            "No migration required.",
        )
        page.write_text(rendered, encoding="utf-8")

    def test_prepare_preserves_full_github_notes_and_refuses_overwrite(self) -> None:
        page = self.prepare()
        sidecar = self.release_dir / "_0-2-0.json"
        generated = page.read_text(encoding="utf-8")
        provenance = json.loads(sidecar.read_text(encoding="utf-8"))

        self.assertIn(GITHUB_NOTES, generated)
        self.assertEqual(provenance["generated_source"], GITHUB_NOTES)
        self.assertEqual(
            provenance["generated_source_sha256"],
            hashlib.sha256(GITHUB_NOTES.encode("utf-8")).hexdigest(),
        )

        reviewed = generated + "\nReviewed prose stays in place.\n"
        page.write_text(reviewed, encoding="utf-8")
        status, _, error = self.invoke(
            "prepare",
            "0.2.0",
            "--date",
            "2026-10-04",
            "--channel",
            "preview",
            "--previous",
            "0.1.0",
            "--github-notes",
            str(self.notes_path),
        )
        self.assertEqual(status, 2)
        self.assertIn("refusing to overwrite", error)
        self.assertEqual(page.read_text(encoding="utf-8"), reviewed)

    def test_check_and_body_validate_finalized_content_and_allow_metadata_edits(self) -> None:
        page = self.prepare()
        status, _, error = self.invoke("check", "0.2.0")
        self.assertEqual(status, 2)
        self.assertIn("draft must be false", error)
        status, _, error = self.invoke("body", "0.2.0")
        self.assertEqual(status, 2)
        self.assertIn("draft must be false", error)

        self.finalize(page, date="2026-10-05", channel="recommended")
        rendered = page.read_text(encoding="utf-8")
        self.assertIn("Fixed redirect timeout handling.", rendered)
        fenced_example = "```markdown\n## Upgrading\nTODO: this is literal sample output.\n```"
        rendered = rendered.replace(
            "Fixed redirect timeout handling.",
            "Fixed redirect timeout handling. The example prints `TODO: upstream` unchanged.\n\n"
            + fenced_example,
            1,
        )
        self.assertIn(fenced_example, rendered)
        self.assertIn("`TODO: upstream`", rendered)
        page.write_text(rendered, encoding="utf-8")
        status, output, error = self.invoke("check", "0.2.0", "--json")
        self.assertEqual(status, 0, error)
        self.assertEqual(
            json.loads(output),
            {
                "version": "0.2.0",
                "date": "2026-10-05",
                "channel": "recommended",
                "previous": "0.1.0",
                "draft": False,
                "file": "docs/public/releases/0-2-0.md",
            },
        )

        document = release.read_document(page)
        status, body, error = self.invoke("body", "0.2.0")
        self.assertEqual(status, 0, error)
        self.assertEqual(body, document.body)
        self.assertIn(GITHUB_NOTES, body)

        tampered = page.read_text(encoding="utf-8").replace(
            "https://github.com/example/yosoi/compare/v0.1.0...v0.2.0",
            "https://github.com/example/yosoi/compare/v0.1.0...v0.2.1",
        )
        page.write_text(tampered, encoding="utf-8")
        status, _, error = self.invoke("check", "0.2.0")
        self.assertEqual(status, 2)
        self.assertIn("imported attribution or source references changed", error)

    def test_history_is_stable_newest_first_and_refuses_manual_edits(self) -> None:
        first = self.prepare()
        self.finalize(first)
        self.notes_path.write_text("## What's Changed\n\n* A later release.\n", encoding="utf-8")
        second_status, _, error = self.invoke(
            "prepare",
            "0.10.0",
            "--date",
            "2026-10-06",
            "--channel",
            "recommended",
            "--previous",
            "0.2.0",
            "--github-notes",
            str(self.notes_path),
        )
        self.assertEqual(second_status, 0, error)
        second = self.release_dir / "0-10-0.md"
        self.finalize(
            second,
            date="2026-10-06",
            channel="recommended",
            include_highlights=True,
        )

        status, _, error = self.invoke("history")
        self.assertEqual(status, 0, error)
        index = self.release_dir / "index.md"
        first_result = index.read_bytes()
        status, _, error = self.invoke("history")
        self.assertEqual(status, 0, error)
        self.assertEqual(index.read_bytes(), first_result)
        self.assertLess(first_result.index(b"0.10.0"), first_result.index(b"0.2.0"))
        self.assertIn(b"**Recommended**", first_result)
        self.assertIn(b"**Preview**", first_result)

        edited = first_result + b"\nManual note.\n"
        index.write_bytes(edited)
        status, _, error = self.invoke("history")
        self.assertEqual(status, 2)
        self.assertIn("refusing to overwrite edited release history", error)
        self.assertEqual(index.read_bytes(), edited)

    def test_invalid_inputs_placeholders_and_missing_previous_do_not_write(self) -> None:
        invalid_inputs = (
            ("0.100001.0", "2026-10-04", "preview", "0.1.0", "MINOR must be between"),
            ("0.2.0", "2026-02-30", "preview", "0.1.0", "invalid calendar date"),
            ("0.2.0", "2026-10-04", "nightly", "0.1.0", "invalid choice"),
        )
        for version, date, channel, previous, expected_error in invalid_inputs:
            with self.subTest(version=version, date=date, channel=channel):
                before = self.snapshot()
                status, _, error = self.invoke(
                    "prepare",
                    version,
                    "--date",
                    date,
                    "--channel",
                    channel,
                    "--previous",
                    previous,
                    "--github-notes",
                    str(self.notes_path),
                )
                self.assertEqual(status, 2)
                self.assertIn(expected_error, error)
                self.assertEqual(self.snapshot(), before)

        first = self.prepare("0.1.0", previous=None)
        self.finalize(first)
        finalized = first.read_text(encoding="utf-8")
        first.write_text(
            finalized.replace(
                "Fixed redirect timeout handling.",
                "TODO: finish documenting redirect timeout handling.",
                1,
            ),
            encoding="utf-8",
        )
        unresolved = self.snapshot()
        status, _, error = self.invoke("check", "0.1.0")
        self.assertEqual(status, 2)
        self.assertIn("placeholders must be resolved", error)
        self.assertEqual(self.snapshot(), unresolved)

        first.write_text(finalized, encoding="utf-8")
        before_missing_previous = self.snapshot()
        status, _, error = self.invoke(
            "prepare",
            "0.2.0",
            "--date",
            "2026-10-04",
            "--channel",
            "preview",
            "--github-notes",
            str(self.notes_path),
        )
        self.assertEqual(status, 2)
        self.assertIn("--previous VERSION is required", error)
        self.assertEqual(self.snapshot(), before_missing_previous)

    def test_explicit_fetch_requests_notes_only_and_preserves_export_on_rerun(self) -> None:
        output = self.root / "exported-notes.md"
        target = "a" * 40
        response = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"body": GITHUB_NOTES}), stderr=""
        )
        arguments = (
            "fetch", "0.2.0", "--repository", "example/yosoi",
            "--previous-tag", "v0.1.0", "--target-ref", target,
            "--output", str(output),
        )
        with patch.object(release.shutil, "which", return_value="fixture-gh"), patch.object(
            release.subprocess, "run", return_value=response
        ) as request:
            status, _, error = self.invoke(*arguments)
            self.assertEqual(status, 0, error)
            self.assertEqual(output.read_text(encoding="utf-8"), GITHUB_NOTES)
            self.assertEqual(request.call_args.args[0], [
                "fixture-gh", "api", "--method", "POST",
                "repos/example/yosoi/releases/generate-notes",
                "-f", "tag_name=v0.2.0", "-f", f"target_commitish={target}",
                "-f", "previous_tag_name=v0.1.0",
            ])
            status, _, error = self.invoke(*arguments)
            self.assertEqual(status, 2)
            self.assertIn("refusing to overwrite", error)
            self.assertEqual(output.read_text(encoding="utf-8"), GITHUB_NOTES)

    def test_prepare_rejects_symlinked_release_directory_without_writing_through_it(self) -> None:
        outside = self.root / "outside-release-target"
        outside.mkdir()
        sentinel = outside / "existing.md"
        sentinel.write_text("leave this directory alone\n", encoding="utf-8")
        self.release_dir.rmdir()
        self.release_dir.symlink_to(outside, target_is_directory=True)
        before = {
            path.relative_to(outside).as_posix(): path.read_bytes()
            for path in outside.rglob("*")
            if path.is_file()
        }

        status, _, error = self.invoke(
            "prepare",
            "0.2.0",
            "--date",
            "2026-10-04",
            "--channel",
            "preview",
            "--previous",
            "0.1.0",
            "--github-notes",
            str(self.notes_path),
        )

        self.assertEqual(status, 2)
        self.assertIn("release path cannot contain a symlink", error)
        after = {
            path.relative_to(outside).as_posix(): path.read_bytes()
            for path in outside.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertEqual({path.name for path in self.release_dir.iterdir()}, {sentinel.name})


if __name__ == "__main__":
    unittest.main()
