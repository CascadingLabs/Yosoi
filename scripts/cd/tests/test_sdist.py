"""Exercise the exported workspace lock with real Cargo metadata, no builds."""

import hashlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sdist  # noqa: E402


class SdistTests(unittest.TestCase):
    def test_refuses_dependency_upgrade_or_checksum_change(self):
        def lock(version="1.0.0", checksum="a"):
            return (
                f'[[package]]\nname="dependency"\nversion="{version}"\n'
                f'source="registry+test"\nchecksum="{checksum}"\n'
            ).encode()

        for changed in (lock("1.1.0"), lock(checksum="b")):
            with self.assertRaisesRegex(ValueError, "changed locked package"):
                sdist.verify_resolution(lock(), changed)

    def test_pruned_workspace_remains_locked_and_preserves_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "yosoi-0.1.0rc2"
            root.mkdir()
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers=["crates/yosoi-python", "unused"]\nresolver="2"\n'
            )
            for name, path in (
                ("yosoi-python", "crates/yosoi-python"),
                ("unused", "unused"),
            ):
                crate = root / path
                (crate / "src").mkdir(parents=True)
                (crate / "Cargo.toml").write_text(
                    f'[package]\nname="{name}"\nversion="0.1.0-rc.2"\nedition="2024"\n'
                )
                (crate / "src/lib.rs").write_text("pub fn marker() {}\n")
            subprocess.run(
                ["cargo", "generate-lockfile", "--offline"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            original = (root / "Cargo.lock").read_bytes()
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers=["crates/yosoi-python"]\nresolver="2"\n'
            )
            archive = base / "yosoi.tar.gz"
            with tarfile.open(archive, "w:gz") as packed:
                packed.add(root, arcname=root.name)
            sdist.prepare(archive)
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            sdist.prepare(archive)
            self.assertEqual(checksum, hashlib.sha256(archive.read_bytes()).hexdigest())
            with tarfile.open(archive) as packed:
                rewritten = packed.extractfile(f"{root.name}/Cargo.lock").read()
                self.assertLess(
                    len(sdist.locked_packages(rewritten)),
                    len(sdist.locked_packages(original)),
                )
                self.assertEqual(
                    packed.extractfile(
                        f"{root.name}/crates/yosoi-python/src/lib.rs"
                    ).read(),
                    b"pub fn marker() {}\n",
                )
                self.assertEqual(packed.getmember(f"{root.name}/Cargo.toml").mtime, 0)


if __name__ == "__main__":
    unittest.main()
