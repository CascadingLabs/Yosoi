# Surface documentation review

Workspace: `/home/andrew/Desktop/cl/yosoi-observation-index-spike`.
Delivery: draft PR #164, `andberg9/cas-616-surfaces`.
Rust API artifact: `a408de85a8d2f22fef001f3a11d454bdc8fcbf2a`, features
`browser,surface-video`, verified unsigned preview. The current SDK source and
manifest have zero changes from that artifact's SDK source. Python references
are regenerated from the working package by the normal docs pipeline.

## Reader claims and evidence

| Page | Reader task | Implementing evidence |
| --- | --- | --- |
| `concepts/exploring-a-surface.md` | Find a region, inspect exact evidence, follow bounded continuations | Rust Surface; installed Python tests; six shared Rust/Python document vectors |
| `concepts/exploring-video.md` | Select media time, obtain actual pixels, restore archived PNG evidence | Rust VideoSurface/DecodedFrame; installed Python video tests; both supplied MP4s |
| `sdk/surfaces.md` | Distinguish references, capabilities, cursor ownership and adapter lifecycle | Shared model, Session/Cursor/ActionLease and native Python bindings |
| `cli/surface.md` | Drive JSON lines, confirm a version switch, replay evidence or repeat effects | Installed CLI, public version driver, normal Archive/AutomationRecord |

The immutable web SDK reader is non-controllable. Session coordinates an
external adapter; attachment is not an automatic DOM subscription. CLI web
captures are explicit and actions attempt fresh evidence. No live-streaming,
OCR, audio decoding or additional device provider is claimed.

## Executed examples

The exact Rust and Python fences from both concept pages were extracted to
`.local/surface-doc-snippets/src`. Both languages' document programs printed
`Arc desk lamp`; both video programs measured source PTS 3,500,000 and restored
a 440,661-byte PNG. Scoped formatting did not change any executed fence.

The installed free-threaded CPython 3.14 wheel passed 18 Surface checks.
The wheel's Python files match the working source. Shared conformance compares
HTML, XML, JSON, text, rendered DOM and partial accessibility evidence across
Rust and Python, retaining reference, overview, find and inspection values.
Surface is included in the parity inventory; its previous deferral is removed.

`surface_read` and `python/examples/surface_read.py` acquired the live QScrape
lamp page: 82 indexed nodes, six literal matches, and the same index identity
after normal Archive restoration. Both SDKs processed each supplied recording;
timeline/metadata/frame/crop values and actual PNG bytes matched. Fresh Python
processes restored the saved crops with both video tool paths unavailable.

The installed CLI completed the public docs version driver with two confirmed
clicks. Offline replay ran three iterations with no browser. Three fresh live
repetitions each confirmed both clicks and reached the v0.1.0 archive URL.
The installed two-provider CLI verifier passed 17 web and 16 video replies,
including archived pixels with its source copy deleted and decoder disabled.

The first public version-driver run intentionally retained an unconfirmed
receipt: the site removed its theme query parameter, so exact navigation did
not match. The completed driver instead checks the observed version notice and
the destination's origin, path and version. The generic exact navigation check
was preserved. Failed driver runs now retain transcripts too.

## Rendered review

The existing CascadingLabsFE pipeline ran on port 4321 with
`YOSOI_REPO_ROOT` explicitly selecting this workspace and the verified Rust API
artifact explicitly overriding its older local configuration. The serving
process's working directory and environment were checked. Actual HTTP pages
contained all four current guides.

The initial guide rendered correctly. Through the installed Surface CLI, a
6,481-node rendered document was navigated structurally to its Python tab.
The native click was confirmed and the resulting URL included `code=python`.
Both selected-language screenshots were inspected. No frontend source was
changed and no documentation was deployed.

## Checks and delivery boundary

Passed locally: SDK all-feature library check; strict native/library/example
Clippy; public-source Ruff and Python typing; reference tooling tests; docs
validation and native Markdown rendering; 25 docs-tooling tests; 123 parity
tooling tests; focused release-matrix tests. The full docs gate validated 673
Markdown pages and four assets. Hosted checks must validate the final PR head
before handoff; older green checks are separate evidence.

Private recordings, screenshots, raw archives and reports stay in `.local`.
The browser adapter's production integration/certification and recording
storage optimizations remain separately tracked. No merge or release is
authorized by these local results.
