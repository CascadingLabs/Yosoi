# Local evidence — 2026-10-25

Parent: PR #166 head `44928628df764a34b40447aed296d5c4cbf0edfa`.
This identifies the recorded experiments. The delivery branch is rebased onto
the refreshed #166 head `6f4e8fa75f395412edbedca20d51b04deb39e7de`; hosted delivery
checks are reported on the draft PR separately from these local observations.
This is a local capture/transport spike. No production SDK API changes, hosted CI, release,
deployment or cross-platform certification is claimed.

## Saved MP4

Artifact in this workspace:
`.generated/live-recording/yosoi-firefox-continuous-display.mp4`.

Captured directly from Firefox's Xvfb display with FFmpeg `x11grab` while a
WebRTC receiver consumed the same display through aiortc. No screenshot files
were assembled or concatenated into the recording.

| Check | Result |
| --- | --- |
| Browser | Regular Firefox 158.0.1 |
| Codec / dimensions | H.264, 1280×720 |
| Duration / size | 19.066667 seconds / 1,106,317 bytes |
| Decoded frames | 572 |
| Unique decoded frame hashes | 572 |
| Adjacent identical frames | 0 |
| Reported average frame rate | 30/1 |
| Consecutive presentation timestamps | Strictly increasing |
| Min / max presentation interval | 33.333 / 33.334 ms |
| Full FFmpeg decode | No errors |

Raw verification: `.generated/live-recording/playback-verification.json`.
The clean cadence and unique frames establish this file's timing; subjective
playback and sustained live-view buffering still need to be assessed.

## Transport and input probes

- Regular Chrome 156.0.8078.47: received 90 WebRTC frames while recording,
  with 89 distinct received frame hashes in the final short run.
- Regular Firefox 158.0.1: received 600 WebRTC frames while recording,
  with 583 distinct received frame hashes in the final long run.
- Both: human input rejected in automation mode, OS input acknowledged in
  human mode, return to automation acknowledged, cross-origin request rejected,
  noVNC HTML served, and VNC RFB greeting received through the WebSocket bridge.
- noVNC v1.7.0; x11vnc 0.9.17; aiortc 1.14.0; aiohttp 3.13.3.
- Received images were inspected to confirm the intended animated fixture.
  Initial setup exposed a Firefox welcome screen and inherited Wayland/scaling
  settings; the launcher now supplies a fresh configured X11 profile and scale.

Receiver throughput is a short-window arrival measurement, not a claim that the
source or viewer renders faster than 30 fps. WebRTC frame counts and the saved
file's counts are independently timed paths and need not match.

## Checks and remaining boundaries

Ruff lint/format, launcher shell syntax and viewer JavaScript syntax pass.
No full SDK build/test suite was needed for this standalone spike. Only one
browser lab ran at a time, and all owned lab services were stopped afterward.

The computer-use browser inventory was empty, so full viewer UI and noVNC canvas
rendering were not validated. VNC is view-only; accepted OS input is not a
verified visible click/text outcome. No Yosoi Session/action dispatcher is
attached, so actual automation takeover remains unimplemented. No native VNC
client, remote network, CPU/bandwidth benchmark, input-to-visible latency,
Hyprland, Windows or Moli behavior was qualified.

## Earlier run: MSNBC navigation with the ChromeDriver Surface adapter

The separate `surface_record.py` supervisor ran an existing native Surface CLI
on a private Xvfb display with regular Chrome 156.0.8078.47 and matching
ChromeDriver. The copied CLI binary's digest and executable versions are saved
in `.generated/live-recording/msnbc/run-1/identity.json`; this reused binary is
not claimed as an exact-head build from this workspace.

Surface opened `https://www.msnbc.com/`, observed its redirect to MS NOW,
found the visible article text, followed its parent to the indexed anchor,
inspected the destination and checked native eligibility. The link was visible,
unoccluded, enabled and unchanged. After acquiring hot authority, Surface
dispatched the native click and returned a **Confirmed** receipt with the
observed destination URL and heading. Two native wheel actions followed;
their receipts remain unconfirmed, with resulting viewport screenshots saved.

Final page:
<https://www.ms.now/opinion/abdul-el-sayed-mchigan-tommy-election>

Observed heading: “How Abdul El-Sayed is trying to pull off the impossible in
the Rust Belt.” No legal agreement, login, subscription or paywall was accepted.

Artifacts:

- `.generated/live-recording/msnbc/run-1/display.mp4`: continuous full capture,
  97.066667 seconds, 1440×1000 H.264, 30 fps, 2,912 frames.
- `.generated/live-recording/msnbc-surface-actions.mp4`: a continuous 54-second
  excerpt from seconds 42–96, preserving normal playback speed, covering the
  homepage, click/navigation and scrolling. It is a trimmed/re-encoded portion
  of the original video, with no frame assembly or concatenation.
- `.generated/live-recording/msnbc/run-1/transcript.json`: exact Surface requests
  and replies, including the confirmed click and independently read final URL.
- `.generated/live-recording/msnbc/run-1/surface/surface.png`: final viewport.

FFmpeg captured pixels directly during all Surface reads/actions. These were
native Surface/ChromeDriver actions, not a production CDP/BiDi integration test.
The wrapper and child processes exited after the `close` command.

## Native replacement: Yosoi owns the browser and controller

The recording runner now starts `live_recording_native`, built from this
workspace, instead of invoking the ChromeDriver Surface CLI. The worker acquires
the public Rust `session::Session`, retains one `Work` lease, and uses its
production Chromiumoxide/CDP controller for browser acquisition, navigation,
evaluation and native clicks. Chrome launch/profile cleanup remains owned by
Yosoi. The Python supervisor owns only the private Xvfb display and FFmpeg process.
No driver executable or wrapper around Chrome is supplied.

