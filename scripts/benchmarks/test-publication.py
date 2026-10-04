#!/usr/bin/env python3
"""Exercise result retention and recovery without compiling or measuring Rust."""

import csv
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PUBLISHER = Path(__file__).with_name("publish-benchmark-result.sh").resolve()


class PublicationTests(unittest.TestCase):
    def test_dashboard_uses_latest_measurement_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in (100, 200):
                staging = root / "staging"
                estimate = staging / "criterion-raw/sha256_only/encoded_bytes/large-html/new/estimates.json"
                estimate.parent.mkdir(parents=True)
                estimate.write_text(json.dumps({"median": {"point_estimate": value}}))
                subprocess.run([PUBLISHER, staging, root / "criterion"], check=True)
            subprocess.run([sys.executable, PUBLISHER.with_name("summarize-benchmark-change.py"), root], check=True)
            with (root / "summary.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["value"], "200")

    def test_capture_runner_rejects_overlap_before_creating_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = root / "scripts/benchmarks/run-cas-307-benchmarks.sh"
            runner.parent.mkdir(parents=True)
            runner.write_bytes(PUBLISHER.with_name(runner.name).read_bytes())
            commands = root / "commands"
            commands.mkdir()
            jj = commands / "jj"
            jj.write_text('#!/bin/bash\nprintf "test-identity"\n')
            jj.chmod(0o755)
            (root / "target").mkdir()
            with (root / "target/.capture-benchmark.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(["bash", runner, root / "results/criterion"],
                                        env=dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}"),
                                        capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("another capture measurement is running", result.stderr)
            self.assertEqual(list((root / "results").iterdir()), [])

    def test_repeated_publication_retains_each_run_without_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "criterion"
            inodes = []
            for value in ("first", "second", "third"):
                staging = root / "staging"
                staging.mkdir()
                evidence = staging / "environment.txt"
                evidence.write_text(value)
                inodes.append(evidence.stat().st_ino)
                subprocess.run([PUBLISHER, staging, destination], check=True)
            self.assertEqual((destination / "environment.txt").read_text(), "third")
            archived = list((root / "history/criterion").glob("*/result/environment.txt"))
            self.assertEqual({path.read_text() for path in archived}, {"first", "second"})
            self.assertEqual({path.stat().st_ino for path in archived}, set(inodes[:2]))
            self.assertEqual((destination / "environment.txt").stat().st_ino, inodes[2])

    def test_failed_publication_restores_previous_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            staging.mkdir()
            destination = root / "criterion"
            destination.mkdir()
            (destination / "evidence").write_text("previous")
            commands = root / "commands"
            commands.mkdir()
            # Fail the staging move after the previous result has been archived.
            mover = commands / "mv"
            mover.write_text('#!/bin/bash\nif test "$2" = "$FAILED_STAGING"; then exit 1; fi\nexec /usr/bin/mv "$@"\n')
            mover.chmod(0o755)
            environment = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}", FAILED_STAGING=str(staging))
            result = subprocess.run([PUBLISHER, staging, destination], env=environment, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / "evidence").read_text(), "previous")
            self.assertTrue(staging.is_dir())
            self.assertEqual(list((root / "history/criterion").iterdir()), [])

    def test_missing_staging_does_not_touch_existing_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "criterion"
            destination.mkdir()
            (destination / "evidence").write_text("previous")
            result = subprocess.run([PUBLISHER, root / "missing", destination], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual((destination / "evidence").read_text(), "previous")
            self.assertFalse((root / "history").exists())


if __name__ == "__main__":
    unittest.main()
