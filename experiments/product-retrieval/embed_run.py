"""Collect exact experiment strings or embed them with a pinned local runtime."""

import argparse
import json
import time
from pathlib import Path

from methods import representation_text
from run_matrix import FIELDS, REPRESENTATIONS
from semantic import embed_texts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "embed"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a fresh path; cached vectors remain reusable")
    value = json.loads(args.input.read_text())
    if args.command == "collect":
        texts = set(FIELDS.values())
        texts.update(
            representation_text(candidate, representation)
            for case in value["cases"]
            for candidate in case["candidates"]
            for representation in REPRESENTATIONS
        )
        result = sorted(texts)
    else:
        if not args.model or not args.cache:
            parser.error("embed requires --model and --cache")
        started = time.perf_counter()
        result = embed_texts(value, args.cache, "fastembed", args.model)
        result["ledger"]["total_adapter_wall_ms"] = (
            time.perf_counter() - started
        ) * 1000
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False))
    print(json.dumps({"output": str(args.output), "entries": len(result)}))


if __name__ == "__main__":
    main()
