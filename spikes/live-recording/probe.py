"""Exercise a running lab with a real WebRTC receiver and saved video."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from aiohttp import ClientSession, WSMsgType
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription


async def probe(base, output, frames):
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    video = asyncio.get_running_loop().create_future()

    @peer.on("track")
    def track_ready(track):
        if track.kind == "video" and not video.done():
            video.set_result(track)

    try:
        async with ClientSession() as client:
            response = await client.get(base + "/status")
            status = await response.json()
            assert status["browser_running"], status
            forbidden = await client.get(
                base + "/status", headers={"Origin": "http://example.com"}
            )
            assert forbidden.status == 403
            async with client.ws_connect(base + "/control") as control:

                async def send(payload):
                    await control.send_json(payload)
                    message = await asyncio.wait_for(control.receive(), 5)
                    assert message.type == WSMsgType.TEXT
                    return json.loads(message.data)

                assert (await send({"action": "owner", "owner": "automation"}))[
                    "owner"
                ] == "automation"
                rejected = await send(
                    {"action": "input", "kind": "text", "text": "blocked"}
                )
                assert "error" in rejected
                assert (await send({"action": "owner", "owner": "human"}))[
                    "owner"
                ] == "human"
                assert "error" not in await send(
                    {"action": "input", "kind": "key", "key": "Tab"}
                )
                assert "error" not in await send(
                    {"action": "input", "kind": "text", "text": "display-input"}
                )
                peer.addTransceiver("video", direction="recvonly")
                await peer.setLocalDescription(await peer.createOffer())
                response = await client.post(
                    base + "/offer",
                    json={"sdp": peer.localDescription.sdp, "type": "offer"},
                )
                assert response.status == 200, await response.text()
                answer = await response.json()
                await peer.setRemoteDescription(RTCSessionDescription(**answer))
                track = await asyncio.wait_for(video, 10)
                started = await send({"action": "record"})
                assert started.get("recording"), started
                # Frame arrival supplies synchronization; no readiness sleeps.
                fingerprints = set()
                first = time.monotonic()
                for index in range(frames):
                    frame = await asyncio.wait_for(track.recv(), 10)
                    if index == 0:
                        first = time.monotonic()
                    fingerprints.add(hash(bytes(frame.planes[0])))
                elapsed = time.monotonic() - first
                output.mkdir(parents=True, exist_ok=True)
                rgb = frame.reformat(format="rgb24")
                plane = rgb.planes[0]
                rows = bytes(plane)
                pixels = b"".join(
                    rows[y * plane.line_size : y * plane.line_size + rgb.width * 3]
                    for y in range(rgb.height)
                )
                (output / f"{status['engine']}-receiver.ppm").write_bytes(
                    f"P6\n{rgb.width} {rgb.height}\n255\n".encode() + pixels
                )
                stopped = await send({"action": "stop"})
                assert "error" not in stopped, stopped
                assert len(fingerprints) > 10, "Expected changing fixture video"
                assert (await send({"action": "owner", "owner": "automation"}))[
                    "owner"
                ] == "automation"
                if status["novnc"]:
                    response = await client.get(base + "/novnc/vnc.html")
                    assert response.status == 200
                    async with client.ws_connect(
                        base + "/vnc", protocols=["binary"]
                    ) as vnc:
                        greeting = await asyncio.wait_for(vnc.receive(), 5)
                        assert greeting.type == WSMsgType.BINARY
                        assert greeting.data.startswith(b"RFB "), greeting
                result = {
                    "engine": status["engine"],
                    "frames": frames,
                    "distinct_frames": len(fingerprints),
                    "receiver_fps": round((frames - 1) / elapsed, 2),
                    "recording": started["recording"],
                    "input_gate": "passed",
                    "cross_origin": "rejected",
                    "vnc_rfb_handshake": status["novnc"],
                    "limits": "Local receiver; no visible input latency assertion",
                }
                (output / f"{status['engine']}-probe.json").write_text(
                    json.dumps(result, indent=2) + "\n"
                )
                print(json.dumps(result, indent=2))
    finally:
        await peer.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--frames", type=int, default=90)
    parser.add_argument(
        "--output", type=Path, default=Path(".generated/live-recording")
    )
    args = parser.parse_args()
    if not 30 <= args.frames <= 1800:
        parser.error("Use 30–1800 frames")
    asyncio.run(probe(args.url, args.output, args.frames))
