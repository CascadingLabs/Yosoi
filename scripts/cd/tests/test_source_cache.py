"""Unchanged sources may reuse builds; changed sources must still compile."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ACTION = (
    Path(__file__).resolve().parents[3] / ".github/actions/rust-source-cache/index.mjs"
)


class SourceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = self.root / "before.json"
        self.source = self.root / "src/main.rs"
        self.source.parent.mkdir()
        self.source.write_text('fn main() { println!("one"); }\n')
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "cache-probe"\nversion = "0.1.0"\nedition = "2021"\n'
        )
        self.command("git", "init", "-q")
        self.command("git", "add", "Cargo.toml", "src/main.rs")
        self.snapshot = self.root / ".generated/ci-source-inputs/inputs.json"

    def command(self, *args, **kwargs):
        return subprocess.run(
            args, cwd=self.root, check=True, capture_output=True, text=True, **kwargs
        )

    def action(self, method):
        args = (
            [str(self.root), str(self.state)]
            if method == "prepare"
            else [str(self.state)]
        )
        self.command(
            "node",
            "--input-type=module",
            "-e",
            f"const m = await import({json.dumps(ACTION.as_uri())}); "
            f"await m.{method}(...{json.dumps(args)});",
        )

    def test_content_changes_do_not_restore_old_timestamp(self):
        old = time.time() - 60
        os.utime(self.source, (old, old))
        self.action("prepare")
        self.action("finish")
        self.source.write_text('fn main() { println!("two"); }\n')
        changed = self.source.stat().st_mtime
        self.action("prepare")
        self.assertEqual(self.source.stat().st_mtime, changed)

    def test_mutation_during_build_discards_the_snapshot(self):
        self.action("prepare")
        self.action("finish")
        self.action("prepare")
        self.source.write_text("changed source\n")
        self.action("finish")
        self.assertFalse(self.snapshot.exists())

    def test_environment_files_and_links_are_never_hashed(self):
        (self.root / ".env.secret").write_text("private fixture\n")
        (self.root / "linked.rs").symlink_to(self.root / ".env.secret")
        self.command("git", "add", ".env.secret", "linked.rs")
        self.action("prepare")
        files = json.loads(self.state.read_text())["files"]
        self.assertEqual(
            {entry["path"] for entry in files}, {"Cargo.toml", "src/main.rs"}
        )

    def test_corrupt_metadata_falls_back_to_normal_freshness(self):
        self.snapshot.parent.mkdir(parents=True)
        self.snapshot.write_text("invalid JSON")
        before = self.source.stat().st_mtime_ns
        self.action("prepare")
        self.assertEqual(self.source.stat().st_mtime_ns, before)

    def test_cargo_reuses_unchanged_binary_and_rebuilds_changed_code(self):
        # A dependency-free fixture proves real Cargo behavior cheaply, one worker.
        old = time.time() - 60
        for file in (self.source, self.root / "Cargo.toml"):
            os.utime(file, (old, old))
        env = dict(
            os.environ,
            CARGO_BUILD_JOBS="1",
            CARGO_INCREMENTAL="0",
            RAYON_NUM_THREADS="1",
            CARGO_TARGET_DIR=str(self.root / "target"),
        )
        self.action("prepare")
        first = self.command("cargo", "build", "--offline", env=env)
        self.assertIn("Compiling cache-probe", first.stderr)
        self.action("finish")
        for file in (self.source, self.root / "Cargo.toml"):
            os.utime(file, None)
        self.action("prepare")
        reused = self.command("cargo", "build", "--offline", env=env)
        self.assertNotIn("Compiling cache-probe", reused.stderr)
        self.action("finish")
        self.source.write_text('fn main() { println!("two"); }\n')
        self.action("prepare")
        rebuilt = self.command("cargo", "build", "--offline", env=env)
        self.assertIn("Compiling cache-probe", rebuilt.stderr)
        self.assertEqual(
            self.command(str(self.root / "target/debug/cache-probe")).stdout.strip(),
            "two",
        )
