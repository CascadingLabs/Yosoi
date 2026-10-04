---
title: Text and regex
description: Find literal text and named captures in decoded UTF-8 documents.
order: 10
---

# Text and regex

Text locators operate on a decoded UTF-8 document. Use literal matching for a fixed string and regex for a pattern.

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;

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

The `order` findings contain the full matched text and the requested `id` capture. Use `.text()` if you only need the full match.

## Capture names

`.captures(["id"])` requests named groups explicitly. Empty capture lists, duplicate names, and names absent from the regex are errors. Captures are returned in `ProjectedValue::TextWithCaptures`; the map contains the named groups that participated in the match.

Regex syntax follows the Rust `regex` engine. Look-around and backreferences are not supported. Pattern size, evaluation work, matches, captures, and output are bounded by Policy.

## Text is a representation

Text ranges refer to the decoded text input. They are not byte offsets into a compressed HTTP body or a rendered page. Preserve the input document when storing findings.

`Document::text` does not strip HTML tags. Use [HTML selectors](html.md) to find element text, or create a text document from a deliberate text conversion in your application.

For a fixed value stored on a Contract, `ys::locator::text_literal("...").text()` is the static authoring form. See [Contracts](contracts.md).
