---
title: Surface
description: Drive bounded web and video observations through a persistent JSON-lines session.
---

# Surface

`yosoi surface` keeps a reader alive while a coding agent sends one JSON command per line. Replies include the caller's optional `id`, an explicit success or error, and bounded evidence. Errors leave the session available for the next valid command.

## Open a web surface

```sh
yosoi surface web --url https://cascadinglabs.com/yosoi/getting-started/what-is-yosoi/ --headless --archive ./surface-evidence --output ./surface-run
```

The web adapter uses ChromeDriver and regular sandboxed Chrome or Chromium. Set `CHROMEDRIVER` and `CHROME` to select installed executables. Each session starts an isolated profile.

Send commands on standard input:

```json
{"id":1,"op":"describe"}
{"id":2,"op":"read","request":{"operation":{"kind":"overview"},"budget":{"bytes":2048,"items":5}}}
{"id":3,"op":"attach"}
{"id":4,"op":"status"}
```

The initial cursor is detached. `attach` enables a live reader; `hot` acquires the action slot. Reading and focusing do not grant action authority. Captures are explicit: `refresh` publishes current evidence, and effects attempt a fresh capture before reporting their outcome. A live reader can inspect without clicking.

## Follow a reference before acting

Search with `read` and a search operation, then copy a returned shared reference into `focus_evidence`. The reply contains the cursor's native focus reference for action commands. Keep the two reference types distinct.

Before a click, the adapter checks that the current target still belongs to the captured document and is visible, enabled, and reachable by a hit test. A stale reference, detached cursor, or covered element is rejected. Each effect also revalidates the Rust action lease.

For the docs version story, search for `Documentation release`, focus its `summary` element, acquire `hot`, and click with a text expectation for `v0.1.0`. Search again after that capture, focus the `v0.1.0` link, and click with a text expectation for the archived page's version notice. Verify that the observed destination is the v0.1.0 archive route.

For a complete agent task on QScrape’s synthetic shop, follow [Surfaces](../concepts/surfaces.md).

An effect without an observed postcondition remains unconfirmed. A successful transport call alone does not establish that the requested task succeeded. Other web operations include fill, key, scroll, navigate, article inspection, screenshots, refresh, cool, and detach.

## Open a video surface

Install FFmpeg and FFprobe on PATH, or select their executable paths with `YOSOI_FFMPEG` and `YOSOI_FFPROBE`. Archive storage requires Unix.

```sh
yosoi surface video --file recording.mp4 --archive ./video-evidence --output ./video-run
```

Use describe and the shared read protocol to explore its lazy timeline. `seek` selects a time in microseconds; frame and crop commands materialize PNG artifacts and return their paths with measured timestamps and integrity metadata. Video advertises `controllable: false` and rejects action commands.

## Replay or run again

Archive policy is enabled by `--archive`. Each command checkpoints immutable evidence and updates `record.json`. Normal close also exports `surface.yosoi`, a self-contained portable file. Move that file to another directory or machine without keeping the original Archive. Close the session to seal it before using a confirmed action recipe for a live repeat.

```sh
yosoi surface replay --record ./surface-run/surface.yosoi --repeat 3
yosoi surface repeat --record ./surface-run/surface.yosoi --count 3 --headless --output ./surface-repeat
yosoi surface replay --record ./video-run/surface.yosoi --repeat 3 --output ./saved-pixels
yosoi surface export --record ./surface-run/record.json --file ./portable-copy.yosoi
```

Replay reads saved evidence without opening a browser. Saved video frames replay without a decoder. Repeat performs new effects in a fresh browser session on each iteration, resolving targets against new evidence. It requires a sealed confirmed recipe with explicit targets and postconditions; it does not reuse old references as action permits. Existing `record.json` handles remain readable while their original directory exists. `export` can package those older runs into a portable file. Export destinations must not exist.

Incomplete portable outcomes remain inspectable through the SDK, but CLI replay rejects them rather than claiming a complete reconstruction. Portable files preserve rejected and unknown operation receipts. See [Archiving a surface](../concepts/archiving-a-surface.md) for Rust and Python save/reload examples and retention limits.

Archive storage is opt-in. A recording failure prevents further effects rather than silently discarding their evidence. EOF, close, Ctrl-C, and SIGTERM release the browser session. Replies default to 4,096 bytes, support 1,024 through 16,384 bytes, and reject oversized input lines above 64 KiB.

Use `yosoi surface --help` for command options. Continue with [Surfaces](../concepts/surfaces.md) for document and video walkthroughs, or [Archiving a surface](../concepts/archiving-a-surface.md) for portable outcomes.
