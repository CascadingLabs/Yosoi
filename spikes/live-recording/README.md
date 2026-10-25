# Live display and recording lab

Exploratory work based on PR #166 for
[Custom noVNC & video recording](https://linear.app/cascadinglabs/project/custom-novnc-and-video-recording-d253f26cbd2c/overview).
Project fit is undecided. No public SDK API or production backend is changed.
The reviewed recordings were captured over original head `44928628`; the
delivery branch is rebased onto refreshed #166 head `6f4e8fa7`.

## What the spike demonstrated

**One native Yosoi-owned Chrome browser can record separate live audio/video
streams from two YouTube tabs in isolated browser contexts.** The recordings
overlapped for 25.999 seconds, started 5 ms apart, and showed no observed bleed.
Pausing either movie produced digital silence in its own captured audio while
the other recording stayed audible. Andrew reviewed the clips and accepted
their visual/audio separation. See the [reviewed videos and proof](evidence/README.md).

The progression matters: the first probe qualified display capture, the second
put acquisition/actions on the public native Session/Work path, and the final
probe qualified Chrome's independent tab media sources through Yosoi's private
native provider. These are separate experiments; the final per-tab capture
configuration is not a released public SDK API.

This makes a tab a credible unit for scheduling, interaction authority,
recording and eventual streaming. The [architecture guide](architecture.md)
describes pods → browser instances → contexts → tabs → readers and one hot
cursor, with separate action and capture capacities. Kubernetes deployment,
the scheduler and concurrent per-tab WebRTC delivery are not implemented here.

The question: can we view and record the same headed browser display without
depending on its CDP or BiDi automation protocol? The lab launches a private
Xvfb display and regular Chrome or Firefox, streams its pixels over WebRTC,
records it independently with FFmpeg, and optionally exposes the same display
through a VNC server and noVNC. Read [the architecture guide](architecture.md)
first for the terminology and the path toward Hyprland and Windows.

## Run

Linux prerequisites: `uv`, `Xvfb`, `ffmpeg` with x11grab/libx264, `xdotool`, and a
regular Stable Chrome executable or regular Firefox. No testing distributions,
sandbox-disabling switches, Rust builds, credentials, or system configuration
changes are needed. Python dependencies use UV's shared cache, with Python 3.12
to use binary wheels. This standalone tool deliberately does not install/build
the parent Rust/Python package or create a project virtual environment.

From the workspace root:

```sh
spikes/live-recording/run.sh --engine chrome --browser /absolute/path/to/chrome
# Or, after stopping that run:
spikes/live-recording/run.sh --engine firefox --browser /absolute/path/to/firefox
```

Open <http://127.0.0.1:8765>. Connect WebRTC, take human control, click the fixture
input and type, start recording, interact, then save. Saved MP4 links appear
below the viewer. The keyboard supports text, navigation keys, and wheel input;
dragging, held modifiers, clipboard, IME fidelity and audio remain future work.

For the VNC comparison, install/provide `x11vnc` and an unpacked noVNC release:

```sh
spikes/live-recording/run.sh --engine chrome --browser /absolute/path/to/chrome \
  --novnc /absolute/path/to/noVNC-1.7.0 --x11vnc /absolute/path/to/x11vnc
```

Expand the noVNC comparison below the WebRTC viewer. The embedded client uses
`/vnc`, a small WebSocket-to-TCP bridge in this tool. A native VNC viewer can
also connect to `127.0.0.1:5905`. Both VNC views are **read-only**, enforced by
x11vnc, so they cannot bypass the lab input gate. Interactive noVNC/native VNC
with server-enforced ownership is a separate next experiment.

The lab listens on loopback and rejects other Host/Origin values. It is a
trusted local experiment, without remote authentication, TURN, TLS or tenant
isolation. Xvfb is a separate display, not a container or security boundary.
Do not publish these ports. Ctrl+C stops recording and terminates owned child
processes. Output defaults to `.generated/live-recording/`; use `--output` to
keep runs separate. Requested resolution defaults to 1280×720 at 30 fps.

## Focused validation

While one lab is running:

```sh
uv run --no-project --python 3.12 \
  --with aiortc==1.14.0 --with aiohttp==3.13.3 \
  python spikes/live-recording/probe.py
```

The probe checks the input gate, accepts human input, rejects a cross-origin
request, receives 90 real WebRTC frames while recording, checks changing pixels,
finalizes the recording, and returns control. With noVNC enabled it also checks
the client asset and an RFB greeting through the WebSocket bridge. It saves a
received PPM image and JSON receiver measurements. Inspect the image: changing
pixels alone can come from a welcome screen rather than the intended fixture.
Use `ffprobe` on the named MP4 to verify codec, dimensions, frames and duration.
If the probe fails during recording, save/stop in the viewer before rerunning.

The probe is a transport/capture check, not a full noVNC rendering test or proof
that the intended click/text had a visible effect. Receiver fps, encoded file
fps, and the viewer's jitter-buffer statistics are different measurements.
None establishes input-to-visible-response latency. A nearby-server target of
30 fps and under 150 ms visible response remains unproven.

## Scope and next experiment

- The initial fixture uses no automation protocol for capture, recording or OS
  input. The native worker below adds Chrome Session/Work recording evidence.
  BiDi qualification and simultaneous live WebRTC/noVNC viewing remain separate.
- The owner switch gates lab human input only. No Yosoi automation worker is
  attached or paused. Production takeover must stop admission of new actions,
  settle/cancel in-flight work, grant a controller lease, and resume explicitly.
  All viewers currently share the local human role; there are no per-user leases.
- Live consumers use an unbuffered relay; recording uses a second capture and
  encoder process. This isolates file-write queues, but CPU contention still
  affects streaming. It also duplicates capture/encode work. Recording runs at
  one FFmpeg encoder thread; aiortc/browser internals may use additional threads.
- Moli's headless renderer has no persistent GUI desktop. No Moli parity is
  claimed. Hyprland, Windows, remote networking, performance targets and a
  maintained Neko/Kernel backend comparison remain unqualified.

Next: qualify both automation controllers with the native Session worker,
then implement ownership at the action dispatcher
and qualify VNC input through the same authority. Compare a maintained Neko or
Kernel streaming backend before adopting this Python implementation.

## Record native Yosoi Session actions

`surface_record.py` owns a private display and FFmpeg recorder. Its worker uses
Yosoi's production `session::Session` and `Work` API to acquire regular Chrome,
navigate, evaluate evidence, click and capture screenshots through
Chromiumoxide/CDP. It does not use ChromeDriver, manually launch Chrome, attach
an external controller, or disable Chrome's automation banner cosmetically.

Build the worker from this workspace, using the existing Cargo target/cache:

```sh
CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 cargo build -p yosoi \
  --features browser-bidi,surface-video --example live_recording_native
```

```sh
uv run --no-project --python 3.12 python spikes/live-recording/surface_record.py \
  --worker /absolute/path/to/target/debug/examples/live_recording_native \
  --chrome /absolute/path/to/chrome --url https://www.msnbc.com/ \
  --output .generated/live-recording/my-surface-run
```

Add `--query 'text from a visible article link'` for an automatic run. It uses
Surface reads to discover the link, verifies the native click and destination
capture, checks rejection of the stale reference, observes a programmatic
scroll, reads the final URL and closes the browser. It never accepts site terms.

The native worker keeps the same owned Session and Work lease for its lifetime.
Read its ready response, then send `attach`, `find`, `parent`, `inspect`,
`eligibility`, `click` and `scroll` commands using returned Surface references.
`{"op":"close"}` finalizes `display.mp4` and saves the command transcript.
The worker acquires a Surface action lease for each click and confirms the
destination URL and heading independently of the native dispatch receipt.

Current native `Work.click` takes a unique selector. The adapter derives a
temporary structural path from the exact object in the captured DOM, verifies
that it resolves to that object, and rejects changed, occluded or disabled
targets before dispatch. There are no stored site selectors or JavaScript
`element.click()` calls. Captures retain the existing explicit string-normalization
metadata. Large snapshots are transferred in bounded chunks without truncation.

`scroll` uses explicitly authorized `Work.evaluate` because the public Work API
has no wheel action. It reports a programmatic scroll and the observed before/
after positions; it does not claim trusted native wheel input. Surface reads
and postcondition inspection use the same policy-authorized evaluation API.

`identity.json` pins the native worker digest; `owned-processes.json` records
only its descendants and launch arguments. `surface/native-receipts.jsonl`
retains original native receipts and Session/tab provenance. This entry point
is a spike adapter around public SDK APIs, not a replacement of the existing
Surface web runtime's ChromeDriver adapter or a new public SDK interface.

Human takeover coordination, BiDi recording qualification and live WebRTC/noVNC
interaction during native automation remain separate work. See [results](results.md)
for the earlier ChromeDriver run and the native replacement's evidence.

For the planned scheduler, see [one browser, N scheduled tabs](architecture.md#one-browser-n-scheduled-tabs).
This worker qualifies one tab; its display recorder does not claim independent
background-tab streams.

## Concurrent per-tab audio/video

There are two explicitly ignored native-provider probes. They use regular
Chrome Stable, disposable profiles and Xvfb; sandboxing/site isolation remain
enabled. The opt-in harness supplies Chrome's `auto-accept-this-tab-capture`
test switch so the requested sources can capture themselves. No microphone,
camera, ordinary desktop, existing profile or authentication cookies are used.
This consent setup is a test prerequisite, not a production authorization design.

Additional Linux prerequisites: `taskset`, `pactl`, and a running PulseAudio or
PipeWire-Pulse server. The harness creates a named null sink, routes only its
browser to it, and unloads that sink afterward. It binds the whole experiment
to one logical CPU. Use a fresh output directory for each run.

```sh
CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 cargo test -p yosoi \
  --features browser-bidi,surface-video --lib tab_av_spike --no-run
```

Use the test executable path printed by Cargo:

```sh
# Two animated/tone fixture tabs sharing one browser window:
uv run --no-project --python 3.12 python spikes/live-recording/tab_av.py \
  --test-binary /absolute/path/from/cargo --chrome /absolute/path/to/chrome \
  --tabs 2 --output .generated/live-recording/av-fixture

# Two real YouTube movies in separate contexts of the same browser:
uv run --no-project --python 3.12 python spikes/live-recording/tab_av.py \
  --test-binary /absolute/path/from/cargo --chrome /absolute/path/to/chrome \
  --youtube --output .generated/live-recording/av-youtube

uv run --no-project --python 3.12 python spikes/live-recording/verify_youtube_av.py \
  .generated/live-recording/av-youtube
```

The YouTube experiment uses *Big Buck Bunny* and *Sintel*. It first checks that
fixture cookies/local storage did not cross the fresh contexts. It then plays
both actual movies, starts a real `getDisplayMedia()` A/V stream in each tab,
and uses Chrome Region Capture to crop to the video element. `MediaRecorder`
encodes VP8/Opus directly. The supervisor collects bounded chunks through the
native provider; there is no screenshot assembly or external video downloader.
The verifier decodes the original streams and creates H.264/AAC review copies,
preserving timestamps and letterboxing rather than stretching capture resizes.
Use `--no-transcode` to recheck existing outputs without rewriting the MP4s.

The 26-second recordings include intentional pauses: A around seconds 6–11,
B around seconds 14–19. Interior pause-window PCM is compared with the other
simultaneously active recording. Exact decoded zeros are reported as digital
silence, not as an invented finite dB separation figure. A sign-in/CAPTCHA,
consent or player gate stops the experiment and saves diagnostics; it never
substitutes downloaded media for an unsuccessful browser run.

The fixture supports a bounded 2–4-tab parameter; only two simultaneous streams
were qualified in this spike. Requested 30 fps is not a measured performance
guarantee, especially under the one-CPU constraint and intentional pauses.
The synthetic verifier can inspect its frame barcode and distinct tones:

```sh
uv run --no-project --python 3.12 python spikes/live-recording/verify_tab_av.py \
  .generated/live-recording/av-fixture
```

Capture pins the source tabs' rendering: Chrome can report them as `visible`
while the control tab is focused. Focus/activation and capture rendering state
must be treated separately by a future scheduler.
