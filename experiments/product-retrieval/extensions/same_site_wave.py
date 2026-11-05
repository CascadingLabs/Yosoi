"""Compare manually selected same-site references on disjoint target pages.

The dataset has one template family per site. This is a reference-source factor,
not evidence of an automatic template detector or a blind evaluation.
"""

import argparse
import json
import os
from pathlib import Path

from run_wave import run


def heldout_cases(source):
    config = json.loads((source / "frozen.json").read_text())
    cases = json.loads((source / "corpus.json").read_text())["cases"]
    groups = {group["id"]: set(group["cases"]) for group in config["reference_groups"]}
    selected = []
    for case in cases:
        if case["split"] != "fresh_cross_site":
            continue
        group = case["family"] + "/2"
        if group not in groups:
            raise ValueError("site's two-reference group is not declared")
        if case["id"] not in groups[group]:
            selected.append(
                {"case": case["id"], "family": case["family"], "group": group}
            )
    return selected


def link_view(directory, target):
    target.mkdir(parents=True, exist_ok=True)
    for name in ("summary.json", "shard-complete.json"):
        destination = target / name
        if not destination.exists():
            os.link(directory / name, destination)


def compare(source, inputs, foreign, destination):
    targets = heldout_cases(source)
    if not targets:
        raise ValueError("no disjoint site targets")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "target-plan.json").write_text(
        json.dumps(
            {
                "targets": targets,
                "reference_selection": (
                    "manually supplied site/template groups; not "
                    "inferred from target field gold"
                ),
                "population": (
                    "last two pages per site, disjoint from first two reference pages"
                ),
                "limitations": [
                    "One template per site confounds host and template.",
                    (
                        "Agent-annotated toy shop source HTML, not blind "
                        "human gold or live DOM."
                    ),
                    (
                        "Fields absent in both references do not establish "
                        "absence on future pages."
                    ),
                ],
            },
            indent=2,
        )
    )
    completed = []
    foreign_completed = []
    for target in targets:
        local_wave = destination / "cases" / target["case"]
        run(
            source,
            {slug: inputs / f"{slug}-v1.json" for slug in ("minilm", "bge-small")},
            local_wave,
            case=target["case"],
            group=target["group"],
        )
        for slug in ("minilm", "bge-small"):
            actual = local_wave / slug / target["case"]
            link_view(actual, destination / "same-site-view" / slug / target["case"])
            old = foreign / slug / target["case"]
            if not (old / "shard-complete.json").exists():
                raise ValueError("foreign comparison shard is not complete")
            link_view(old, destination / "foreign-view" / slug / target["case"])
            entry = {
                "model": slug,
                "case": target["case"],
                "raw_source_directory": str(actual),
            }
            completed.append(entry)
            foreign_completed.append({**entry, "raw_source_directory": str(old)})
        print(
            json.dumps(
                {
                    "case": target["case"],
                    "completed_targets": len(completed) // 2,
                    "total_targets": len(targets),
                }
            ),
            flush=True,
        )
    for view, entries in (
        ("same-site-view", completed),
        ("foreign-view", foreign_completed),
    ):
        (destination / view / "wave-complete.json").write_text(
            json.dumps({"completed": entries}, indent=2)
        )
    from aggregate_wave import aggregate

    aggregate(destination / "same-site-view", destination / "same-site-aggregate")
    aggregate(destination / "foreign-view", destination / "foreign-aggregate")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--foreign-wave", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compare(args.source, args.input_dir, args.foreign_wave, args.output)
