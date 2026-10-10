"""Reuse exact-source main CI rather than repeating it when a tag is pushed."""

from __future__ import annotations

import argparse
import json
import re
import subprocess

WORKFLOWS = ("rust-ci-test.yml", "python-ci.yml")


def select_run(runs: list[dict], source: str, workflow: str) -> dict:
    matching = [
        run
        for run in runs
        if run.get("head_sha") == source
        and run.get("head_branch") == "main"
        and run.get("event") == "push"
        and run.get("path") == f".github/workflows/{workflow}"
    ]
    if not matching:
        raise ValueError(f"No main {workflow} run exists for {source}")
    # A newer failed/pending execution must not be hidden by an older success.
    return max(matching, key=lambda run: run["id"])


def require_success(run: dict) -> None:
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError(f"Source CI is not successful: {run['html_url']}")


def observe(endpoint: str, source: str, workflow: str) -> dict:
    response = subprocess.run(
        ["gh", "api", endpoint], check=True, capture_output=True, text=True
    )
    return select_run(json.loads(response.stdout)["workflow_runs"], source, workflow)


def check(repository: str, source: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected an owner/repository")
    if not re.fullmatch(r"[a-f0-9]{40}", source):
        raise ValueError("Expected a full source commit")
    for workflow in WORKFLOWS:
        endpoint = (
            f"repos/{repository}/actions/workflows/{workflow}/runs"
            f"?head_sha={source}&event=push&branch=main&per_page=100"
        )

        run = observe(endpoint, source, workflow)
        # Watch the same live run, never launch another build to establish proof.
        for _ in range(3):
            if run["status"] == "completed":
                break
            subprocess.run(
                [
                    "gh",
                    "run",
                    "watch",
                    str(run["id"]),
                    "--repo",
                    repository,
                    "--interval",
                    "30",
                    "--exit-status",
                ],
                check=False,
            )
            run = observe(endpoint, source, workflow)
        require_success(run)
        print(f"Verified exact-source main CI: {run['html_url']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    check(args.repository, args.source)
