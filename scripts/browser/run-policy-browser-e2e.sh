#!/usr/bin/env bash
# Run one SDK browser test with an explicit regular-Stable identity and owned display.
set -euo pipefail

if [ "$#" -ne 4 ]; then
  printf 'usage: %s <browser-executable> <sha256> <headless|headful> <exact-test-name>\n' "$0" >&2
  exit 64
fi
task_browser=$(realpath -- "$1")
task_expected_digest=$2
task_mode=$3
task_test_name=$4
case "$task_mode" in
  headless|headful) ;;
  *) printf 'unsupported test mode\n' >&2; exit 64 ;;
esac
task_actual_digest=$(sha256sum -- "$task_browser" | awk '{print $1}')
if [ "$task_actual_digest" != "$task_expected_digest" ]; then
  printf 'browser identity mismatch\n' >&2
  exit 1
fi
task_version=$("$task_browser" --version)
case "$task_version" in
  *'for Testing'*) printf 'testing-only browsers are prohibited\n' >&2; exit 1 ;;
  'Google Chrome '*|'Chromium '*) ;;
  *) printf 'unrecognized browser distribution\n' >&2; exit 1 ;;
esac
printf 'Browser: %s\nSHA-256: %s\nMode: %s\n' "$task_version" "$task_actual_digest" "$task_mode"

python3 - "$task_browser" "$task_mode" "$task_test_name" <<'PY'
import os
import re
import select
import subprocess
import sys

browser, mode, test_name = sys.argv[1:]
child_environment = os.environ.copy()
child_environment["CHROME"] = browser
child_environment["CHROME_NO_SANDBOX"] = "0"
child_environment["CARGO_BUILD_JOBS"] = "1"
child_environment["CMAKE_BUILD_PARALLEL_LEVEL"] = "1"
child_environment.setdefault("CARGO_PROFILE_TEST_DEBUG", "0")
display_server = None

try:
    if mode == "headful":
        display_server = subprocess.Popen(
            ["Xvfb", "-displayfd", "1", "-screen", "0", "1280x720x24", "-nolisten", "tcp"],
            stdout=subprocess.PIPE,
        )
        # Xvfb emits the allocated display only after its server is ready.
        # The timeout bounds a failed server; it is not the readiness signal.
        ready, _, _ = select.select([display_server.stdout], [], [], 15)
        if not ready:
            raise RuntimeError("Xvfb did not emit its readiness event")
        display = display_server.stdout.readline().decode("ascii").strip()
        if not display.isdecimal():
            raise RuntimeError("Xvfb exited without an allocated display")
        child_environment["DISPLAY"] = f":{display}"
        child_environment.pop("WAYLAND_DISPLAY", None)
        child_environment["XDG_SESSION_TYPE"] = "x11"

    command = [
        "cargo", "test", "-p", "yosoi", "--features", "browser",
        "--test", "policy_capture_browser", "--offline", "--jobs", "1",
        test_name, "--", "--exact", "--test-threads=1",
    ]
    result = subprocess.run(command, env=child_environment, stdout=subprocess.PIPE, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    if not re.search(r"test result: ok\. [1-9][0-9]* passed; 0 failed;", result.stdout):
        raise RuntimeError("browser test filter ran no passing tests")
finally:
    if display_server is not None:
        if display_server.poll() is None:
            display_server.terminate()
        try:
            display_server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            display_server.kill()
            display_server.wait()
PY
