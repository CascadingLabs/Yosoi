---
title: XML
description: Query XML with explicit namespace bindings.
order: 8
---

# XML

XML documents support CSS, XPath, and tree text queries. Names are case sensitive, and namespace identity matters.

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::xml(
        "catalog.xml",
        br#"<catalog xmlns="urn:shop"><product sku="tea"><name>Tea</name></product></catalog>"#.to_vec(),
    )?;
    let names = ys::xpath("/s:catalog/s:product/s:name")?
        .with_namespace("s", "urn:shop")?;
    let products = ys::css("s|product")?.with_namespace("s", "urn:shop")?;
    let plan = ys::Plan::new([
        ys::output("name", names.text())?,
        ys::output("sku", products.attribute("sku")?)?,
    ])?;
    println!("{:?}", document.locate(&plan));
    Ok(())
}
```

The query prefix `s` is local to your query. It resolves to `urn:shop`, regardless of which prefix the source document uses.

## Namespaces

Use `.with_namespace(prefix, uri)?` for prefixed queries. CSS also supports `.with_default_namespace(uri)?` for unprefixed element selectors. XPath's unprefixed element names match elements in no namespace; use a bound prefix for namespaced elements. Namespace bindings belong to each query, so add them to region and child queries that need them.

Default element namespaces do not automatically qualify unprefixed attributes. In the example, `sku` has no namespace.

## Supported queries

Use element paths, descendant selection, supported predicates, and CSS selectors within Yosoi's XML subset. Finish with `.text()`, `.attribute(name)?`, or `.node()`. Unsupported syntax and unbound prefixes produce errors; Yosoi does not silently switch query engines.

XML parsing is strict. Malformed XML is a parse failure, while well-formed XML with no matching element is a no-match result. XML tree coordinates retain expanded names so evidence is tied to namespace URIs, not merely source prefixes.

Use [Map](map.md) when your task is sitemap discovery. It already handles discovery documents and their source outcomes.
