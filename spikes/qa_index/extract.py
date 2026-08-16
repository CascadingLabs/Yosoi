"""The oracle: execute a proposed selector set against a frozen capture.

This is what makes selector discovery self-verifying. The agent's output is not content
— it is a SPEC, one layer up. A spec can be run, and running it produces exact evidence:
how many records matched, which fields filled, what the values look like. No LLM judge,
no hand-labeled ground truth, no network.

That feedback is why a few-shot loop should beat one-shot: each round returns executed
results, not more page.

Spec format (JSON):
    {
      "record": "article.product_pod",
      "fields": {
        "title": "h3 a::attr(title)",
        "price": "p.price_color::text",
        "url":   "h3 a::attr(href)"
      }
    }

Usage:
    uv run python extract.py --target books_toscrape --spec spec.json
    uv run python extract.py --target books_toscrape --spec spec.json --show 5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parsel import Selector

from cursor import resolve


def run_spec(html: str, spec: dict) -> tuple[list[dict], dict]:
    sel = Selector(text=html)
    record_css = spec.get("record")
    fields: dict[str, str] = spec.get("fields", {})
    if not record_css or not fields:
        raise SystemExit("spec needs both 'record' and non-empty 'fields'")

    nodes = sel.css(record_css)
    records: list[dict] = []
    for n in nodes:
        rec = {}
        for name, css in fields.items():
            vals = [v.strip() for v in n.css(css).getall() if v and v.strip()]
            rec[name] = vals[0] if vals else None
        records.append(rec)

    filled = {f: sum(1 for r in records if r.get(f)) for f in fields}
    report = {
        "records": len(records),
        "fill_rate": {f: round(filled[f] / len(records), 3) if records else 0.0 for f in fields},
        "complete_records": sum(1 for r in records if all(r.get(f) for f in fields)),
    }
    return records, report


def verdict(report: dict) -> tuple[bool, list[str]]:
    """Deterministic pass/fail plus actionable reasons — the loop's feedback signal."""
    problems: list[str] = []
    if report["records"] == 0:
        problems.append("record selector matched 0 nodes — wrong container")
    elif report["records"] == 1:
        problems.append("record selector matched exactly 1 node — likely the page, not a row")
    for f, rate in report["fill_rate"].items():
        if rate == 0.0:
            problems.append(f"field {f!r} never filled — selector wrong or wrong scope")
        elif rate < 0.9:
            problems.append(f"field {f!r} filled only {rate:.0%} — partial match")
    return (not problems), problems


def main() -> None:
    ap = argparse.ArgumentParser(description="Execute a selector spec against a frozen capture.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--capture", default=None, help="capture id; defaults to pins.toml")
    ap.add_argument("--spec", required=True, help="path to spec JSON")
    ap.add_argument("--show", type=int, default=3)
    args = ap.parse_args()

    cur = resolve(args.target, args.capture)
    cap = cur.path
    html = cur.artifact("rendered.html").read_text(errors="replace")
    spec = json.loads(Path(args.spec).read_text())

    records, report = run_spec(html, spec)
    ok, problems = verdict(report)

    print(f"capture   {cap.name}")
    print(f"record    {spec['record']!r} → {report['records']} nodes")
    for f, rate in report["fill_rate"].items():
        print(f"  {f:<12} {rate:>6.0%}   {spec['fields'][f]}")
    print(f"complete  {report['complete_records']}/{report['records']}")
    print(f"verdict   {'PASS' if ok else 'FAIL'}")
    for p in problems:
        print(f"  ! {p}")
    if records:
        print("\nsample:")
        for r in records[: args.show]:
            print(f"  {json.dumps(r, ensure_ascii=False)[:150]}")


if __name__ == "__main__":
    main()
