"""Verify an installed CLI against an exact local HTTP document and typed pipe."""

import argparse
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DOCUMENT = b"<html><h1>Yosoi installation verified</h1></html>"


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(DOCUMENT)))
        self.end_headers()
        self.wfile.write(DOCUMENT)

    def log_message(self, *_args):
        pass


def verify_installation(executable: Path, version: str) -> None:
    binary = str(executable.resolve(strict=True))

    def run(*args, content=None):
        return subprocess.run(
            [binary, *args], input=content, check=True, capture_output=True, timeout=30
        ).stdout

    if run("--version").strip() != f"yosoi {version}".encode():
        raise ValueError("Installed CLI version mismatch")
    server = HTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        if run("request", url, "--raw") != DOCUMENT:
            raise ValueError("Installed CLI did not return the exact fixture document")
        frame = run("request", url, "--pipe-document")
        located = run(
            "locate", "--pipe-document", "--css", "h1", "--json", content=frame
        )
        if b"Yosoi installation verified" not in located:
            raise ValueError("Installed Request/Locate pipeline failed")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    print("Installed CLI version, exact HTTP document, and typed pipeline passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    verify_installation(args.executable, args.version)
