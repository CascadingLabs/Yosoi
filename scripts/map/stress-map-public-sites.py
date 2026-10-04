#!/usr/bin/env python3
"""Run bounded Map checks and compare inventories with public documentation indexes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CASES = [
    ("anthropic", "https://anthropic.com/", "passive"),
    ("firecrawl", "https://docs.firecrawl.dev/", "pages"),
    ("vercel", "https://vercel.com/docs", "pages"),
]


def fetch(url, cap):
    request = urllib.request.Request(url, headers={"User-Agent": "YosoiMapCoverage/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(cap + 1)
    if len(body) > cap:
        raise ValueError(f"published inventory exceeded {cap} bytes")
    return body


def compare_indexes(label, seed, case, data, report):
    actual = {page["url"] for page in data["pages"]}
    parts = urllib.parse.urlsplit(seed)
    origin = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    body = fetch(origin + "/sitemap.xml", 8 * 1024 * 1024)
    if b"<!DOCTYPE" in body.upper():
        raise ValueError("DTD forbidden in coverage XML")
    root = ET.fromstring(body)
    if root.tag.split("}")[-1] != "urlset":
        raise ValueError("coverage comparison requires a flat URL sitemap")
    expected = set()
    for node in root.iter():
        if node.tag.split("}")[-1] != "loc" or not node.text:
            continue
        url = node.text.strip()
        target = urllib.parse.urlsplit(url)
        if target.netloc != parts.netloc:
            continue
        if parts.path == "/" or target.path == parts.path or target.path.startswith(parts.path + "/"):
            expected.add(url)
    (case / "sitemap.xml").write_bytes(body)
    report.update(sitemap_urls=len(expected), missing_sitemap_urls=sorted(expected - actual),
                  sitemap_sha256=hashlib.sha256(body).hexdigest())
    if label == "firecrawl":
        body = fetch(origin + "/llms.txt", 2 * 1024 * 1024)
        (case / "llms.txt").write_bytes(body)
        expected = {url.rstrip(".,") for url in re.findall(
            r"https://docs\.firecrawl\.dev/[^\s\)<>]+", body.decode())}
        report.update(published_index_urls=len(expected), missing_index_urls=sorted(expected - actual),
                      index_sha256=hashlib.sha256(body).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("target/debug/yosoi"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    version = subprocess.check_output([str(binary), "--version"], text=True).strip().split()[-1]
    for label, seed, mode in CASES:
        case = args.output / label
        case.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as config:
            env = os.environ.copy()
            env["XDG_CONFIG_HOME"] = config
            explanation = subprocess.check_output(
                [str(binary), "map", seed, "--mode", mode, "--explain"], env=env, text=True)
            policy = json.loads(explanation[explanation.index("{"):])
            limits = policy["map"]["limits"]
            limits.update(max_requests=80, max_urls=20000, max_hosts=2000,
                          max_relationships=50000, max_observations=100000, max_pending=20000,
                          max_inventory_bytes=32 * 1024 * 1024,
                          max_total_response_bytes=64 * 1024 * 1024,
                          max_response_bytes=8 * 1024 * 1024, max_parser_entries=50000,
                          maximum_elapsed={"seconds": 120, "nanoseconds": 0})
            store = Path(config, "yosoi", "policies.json")
            store.parent.mkdir()
            store.write_text(json.dumps({"format_version": 1, "cli_versions": {
                version: {"profiles": {"stress": {"map": policy["map"]}}}}}))
            command = [str(binary), "--profile", "stress", "map", seed, "--json", "--stats"]
            start = time.monotonic()
            with (case / "map.json").open("wb") as output:
                completed = subprocess.run(command, env=env, stdout=output,
                                           stderr=subprocess.PIPE, timeout=140)
            elapsed = time.monotonic() - start
        (case / "stderr.txt").write_bytes(completed.stderr)
        data = json.loads((case / "map.json").read_bytes())
        report = {"seed": seed, "command": command, "exit": completed.returncode,
                  "elapsed_seconds": elapsed, "binary_sha256": binary_hash,
                  "termination": data["termination"], "summary": data["summary"],
                  "sources": data["sources"], "policy_identity": data["policy_identity"],
                  "limits": limits, "request_hosts": sorted({
                      urllib.parse.urlsplit(row["target"]).hostname for row in data["request_trace"]})}
        if mode == "pages":
            try:
                compare_indexes(label, seed, case, data, report)
            except (OSError, ValueError, ET.ParseError) as error:
                report["index_error"] = str(error)
        (case / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"case": label, "exit": report["exit"],
                          "summary": report["summary"], "termination": report["termination"]}), flush=True)


if __name__ == "__main__":
    main()
