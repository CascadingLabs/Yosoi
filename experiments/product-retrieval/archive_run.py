"""Store experiment artifacts in SDK Archive and restore them with integrity checks."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import zlib
from pathlib import Path

from yosoi import Archive
from yosoi.archive import DocumentArchiveRef
from yosoi.documents import Document

CHUNK = 2_000_000


async def bundle(output, extras):
    if (output / "bundle.ref.json").exists():
        raise ValueError("refusing to overwrite an archived run")
    archive = await Archive.open(output / "archive")
    paths = sorted(
        p
        for p in output.iterdir()
        if p.is_file() and p.suffix in (".json", ".csv", ".md")
    )
    paths.extend(extras)
    entries = []
    for path in paths:
        if path.is_symlink():
            raise ValueError("symlinks are not experiment artifacts")
        raw = path.read_bytes()
        compressed = zlib.compress(raw)
        refs = []
        for offset in range(0, len(compressed), CHUNK):
            payload = {
                "kind": "product-retrieval-chunk-v1",
                "base64_zlib": base64.b64encode(
                    compressed[offset : offset + CHUNK]
                ).decode(),
            }
            document = Document.from_json(
                f"retrieval-{path.name}-{offset}", json.dumps(payload)
            )
            ref = await archive.write(document)
            refs.append(ref.model_dump(mode="json"))
        entries.append(
            {
                "path": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_len": len(raw),
                "compressed_bytes": len(compressed),
                "chunks": refs,
            }
        )
    if len({e["path"] for e in entries}) != len(entries):
        raise ValueError("artifact basename collision")
    manifest = {"kind": "product-retrieval-bundle-v1", "entries": entries}
    ref = await archive.write(
        Document.from_json("product-retrieval-bundle-v1", json.dumps(manifest))
    )
    (output / "bundle.json").write_text(json.dumps(manifest, indent=2))
    (output / "bundle.ref.json").write_text(ref.model_dump_json())
    print(
        json.dumps(
            {
                "artifacts": len(entries),
                "archive": str(output / "archive"),
                "uncompressed_bytes": sum(e["byte_len"] for e in entries),
            }
        )
    )


async def restore(output, destination):
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("restore requires an empty destination")
    destination.mkdir(parents=True, exist_ok=True)
    archive = await Archive.open(output / "archive")
    ref = DocumentArchiveRef.model_validate_json(
        (output / "bundle.ref.json").read_text()
    )
    document = await archive.read(ref)
    manifest = json.loads(document.data)
    if manifest["kind"] != "product-retrieval-bundle-v1":
        raise ValueError("unsupported bundle")
    verified = []
    for entry in manifest["entries"]:
        relative = Path(entry["path"])
        if (
            relative.is_absolute()
            or len(relative.parts) != 1
            or relative.name in (".", "..")
        ):
            raise ValueError("unsafe artifact path")
        compressed = bytearray()
        for chunk_ref in entry["chunks"]:
            chunk = await archive.read(DocumentArchiveRef.model_validate(chunk_ref))
            value = json.loads(chunk.data)
            if value["kind"] != "product-retrieval-chunk-v1":
                raise ValueError("unexpected chunk schema")
            compressed.extend(base64.b64decode(value["base64_zlib"], validate=True))
        # Generated local bundles have a declared length; bound decompression too.
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, entry["byte_len"] + 1)
        if (
            not decompressor.eof
            or decompressor.unused_data
            or len(raw) != entry["byte_len"]
            or hashlib.sha256(raw).hexdigest() != entry["sha256"]
        ):
            raise ValueError("artifact integrity mismatch")
        (destination / relative).write_bytes(raw)
        verified.append(entry["path"])
    certificate = {
        "kind": "product-retrieval-restore-v1",
        "verified": verified,
        "bundle_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
    }
    (destination / "restore-certificate.json").write_text(
        json.dumps(certificate, indent=2)
    )
    print(json.dumps(certificate))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bundle", "restore"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extra", type=Path, action="append", default=[])
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.command == "bundle":
        asyncio.run(bundle(args.output, args.extra))
    elif args.destination:
        asyncio.run(restore(args.output, args.destination))
    else:
        parser.error("restore requires --destination")


if __name__ == "__main__":
    main()
