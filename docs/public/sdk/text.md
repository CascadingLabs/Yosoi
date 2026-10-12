---
title: Text and regex
description: Find literal text and named captures in decoded UTF-8 documents.
order: 10
---

# Text and regex

Text locators operate on a decoded UTF-8 document. Use literal matching for a fixed string and regex for a pattern.

## Example: text

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::text(
        "orders.txt",
        b"Order #123 shipped. Order #456 pending.".to_vec(),
    )?;
    let plan = ys::Plan::new([
        ys::output("shipped", ys::text_literal("shipped")?.text())?,
        ys::output(
            "order",
            ys::regex(r"Order #(?P<id>\d+)")?.captures(["id"])?,
        )?,
    ])?;
    println!("{:?}", document.locate(&plan));
    Ok(())
}
```

The literal query reads decoded text. The regex names a capture, so callers can distinguish the order ID from the full match.

### Python

```python
import yosoi as ys

document = ys.Document.text("orders.txt", "Order #123 shipped. Order #456 pending.")
plan = ys.Plan(outputs=[
    ys.output("shipped", ys.text_literal("shipped").text()),
    ys.output("order", ys.regex(r"Order #(?P<id>\d+)").captures("id")),
])
outcome = document.locate(plan)
assert outcome.values("shipped") == ["shipped"]
print(outcome.values("order"))
```

The same named capture is authored with `captures`. Regex operates on the text document rather than a DOM.

## Walk through the result

The `order` findings contain the full matched text and the requested `id` capture. Use `.text()` if you only need the full match.

## Capture names

`.captures(["id"])` requests named groups explicitly. Empty capture lists, duplicate names, and names absent from the regex are errors. Captures are returned in `ProjectedValue::TextWithCaptures`; the map contains the named groups that participated in the match.

Regex syntax follows the Rust `regex` engine. Look-around and backreferences are not supported. Pattern size, evaluation work, matches, captures, and output are bounded by Policy.

## Text is a representation

Text ranges refer to the decoded text input. They are not byte offsets into a compressed HTTP body or a rendered page. Preserve the input document when storing findings.

`Document::text` does not strip HTML tags. Use [HTML selectors](html.md) to find element text, or create a text document from a deliberate text conversion in your application.

For a fixed value stored on a Contract, `ys::locator::text_literal("...").text()` is the static authoring form. See [Contracts](contracts.md).
