"""Bounded live-page layout capture over loopback CDP.

The probe stores browser response bytes, post-JavaScript DOM, generic
all-element box/font/style data, and a viewport screenshot separately. It does
not read retrieval gold or implement site-specific selectors.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / ".generated" / "product-retrieval-layout-v1"
DEFAULT_CHROME = Path("/usr/lib/chromium/chromium")
QSCRAPE_URL = "https://qscrape.dev/eshop/javascript/product/obj-001/"
FRESH_IDS = ("books-obsession", "webscraper-packard-255-g2", "scrapeme-bulbasaur")
REVIEWED_IDENTITIES = {"Chromium 155.0.8059.84", "Chromium 155.0.8059.84 Arch Linux"}
VIEWPORT = {"width": 1920, "height": 1080, "device_scale_factor": 1.0}
PAGE_TIMEOUT = 30.0
OVERALL_TIMEOUT = 150.0
MAX_EVENTS = 4096
MAX_RESOURCES = 512
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_RENDERED_BYTES = 2 * 1024 * 1024
MAX_LAYOUT_BYTES = 8 * 1024 * 1024
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_ELEMENTS = 2000
MAX_ATTRIBUTES = 32
MAX_TEXT_CHARS = 240
MAX_ATTRIBUTE_CHARS = 160
CDP_MESSAGE_BYTES = 32 * 1024 * 1024
_DEFAULT_SESSION = object()
REVIEWED_AT = 1792800000
RELEASED_AT = 1792526230
MAX_AGE = 30 * 24 * 60 * 60
STYLE_PROPERTIES = (
    "display",
    "position",
    "visibility",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "line-height",
    "letter-spacing",
    "color",
    "background-color",
    "white-space",
    "text-align",
    "box-sizing",
    "opacity",
    "overflow-x",
    "overflow-y",
)


class CaptureError(RuntimeError):
    """A bounded capture failed or exceeded a declared limit."""


def build_capture_plan(
    fresh_manifest: Mapping[str, Any], qscrape_reference=None
) -> list[dict[str, Any]]:
    pages = fresh_manifest.get("pages")
    if not isinstance(pages, list):
        raise ValueError("fresh manifest has no pages list")
    by_id = {item.get("id"): item for item in pages if isinstance(item, Mapping)}
    missing = [case_id for case_id in FRESH_IDS if case_id not in by_id]
    if missing:
        raise ValueError(f"fresh manifest is missing cases: {missing}")
    plan = [
        {
            "case_id": "obj-001",
            "template": "javascript_product_detail",
            "url": QSCRAPE_URL,
            "capture_mode": "live_navigation",
            "saved_reference_kind": "archived_rendered_dom_not_raw_html",
            "saved_reference_sha256": None
            if qscrape_reference is None
            else qscrape_reference.get("payload_sha256"),
        }
    ]
    for case_id in FRESH_IDS:
        page = by_id[case_id]
        url = page.get("requested_url")
        if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError(f"fresh page {case_id} has an invalid URL")
        plan.append(
            {
                "case_id": case_id,
                "template": page.get("site_template"),
                "url": url,
                "capture_mode": "live_navigation",
                "saved_reference_kind": "saved_http_response_html",
                "saved_reference_file": page.get("file"),
                "saved_reference_sha256": page.get("sha256"),
                "saved_reference_retrieved_at_utc": page.get("retrieved_at_utc"),
            }
        )
    return plan


def load_capture_plan(repo_root: str | Path = REPO_ROOT) -> list[dict[str, Any]]:
    root = Path(repo_root)
    manifest_path = root / ".generated/product-retrieval-fresh/manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"fresh manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reference = None
    base_path = root / ".generated/product-retrieval-input/corpus.json"
    if base_path.is_file():
        base = json.loads(base_path.read_text(encoding="utf-8"))
        reference = next(
            (
                item
                for item in base.get("provenance", {}).get("source_checksums", [])
                if item.get("source_id") == "obj-001"
            ),
            None,
        )
    return build_capture_plan(manifest, reference)


def validated_viewport(value=None):
    viewport = dict(VIEWPORT if value is None else value)
    for key in ("width", "height"):
        dimension = viewport.get(key)
        if (
            isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or not 200 <= dimension <= 4096
        ):
            raise ValueError("viewport dimensions must be integers from 200 to 4096")
    if viewport.get("device_scale_factor") != 1.0:
        raise ValueError("this viewport experiment fixes device scale factor at one")
    return viewport


def build_chrome_args(
    executable: str | Path, profile: str | Path, port: int, viewport=None
) -> list[str]:
    viewport = validated_viewport(viewport)
    binary, user_data = Path(executable), Path(profile)
    if not binary.is_absolute() or not binary.is_file():
        raise ValueError("browser executable must be an existing absolute path")
    if not user_data.is_absolute() or not user_data.is_dir():
        raise ValueError("profile must be an existing temporary directory")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("CDP port must be nonzero and in range")
    args = [
        str(binary),
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--headless=new",
        f"--window-size={viewport['width']},{viewport['height']}",
        "--disable-breakpad",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-service-autorun",
        "--no-default-browser-check",
        "--no-pings",
        "--password-store=basic",
        "--disable-session-crashed-bubble",
        "--disable-search-engine-choice-screen",
        "--homepage=about:blank",
    ]
    if any(
        arg.startswith(
            (
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-site-isolation-trials",
            )
        )
        for arg in args
    ):
        raise ValueError("sandbox and site isolation must remain enabled")
    if any(arg.startswith("--load-extension") for arg in args):
        raise ValueError("capture must not load user extensions")
    return args


def layout_script() -> str:
    """Generic read-only element walk; no CSS/XPath or site selectors."""
    config = json.dumps(
        {
            "maxElements": MAX_ELEMENTS,
            "maxAttributes": MAX_ATTRIBUTES,
            "maxTextChars": MAX_TEXT_CHARS,
            "maxAttributeChars": MAX_ATTRIBUTE_CHARS,
            "maxBytes": MAX_LAYOUT_BYTES,
            "styles": STYLE_PROPERTIES,
        },
        separators=(",", ":"),
    )
    return f"""
