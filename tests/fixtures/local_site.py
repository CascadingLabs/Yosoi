"""A real localhost HTTP server for tests that must exercise the transport, not a mock.

Charset resolution and crawl budgeting both depend on what actually comes back over HTTP —
raw bytes, the ``Content-Type`` header, and the number of requests the fetcher issues.
Mocking the response object hides exactly those things, so these tests serve real bytes
from a background ``ThreadingHTTPServer`` and let ``SimpleFetcher`` do a real round trip.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Route:
    """One served response: raw body bytes plus the exact ``Content-Type`` to send."""

    body: bytes
    content_type: str = 'text/html'
    status: int = 200


@dataclass
class LocalSite:
    """A running localhost site: its base URL and the request log it collected."""

    base_url: str
    requests: list[str] = field(default_factory=list)

    def url(self, path: str) -> str:
        return f'{self.base_url}{path}'


@contextmanager
def serve(routes: dict[str, Route]) -> Iterator[LocalSite]:
    """Serve ``routes`` on an ephemeral localhost port for the duration of the block."""
    site = LocalSite(base_url='')
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self) -> None:  # BaseHTTPRequestHandler dispatches on this exact name
            with lock:
                site.requests.append(self.path)
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(route.status)
            self.send_header('Content-Type', route.content_type)
            self.send_header('Content-Length', str(len(route.body)))
            self.end_headers()
            self.wfile.write(route.body)

        def log_message(self, *_args: object) -> None:
            """Silence the default stderr access log."""

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    site.base_url = f'http://127.0.0.1:{server.server_address[1]}'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield site
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
