"""Run a small, serial Search repair corpus; live provider access is explicit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def classify(provider: dict) -> str:
    """Keep transport, blocks, parser failures, empty, and relaxed results distinct."""
    status = provider.get("status")
    detail = provider.get("detail")
    if status == "results":
        if provider.get("recovery_query") is not None:
            return "relaxed_results"
        if provider.get("coverage", {}).get("web") == "partial":
            return "partial_results"
        return "original_query_results"
    if status == "empty":
        return "actual_empty"
    if status in {"cancelled", "not_started"}:
        return status
    return {
        "rate_limited": "rate_limit",
        "challenge": "provider_block",
        "transport_failure": "acquisition_failure",
        "malformed_response": "parser_failure",
        "query_mismatch": "parser_failure",
        "budget_exhausted": "budget_exhausted",
        "provider_unavailable": "provider_unavailable",
    }.get(detail, "unknown")


def cell(case: dict, name: str, provider: dict) -> dict:
    """Report useful/relevance proxies independently of acquisition and row count."""
    hits = provider.get("hits", [])
    terms = [term.casefold() for term in case["relevance_terms"]]
    relevant = sum(
        any(
            term
            in " ".join(
                str(hit.get(key) or "") for key in ("title", "snippet", "url")
            ).casefold()
            for term in terms
        )
        for hit in hits
    )
    attempts = provider.get("attempts", [])
    return {
        "case": case["id"],
        "category": case["category"],
        "provider": name,
        "classification": classify(provider),
        "skipped": False,
        "http_success": any(
            200 <= (attempt.get("http_status") or 0) < 300 for attempt in attempts
        ),
        "hit_count": len(hits),
        "topic_matching_hits": relevant,
        "useful_results_proxy": bool(relevant),
        "relevance_method": "lexical_topic_proxy_not_intent_judgment",
        "relevance_fraction": relevant / len(hits) if hits else None,
        "query_intent_verified": False,
        "attempts": attempts,
    }


def cli_search(args: argparse.Namespace, case: dict, provider: str) -> dict:
    """Execute one bounded provider cell through the public CLI."""
    command = [
        str(args.binary),
        "search",
        case["query"],
        "--providers",
        provider,
        "--max-in-flight",
        "1",
        "--per-provider-limit",
        "5",
        "--output",
        "json",
        "--diagnostic-archive",
        str(args.output_dir),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=180, check=False
    )
    # Deliberately discard arbitrary stderr: it can contain local profile/path details.
    if not result.stdout.strip():
        return {
            "status": "not_started",
            "detail": "cli_setup_or_output_failure",
            "attempts": [],
        }
    return json.loads(result.stdout)["providers"][0]


async def sdk_search(args: argparse.Namespace, case: dict, provider: str) -> dict:
    """Execute the same bounded cell through the public Python SDK."""
    from yosoi import search
    from yosoi.archive import Archive
    from yosoi.policy import Policy, ProviderSelection, Search

    policy = Policy(
        search=Search(
            providers=[
                ProviderSelection(
                    provider="duck_duck_go" if provider == "duckduckgo" else provider
                )
            ],
            max_in_flight=1,
            max_browser_in_flight=1,
        )
    )
    archive = await Archive.open(args.output_dir)
    response = (
        await search.new(case["query"]).bind(policy).send(diagnostic_archive=archive)
    )
    item = response.providers[0].model_dump(mode="json")
    outcome = item["outcome"]
    page = outcome.get("value", {}) if outcome["status"] == "results" else {}
    value = {
        **item,
        "status": outcome["status"],
        "hits": [{**hit, **hit.get("metadata", {})} for hit in page.get("hits", [])],
        "coverage": page.get("coverage", {}),
        "detail": outcome.get("value")
        if outcome["status"] in {"failed", "not_started"}
        else None,
    }
    # Save native records as a bounded SDK evidence collection, retaining both phases.
    path = args.output_dir / f"sdk-{response.request_id}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {"schema_version": 1, "interface": "python", "records": item["captures"]},
            stream,
        )
    return value


def identity(args: argparse.Namespace) -> dict:
    """Record exact executable bytes separately from a source revision assertion."""
    path = args.binary
    if args.interface == "sdk":
        from yosoi import _native

        path = Path(_native.__file__)
    if path is None or not path.is_file():
        raise ValueError("select an existing --binary for CLI execution")
    with path.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    return {
        "interface": args.interface,
        "binary_sha256": digest,
        "source_revision_assertion": args.source_revision,
        "exact_source_validation": False,
    }


async def run(args: argparse.Namespace) -> dict:
    """Keep failures and skipped cells in the authored denominator; stop on blocks."""
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    cases = corpus["cases"]
    if len(cases) > 16 or len(args.providers) > 4 or not 1 <= args.max_cells <= 32:
        raise ValueError("corpus/provider/live-cell bound exceeded")
    rows = []
    stop = None if args.live else "live_not_requested"
    executed = 0
    provenance = identity(args) if args.live else {"interface": args.interface}
    if args.live:
        args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for case in cases:
        for provider in args.providers:
            reason = stop or ("cell_limit" if executed >= args.max_cells else None)
            if reason is not None:
                rows.append(
                    {
                        "case": case["id"],
                        "category": case["category"],
                        "provider": provider,
                        "classification": "skipped",
                        "skipped": True,
                        "reason": reason,
                    }
                )
                continue
            executed += 1
            try:
                result = (
                    await sdk_search(args, case, provider)
                    if args.interface == "sdk"
                    else cli_search(args, case, provider)
                )
                row = cell(case, provider, result)
            except (
                Exception
            ):  # Application boundary: preserve failed cells without raw provider text.
                row = {
                    "case": case["id"],
                    "category": case["category"],
                    "provider": provider,
                    "classification": "unknown",
                    "skipped": False,
                    "reason": "execution_or_report_failure",
                }
            rows.append(row)
            if row["classification"] in {"provider_block", "rate_limit"}:
                stop = row["classification"]
    denominator = len(rows)
    return {
        "schema_version": 1,
        "identity": provenance,
        "denominator": denominator,
        "executed": executed,
        "skipped": sum(row["skipped"] for row in rows),
        "http_success": sum(row.get("http_success", False) for row in rows),
        "useful_results_proxy": sum(
            row.get("useful_results_proxy", False) for row in rows
        ),
        "relevance_method": "lexical_topic_proxy_not_intent_judgment",
        "stop_reason": stop,
        "cells": rows,
    }


def main() -> None:
    """Parse explicit retention/network options and print one JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="opt in to serial provider requests and query/page retention",
    )
    parser.add_argument("--interface", choices=["cli", "sdk"], default="cli")
    parser.add_argument("--binary", type=Path)
    parser.add_argument(
        "--source-revision", help="caller assertion; not exact-head validation proof"
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=["bing", "brave", "duckduckgo"],
        default=["bing"],
    )
    parser.add_argument("--max-cells", type=int, default=3)
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus.json")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".generated/search-corpus")
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
