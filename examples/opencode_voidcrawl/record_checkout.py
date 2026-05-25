"""Record the eshop checkout ReplayPlan as a marketing GIF/MP4 — with a debug HUD.

Replays the same `eshop_checkout` plan node-by-node and, after each step, injects a
fixed on-page debug badge (● REC · voidcrawl replay · step k/N: <action> [OK]) and
captures a frame — so the recording shows the system driving the checkout in real time,
step by step. Frames are stitched with ffmpeg into a GIF and an MP4.

    uv run python examples/opencode_voidcrawl/record_checkout.py
    HEADFUL=1 uv run python examples/opencode_voidcrawl/record_checkout.py   # watch it live (needs a display)
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from eshop_checkout import build_checkout_plan
from replay_runtime import run_node
from voidcrawl import BrowserConfig, BrowserSession

HERE = Path(__file__).parent
VID = HERE / '.yosoi' / 'video'
FRAMES = VID / 'frames'
_HEADLESS = os.getenv('HEADFUL') != '1'

_BADGE_CSS = (
    'position:fixed;top:0;left:0;right:0;z-index:2147483647;'
    'background:rgba(8,10,14,.93);color:#39ff14;font:600 15px ui-monospace,SFMono-Regular,Menlo,monospace;'
    'padding:9px 14px;letter-spacing:.4px;box-shadow:0 2px 10px rgba(0,0,0,.45)'
)


async def _badge(page: Any, text: str) -> None:
    css, txt = json.dumps(_BADGE_CSS), json.dumps(text)
    js = (
        "(()=>{let b=document.getElementById('__vc_hud');"
        "if(!b){b=document.createElement('div');b.id='__vc_hud';b.style.cssText="
        + css
        + ';document.body.appendChild(b);}'
        'b.textContent=' + txt + ';})()'
    )
    await page.evaluate_js(js)


async def _unbadge(page: Any) -> None:
    await page.evaluate_js("(()=>{const b=document.getElementById('__vc_hud');if(b)b.remove();})()")


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', *args], check=True)


async def main() -> None:
    FRAMES.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.glob('*.png'):
        old.unlink()

    plan = build_checkout_plan()
    cfg = BrowserConfig(headless=_HEADLESS, stealth=True, no_sandbox=True)
    n = len(plan.nodes)
    frame = 0
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')
        for k, node in enumerate(plan.nodes, 1):
            result = await run_node(k - 1, node, page)
            status = 'OK' if result.passed else 'FAIL'
            label = f'● REC · voidcrawl replay · step {k}/{n}: {node.act.op} — {node.intent or ""} [{status}]'
            await _badge(page, label)
            await page.screenshot(path=str(FRAMES / f'frame_{frame:03d}.png'))
            frame += 1
            await _unbadge(page)  # remove so the HUD never blocks the next action
        # hold the confirmation a beat
        await _badge(page, '● voidcrawl replay · order confirmed ✓')
        for _ in range(3):
            await page.screenshot(path=str(FRAMES / f'frame_{frame:03d}.png'))
            frame += 1

    pattern = str(FRAMES / 'frame_%03d.png')
    gif, mp4 = VID / 'eshop_checkout.gif', VID / 'eshop_checkout.mp4'
    # Full-page screenshots vary in height per step, so normalise every frame onto a
    # uniform even canvas first (ffmpeg's palette filtergraph errors on mixed sizes).
    norm = 'scale=780:1726:force_original_aspect_ratio=decrease,pad=780:1726:(ow-iw)/2:0:color=0x0a0a0f,setsar=1'
    # MP4 from the normalised frames (1s/step, held at 12fps), then derive the GIF from
    # the uniform MP4 — palettegen on the mixed-size frames is what hit ffmpeg's bug.
    _ffmpeg(
        ['-framerate', '1', '-i', pattern, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-vf', f'{norm},fps=12', str(mp4)]
    )
    _ffmpeg(
        [
            '-i',
            str(mp4),
            '-vf',
            'fps=1,scale=780:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse',
            str(gif),
        ]
    )
    print(f'captured {frame} frames', flush=True)
    print(f'GIF -> {gif}  ({gif.stat().st_size // 1024} KB)', flush=True)
    print(f'MP4 -> {mp4}  ({mp4.stat().st_size // 1024} KB)', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