(() => {{
const c={config},
all=document.getElementsByTagName('*'),
n=Math.min(all.length,
c.maxElements),
rows=[],
idx=new Map();

for(let i=0;
i<n;
i++)idx.set(all[i],
i);

const path=e=>{{const p=[];
for(let x=e;
x&&
x.nodeType===1;
x=x.parentElement){{let j=0;
for(let s=x.previousElementSibling;
s;
s=s.previousElementSibling)j++;
p.push(x.localName+'['+j+']')}}return p.reverse().join('/')}};

let estimate=0,
truncated=all.length>n;

for(let i=0;
i<n;
i++){{const e=all[i],
r=e.getBoundingClientRect(),
s=getComputedStyle(e),
a=[...e.attributes];
const attrs=a.slice(0,
c.maxAttributes).map(x=>({{name:x.name,
value:x.value.slice(0,
c.maxAttributeChars),
truncated:x.value.length>c.maxAttributeChars}})),
styles={{}};
for(const k of c.styles)styles[k]=s.getPropertyValue(k);
const t=(e.textContent||'').trim();
const row={{ordinal:i,
parentOrdinal:idx.has(e.parentElement)?idx.get(e.parentElement):null,
path:path(e),
tag:e.localName,
attributes:attrs,
attributesTotal:a.length,
attributesTruncated:a.length>c.maxAttributes,
text:t.slice(0,
c.maxTextChars),
textTruncated:t.length>c.maxTextChars,
box:{{x:r.x,
y:r.y,
width:r.width,
height:r.height,
top:r.top,
right:r.right,
bottom:r.bottom,
left:r.left}},
client:{{width:e.clientWidth,
height:e.clientHeight}},
scroll:{{width:e.scrollWidth,
height:e.scrollHeight}},
clientRectCount:e.getClientRects().length,
styles}};
const size=new TextEncoder().encode(JSON.stringify(row)).length;
if(estimate+size>c.maxBytes){{truncated=true;
break}}rows.push(row);
estimate+=size}}
return{{url:location.href,
title:document.title,
readyState:document.readyState,
fontStatus:document.fonts?document.fonts.status:'unsupported',
userAgent:navigator.userAgent,
platform:navigator.platform,
language:navigator.language,
webdriver:navigator.webdriver,
viewport:{{width:innerWidth,
height:innerHeight,
dpr:devicePixelRatio}},
screen:{{width:screen.width,
height:screen.height}},
totalElementCount:all.length,
retainedElementCount:rows.length,
nodesTruncated:truncated,
nodes:rows}};

}})()
"""


class CdpClient:
    """Sequential CDP request/response client with bounded event retention."""

    def __init__(self, websocket: Any, max_events: int = MAX_EVENTS) -> None:
        self.websocket, self.max_events = websocket, max_events
        self.session_id: str | None = None
        self.events: deque[dict[str, Any]] = deque()
        self.next_id, self.events_dropped = 0, 0

    async def command(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        session_id: Any = _DEFAULT_SESSION,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        message: dict[str, Any] = {
            "id": request_id,
            "method": method,
            "params": dict(params or {}),
        }
        session = self.session_id if session_id is _DEFAULT_SESSION else session_id
        if session is not None:
            message["sessionId"] = session
        await self.websocket.send(json.dumps(message, separators=(",", ":")))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"CDP command timed out: {method}")
            reply = json.loads(await asyncio.wait_for(self.websocket.recv(), remaining))
            if reply.get("id") == request_id:
                if reply.get("error"):
                    raise CaptureError(f"CDP {method} failed: {reply['error']}")
                result = reply.get("result", {})
                if not isinstance(result, dict):
                    raise CaptureError(f"CDP {method} returned a non-object")
                return result
            self._queue(reply)

    async def event(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            for index, event in enumerate(self.events):
                if event.get("sessionId") == self.session_id:
                    del self.events[index]
                    return event
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("CDP event wait timed out")
            event = json.loads(await asyncio.wait_for(self.websocket.recv(), remaining))
            if event.get("method") and event.get("sessionId") == self.session_id:
                return event
            self._queue(event)

    def _queue(self, event: Mapping[str, Any]) -> None:
        if not event.get("method"):
            return
        if len(self.events) >= self.max_events:
            self.events_dropped += 1
        else:
            self.events.append(dict(event))


async def _wait_page_ready(
    cdp: CdpClient, frame: str, loader: str | None, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    lifecycle: set[str] = set()
    request_types: dict[str, str] = {}
    requests, responses, failures = Counter(), Counter(), Counter()
    main_id: str | None = None
    main_response: dict[str, Any] = {"status": "unavailable"}
    source: bytes | None = None
    source_error: str | None = None
    redirects = 0
    event_count = 0
    while time.monotonic() < deadline:
        try:
            event = await cdp.event(max(0.05, deadline - time.monotonic()))
        except TimeoutError:
            break
        event_count += 1
        if event_count > MAX_EVENTS:
            break
        method, params = event.get("method"), event.get("params", {})
        if not isinstance(params, Mapping):
            continue
        if method == "Network.requestWillBeSent":
            rid, kind = params.get("requestId"), str(params.get("type", "Other"))
            if isinstance(rid, str):
                request_types[rid] = kind
                requests[kind] += 1
            if (
                kind == "Document"
                and params.get("frameId") == frame
                and (loader is None or params.get("loaderId") == loader)
            ):
                main_id = rid if isinstance(rid, str) else None
                redirects += int(bool(params.get("redirectResponse")))
        elif method == "Network.responseReceived":
            kind, response = (
                str(params.get("type", "Other")),
                params.get("response", {}),
            )
            responses[kind] += 1
            if (
                kind == "Document"
                and params.get("frameId") == frame
                and (loader is None or params.get("loaderId") == loader)
            ):
                main_response = {
                    "status": "response_received",
                    "url": _safe_url(str(response.get("url", ""))),
                    "status_code": response.get("status"),
                    "mime_type": response.get("mimeType"),
                    "headers": _safe_headers(response.get("headers", {})),
                    "from_disk_cache": response.get("fromDiskCache"),
                    "from_service_worker": response.get("fromServiceWorker"),
                }
        elif method == "Network.loadingFailed":
            rid = str(params.get("requestId"))
            failures[request_types.get(rid, "Other")] += 1
            if rid == main_id:
                main_response = {
                    "status": "request_failed",
                    "error_text": str(params.get("errorText", ""))[:200],
                }
        elif (
            method == "Network.loadingFinished"
            and params.get("requestId") == main_id
            and source is None
        ):
            encoded_size = params.get("encodedDataLength")
            if (
                isinstance(encoded_size, (int, float))
                and encoded_size > MAX_SOURCE_BYTES
            ):
                source_error = "encoded main response exceeds source cap"
            else:
                try:
                    body = await cdp.command(
                        "Network.getResponseBody", {"requestId": main_id}, timeout=5.0
                    )
                    raw = body.get("body")
                    source = (
                        base64.b64decode(raw, validate=True)
                        if body.get("base64Encoded") is True and isinstance(raw, str)
                        else raw.encode("utf-8")
                        if isinstance(raw, str)
                        else None
                    )
                    if source is not None and len(source) > MAX_SOURCE_BYTES:
                        source, source_error = (
                            None,
                            "decoded main response exceeds source cap",
                        )
                except Exception as error:
                    source_error = _safe_error(error)
        elif (
            method == "Page.lifecycleEvent"
            and params.get("frameId") == frame
            and (loader is None or params.get("loaderId") == loader)
        ):
            if isinstance(params.get("name"), str):
                lifecycle.add(params["name"])
        if "load" in lifecycle and ({"networkIdle", "networkAlmostIdle"} & lifecycle):
            break
    idle = (
        "networkIdle"
        if "networkIdle" in lifecycle
        else "networkAlmostIdle"
        if "networkAlmostIdle" in lifecycle
        else None
    )
    main_response.update(
        {
            "body_layer": "browser_decoded_response_representation",
            "body_state": "complete"
            if source is not None
            else "unavailable_or_over_budget",
            "body_error": source_error,
            "retained_bytes": 0 if source is None else len(source),
        }
    )
    return {
        "source_body": source,
        "source_response": main_response,
        "readiness": {
            "complete": "load" in lifecycle and idle is not None,
            "load_event": "load" in lifecycle,
            "idle_event": idle,
            "lifecycle_events": sorted(lifecycle),
            "event_count": event_count,
            "events_dropped": cdp.events_dropped,
            "timeout_seconds": timeout,
        },
        "network": {
            "requests_by_type": dict(requests),
            "responses_by_type": dict(responses),
            "failures_by_type": dict(failures),
            "redirect_count": redirects,
            "resources_truncated": sum(requests.values()) > MAX_RESOURCES,
            "resource_limit": MAX_RESOURCES,
        },
    }


def _fonts_expression() -> str:
    return (
        "document.fonts ? document.fonts.ready.then(() => document.fonts.status) "
        ": 'unsupported'"
    )


def _outer_html_expression() -> str:
    return f"""
