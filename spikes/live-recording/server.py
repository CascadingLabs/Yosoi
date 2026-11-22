"""Local experiment: display video and input without a CDP or BiDi dependency."""

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from aiohttp import WSMsgType, web
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay

ROOT = Path(__file__).parent


class Lab:
    def __init__(self, args):
        self.args = args
        self.children = []
        self.peers = set()
        self.relay = MediaRelay()
        self.player = None
        self.recorder = None
        self.recording = None
        self.owner = "automation"
        self.lock = asyncio.Lock()
        self.sockets = set()
        self.events = []
        self.profile = tempfile.TemporaryDirectory(prefix="yosoi-live-")
        args.output.mkdir(parents=True, exist_ok=True)

    def spawn(self, *command, **kwargs):
        child = subprocess.Popen(command, start_new_session=True, **kwargs)
        self.children.append(child)
        return child

    async def start(self, app):
        read_fd, write_fd = os.pipe()
        try:
            self.spawn(
                "Xvfb",
                "-displayfd",
                str(write_fd),
                "-screen",
                "0",
                f"{self.args.width}x{self.args.height}x24",
                "-nolisten",
                "tcp",
                pass_fds=(write_fd,),
            )
        finally:
            os.close(write_fd)
        try:
            # Xvfb writes only after the display accepts connections.
            display = await asyncio.wait_for(
                asyncio.to_thread(os.read, read_fd, 32), 15
            )
        finally:
            os.close(read_fd)
        if not display.strip().isdigit():
            raise RuntimeError("Xvfb did not report a ready display")
        self.display = ":" + display.decode().strip()
        self.env = dict(
            os.environ, DISPLAY=self.display, MOZ_ENABLE_WAYLAND="0", GDK_BACKEND="x11"
        )
        self.env.pop("WAYLAND_DISPLAY", None)
        url = f"http://127.0.0.1:{self.args.port}/fixture"
        if self.args.engine == "chrome":
            command = [
                self.args.browser,
                f"--user-data-dir={self.profile.name}",
                "--no-first-run",
                "--no-default-browser-check",
                "--ozone-platform=x11",
                "--force-device-scale-factor=1",
                f"--window-size={self.args.width},{self.args.height}",
                "--kiosk",
                url,
            ]
        else:
            (Path(self.profile.name) / "user.js").write_text(
                'user_pref("browser.aboutwelcome.enabled", false);\n'
                'user_pref("layout.css.devPixelsPerPx", "1.0");\n'
                'user_pref("browser.startup.homepage_override.mstone", "ignore");\n'
                'user_pref("datareporting.policy.'
                'dataSubmissionPolicyBypassNotification", true);\n'
            )
            command = [
                self.args.browser,
                "--no-remote",
                "--profile",
                self.profile.name,
                "--kiosk",
                url,
            ]
        self.browser = self.spawn(*command, env=self.env, stdout=subprocess.DEVNULL)
        self.player = MediaPlayer(
            self.display,
            format="x11grab",
            options={
                "video_size": f"{self.args.width}x{self.args.height}",
                "framerate": str(self.args.fps),
                "threads": "1",
            },
        )
        if self.player.video is None:
            raise RuntimeError("No display video track")
        if self.args.novnc:
            # Server enforces view-only; lab input is gated below.
            self.vnc = self.spawn(
                self.args.x11vnc,
                "-display",
                self.display,
                "-localhost",
                "-no6",
                "-rfbport",
                str(self.args.vnc_port),
                "-forever",
                "-shared",
                "-viewonly",
                "-nopw",
                "-noxdamage",
                stdout=subprocess.DEVNULL,
                env={**self.env, "XDG_SESSION_TYPE": "x11"},
            )
        print(
            json.dumps(
                {
                    "viewer": f"http://127.0.0.1:{self.args.port}",
                    "display": self.display,
                    "engine": self.args.engine,
                    "capture": "x11grab",
                    "fps_requested": self.args.fps,
                }
            ),
            flush=True,
        )

    def state(self):
        return {
            "owner": self.owner,
            "recording": self.recording,
            "engine": self.args.engine,
            "capture": "x11grab",
            "display": self.display,
            "novnc": bool(self.args.novnc),
            "browser_running": self.browser.poll() is None,
            "recordings": sorted(p.name for p in self.args.output.glob("*.mp4")),
        }

    async def control(self, payload):
        async with self.lock:
            action = payload.get("action")
            if action == "owner":
                owner = payload.get("owner")
                if owner not in ("human", "automation"):
                    raise ValueError("Invalid owner")
                self.owner = owner
            elif action == "input":
                if self.owner != "human":
                    raise ValueError("Take human control first")
                kind = payload.get("kind")
                if kind == "click":
                    x, y = int(payload["x"]), int(payload["y"])
                    if not (0 <= x < self.args.width and 0 <= y < self.args.height):
                        raise ValueError("Input outside display")
                    command = ["mousemove", "--sync", str(x), str(y), "click", "1"]
                elif kind == "text":
                    value = payload["text"]
                    if not isinstance(value, str) or len(value) > 2048:
                        raise ValueError("Text must be at most 2048 characters")
                    command = ["type", "--clearmodifiers", "--delay", "0", "--", value]
                elif kind == "key":
                    key = payload["key"]
                    if key not in (
                        "Return",
                        "Tab",
                        "BackSpace",
                        "Escape",
                        "Left",
                        "Right",
                        "Up",
                        "Down",
                        "Home",
                        "End",
                        "Delete",
                    ):
                        raise ValueError("Unsupported key")
                    command = ["key", "--clearmodifiers", key]
                elif kind == "scroll":
                    command = ["click", "4" if int(payload["delta"]) < 0 else "5"]
                else:
                    raise ValueError("Unsupported input")
                process = await asyncio.create_subprocess_exec(
                    "xdotool", *command, env=self.env
                )
                try:
                    code = await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    raise ValueError("Input timed out") from None
                if code:
                    raise ValueError("Input failed")
            elif action == "record":
                if self.recorder:
                    raise ValueError("Already recording")
                self.recording = f"{time.time_ns()}-{self.args.engine}.mp4"
                # Independent capture: file writes never queue live frames.
                self.recorder = self.spawn(
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-n",
                    "-threads",
                    "1",
                    "-f",
                    "x11grab",
                    "-video_size",
                    f"{self.args.width}x{self.args.height}",
                    "-framerate",
                    str(self.args.fps),
                    "-i",
                    self.display,
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
                    str(self.args.output / self.recording),
                )
            elif action == "stop":
                await self.stop_recording()
            else:
                raise ValueError("Unsupported action")
            event = {"action": action, "server_monotonic_ns": time.monotonic_ns()}
            self.events.append(event)
            return {**self.state(), "ack": event}

    async def stop_recording(self):
        if self.recorder:
            child, self.recorder = self.recorder, None
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
            try:
                code = await asyncio.wait_for(asyncio.to_thread(child.wait), 10)
            except TimeoutError:
                child.kill()
                await asyncio.to_thread(child.wait)
                raise ValueError("Recording finalization timed out") from None
            self.recording = None
            if code not in (0, 255):
                raise ValueError(f"Recorder failed: {code}")

    async def close(self, app):
        with contextlib.suppress(ValueError):
            await self.stop_recording()
        await asyncio.gather(*(socket.close() for socket in self.sockets))
        await asyncio.gather(*(peer.close() for peer in list(self.peers)))
        if self.player and self.player.video:
            self.player.video.stop()
        for child in reversed(self.children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(asyncio.to_thread(child.wait), 5)
                except TimeoutError:
                    os.killpg(child.pid, signal.SIGKILL)
                    await asyncio.to_thread(child.wait)
        (self.args.output / "events.json").write_text(
            json.dumps(self.events, indent=2) + "\n"
        )
        self.profile.cleanup()


def application(args):
    lab = Lab(args)

    @web.middleware
    async def local_only(request, handler):
        # Reject DNS rebinding and cross-origin control on the loopback listener.
        allowed = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
        if request.host not in allowed:
            raise web.HTTPForbidden(text="Local host required")
        origin = request.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in allowed}:
            raise web.HTTPForbidden(text="Same origin required")
        return await handler(request)

    app = web.Application(middlewares=[local_only], client_max_size=256 * 1024)
    app.on_startup.append(lab.start)
    app.on_cleanup.append(lab.close)

    async def index(request):
        return web.FileResponse(ROOT / "viewer.html")

    async def fixture(request):
        return web.FileResponse(ROOT / "fixture.html")

    async def status(request):
        return web.json_response(lab.state())

    async def offer(request):
        if len(lab.peers) >= 2:
            raise web.HTTPTooManyRequests(text="Two viewers maximum")
        payload = await request.json()
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        lab.peers.add(peer)

        @peer.on("connectionstatechange")
        async def changed():
            if peer.connectionState in ("failed", "closed", "disconnected"):
                await peer.close()
                lab.peers.discard(peer)

        try:
            await peer.setRemoteDescription(
                RTCSessionDescription(sdp=payload["sdp"], type="offer")
            )
            peer.addTrack(lab.relay.subscribe(lab.player.video, buffered=False))
            await peer.setLocalDescription(await peer.createAnswer())
            return web.json_response(
                {"sdp": peer.localDescription.sdp, "type": "answer"}
            )
        except Exception:
            await peer.close()
            lab.peers.discard(peer)
            raise

    async def control(request):
        socket = web.WebSocketResponse(max_msg_size=8192)
        await socket.prepare(request)
        lab.sockets.add(socket)
        try:
            async for message in socket:
                if message.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(message.data)
                        result = await lab.control(payload)
                    except (ValueError, KeyError, TypeError) as error:
                        result = {"error": str(error)}
                    await socket.send_json(result)
        finally:
            lab.sockets.discard(socket)
        return socket

    async def vnc(request):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", args.vnc_port)
        except OSError as error:
            raise web.HTTPServiceUnavailable(text="VNC server unavailable") from error
        socket = web.WebSocketResponse(protocols=["binary"])
        await socket.prepare(request)
        lab.sockets.add(socket)

        async def outbound():
            while chunk := await reader.read(65536):
                await socket.send_bytes(chunk)
            await socket.close()

        task = asyncio.create_task(outbound())
        try:
            async for message in socket:
                if message.type == WSMsgType.BINARY:
                    writer.write(message.data)
                    await writer.drain()
        finally:
            lab.sockets.discard(socket)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            writer.close()
            await writer.wait_closed()
        return socket

    app.router.add_get("/", index)
    app.router.add_get("/fixture", fixture)
    app.router.add_get("/status", status)
    app.router.add_post("/offer", offer)
    app.router.add_get("/control", control)
    if args.novnc:
        app.router.add_get("/vnc", vnc)
        app.router.add_static("/novnc/", args.novnc)
    app.router.add_static("/recordings/", args.output)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["chrome", "firefox"], required=True)
    parser.add_argument(
        "--browser", required=True, help="Regular Stable browser executable"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--output", type=Path, default=Path(".generated/live-recording")
    )
    parser.add_argument(
        "--novnc", type=Path, help="Optional noVNC checkout for comparison"
    )
    parser.add_argument("--x11vnc", default="x11vnc")
    parser.add_argument("--vnc-port", type=int, default=5905)
    args = parser.parse_args()
    if not (
        16 <= args.width <= 1920
        and 16 <= args.height <= 1080
        and args.width % 2 == 0
        and args.height % 2 == 0
        and 1 <= args.fps <= 30
    ):
        parser.error("Use even dimensions up to 1920x1080 and 1–30 fps")
    web.run_app(application(args), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
