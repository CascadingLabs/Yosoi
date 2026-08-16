"""Capture every section of a tabbed/routed page, scroll included, with an audit trail.

For each nav section: click it, wait for the DOM to settle, discover a selector for both
the control and the panel, then screenshot the panel cropped to its own rectangle. If the
panel scrolls internally, step through it a viewport at a time so nothing below the fold
is missed.

Two things worth knowing about how this is built:

  * Cropping uses VoidCrawl's selector-backed screenshot (`selector_type="css"`), which
    raises on an ambiguous or non-visual selector rather than silently cropping the wrong
    thing. Where a union of two rects is needed (control + panel) it falls back to an
    explicit bbox computed in-page.
  * Inner panels scroll their own overflow container, not the window, so `scroll_viewports`
    would not move them. Scrolling is done by setting scrollTop on the discovered
    scroller and re-cropping.

AUDIT RECORDING uses VoidCrawl's screencast (Page.start_recording / handle.stop). An
earlier version of this file stitched per-state PNGs with ffmpeg and claimed no screencast
API existed — that was true when written and is no longer, so the claim is retracted
rather than left standing.

Two properties of the real screencast that the stitched version could not have:
frames arrive when Chrome PAINTS, so transitions and loading states are captured rather
than only settled states; and `encode=["mp4"]` RAISES when the feature is unavailable
instead of silently producing nothing.

VERIFIED IN ISOLATION, NOT END TO END. start_recording/stop works and wrote 20 JPEG
frames at 9.3 effective fps (foregrounded=True); `encode=["mp4"]` correctly raises
because this build lacks the `encode-ffmpeg` cargo feature. What is NOT verified is
--record across the full section walk: that run timed out twice, and the leading
hypothesis is that the screencast holds the browser's capture lock while `shoot()`
wants it for a bbox screenshot. Do not trust --record until that is confirmed or
disproved; the un-recorded path is unaffected and works.

Kwarg names come from the COMPILED extension (output_dir / frame_format), which
disagrees with _ext.pyi (dir / format). The .so is newer, so the binary wins.

Usage:
    uv run python sections.py --url http://localhost:8080/#/bio
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
SHOTS = HERE / "sections"

# Discover nav controls and the panel they drive, with rectangles, in one round trip.
DISCOVER_JS = """
(() => {
  const rect = (e) => { const r = e.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; };
  const cssPath = (el) => {
    const parts = [];
    let e = el;
    while (e && e.nodeType === 1 && parts.length < 8) {
      if (e.id) { parts.unshift('#' + CSS.escape(e.id)); break; }
      const cls = (e.className || '').toString().trim().split(/\\s+/).filter(Boolean)
        .filter(c => !c.includes(':') && !c.includes('[')).slice(0, 2);
      let seg = e.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
      const p = e.parentElement;
      if (p) {
        const same = [...p.children].filter(s => s.tagName === e.tagName);
        if (same.length > 1) seg += `:nth-of-type(${same.indexOf(e) + 1})`;
      }
      parts.unshift(seg);
      e = e.parentElement;
    }
    return parts.join(' > ');
  };
  const buttons = [...document.querySelectorAll('button')]
    .filter(b => (b.textContent || '').trim().length && rect(b).w > 0)
    .map(b => ({label: (b.textContent || '').trim(), css: cssPath(b), rect: rect(b)}));
  // Pick the VISIBLE panel. During a section transition the outgoing container is
  // still in the DOM at 0x0, and querySelector returns it first — which silently
  // produced 0x0 rects and bboxes cropped to a sliver of the page.
  const panels = [...document.querySelectorAll('.content-container')]
    .map(e => ({el: e, r: rect(e)}))
    .filter(o => o.r.w > 0 && o.r.h > 0)
    .sort((a, b) => (b.r.w * b.r.h) - (a.r.w * a.r.h));
  const panel = panels.length ? panels[0].el : null;
  const scroller = panel
    ? [panel, ...panel.querySelectorAll('*')].find(e => e.scrollHeight > e.clientHeight + 8 && e.clientHeight > 40)
    : null;
  return {
    buttons,
    panel: panel ? {css: cssPath(panel), rect: rect(panel)} : null,
    scroller: scroller ? {css: cssPath(scroller), scrollHeight: scroller.scrollHeight,
                          clientHeight: scroller.clientHeight, rect: rect(scroller)} : null,
    viewport: {w: innerWidth, h: innerHeight},
  };
})()
"""


def scroll_js(css: str, top: int) -> str:
    return f"(() => {{ const e = document.querySelector({css!r}); if(!e) return -1; e.scrollTop = {top}; return e.scrollTop; }})()"


async def settle_layout(tab, *, rounds: int = 3, max_polls: int = 25, wait: float = 0.2) -> dict:
    """Poll the panel RECTANGLE until it stops moving.

    settle_dom counts elements, and a CSS transition changes no element count — so a
    panel mid-animation looks perfectly settled. On mobile that produced panels measured
    at 169-335px inside a 393px viewport, and bboxes cropped to a half-open card.

    Geometry needs a geometric settle condition. Nothing else in this file may assume a
    rect is final before this returns.
    """
    last, stable, polls = None, 0, 0
    while polls < max_polls:
        state = await tab.eval_js(DISCOVER_JS)
        r = state["panel"]["rect"] if state["panel"] else None
        # A stable 0x0 is still stable — settling on "stopped changing" without also
        # requiring "is valid" is how the transition artefact got through last time.
        valid = r is not None and r["w"] > 0 and r["h"] > 0
        stable = stable + 1 if valid and r == last else 0
        last = r
        polls += 1
        if stable >= rounds:
            return state
        await asyncio.sleep(wait)
    raise SystemExit(f"panel rect never stopped moving after {polls} polls (last {last})")


async def shoot(tab, *, device: str | None, expect_w: int | None, **kw) -> None:
    """Screenshot, then re-assert the viewport and verify it actually held.

    VoidCrawl bug, measured: a plain ``screenshot()`` with no bbox/viewport kwargs
    RESETS a persistent ``set_viewport`` override back to the launch default
    (393px/dpr3 -> 780px/dpr1). A bbox screenshot does not. Since the audit frame is a
    plain capture taken after every section, the first section rendered at the mobile
    viewport and every later one silently fell back to desktop — producing a "mobile"
    run that was 1 mobile frame and 13 desktop ones.

    So: re-assert after every capture, and CHECK. A viewport that silently reverts is
    exactly the class of failure that makes a screenshot look plausible and be wrong.
    """
    await tab.screenshot(**kw)
    if not device:
        return
    await tab.set_viewport(preset=device)
    got = await tab.eval_js("(() => innerWidth)()")
    if expect_w is not None and int(got) != expect_w:
        raise SystemExit(
            f"viewport did not hold after screenshot: expected {expect_w}px, got {got}px"
        )


async def run(
    url: str, out_dir: Path, *, pad: int, device: str | None, record: bool, encode: str | None
) -> dict:
    from capture import settle_dom
    from voidcrawl import BrowserConfig, BrowserSession

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rec_dir = out_dir / "recording"
    if record:
        rec_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"url": url, "captured_at": out_dir.name, "device": device, "sections": []}
    frame_no = 0

    session = BrowserSession(BrowserConfig(headless=True, stealth=True, no_sandbox=True))
    async with session:
        tab = await session.new_page()
        try:
            if device:
                # Persistent viewport override — set BEFORE navigating so the responsive
                # layout, media queries and touch identity apply to the page we discover
                # and click, not just to the final screenshot. A one-shot viewport_* on
                # screenshot() would crop a desktop layout to phone dimensions and look
                # plausible while being wrong.
                await tab.set_viewport(preset=device)
            await tab.navigate(url)
            settle = await settle_dom(tab)
            if not settle["settled"]:
                raise SystemExit(f"DOM never settled for {url}; refusing to capture mid-render")

            rec_handle = None
            if record:
                # Encode is requested explicitly: it raises if the feature is missing
                # rather than quietly leaving us with no video.
                # NOTE the kwarg names: the compiled extension takes output_dir /
                # frame_format, while _ext.pyi currently documents dir / format. The .so
                # is newer than the stub, so the binary is the truth — worth fixing
                # upstream, but not worth guessing around here.
                kw = {
                    "output_dir": str(rec_dir),
                    "fps": 10,
                    "frame_format": "jpeg",
                    "quality": 70,
                    "write_frames": True,
                }
                if encode:
                    # Opt-in only. mp4/webm need the `encode-ffmpeg` cargo feature, which
                    # this build lacks; requesting it RAISES with that message rather than
                    # silently producing no video, so it must not be a default.
                    kw["encode"] = [encode]
                rec_handle = await tab.start_recording(**kw)
                print("recording  screencast armed (paint-driven, not clock-driven)")

            disco = await tab.eval_js(DISCOVER_JS)
            expect_w = disco["viewport"]["w"] if device else None
            labels = [b["label"] for b in disco["buttons"]]
            print(f"viewport   {disco['viewport']['w']}x{disco['viewport']['h']}")
            print(f"sections   {labels}")
            print(f"panel      {disco['panel']['css'] if disco['panel'] else 'NOT FOUND'}\n")
            if not disco["panel"]:
                raise SystemExit("no .content-container panel found — page shape changed")

            for btn in disco["buttons"]:
                label = btn["label"]
                slug = label.lower().replace(" ", "_").replace(".", "").replace("/", "-")

                await tab.click_by_role("button", label)
                st = await settle_dom(tab)
                state = await settle_layout(tab)
                panel = state["panel"]
                scroller = state["scroller"]

                # Union of control + panel so the shot carries its own label, like a
                # human screenshot would.
                #
                # The control's rect MUST come from the post-click re-discovery: clicking
                # a section resizes the panel and moves every nav control with it. Using
                # the pre-click rect unions two positions that never coexisted and
                # produces a huge box full of empty page.
                live_btn = next((x for x in state["buttons"] if x["label"] == label), None)
                if live_btn is None:
                    raise SystemExit(f"control {label!r} vanished after clicking it")
                b, p = live_btn["rect"], panel["rect"]
                x0, y0 = min(b["x"], p["x"]) - pad, min(b["y"], p["y"]) - pad
                x1 = max(b["x"] + b["w"], p["x"] + p["w"]) + pad
                y1 = max(b["y"] + b["h"], p["y"] + p["h"]) + pad
                union = (max(0, x0), max(0, y0), x1 - max(0, x0), y1 - max(0, y0))

                shots = []
                if scroller:
                    span = scroller["scrollHeight"] - scroller["clientHeight"]
                    step = max(1, scroller["clientHeight"] - 40)  # overlap so nothing is cut
                    tops = list(range(0, span + step, step))[:12]
                    print(
                        f"  {label:<14} scrolls: {scroller['scrollHeight']}px in "
                        f"{scroller['clientHeight']}px viewport → {len(tops)} frame(s)"
                    )
                    for i, top in enumerate(tops):
                        landed = await tab.eval_js(scroll_js(scroller["css"], top))
                        await asyncio.sleep(0.35)
                        path = out_dir / f"{slug}_{i:02d}.png"
                        await shoot(
                            tab, device=device, expect_w=expect_w, path=str(path), bbox=union
                        )
                        shots.append({"path": path.name, "scroll_top": landed})
                        frame_no += 1
                        await shoot(
                            tab,
                            device=device,
                            expect_w=expect_w,
                            path=str(frames_dir / f"{frame_no:04d}.png"),
                        )
                else:
                    print(f"  {label:<14} single view (no internal scroll)")
                    path = out_dir / f"{slug}.png"
                    await shoot(tab, device=device, expect_w=expect_w, path=str(path), bbox=union)
                    shots.append({"path": path.name, "scroll_top": 0})
                    frame_no += 1
                    await shoot(
                        tab,
                        device=device,
                        expect_w=expect_w,
                        path=str(frames_dir / f"{frame_no:04d}.png"),
                    )

                manifest["sections"].append(
                    {
                        "label": label,
                        "control_selector": btn["css"],
                        "panel_selector": panel["css"],
                        "scroller_selector": scroller["css"] if scroller else None,
                        "settled": st["settled"],
                        "bbox": union,
                        "shots": shots,
                    }
                )
            if rec_handle is not None:
                rec = await rec_handle.stop()
                manifest["recording"] = {
                    "frames_captured": rec.frames_captured,
                    "frames_dropped": rec.frames_dropped,
                    "effective_fps": round(rec.effective_fps(), 2),
                    "duration_ms": round(rec.duration_ms),
                    "device_pixel_ratio": rec.device_pixel_ratio,
                    "foregrounded": rec.foregrounded,
                    "regions": [str(x) for x in rec.regions],
                    "frames_on_disk": len(list(rec_dir.rglob("*.jpg"))),
                }
                print(
                    f"recording  {rec.frames_captured} frames "
                    f"({rec.frames_dropped} dropped) @ {rec.effective_fps():.1f} fps, "
                    f"{rec.duration_ms / 1000:.1f}s, foregrounded={rec.foregrounded}, "
                    f"{len(list(rec_dir.rglob('*.jpg')))} frames on disk"
                )
        finally:
            await tab.close()

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Screenshot every section, scroll included.")
    ap.add_argument("--url", required=False)
    ap.add_argument("--pad", type=int, default=12)
    ap.add_argument("--device", default=None, help='viewport preset, e.g. "iPhone 16"')
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--record", action="store_true", help="screencast the whole session")
    ap.add_argument(
        "--encode",
        choices=["mp4", "webm", "gif"],
        default=None,
        help="encode the screencast; needs the encode-ffmpeg cargo feature (raises without it)",
    )
    args = ap.parse_args()

    if args.list_devices:
        from voidcrawl.viewport import list_device_presets

        for p in list_device_presets():
            print(
                f"  {p.name:<20} {p.width}x{p.height}  dpr {p.device_scale_factor}  mobile={p.mobile}"
            )
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = (args.device or "desktop").lower().replace(" ", "-")
    out = SHOTS / f"{stamp}_{slug}"
    m = asyncio.run(
        run(args.url, out, pad=args.pad, device=args.device, record=args.record, encode=args.encode)
    )

    total = sum(len(s["shots"]) for s in m["sections"])
    print(f"\ncaptured   {total} section frame(s) across {len(m['sections'])} section(s)")
    print(f"output     {out}")
    if m.get("recording"):
        print(f"audit      {out / 'recording'}  (VoidCrawl screencast)")


if __name__ == "__main__":
    main()
