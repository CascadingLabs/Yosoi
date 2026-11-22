"""Run the isolated native-provider N-tab A/V fixture and collect browser streams."""

import argparse
import json
import os
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from surface_record import line, owned_processes

TEST = "internal::browser::integration_tests::tab_av_spike::concurrent_tab_av_spike"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-binary", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--tabs", type=int, choices=[2, 3, 4], default=2)
    parser.add_argument(
        "--youtube",
        action="store_true",
        help="Use two real videos in separate contexts",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.youtube and args.tabs != 2:
        parser.error("The YouTube isolation experiment uses exactly two tabs")
    args.output.mkdir(parents=True, exist_ok=False)
    sequences = [0] * args.tabs
    lock = threading.Lock()
    phase = threading.Event()
    running = {}
    fixture = (Path(__file__).parent / "tab-av.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/tab":
                body = fixture
            elif path == "/control":
                body = (
                    b"<!doctype html><title>Yosoi capture control</title>"
                    b"<body style='background:#211831;color:white;font:32px system-ui'>"
                    b"<h1>Control tab is foreground</h1>"
                    b"<p>All source tabs continue recording in the background.</p>"
                )
                phase.set()
                if "pid" in running:
                    with lock:
                        (args.output / "owned-processes.json").write_text(
                            json.dumps(owned_processes(running["pid"]), indent=2)
                        )
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            parts = self.path.strip("/").split("/")
            try:
                size = int(self.headers.get("Content-Length", "0"))
                index = int(parts[1])
                if not (0 < size <= 8 * 1024 * 1024 and 0 <= index < args.tabs):
                    raise ValueError("invalid upload")
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError("incomplete upload")
                with lock:
                    if parts[0] == "chunk" and len(parts) == 3:
                        sequence = int(parts[2])
                        if sequence != sequences[index]:
                            raise ValueError("out-of-order chunk")
                        if sequence == 0 and not body.startswith(
                            bytes.fromhex("1a45dfa3")
                        ):
                            raise ValueError("WebM header required")
                        with (args.output / f"tab-{index}.webm").open("ab") as stream:
                            stream.write(body)
                        sequences[index] += 1
                    elif parts[0] == "result" and len(parts) == 2:
                        result = json.loads(body)
                        (args.output / f"tab-{index}.json").write_text(
                            json.dumps(result, indent=2)
                        )
                    else:
                        raise ValueError("invalid route")
            except (ValueError, IndexError, KeyError):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    children, module = [], None

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
                "1280x720x24",
                "-dpi",
                "96",
                "-nolisten",
                "tcp",
                pass_fds=(write_fd,),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            os.close(write_fd)
        with os.fdopen(read_fd, "rb", buffering=0) as stream:
            display_number = line(stream, 15).decode().strip()
        if not display_number.isdigit():
            raise RuntimeError("Xvfb readiness failed")
        sink = f"yosoi_av_{os.getpid()}"
        module = subprocess.check_output(
            ["pactl", "load-module", "module-null-sink", f"sink_name={sink}"], text=True
        ).strip()
        environment = dict(
            os.environ,
            CHROME=str(args.chrome),
            DISPLAY=":" + display_number,
            PULSE_SINK=sink,
            GDK_BACKEND="x11",
            XDG_SESSION_TYPE="x11",
            YOSOI_TAB_AV_ORIGIN=origin,
            YOSOI_TAB_AV_OUTPUT=str(args.output),
            YOSOI_TAB_AV_COUNT=str(args.tabs),
            RAYON_NUM_THREADS="1",
        )
        environment.pop("WAYLAND_DISPLAY", None)
        # Bound the entire browser/capture experiment to one logical CPU.
        cpu = min(os.sched_getaffinity(0))
        test = (
            TEST.replace("concurrent_tab_av_spike", "youtube::youtube_tab_av_spike")
            if args.youtube
            else TEST
        )
        command = [
            "taskset",
            "-c",
            str(cpu),
            str(args.test_binary),
            test,
            "--ignored",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ]
        (args.output / "conditions.json").write_text(
            json.dumps(
                {
                    "tabs": args.tabs,
                    "mode": "youtube" if args.youtube else "fixture",
                    "origin": origin,
                    "display": ":" + display_number,
                    "cpu_affinity": [cpu],
                    "resolution_requested": "640x360",
                    "fps_requested": 30,
                    "duration_requested_ms": 26000 if args.youtube else 16000,
                    "capture_grant": "auto-accept-this-tab-capture",
                    "scope": (
                        "two authorized YouTube sources; no microphone or camera"
                        if args.youtube
                        else "isolated fixture tabs only; no microphone or camera"
                    ),
                },
                indent=2,
            )
        )
        with (args.output / "native.log").open("w") as log:
            process = spawn(
                *command, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
            running["pid"] = process.pid

            def completed():
                process.wait()
                phase.set()

            waiter = threading.Thread(target=completed, daemon=True)
            waiter.start()
            if not phase.wait(timeout=90):
                raise TimeoutError("Control tab was not reached")
            if process.poll() is None:
                (args.output / "owned-processes.json").write_text(
                    json.dumps(owned_processes(process.pid), indent=2)
                )
            code = process.wait(timeout=120)
            waiter.join(timeout=5)
        if code:
            raise RuntimeError(
                f"native probe failed ({code}); see {args.output / 'native.log'}"
            )
        report = json.loads((args.output / "browser-report.json").read_text())
        if len(report["results"]) != args.tabs:
            raise RuntimeError("missing per-tab results")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "tabs": args.tabs,
                    "results": report["results"],
                },
                indent=2,
            )
        )
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        if module is not None:
            subprocess.run(["pactl", "unload-module", module], check=True)


if __name__ == "__main__":
    main()
