# Plain Markdown page template

Use a single task or concept per page. The sections below describe the authoring shape. Copy the relevant structure into a `.md` page with title, description and `draft: true` frontmatter until it passes review.

## Opening

Say what the task achieves or what the concept means in one or two sentences. Introduce a concrete input and the useful result. Avoid starting with implementation architecture.

## Explain the sequence

Use ordinary numbered steps when the reader needs the overall sequence. Keep code fences for actual APIs.

1. Construct a source HTML Document from local bytes.
2. Keep its identity with the capture.
3. Inspect the same retained bytes.

## Example

### Rust

```rust
use std::error::Error;
use yosoi::documents::Document;

fn main() -> Result<(), Box<dyn Error>> {
    let html = b"<h1>Hello</h1>".to_vec();
    let document = Document::html("greeting", html.clone())?;
    assert_eq!(document.id().as_str(), "greeting");
    assert_eq!(document.bytes(), html.as_slice());
    Ok(())
}
```

`Document::html` constructs a source HTML document. The caller supplies an identity and bytes. The `?` propagates a construction error. The two checks show that the identity and original bytes remain available.

### Python

```python
import yosoi as ys

html = b"<h1>Hello</h1>"
document = ys.Document.html("greeting", html)
assert document.id == "greeting"
assert document.data == html
```

`ys.Document.html` constructs the corresponding document from the same input. The checks inspect its identity and retained bytes. Python exposes these values as fields and properties rather than Rust accessor calls.

## Result

Explain what both variants establish. Construction preserves identity and source data. It does not prove that later parsing or extraction will succeed.

These starter examples are grounded in `crates/yosoi/src/documents.rs` and `python/yosoi/documents.py`. They still need exact-revision execution receipts before being promoted into a public finished page.

## Commands

### Cargo

```sh
cargo add yosoi@0.2.0
cargo run
```

Save the Rust program as `src/main.rs` in an existing Cargo application.

### uv

```sh
uv add yosoi==0.2.0
uv run python example.py
```

Save the Python program as `example.py` in an existing uv project. These commands are the intended 0.2.0 documentation shape. Verify registry availability and the target platform before claiming that an installation was tested.

## Variation

Add another small paired example that changes one important condition. Explain the returned outcome or error. Avoid a long omnibus example that introduces unrelated APIs.

## Next step

Link to the next task, a concept that explains the behavior, or a specific reference symbol. Public pages should not contain maintainer checklists or workstation build receipts.