(() => {{const html=document.documentElement?document.documentElement.outerHTML:'';
const max={MAX_RENDERED_BYTES},
enc=new TextEncoder(),
full=enc.encode(html).length;
let lo=0,
hi=html.length;
while(lo<hi){{const mid=Math.ceil((lo+hi)/2);
if(enc.encode(html.slice(0,
mid)).length<=max)lo=mid;
else hi=mid-1}}if(lo>0&&
html.charCodeAt(lo-1)>=0xd800&&
html.charCodeAt(lo-1)<=0xdbff)lo--;
return{{html:html.slice(0,
lo),
completeBytes:full,
truncated:lo<html.length}}}})()
"""


def _admitted(identity: str) -> bool:
    now = time.time()
    return (
        identity in REVIEWED_IDENTITIES
        and REVIEWED_AT <= now
        and now - REVIEWED_AT <= MAX_AGE
        and now - RELEASED_AT <= MAX_AGE
    )


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = (
        int.from_bytes(data[16:20], "big"),
        int.from_bytes(data[20:24], "big"),
    )
    return (width, height) if width > 0 and height > 0 else None


def _safe_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.hostname:
        return value
    host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    authority = host if parts.port is None else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, authority, parts.path, "", ""))


def _safe_headers(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    allowed = {"content-type", "content-length", "cache-control", "last-modified"}
    return {
        str(key).lower(): str(item)[:200]
        for key, item in value.items()
        if str(key).lower() in allowed
    }


def _redact_command_line(command_line: Any, profile: Path, port: int) -> list[str]:
    if not isinstance(command_line, str):
        return []
    result = []
    for arg in command_line.split():
        if arg.startswith("--user-data-dir=") or str(profile) in arg:
            result.append("--user-data-dir=<TEMP_PROFILE>")
        elif arg.startswith("--remote-debugging-port="):
            result.append("--remote-debugging-port=<EPHEMERAL_LOOPBACK_PORT>")
        else:
            result.append(arg)
    return result


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _safe_error(error: Exception) -> str:
    message = str(error).split("?", 1)[0].split("#", 1)[0]
    return f"{type(error).__name__}: {message[:300]}"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False))


def _terminate_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


async def _wait_process(process: asyncio.subprocess.Process, timeout: float) -> bool:
    try:
        await asyncio.wait_for(process.wait(), timeout)
        return True
    except TimeoutError:
        return False


async def _close_browser(
    process: asyncio.subprocess.Process, cdp: CdpClient | None, target_id: str | None
) -> dict[str, Any]:
    errors = []
    if cdp is not None:
        try:
            if target_id:
                await cdp.command(
                    "Target.closeTarget",
                    {"targetId": target_id},
                    session_id=None,
                    timeout=2.0,
                )
            await cdp.command("Browser.close", session_id=None, timeout=2.0)
        except Exception as error:
            errors.append(_safe_error(error))
    reaped = await _wait_process(process, 5.0)
    if not reaped:
        _terminate_group(process.pid, signal.SIGTERM)
        reaped = await _wait_process(process, 2.0)
    if not reaped:
        _terminate_group(process.pid, signal.SIGKILL)
        reaped = await _wait_process(process, 2.0)
    if not reaped:
        errors.append("owned browser process group did not reap")
    return {
        "status": "complete" if reaped else "failed",
        "browser_process_reaped": reaped,
        "errors": errors,
    }


def _slug(value):
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise ValueError("invalid capture case ID")
    return value


async def _evaluate(cdp, expression, *, promise=False, timeout=10):
    reply = await cdp.command(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": promise,
        },
        timeout=timeout,
    )
    if reply.get("exceptionDetails"):
        raise CaptureError("page expression raised an exception")
    return reply.get("result", {}).get("value")


async def _await_fonts(cdp, session, timeout):
    try:
        value = await _evaluate(cdp, _fonts_expression(), promise=True, timeout=timeout)
        return {"status": value, "timeout_seconds": timeout}
    except TimeoutError:
        return {"status": "timeout", "timeout_seconds": timeout}


async def _document_identity(cdp, session):
    return await _evaluate(
        cdp, "({url:location.href,timeOrigin:performance.timeOrigin})"
    )


async def _capture_page_data(cdp, session, out):
    dom = await _evaluate(cdp, _outer_html_expression())
    if not isinstance(dom, dict) or not isinstance(dom.get("html"), str):
        raise CaptureError("rendered DOM expression returned no HTML")
    raw = dom["html"].encode()
    if len(raw) > MAX_RENDERED_BYTES:
        raise CaptureError("rendered DOM exceeded byte cap")
    (out / "rendered-dom.html").write_bytes(raw)
    layout = await _evaluate(cdp, layout_script())
    layout_raw = _json_bytes(layout)
    if len(layout_raw) > MAX_LAYOUT_BYTES + 4096:
        raise CaptureError("element layout exceeded byte cap")
    (out / "element-layout.json").write_bytes(layout_raw)
    metrics = await cdp.command("Page.getLayoutMetrics")
    _write_json(out / "layout-metrics.json", metrics)
    png_result = await cdp.command(
        "Page.captureScreenshot",
        {
            "format": "png",
            "captureBeyondViewport": False,
        },
    )
    png = base64.b64decode(png_result.get("data", ""), validate=True)
    if len(png) > MAX_PNG_BYTES or _png_dimensions(png) is None:
        raise CaptureError("viewport screenshot invalid or over budget")
    (out / "viewport.png").write_bytes(png)
    after = await _evaluate(cdp, _outer_html_expression())
    stable = dom == after
    return {
        "rendered_dom": {
            "status": "truncated" if dom["truncated"] else "complete",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "complete_bytes": dom["completeBytes"],
        },
        "element_layout": {
            "status": "truncated" if layout["nodesTruncated"] else "complete",
            "sha256": hashlib.sha256(layout_raw).hexdigest(),
            "bytes": len(layout_raw),
            "elements": layout["retainedElementCount"],
            "total_elements": layout["totalElementCount"],
        },
        "screenshot": {
            "status": "complete",
            "sha256": hashlib.sha256(png).hexdigest(),
            "bytes": len(png),
            "dimensions": _png_dimensions(png),
        },
        "rendered_dom_stable_across_capture": stable,
    }


async def _launch_and_capture_one(
    spec: Mapping[str, Any],
    *,
    chrome: Path,
    output_root: Path,
    timeout: float,
    connect: Any,
    viewport: Mapping[str, Any],
) -> dict[str, Any]:
    out = output_root / _slug(str(spec["case_id"]))
    out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="yosoi-layout-profile-") as profile_name:
        profile = Path(profile_name)
        port = _reserve_port()
        process = await asyncio.create_subprocess_exec(
            *build_chrome_args(chrome, profile, port, viewport),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        endpoint_task = asyncio.create_task(_read_devtools_endpoint(process))
        result: dict[str, Any] = {
            "case_id": spec["case_id"],
            "template": spec.get("template"),
            "capture_mode": "live_navigation",
            "requested_url": _safe_url(str(spec["url"])),
            "saved_reference_kind": spec.get("saved_reference_kind"),
            "saved_reference_sha256": spec.get("saved_reference_sha256"),
            "status": "starting",
        }
        cdp = None
        websocket = None
        target_id = None
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        try:
            endpoint, drain_task = await asyncio.wait_for(
                asyncio.shield(endpoint_task), 15.0
            )
            websocket = await connect(
                endpoint,
                open_timeout=10.0,
                close_timeout=2.0,
                max_size=CDP_MESSAGE_BYTES,
                proxy=None,
            )
            cdp = CdpClient(websocket)
            version = await cdp.command("Browser.getVersion")
            system = await cdp.command("SystemInfo.getInfo")
            created = await cdp.command(
                "Target.createTarget", {"url": "about:blank", "background": False}
            )
            target_id = created.get("targetId")
            if not isinstance(target_id, str):
                raise CaptureError("browser did not create a page target")
            attached = await cdp.command(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
            session = attached.get("sessionId")
            if not isinstance(session, str):
                raise CaptureError("browser did not attach a page session")
            cdp.session_id = session
            await cdp.command("Page.enable", session_id=session)
            await cdp.command(
                "Network.enable",
                {
                    "maxTotalBufferSize": MAX_SOURCE_BYTES,
                    "maxResourceBufferSize": MAX_SOURCE_BYTES,
                },
                session_id=session,
            )
            await cdp.command(
                "Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=session
            )
            await cdp.command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": viewport["width"],
                    "height": viewport["height"],
                    "deviceScaleFactor": viewport["device_scale_factor"],
                    "mobile": False,
                    "screenWidth": viewport["width"],
                    "screenHeight": viewport["height"],
                    "screenX": 0,
                    "screenY": 0,
                },
                session_id=session,
            )
            nav = await cdp.command(
                "Page.navigate", {"url": str(spec["url"])}, session_id=session
            )
            frame, loader = nav.get("frameId"), nav.get("loaderId")
            if not isinstance(frame, str) or nav.get("errorText"):
                raise CaptureError(
                    f"navigation failed: {nav.get('errorText', 'missing frame ID')}"
                )
            ready = await _wait_page_ready(
                cdp, frame, loader if isinstance(loader, str) else None, timeout
            )
            result["browser"] = {
                "identity": version.get("product"),
                "user_agent": version.get("userAgent"),
                "protocol_version": version.get("protocolVersion"),
                "js_version": version.get("jsVersion"),
                "executable": str(chrome),
                "executable_sha256": _sha256_file(chrome),
                "command_line": _redact_command_line(
                    system.get("commandLine", ""), profile, port
                ),
                "viewport": dict(viewport),
                "sandbox_disabled": False,
                "site_isolation_overridden": False,
            }
            result["readiness"], result["network"], result["source_response"] = (
                ready["readiness"],
                ready["network"],
                ready["source_response"],
            )
            if ready.get("source_body") is not None:
                body = ready["source_body"]
                path = out / "current-source-response.html"
                path.write_bytes(body)
                result["source_response"].update(
                    {"artifact": path.name, "sha256": hashlib.sha256(body).hexdigest()}
                )
            result["font_wait"] = await _await_fonts(cdp, session, 5.0)
            before = await _document_identity(cdp, session)
            result.update(await _capture_page_data(cdp, session, out))
            after = await _document_identity(cdp, session)
            result["document_scope_check"] = {
                "before": before,
                "after": after,
                "same_document": before == after,
            }
            response = result["source_response"]
            success = (
                ready["readiness"]["complete"]
                and response.get("body_state") == "complete"
                and 200 <= response.get("status_code", 0) < 300
                and result["rendered_dom"]["status"] == "complete"
                and result["element_layout"]["status"] == "complete"
                and result["screenshot"]["status"] == "complete"
                and result["rendered_dom_stable_across_capture"]
                and result["font_wait"]["status"] == "loaded"
                and before == after
                and cdp.events_dropped == 0
            )
            result["status"] = "complete" if success else "partial"
        except Exception as error:
            result["status"] = "failed"
            result["error"] = _safe_error(error)
        finally:
            result["cleanup"] = await _close_browser(process, cdp, target_id)
            if websocket is not None:
                try:
                    await websocket.close()
                except Exception:
                    pass
            result["timing"] = {
                "wall_seconds": time.perf_counter() - start_wall,
                "process_cpu_seconds": time.process_time() - start_cpu,
            }
            endpoint_task.cancel()
            await asyncio.gather(endpoint_task, return_exceptions=True)
    result["temporary_profile_removed"] = not profile.exists()
    _write_json(out / "manifest.json", result)
    return result


async def _read_devtools_endpoint(
    process: asyncio.subprocess.Process,
) -> tuple[str, asyncio.Task[Any]]:
    if process.stderr is None:
        raise CaptureError("browser stderr pipe unavailable")
    ready = asyncio.get_running_loop().create_future()
    tail: deque[str] = deque(maxlen=20)

    async def drain() -> None:
        while line := await process.stderr.readline():
            text = line.decode("utf-8", "replace").rstrip()
            tail.append(text[-160:])
            marker = "DevTools listening on "
            if marker in text and not ready.done():
                ready.set_result(text.split(marker, 1)[1].strip())
        if not ready.done():
            ready.set_exception(CaptureError("browser exited before DevTools endpoint"))

    task = asyncio.create_task(drain())
    try:
        endpoint = await asyncio.wait_for(asyncio.shield(ready), 15.0)
        return endpoint, task
    except Exception as error:
        task.cancel()
        raise CaptureError(
            f"DevTools endpoint unavailable: {error}; {' | '.join(tail)}"
        ) from error


def _load_ws() -> tuple[Any, str]:
    try:
        client = importlib.import_module("websockets.asyncio.client")
        version = importlib.metadata.version("websockets")
    except (ImportError, importlib.metadata.PackageNotFoundError) as error:
        raise CaptureError(
            "runtime helper required: websockets==15.0.1 via UV"
        ) from error
    if version != "15.0.1":
        raise CaptureError(
            f"websockets helper pin mismatch: expected 15.0.1, got {version}"
        )
    return client.connect, version


def _runtime_metadata() -> dict[str, Any]:
    try:
        client = importlib.import_module("websockets.asyncio.client")
        source = Path(client.__file__).resolve()
        return {
            "websockets_version": importlib.metadata.version("websockets"),
            "websockets_client_file": str(source),
            "websockets_client_sha256": _sha256_file(source),
        }
    except Exception:
        return {
            "websockets_version": None,
            "websockets_client_file": None,
            "websockets_client_sha256": None,
        }


def run_capture(
    output: str | Path = DEFAULT_OUTPUT,
    chrome: str | Path = DEFAULT_CHROME,
    repo_root: str | Path = REPO_ROOT,
    page_timeout: float = PAGE_TIMEOUT,
    overall_timeout: float = OVERALL_TIMEOUT,
    viewport=None,
) -> dict[str, Any]:
    viewport = validated_viewport(viewport)
    out = Path(output)
    if out.exists():
        raise FileExistsError(f"capture output already exists: {out}")
    identity = _browser_identity(Path(chrome))
    if not _admitted(identity):
        raise CaptureError(
            f"browser identity is outside the reviewed allowlist: {identity}"
        )
    connect, websocket_version = _load_ws()
    plan = load_capture_plan(repo_root)
    source_hash = _sha256_file(__file__)
    out.mkdir(parents=True, exist_ok=False)
    (out / "producer.py").write_bytes(Path(__file__).read_bytes())
    start = time.monotonic()
    pages: list[dict[str, Any]] = []
    for spec in plan:
        remaining = overall_timeout - (time.monotonic() - start)
        if remaining <= 0:
            pages.extend(
                {"case_id": item["case_id"], "status": "skipped_overall_timeout"}
                for item in plan[len(pages) :]
            )
            break
        try:
            pages.append(
                asyncio.run(
                    asyncio.wait_for(
                        _launch_and_capture_one(
                            spec,
                            chrome=Path(chrome),
                            output_root=out,
                            timeout=min(page_timeout, remaining),
                            connect=connect,
                            viewport=viewport,
                        ),
                        timeout=remaining,
                    )
                )
            )
        except Exception as error:
            pages.append(
                {
                    "case_id": spec["case_id"],
                    "status": "failed",
                    "error": _safe_error(error),
                }
            )
    counts = Counter(str(page.get("status", "unknown")) for page in pages)
    summary = {
        "format": "product-retrieval-layout-capture-v1",
        "status": "complete"
        if len(pages) == len(plan)
        and all(page.get("status") == "complete" for page in pages)
        else "partial",
        "capture_mode": "live_navigation",
        "viewport": viewport,
        "viewport_policy": (
            "Desktop browser UA, mobile=false, device scale one; "
            "viewport size varies. This is not a mobile-device emulation."
        ),
        "browser": {
            "identity": identity,
            "executable": str(chrome),
            "sha256": _sha256_file(chrome),
            "admission_source": (
                "repository browser_distribution.rs reviewed 2026-10-24"
            ),
            "certification": (
                "M155 launch-eligible under current snapshot; "
                "full certification remains M153"
            ),
        },
        "adapter": {
            "name": "bounded raw CDP WebSocket",
            "websockets_version": websocket_version,
            "source_sha256_before_capture": source_hash,
            **_runtime_metadata(),
        },
        "limits": {
            "page_timeout_seconds": page_timeout,
            "overall_timeout_seconds": overall_timeout,
            "max_source_bytes": MAX_SOURCE_BYTES,
            "max_rendered_dom_bytes": MAX_RENDERED_BYTES,
            "max_layout_bytes": MAX_LAYOUT_BYTES,
            "max_screenshot_bytes": MAX_PNG_BYTES,
            "max_elements": MAX_ELEMENTS,
            "max_attributes_per_element": MAX_ATTRIBUTES,
            "max_events_per_page": MAX_EVENTS,
            "max_resources_per_page": MAX_RESOURCES,
        },
        "plan": plan,
        "page_count": len(pages),
        "status_counts": dict(counts),
        "overall_wall_seconds": time.monotonic() - start,
        "gold_mapping": (
            "not loaded; candidate/source mapping remains a separate annotator sidecar"
        ),
        "source_rendering_note": (
            "live main-response bytes and post-JavaScript rendered DOM are "
            "separate; saved source hashes are references, not live gold"
        ),
        "model_or_api_calls": 0,
        "pages": pages,
    }
    _write_json(out / "summary.json", summary)
    return summary


def _browser_identity(executable: Path) -> str:
    result = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return (result.stdout or result.stderr).strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--page-timeout", type=float, default=PAGE_TIMEOUT)
    parser.add_argument("--overall-timeout", type=float, default=OVERALL_TIMEOUT)
    parser.add_argument("--width", type=int, default=VIEWPORT["width"])
    parser.add_argument("--height", type=int, default=VIEWPORT["height"])
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    summary = run_capture(
        args.output,
        args.chrome,
        args.repo_root,
        args.page_timeout,
        args.overall_timeout,
        {"width": args.width, "height": args.height, "device_scale_factor": 1.0},
    )
    print(
        json.dumps(
            {
                key: summary.get(key)
                for key in (
                    "status",
                    "page_count",
                    "status_counts",
                    "overall_wall_seconds",
                )
            }
        )
    )
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
