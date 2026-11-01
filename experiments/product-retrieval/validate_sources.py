"""Validate all original/derived snapshots with the installed native SDK parser."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import shutil
import tempfile
from pathlib import Path

from yosoi import Archive, locators
from yosoi.archive import DocumentArchiveRef
from yosoi.documents import Document


async def validate(corpus_path, source):
    corpus = json.loads(corpus_path.read_text())
    with tempfile.TemporaryDirectory(prefix="product-retrieval-archive-") as directory:
        staged = Path(directory) / "store"
        for entry in (source / "archive").rglob("*"):
            if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
                raise ValueError("unsafe original Archive entry")
        shutil.copytree(source / "archive", staged)
        for root, _dirs, files in os.walk(staged):
            os.chmod(root, 0o700)
            for name in files:
                os.chmod(Path(root) / name, 0o600)
        archive = await Archive.open(staged)
        originals = []
        for identity in (
            "obj-001",
            "obj-002",
            "obj-003",
            "obj-004",
            "obj-005",
            "obj-006",
        ):
            reference = DocumentArchiveRef(
                value=json.loads((source / f"{identity}.ref.json").read_text())
            )
            document = await archive.read(reference)
            originals.append({"id": identity, "bytes": document.byte_len})
    plan = locators.Plan(
        outputs=(locators.output("parser_probe", locators.css("*").text()),)
    )
    validated = []
    for case in corpus["cases"]:
        wire = case["document"]
        document = Document.rendered_dom(
            case["id"], wire["document_epoch"], json.dumps(wire)
        )
        outcome = document.locate(plan)
        value = outcome.model_dump(mode="json")
        # A parse/resource/unsupported failure must not be mistaken for validation.
        if value.get("status") != "matched":
            raise ValueError(f"native parser did not match {case['id']}: {value}")
        validated.append(
            {
                "id": case["id"],
                "document_sha256": hashlib.sha256(
                    json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        )
    return {
        "kind": "product-retrieval-native-validation-v1",
        "original_archive_reads": originals,
        "validated_cases": validated,
        "sdk_distribution": importlib.metadata.version("yosoi"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    certificate = asyncio.run(validate(args.corpus, args.source))
    args.output.write_text(json.dumps(certificate, indent=2))
    print(
        json.dumps(
            {
                "originals": len(certificate["original_archive_reads"]),
                "native_validated": len(certificate["validated_cases"]),
            }
        )
    )
