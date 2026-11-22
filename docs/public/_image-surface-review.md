# Typed image Surface review

This maintainer receipt is excluded from public pages.

Workspace: `/home/andrew/Desktop/cl/yosoi-image-surfaces`. Base: PR 189 media foundation `26bb05fdac9bc088eaf2bcb5a4bc0bba4be68776`. Source revision before this receipt: `518c16c379ba`; WTF/JJ child: `quoozllp`.

## Public documentation map

| Page | Coverage |
| --- | --- |
| `concepts/surfaces.md` | Direct bounded decode, shared image reader, overview-to-source coordinate mapping, exact crop, Archive restoration, Python/Rust examples, small and dense measured tradeoffs, and the rule that these measurements do not predict model-token savings. |
| `sdk/surfaces.md` | Typed image entry points, PixelArtifact provenance, coordinate/orientation semantics, explicit transforms, independent pixel limits, screenshot/video artifact reuse, and legacy partial video provenance. |
| `sdk/media-documents.md` | PixelArtifact uses the existing typed ImageDocument Archive payload and retains historical Surface image-envelope compatibility. |
| `cli/surface.md` | Image CLI operations, pixel bounds, portable close output, and reopening a root artifact with `--pixel-artifact-ref`. |

The example headings are “Example: read a dense image” in `concepts/surfaces.md` and “Open an image surface” in `cli/surface.md`. The concept page contains separate Rust and Python fences; the CLI page contains shell and JSON-lines examples.

## Evidence

- `cargo fmt --all -- --check` and `git diff --check` passed.
- `CARGO_INCREMENTAL=0 cargo check --locked -p yosoi --lib -j1` passed with only existing session dead-code warnings.
- `CARGO_INCREMENTAL=0 cargo check --locked -p yosoi --lib --all-features -j1` passed.
- The focused Rust image tests passed: five image-filter cases, two PixelArtifact archive/corruption cases, EXIF orientation, legacy video provenance, and legacy text-image-envelope Archive restoration.
- Portable Archive tests passed for typed video source closure, video frame-to-PixelArtifact-to-ImageDocument closure, and screenshot PixelArtifact provenance plus receipt-reference remapping.
- Outcome tests passed in default and all-feature builds, covering typed network profile/state/encoding/projection validation and forced BinaryDocument metadata preservation.
- The image CLI test passed for direct pixels, overview, exact crop, retained-artifact limits, Archive output, source-file deletion, and reopening the saved root PixelArtifact by reference.
- `uvx ruff check yosoi tests` and `uvx ruff format --check yosoi tests` passed. No Python wheel build or Python runtime suite was run; the owner reserved builds for the serial Rust slot.

Measured known-pixel results from the test machine, with millisecond timing resolution:

| Fixture | Direct | Overview | Overview plus crop |
| --- | --- | --- | --- |
| Small pixel-drawn `λ` | 374 bytes / 256 pixels / 0 ms | 285 bytes / 64 pixels / 0 ms | 643 bytes / 208 pixels / 0 ms including index preparation |
| Dense dashboard with a 2×2 red marker | 42,799 bytes / 2,073,600 pixels / 53 ms | 1,621 bytes / 57,600 pixels / 327 ms resize | 1,815 bytes / 57,924 pixels / 380 ms including index, resize and crop |

The small direct result is cheaper to send than its overview plus exact crop. The dense overview loses the marker pixel; mapping a selected region to source coordinates recovers it exactly. These are fixture and machine measurements, not universal performance claims.

## Validation gaps and boundaries

- The public documentation validator was attempted earlier but could not start because `jsonc-parser` is unavailable; dependencies were not installed. Final authored Markdown was reviewed, formatted, and checked for diff whitespace.
- Python runtime parity, wheel compilation, generated reference pages, and public-page rendering remain unverified in this child.
- No live browser screenshot capture was run. Screenshot Artifact creation and portable reopening are covered by native Archive tests; video/network production capture remains owned by its respective slices.
- No OCR, text search, inferred labels, automatic quality selection, or model-token savings are claimed.
- No commit, push, PR, release, or hosted validation was performed.
