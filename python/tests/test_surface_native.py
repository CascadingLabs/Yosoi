"""Opt-in real native Session consumption over an isolated loopback fixture."""

from __future__ import annotations

import asyncio
import os
import unittest

import yosoi as ys


async def target(source: ys.surface.BrowserSurface, query: str) -> dict:
    page = await source.execute({"op": "find", "query": query})
    entry = page["entries"][0]
    if entry["kind"] == "text":
        return await source.execute({"op": "parent", "reference": entry["reference"]})
    return entry["reference"]


@unittest.skipUnless(
    os.environ.get("YOSOI_BROWSER_TESTS") == "1"
    and hasattr(ys._native, "surface_browser_consume_session"),
    "requires an explicit browser test grant and the current native extension",
)
class NativeSurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_facades_and_work_transfer_use_one_retained_native_session(self):
        body = b'''<!doctype html><h1>Native Python</h1><input aria-label="Message" value="existing"><button onclick="this.nextElementSibling.textContent='Clicked'">Click here</button><p>Ready</p>'''

        async def serve(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + body
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        async with server:
            async with ys.browser.session() as browser:
                self.assertIs(
                    ys.browser.surface.consume_session, ys.surface.consume_session
                )
                source = await ys.browser.surface.consume_session(browser)
                try:
                    ready = await source.ready()
                    self.assertEqual(ready["source"]["backend"], "native_session")
                    await source.execute({"op": "attach"})
                    await source.execute(
                        {"op": "focus", "reference": ready["state"]["root"]}
                    )
                    await source.execute({"op": "hot"})
                    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
                    result = await source.execute(
                        {"op": "navigate", "reference": ready["state"]["root"], "url": url}
                    )
                    self.assertEqual(result["receipt"]["status"], "Confirmed")
                    field = await target(source, "Message")
                    result = await source.execute(
                        {"op": "fill", "reference": field, "text": "replacement"}
                    )
                    self.assertEqual(result["receipt"]["status"], "Confirmed")
                    self.assertEqual(result["outcome"]["value"]["characters"], 11)
                    button = await target(source, "Click here")
                    result = await source.execute(
                        {"op": "click", "reference": button, "expect": {
                            "kind": "text", "text": "Clicked", "present": True}}
                    )
                    self.assertEqual(result["receipt"]["status"], "Confirmed")
                finally:
                    await source.close()
                work = browser.work()
                source = await ys.surface.BrowserSurface.consume_work(work)
                try:
                    self.assertTrue(work._released)
                    self.assertEqual(
                        (await source.ready())["source"]["backend"], "native_session"
                    )
                finally:
                    await source.close()
                async with browser.work():
                    pass


if __name__ == "__main__":
    unittest.main()
