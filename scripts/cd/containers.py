"""Smoke and publish the exact Chromium images built by CI, without rebuilding."""

import argparse
import json
import os
import selectors
import subprocess
import time
from pathlib import Path

ROWS = (("headless", "amd64"), ("headless", "arm64"), ("headful", "amd64"))


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def smoke(image, mode, output):
    name = f"chromium-cdp-smoke-{os.getpid()}"
    run(
        "docker",
        "create",
        "--name",
        name,
        "--init",
        "--network",
        "none",
        "--cpus",
        "1",
        "--memory",
        "2g",
        "--pids-limit",
        "512",
        "--shm-size",
        "1g",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        "seccomp=docker/browser/seccomp-chrome.json",
        image,
    )
    # Subscribe before startup; the snapshot covers an event delivered before select.
    events = subprocess.Popen(
        ["docker", "events", "--filter", f"container={name}", "--format", "{{json .}}"],
        stdout=subprocess.PIPE,
        text=False,
    )
    try:
        run("docker", "start", name)
        deadline = time.monotonic() + 120
        with selectors.DefaultSelector() as ready:
            ready.register(events.stdout, selectors.EVENT_READ)
            while True:
                state = json.loads(
                    run("docker", "inspect", "--format", "{{json .State}}", name)
                )
                health = state.get("Health", {}).get("Status")
                if health == "healthy":
                    break
                if health == "unhealthy" or not state["Running"]:
                    raise RuntimeError(f"Container failed startup: {state}")
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not ready.select(remaining):
                    raise TimeoutError("Container did not become healthy")
                if not os.read(events.stdout.fileno(), 65536):
                    raise RuntimeError("Docker event stream ended")
        evidence = json.loads(
            run(
                "docker",
                "exec",
                name,
                "python3",
                "-c",
                r"""
import hashlib, json, os, pathlib, urllib.request
assert os.getuid() == 10001
config = pathlib.Path('/tmp/yosoi/config/supervisord.conf').read_text()
for forbidden in ('--no-sandbox', '--disable-gpu-sandbox',
                  '--disable-web-security', '--disable-site-isolation'):
    assert forbidden not in config, forbidden
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
versions = []
for index in range(int(os.environ['BROWSER_COUNT'])):
    port = int(os.environ['CDP_PORT_BASE']) + index
    with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
        versions.append(json.load(response)['Browser'])
assert all(version == 'Chrome/154.0.8037.92' for version in versions), versions
renderers = []
for process in pathlib.Path('/proc').iterdir():
    if process.name.isdigit():
        try:
            command = (process/'cmdline').read_bytes()
            if b'--type=renderer' in command.replace(b'\0', b' ').split():
                status = (process/'status').read_text()
                filters = int(next(line.split()[1] for line in status.splitlines()
                                   if line.startswith('Seccomp_filters:')))
                assert filters >= 2, status
                renderers.append(int(process.name))
        except FileNotFoundError:
            pass
assert len(renderers) >= int(os.environ['BROWSER_COUNT']), renderers
assert not pathlib.Path('/tmp/yosoi/viewer/lease.env').exists()
print(json.dumps(dict(versions=versions, sandboxed_renderers=len(renderers),
    executable_sha256=hashlib.sha256(pathlib.Path('/usr/lib/chromium/chromium').read_bytes()).hexdigest(),
    distribution=pathlib.Path('/usr/share/chromium-cdp/browser-version').read_text().strip())))
""",
            )
        )
        evidence.update(
            image=image,
            image_id=run("docker", "image", "inspect", "--format", "{{.Id}}", image),
            mode=mode,
        )
        Path(output).write_text(json.dumps(evidence, indent=2) + "\n")
    except Exception:
        subprocess.run(["docker", "logs", "--tail", "100", name], check=False)
        raise
    finally:
        events.terminate()
        events.wait(timeout=10)
        subprocess.run(
            ["docker", "rm", "-f", name], check=True, stdout=subprocess.DEVNULL
        )


def publish(directory, version, repository):
    if not repository.startswith("ghcr.io/") or "/" not in repository[8:]:
        raise ValueError("Expected a GHCR repository")
    import re

    if not re.fullmatch(r"0\.\d+\.\d+(?:-rc\.[1-9]\d*)?", version):
        raise ValueError("Invalid release version")
    directory = Path(directory)
    # Validate the complete set before writing any remote tag.
    images = []
    for mode, arch in ROWS:
        evidence = json.loads((directory / f"{mode}-{arch}.json").read_text())
        archive = directory / f"{mode}-{arch}.tar"
        run("docker", "load", "--input", str(archive))
        actual = run(
            "docker", "image", "inspect", "--format", "{{.Id}}", evidence["image"]
        )
        if actual != evidence["image_id"] or evidence["mode"] != mode:
            raise ValueError("Archive differs from smoke-tested image")
        images.append((mode, arch, evidence))
    for mode, arch, evidence in images:
        target = f"{repository}:{mode}-{version}-{arch}"
        # Never overwrite a versioned tag, including after a partial publication.
        existing = subprocess.run(
            ["docker", "manifest", "inspect", target],
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0:
            manifest = json.loads(existing.stdout)
            if manifest.get("config", {}).get("digest") != evidence["image_id"]:
                raise ValueError(f"Existing tag has different bytes: {target}")
        else:
            if (
                "manifest unknown" not in existing.stderr.lower()
                and "not found" not in existing.stderr.lower()
            ):
                raise RuntimeError(existing.stderr)
            run("docker", "tag", evidence["image"], target)
            run("docker", "push", target)
    for mode in ("headless", "headful"):
        sources = [
            f"{repository}:{mode}-{version}-{arch}"
            for row_mode, arch in ROWS
            if row_mode == mode
        ]
        digests = {
            run(
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                source,
                "--format",
                "{{.Manifest.Digest}}",
            )
            for source in sources
        }
        target = f"{repository}:{mode}-{version}"
        existing = subprocess.run(
            ["docker", "manifest", "inspect", target],
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0:
            manifest = json.loads(existing.stdout)
            if {item["digest"] for item in manifest.get("manifests", [])} != digests:
                raise ValueError(f"Existing index has different bytes: {target}")
        else:
            if (
                "manifest unknown" not in existing.stderr.lower()
                and "not found" not in existing.stderr.lower()
            ):
                raise RuntimeError(existing.stderr)
            # Buildx normally collapses one source into a single image; prefer an
            # index for both variants so immutable reruns use the same check.
            run(
                "docker",
                "buildx",
                "imagetools",
                "create",
                "--prefer-index=true",
                "--tag",
                target,
                *sources,
            )
        # Anonymous pull must work; a private default package cannot count as published.
        config = directory / "anonymous-docker"
        config.mkdir(exist_ok=True)
        run("docker", "--config", str(config), "manifest", "inspect", target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser("smoke")
    test.add_argument("--image", required=True)
    test.add_argument("--mode", choices=("headless", "headful"), required=True)
    test.add_argument("--output", required=True)
    upload = commands.add_parser("publish")
    upload.add_argument("--directory", required=True)
    upload.add_argument("--version", required=True)
    upload.add_argument("--repository", required=True)
    args = parser.parse_args()
    if args.command == "smoke":
        smoke(args.image, args.mode, args.output)
    else:
        publish(args.directory, args.version, args.repository)


if __name__ == "__main__":
    main()
