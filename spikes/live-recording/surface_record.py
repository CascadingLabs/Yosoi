"""Record a private display owned by the native Yosoi Session/Work worker."""

import argparse
import contextlib
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path


def line(stream, timeout=90):
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        if not selector.select(timeout):
            raise TimeoutError("Child did not reply before deadline")
    value = stream.readline()
    if not value:
        raise RuntimeError("Child closed its output")
    return value


def owned_processes(parent):
    """Inspect only this worker's descendants, never other browser sessions."""
    result, pending, visited = [], [parent], set()
    while pending and len(result) < 128:
        pid = pending.pop()
        if pid in visited:
            continue
        visited.add(pid)
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            result.append(
                {"pid": pid, "argv": [part.decode() for part in command if part]}
            )
            # Children can be spawned from a Rust test/runtime worker thread.
            for task in Path(f"/proc/{pid}/task").iterdir():
                try:
                    pending.extend(
                        int(child) for child in (task / "children").read_text().split()
                    )
                except FileNotFoundError:
                    continue
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def demo(exchange, query):
    """Discover one live link through Surface, click natively and verify evidence."""

    def checked(command):
        reply = exchange(command)
        if not reply.get("ok"):
            raise RuntimeError(reply)
        return reply["result"]

    checked({"op": "attach"})
    found = checked({"op": "find", "query": query})
    selected = None
    for entry in found["entries"]:
        reference = entry["reference"]
        for _ in range(6):
            detail = checked({"op": "inspect", "reference": reference})
            if detail.get("next"):
                raise RuntimeError("Demo target inspection needs continuation")
            node = json.loads(detail["content"])
            if node.get("tag_name") == "a":
                guard = checked({"op": "eligibility", "reference": reference})
                native = guard["native"]
                if native["eligible"] and native["unchanged"]:
                    selected = reference
                break
            reference = checked({"op": "parent", "reference": reference})
            if reference is None:
                break
        if selected:
            break
    if selected is None:
        raise RuntimeError("No visible unchanged Surface link matches the query")
    clicked = checked({"op": "click", "reference": selected})
    if clicked["receipt"]["status"] != "Confirmed":
        raise RuntimeError(clicked)
    capture = clicked["observation"]["capture"]
    if clicked["receipt"]["after_capture"] != capture:
        raise RuntimeError("Click receipt does not name the destination capture")
    stale = exchange({"op": "eligibility", "reference": selected})
    if stale.get("ok"):
        raise RuntimeError("Previous capture unexpectedly retained live authority")
    scrolled = checked(
        {"op": "scroll", "reference": clicked["observation"]["root"], "delta_y": 650}
    )
    if scrolled["observed"]["after"] <= scrolled["observed"]["before"]:
        raise RuntimeError("Scroll did not change the observed position")
    final = checked({"op": "article"})
    if final["url"] != clicked["destination"]["url"]:
        raise RuntimeError("Final URL differs from confirmed destination")
    return {
        "query": query,
        "click": clicked,
        "stale_reference_rejected": True,
        "scroll": scrolled["observed"],
        "final_page": final,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--url", default="https://www.msnbc.com/")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--query", help="Run a bounded native Surface demo automatically"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    children = []
    recorder = None
    started = time.monotonic()
    transcript = []

    def spawn(*command, **kwargs):
        process = subprocess.Popen(command, start_new_session=True, **kwargs)
        children.append(process)
        return process

    try:
        read_fd, write_fd = os.pipe()
        try:
            spawn(
                "Xvfb",
                "-displayfd",
                str(write_fd),
                "-screen",
                "0",
                "1920x1080x24",
                "-dpi",
                "96",
                "-nolisten",
                "tcp",
                pass_fds=(write_fd,),
            )
        finally:
            os.close(write_fd)
        with os.fdopen(read_fd, "rb", buffering=0) as stream:
            display_number = line(stream, 15).decode().strip()
        if not display_number.isdigit():
            raise RuntimeError("Xvfb failed readiness")
        display = ":" + display_number
        environment = dict(
            os.environ,
            DISPLAY=display,
            GDK_BACKEND="x11",
            GDK_SCALE="1",
            GDK_DPI_SCALE="1",
            XDG_SESSION_TYPE="x11",
        )
        environment.pop("WAYLAND_DISPLAY", None)
        # Yosoi validates and launches the real executable itself.
        environment.update(CHROME=str(args.chrome), RAYON_NUM_THREADS="1")
        environment.pop("CHROMEDRIVER", None)
        with args.worker.open("rb") as binary:
            worker_digest = hashlib.file_digest(binary, "sha256").hexdigest()
        identity = {
            "browser": subprocess.check_output(
                [str(args.chrome), "--version"], text=True
            ).strip(),
            "controller": "Yosoi Session/Work → Chromiumoxide/CDP",
            "native_worker_sha256": worker_digest,
            "url": args.url,
            "display": display,
            "recording": "display.mp4",
            "capture": "FFmpeg x11grab, 1920x1080, 30fps",
        }
        (args.output / "identity.json").write_text(json.dumps(identity, indent=2))
        with (args.output / "capture.log").open("w") as capture_log:
            recorder = spawn(
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-n",
                "-progress",
                "pipe:1",
                "-nostats",
                "-threads",
                "1",
                "-f",
                "x11grab",
                "-video_size",
                "1920x1080",
                "-framerate",
                "30",
                "-i",
                display,
                "-an",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(args.output / "display.mp4"),
                stdout=subprocess.PIPE,
                stderr=capture_log,
                text=True,
                bufsize=1,
            )
            # Wait for encoded frames before launching the browser.
            while True:
                progress = line(recorder.stdout, 15).strip()
                if progress.startswith("frame=") and int(progress.split("=", 1)[1]) > 0:
                    break
            # Drain progress in a thread to avoid pipe backpressure.
            import threading

            threading.Thread(target=lambda: list(recorder.stdout), daemon=True).start()
            with (args.output / "surface-stderr.log").open("w") as error_log:
                surface = spawn(
                    str(args.worker),
                    "--url",
                    args.url,
                    "--output",
                    str(args.output / "surface"),
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=error_log,
                    text=True,
                    bufsize=1,
                )
                reply = line(surface.stdout)
                (args.output / "owned-processes.json").write_text(
                    json.dumps(owned_processes(surface.pid), indent=2)
                )
                print(reply, end="", flush=True)
                transcript.append(
                    {"at_s": time.monotonic() - started, "reply": json.loads(reply)}
                )

                def exchange(command):
                    surface.stdin.write(json.dumps(command) + "\n")
                    surface.stdin.flush()
                    reply = line(surface.stdout)
                    transcript.append(
                        {
                            "at_s": time.monotonic() - started,
                            "request": command,
                            "reply": json.loads(reply),
                        }
                    )
                    print(reply, end="", flush=True)
                    return json.loads(reply)

                if args.query:
                    try:
                        result = demo(exchange, args.query)
                        (args.output / "demo.json").write_text(
                            json.dumps(result, indent=2)
                        )
                    finally:
                        exchange({"op": "close"})
                        surface.wait(timeout=15)
                else:
                    for request in sys.stdin:
                        command = json.loads(request)
                        exchange(command)
                        if command.get("op") == "close":
                            surface.wait(timeout=15)
                            break
    finally:
        if recorder and recorder.poll() is None:
            recorder.send_signal(signal.SIGINT)
            recorder.wait(timeout=15)
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
        with contextlib.suppress(OSError):
            (args.output / "transcript.json").write_text(
                json.dumps(transcript, indent=2)
            )


if __name__ == "__main__":
    main()
