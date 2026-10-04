---
title: HTML and CSS
description: Select elements, attributes, and text from HTML or rendered DOM.
order: 7
---

# HTML and CSS

Use CSS for familiar element selection. The same plan can inspect source HTML and a compatible rendered-DOM snapshot.

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "article.html",
        br#"<main><h1>Tea <em>guide</em></h1><a class="next" href="/brewing">Next</a></main>"#.to_vec(),
    )?;
    let plan = ys::Plan::new([
        ys::output("title", ys::css("main h1")?.text())?,
        ys::output("next", ys::css("a.next[href]")?.attribute("href")?)?,
    ])?;
    println!("{:?}", document.locate(&plan));
    Ok(())
}
```

The title is descendant text, including text inside `em`. The link value is the authored `/brewing` attribute. Locator projection does not turn relative links into absolute URLs.

## Selection and projection

| Expression               | Selects                                     |
| ------------------------ | ------------------------------------------- |
| `css("h1")?`             | Heading elements                            |
| `css(".product")?`       | Elements with a class                       |
| `css("#main")?`          | An element ID                               |
| `css("a[href]")?`        | Links with an `href` attribute              |
| `css("main > article")?` | Direct children                             |
| `xpath("//article/h2")?` | Elements through the supported XPath subset |

Finish the selection with `.text()`, `.attribute("name")?`, or `.node()`. Select the element with XPath and use `.attribute(...)` for its attribute value.

Yosoi implements bounded selector subsets, not a browser's entire selector or XPath API. Unsupported syntax is rejected. Build the plan once and check the returned error before applying it to documents.

## Find elements by text

`tree_text_contains("Tea")?.text()` selects elements whose descendant text contains the string. Ancestors can match too. Use a structural selector or repeated region when you need a particular row rather than every enclosing element.

For matching text ranges or named regex captures, create a [text document](text.md). Raw HTML bytes and extracted text are different inputs; choose deliberately.

## Source or rendered DOM

Direct HTTP returns the source document. Client-side JavaScript may add content after that source was served. If a field exists only after JavaScript runs, request `DocumentRequest::RenderedDom` through [Browser](browser.md), then apply your plan to that document.

A snapshot is fixed at capture time. Running a locator does not wait for an element, execute JavaScript, click a button, or navigate.

Use [regions](locators.md#keep-repeated-rows-together) or a [Contract root](contracts.md) for product cards and other repeated records.
