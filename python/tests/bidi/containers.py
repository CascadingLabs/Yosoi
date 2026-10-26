"""Shared addresses for the single, test-only Compose project."""

import os
import subprocess
from pathlib import Path

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).with_name("compose.yaml"))]


def compose(*arguments):
    return subprocess.check_output(
        [*COMPOSE, *arguments], text=True, env=os.environ | {"MOLI_HOST_PORT": "0"}
    ).strip()


def environment():
    blocked = compose("port", "blocked", "9222")
    return {
        "YOSOI_MOLI_ENDPOINT": f"ws://{compose('port', 'moli', '9222')}/session",
        "YOSOI_MOLI_BLOCKED_ENDPOINT": f"ws://{blocked}/session",
        "YOSOI_BIDI_FIXTURE_CONTAINER": compose("ps", "-q", "fixture"),
        "YOSOI_BIDI_FIXTURE_URL": "http://fixture:8080/optional-browser.html",
        "YOSOI_MOLI_RESOURCES": "1",
    }


if __name__ == "__main__":
    for name, value in environment().items():
        print(f"{name}={value}")