The final automatic run is `.generated/live-recording/native/run-3/`:

| Evidence | Result |
| --- | --- |
| Browser | Admitted regular Chrome 156.0.8078.47 |
| Owned process snapshot | 28 descendants; no ChromeDriver and no `--enable-automation` |
| Native receipts | 69, all `observed` |
| Browser ownership | One Session ID and one tab ID across the native observations |
| Surface click | `Confirmed`; destination capture recorded in `after_capture` |
| Old capture reference | Rejected after navigation; no fallback target or second click |
| Scroll | Explicitly programmatic `Work.evaluate`; observed Y changed from 0 to 650 |
| Final URL | `https://www.ms.now/opinion/abdul-el-sayed-mchigan-tommy-election` |
| Full video | H.264, 1920×1080, 30 fps, 31.033333 seconds, 931 frames |
| Presentation intervals | 33.333–33.334 ms; strictly increasing |
| Full video decode | No errors |
| Cleanup | No recorded owned process remained after close |

The automation banner is absent in an inspected frame. It was not removed by
changing ChromeDriver flags or cropping the browser UI. The code path and owned
process arguments establish that the production Yosoi controller launched Chrome.
The final run never called the native screenshot operation and does not depend
on SDK screenshot output for video frames. An earlier diagnostic native
screenshot request exceeded the native retained-artifact limit and was rejected;
the limit was preserved and the independent display recording continued.

The first native run exposed an adapter bookkeeping error: the Surface receipt
finished before publication of the destination capture. The adapter now publishes
that evidence before finishing the lease. The final automatic run asserts that
the receipt's `after_capture` equals the fresh destination identity and that a
reference from the previous capture is rejected.

`demo.json`, `transcript.json`, `identity.json`, `owned-processes.json`,
`verification.json`, `source-manifest.json` and `surface/native-receipts.jsonl` retain
the evidence. The original native receipts include full observations, so the
diagnostic log is bulky (over 100 MB for this run); this is not a production
retention/streaming-efficiency result. Surface snapshots occur at action
boundaries, independently of the video's 30 fps capture.

This replaces the spike's recording runner; the existing general-purpose
Surface runtime/CLI ChromeDriver adapter is unchanged. The native worker is a
small adapter around existing public APIs, not a new SDK controller. Native
Chrome recording is demonstrated here; simultaneous live viewers, BiDi, takeover,
audio and independent background-tab recordings were still unqualified at that
stage; the concurrent YouTube follow-up below addresses a bounded Chrome case. The N-tab
scheduler architecture is recorded in `architecture.md`, not implemented here.

The final clip is also copied unchanged to
`.generated/live-recording/yosoi-native-msnbc.mp4` for review. Focused build,
strict Clippy (`-D warnings`), Rust formatting and Python Ruff lint/format pass.
The final live run uses the rebuilt worker after cleanup/lifetime refinements;
its binary digest and source hashes are retained. No full SDK suite or hosted
CI had run at the time of that local experiment. See the draft PR for subsequent
push and hosted-CI delivery evidence.

## Concurrent real YouTube A/V: reviewed and accepted

The [approved clips and portable proof](evidence/README.md) are the main result.
Andrew watched both files and accepted their visual/audio separation.

| Observation | Result |
| --- | --- |
| Browser ownership | One regular Chrome 156.0.8078.47 instance through Yosoi's native provider |
| Website state | Two disposable browser contexts; fresh fixture cookies/local storage did not cross |
| Sources | Actual YouTube playback of *Big Buck Bunny* and *Sintel* |
| Capture | Two distinct live WebContents A/V streams, cropped by Chrome Region Capture |
| Encoding | Independent browser MediaRecorder VP8/Opus streams; H.264/AAC review copies |
| Start difference / overlap | 5 ms / 25.999 seconds |
| A paused, B playing | All 177,936 decoded A samples in the measurement window are zero; B is audible at −21.94 dBFS RMS |
| B paused, A playing | All 178,080 decoded B samples are zero; A is audible at −25.02 dBFS RMS |
| Video separation | Distinct WebContents sources, different decoded pictures, human review accepted |
| Resources | One logical CPU; requested up to 640×360 and 30 fps |

No inter-tab A/V bleed was observed in this run. Digital silence is an exact
decoded-sample observation, not a claimed 200+ dB isolation specification. The
clips intentionally pause A at about 6–11 seconds and B at 14–19 seconds.
Those static pictures/silent intervals are measurement phases, not buffering.
Observed frame intervals remain variable; neither stable 30 fps nor low-latency
remote streaming was established. Native video geometry can change when Chrome
adds sharing UI; the verifier accounts for it rather than stretching frames or
inventing timing. No external downloader or screenshot-to-video assembly is used.

The first export attempt exposed a data-URL parsing bug: the MIME type
`video/webm;codecs=vp8,opus` contains a comma. Export now takes the final comma
delimiter, and the native probe checks the first decoded chunk's WebM signature.

The experiment is an explicitly ignored native-provider test with an opt-in
self-tab capture grant, anonymous profiles, a private X display and a temporary
audio null sink. It does not change normal SDK flags, disable sandbox/site
isolation, capture a camera/microphone, or implement a general consent workflow.
Per-tab capture setup is not yet exposed by the public Session API. Contexts
isolate website state while browser GPU/audio services and failure/resource
domains remain shared. Arbitrary sites, navigation persistence, longer runs,
more than two captures, remote delivery, Firefox/BiDi, Hyprland and Windows are
unqualified. The pod/browser/context/tab scheduler remains a proposed design.
