#!/usr/bin/env python3
"""Deterministically generate the CAS-307 synthetic fixture bytes."""
from __future__ import annotations
import argparse, gzip, hashlib, json, subprocess, tempfile, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "benchmarks/fixtures/web-capture/v1"
SIZES = {"small": 1024, "medium": 32768, "large": 262144}
PREFIX = {
    "html": b"<!doctype html><html><body>",
    "xml": b'<?xml version="1.0"?><root>',
    "json": b'{"items":[',
    "plain": b"",
}
UNIT = {
    "html": b"<p>fixed benchmark text</p>",
    "xml": b"<item>fixed benchmark text</item>",
    "json": b'"fixed benchmark text",',
    "plain": b"fixed benchmark text\n",
}

def fill(kind: str, size: int) -> bytes:
    value = PREFIX[kind] + UNIT[kind] * (size // len(UNIT[kind]) + 2)
    return value[:size]

def generated() -> dict[str, bytes]:
    files = {f"{size}-{kind}.bin": fill(kind, length) for size, length in SIZES.items() for kind in PREFIX}
    medium = files["medium-html.bin"]
    files["small-js-shell.bin"] = b'<!doctype html><div id="app"></div><script>window.__FIXED__=true;</script>'
    files["medium-html-gzip.bin"] = gzip.compress(medium, compresslevel=6, mtime=0)
    files["medium-html-zlib.bin"] = zlib.compress(medium, level=6)
    files["medium-html-truncated.bin"] = medium[:4096]
    files["large-high-ratio-gzip.bin"] = gzip.compress(bytes(262144), compresslevel=9, mtime=0)
    with tempfile.TemporaryDirectory() as directory:
        source, output = Path(directory) / "in", Path(directory) / "out"
        source.write_bytes(medium)
        subprocess.run(["brotli", "--quality=11", "--no-copy-stat", "-o", str(output), str(source)], check=True)
        files["medium-html-br.bin"] = output.read_bytes()
    return files

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = generated()
    if args.check:
        bad = [name for name, data in files.items() if not (ROOT / name).is_file() or (ROOT / name).read_bytes() != data]
        if bad:
            print("fixtures differ: " + ", ".join(bad))
            return 1
        return 0
    for name, data in files.items(): (ROOT / name).write_bytes(data)
    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for fixture in manifest["fixtures"]:
        data = files[fixture["file"]]
        fixture["encoded_bytes"] = len(data)
        fixture["sha256"] = hashlib.sha256(data).hexdigest()
        if fixture["name"] == "medium-html-br": fixture["uncompressed_bytes"] = len(files["medium-html.bin"])
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    anchors = sorted({fixture["file"] for fixture in manifest["fixtures"]})
    (ROOT / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in anchors))
    return 0
if __name__ == "__main__": raise SystemExit(main())
