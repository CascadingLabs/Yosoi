#!/usr/bin/env python3
"""Compare Map with a closed, independently fetched QScrape URL inventory."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "YosoiMapCoverage/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(MAX_DOCUMENT_BYTES + 1)
    if len(body) > MAX_DOCUMENT_BYTES:
        raise ValueError(f"coverage input exceeds byte cap: {url}")
    return body


def xml(body):
    if b"<!DOCTYPE" in body.upper():
        raise ValueError("coverage XML must not contain a DTD")
    return ET.fromstring(body)


def normalized(reference, base):
    value = urllib.parse.urljoin(base, reference.strip())
    parts = urllib.parse.urlsplit(value)
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def in_scope(url, seed):
    target, root = urllib.parse.urlsplit(url), urllib.parse.urlsplit(seed)
    if (target.scheme, target.netloc) != (root.scheme, root.netloc):
        return False
    prefix = root.path
    return prefix == "/" or target.path == prefix or target.path.startswith(prefix if prefix.endswith("/") else prefix + "/")


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href" and value)


def published_inventory(seed):
    origin = urllib.parse.urlunsplit((*urllib.parse.urlsplit(seed)[:2], "/", "", ""))
    robots = fetch(urllib.parse.urljoin(origin, "robots.txt")).decode("utf-8")
    pending = [normalized(line.split(":", 1)[1], origin) for line in robots.splitlines() if line.lower().startswith("sitemap:")]
    if not pending:
        raise ValueError("owned-site coverage requires a declared sitemap")
    expected, resources, seen = {seed}, [], set()
    while pending:
        url = pending.pop(0)
        if url in seen:
            continue
        if len(seen) >= 20 or urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(seed).netloc:
            raise ValueError("coverage sitemap scope/count limit")
        seen.add(url)
        body = fetch(url)
        root = xml(body)
        resources.append({"url": url, "sha256": hashlib.sha256(body).hexdigest()})
        locations = [normalized(node.text or "", url) for node in root.iter() if node.tag.split("}")[-1] == "loc"]
        if root.tag.split("}")[-1] == "sitemapindex":
            pending.extend(locations)
        elif root.tag.split("}")[-1] == "urlset":
            expected.update(url for url in locations if in_scope(url, seed))
        else:
            raise ValueError("published sitemap has unsupported root")
    feed_urls = set()
    for index in sorted(url for url in expected if urllib.parse.urlsplit(url).path.endswith("/rss/")):
        parser = Anchors()
        parser.feed(fetch(index).decode("utf-8"))
        feed_urls.update(normalized(link, index) for link in parser.links if urllib.parse.urlsplit(normalized(link, index)).path.endswith(".xml"))
    feed_links = set()
    article_ids = set()
    for feed in sorted(feed_urls):
        if not in_scope(feed, seed):
            continue
        expected.add(feed)
        body = fetch(feed)
        root = xml(body)
        resources.append({"url": feed, "sha256": hashlib.sha256(body).hexdigest()})
        for node in root.iter():
            if node.tag.split("}")[-1] == "link":
                reference = node.get("href") or (node.text or "").strip()
                if reference:
                    url = normalized(reference, feed)
                    if in_scope(url, seed):
                        expected.add(url)
                        feed_links.add(url)
            if node.tag.split("}")[-1] == "guid" and (node.text or "").startswith("MHH-"):
                article_ids.add(node.text)
    return expected, feed_links, article_ids, resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="https://qscrape.dev/l1/news/")
    parser.add_argument("--binary", type=Path, default=Path("target/debug/yosoi"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qscrape-source", type=Path, default=Path("/home/andrew/Desktop/cl/QScrape"))
    args = parser.parse_args()
    seed = normalized(args.seed, args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    expected, feed_links, feed_ids, resources = published_inventory(seed)
    binary = str(args.binary.resolve())
    version = subprocess.check_output([binary, "--version"], text=True).strip().split()[-1]
    with tempfile.TemporaryDirectory() as config:
        env = __import__("os").environ.copy()
        env["XDG_CONFIG_HOME"] = config
        explanation = subprocess.check_output([binary, "map", seed, "--explain"], env=env, text=True)
        policy = json.loads(explanation[explanation.index("{"):])
        policy["map"]["pages"] = "explore"
        policy["map"]["subdomains"] = "disabled"
        limits = policy["map"]["limits"]
        limits.update(max_link_depth=6, max_requests=2000, max_urls=10000, max_relationships=50000,
                      max_observations=100000, max_pending=10000, max_inventory_bytes=64*1024*1024,
                      max_total_response_bytes=256*1024*1024, max_response_bytes=8*1024*1024,
                      max_parser_entries=50000, maximum_elapsed={"seconds":300,"nanoseconds":0})
        store = Path(config, "yosoi", "policies.json")
        store.parent.mkdir()
        store.write_text(json.dumps({"format_version":1,"cli_versions":{version:{"profiles":{"coverage":{"map":policy["map"]}}}}}))
        with (args.output / "map.json").open("wb") as output:
            completed = subprocess.run([binary,"--profile","coverage","map",seed,"--json","--stats"],env=env,stdout=output,stderr=subprocess.PIPE,timeout=330)
        (args.output / "stderr.txt").write_bytes(completed.stderr)
    if not (args.output / "map.json").stat().st_size:
        raise RuntimeError(f"Map emitted no JSON (exit {completed.returncode}): {completed.stderr.decode(errors="replace")}")
    outcome = json.loads((args.output / "map.json").read_bytes())
    inventoried = {page["url"] for page in outcome["pages"]}
    inspected = {page["url"] for page in outcome["pages"] if page["exploration"]["status"] == "inspected"}
    observed_ids = set()
    for url in inventoried:
        observed_ids.update(re.findall(r"ID=(MHH-\d+)", urllib.parse.unquote(url)))
    source_ids, source_revision = set(), None
    data = args.qscrape_source / "src/data/news/articles.ts"
    if data.is_file():
        source_ids = set(re.findall(r"\bid:\s*['\"](MHH-\d+)['\"]", data.read_text()))
        source_revision = subprocess.check_output(["jj","log","-r","@","--no-graph","-T","commit_id"],cwd=args.qscrape_source,text=True).strip()
    report = {"binary_sha256":hashlib.sha256(Path(binary).read_bytes()).hexdigest(),"seed":seed,"map_exit":completed.returncode,"termination":outcome["termination"],
              "policy_identity":outcome["policy_identity"],"limits":outcome["map_policy"]["limits"],
              "denominator":"declared sitemap URLs plus linked published RSS/Atom URLs in seed scope",
              "published_urls":len(expected),"inventoried_urls":len(inventoried),"inspected_urls":len(inspected),
              "missing_published_urls":sorted(expected-inventoried),"additional_observed_urls":sorted(inventoried-expected),
              "feed_link_urls":len(feed_links),"uninspected_feed_urls":sorted(feed_links-inspected),
              "source_news_ids":sorted(source_ids),"feed_news_ids":sorted(feed_ids),"observed_news_ids":sorted(observed_ids),
              "missing_source_news_ids":sorted(source_ids-observed_ids),"source_revision":source_revision,
              "resources":resources,"scope_note":"closed published inventory coverage; does not prove unpublished/browser-only site URLs"}
    (args.output / "coverage.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({key:report[key] for key in ["published_urls","inventoried_urls","inspected_urls","missing_published_urls","missing_source_news_ids","termination"]},indent=2))
    if completed.returncode not in (0,3) or report["missing_published_urls"] or report["missing_source_news_ids"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
