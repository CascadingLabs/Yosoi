# Reviewed concurrent YouTube A/V evidence

Andrew reviewed both recordings and accepted their visual and audio separation.
The files below are the same approved MP4s, uploaded to Linear for durable access.
The clips require access to the Cascadinglabs Linear workspace; anonymous HTTP
requests are rejected. Media binaries are not added to the Git repository.
[youtube-proof.json](youtube-proof.json) retains their SHA-256 hashes, source URLs,
the observed browser/context facts, recording clocks and decoded pause checks.

- [Tab A — Big Buck Bunny](https://uploads.linear.app/7a9c5ed5-af54-43ad-a9ba-eb5cbc638eb6/37c9eaf5-f70a-4d4e-a8cb-83ae1565148a/0a812832-0277-4c0e-b4c9-764a5c5186ef)
- [Tab B — Sintel](https://uploads.linear.app/7a9c5ed5-af54-43ad-a9ba-eb5cbc638eb6/27251318-bf2f-4e6c-86af-ca3c6e083d83/6f31f497-a6b7-408e-aa55-ceb3791d98fb)

The streams overlap for **25.999 seconds** and their starts differ by **5 ms**.
One Chrome browser instance owns two separate disposable browser contexts and
distinct WebContents capture sources. The context fixture state was absent in
each new context. These are browser storage/control boundaries, not VM isolation.

Pause windows are intentional:

| Paused source | Own clip interval | Decoded audio in interior measurement window | Other source |
| --- | --- | --- | --- |
| A | 6.002–11.009 s | All 177,936 decoded samples are zero | B remains audible at −21.94 dBFS RMS |
| B | 14.007–19.017 s | All 178,080 decoded samples are zero | A remains audible at −25.02 dBFS RMS |

This demonstrates no observed inter-tab A/V bleed in the tested run. It does not
establish a universal security guarantee or maximum tab/encoder capacity. The
whole browser test was limited to one logical CPU, with a 640×360 / 30 fps capture
request. Observed frame timing is variable; this is not a 30 fps certification.
Pausing the source intentionally creates static pictures and silence.

## Source attribution

The code in this repository retains its repository license. The linked movie
excerpts contain separately licensed content:

- **Big Buck Bunny** — copyright 2008, Blender Foundation / www.bigbuckbunny.org.
  [Original YouTube source](https://www.youtube.com/watch?v=aqz-KE-bpKQ&t=30s).
  [Project license information](https://peach.blender.org/about/).
- **Sintel** — Blender Foundation, 2010.
  [Original YouTube source](https://www.youtube.com/watch?v=eRsGyueVLvQ&t=60s).
  [Project license information](https://durian.blender.org/about/).

Both films are released under [Creative Commons Attribution 3.0](https://creativecommons.org/licenses/by/3.0/).
Modifications: approximately 26-second browser recordings, deliberate playback
pauses for the isolation test, browser cropping to the video element, and
H.264/AAC compatibility transcoding with letterboxing. Source timing is preserved.
