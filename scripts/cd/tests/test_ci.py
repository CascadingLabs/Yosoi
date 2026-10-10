"""Exact-source CI reuse must not accept another branch or stale success."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci  # noqa: E402

SOURCE = "a" * 40


def run(**changes):
    return (
        dict(
            id=1,
            head_sha=SOURCE,
            head_branch="main",
            event="push",
            path=".github/workflows/rust-ci-test.yml",
            status="completed",
            conclusion="success",
            html_url="https://github.com/example/run/1",
        )
        | changes
    )


class SourceCiTests(unittest.TestCase):
    def test_requires_exact_source_main_push_and_workflow(self):
        for changes in (
            dict(head_sha="b" * 40),
            dict(head_branch="feature"),
            dict(event="pull_request"),
            dict(path=".github/workflows/other.yml"),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ci.select_run([run(**changes)], SOURCE, "rust-ci-test.yml")

    def test_new_failed_run_cannot_use_old_success(self):
        selected = ci.select_run(
            [run(), run(id=2, conclusion="failure")], SOURCE, "rust-ci-test.yml"
        )
        with self.assertRaises(ValueError):
            ci.require_success(selected)

    def test_incomplete_and_cancelled_runs_do_not_pass(self):
        for changes in (
            dict(status="queued"),
            dict(status="in_progress"),
            dict(conclusion="cancelled"),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ci.require_success(run(**changes))

    def test_pending_run_is_watched_and_rechecked_not_rebuilt(self):
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            if args[1] == "run":
                self.assertEqual(args[2:4], ["watch", "1"])
                return SimpleNamespace(returncode=1)  # Transient observer failure.
            workflow = (
                "python-ci.yml" if "python-ci.yml" in args[2] else "rust-ci-test.yml"
            )
            status = "queued" if len(calls) == 1 else "completed"
            return SimpleNamespace(
                stdout=json.dumps(
                    dict(
                        workflow_runs=[
                            run(path=f".github/workflows/{workflow}", status=status)
                        ]
                    )
                )
            )

        with patch.object(ci.subprocess, "run", side_effect=command):
            ci.check("CascadingLabs/Yosoi", SOURCE)
        self.assertEqual(len(calls), 4)

    def test_inputs_are_validated_before_any_process(self):
        with patch.object(ci.subprocess, "run") as command:
            for repository, source in (
                ("--invalid", SOURCE),
                ("CascadingLabs/Yosoi", "main"),
            ):
                with self.subTest(repository=repository), self.assertRaises(ValueError):
                    ci.check(repository, source)
            command.assert_not_called()
