---
title: Accessibility
description: Query roles, names, text, and states in a captured accessibility tree.
order: 11
---

# Accessibility

An accessibility document describes the semantic tree captured from a browser. Query it by role, accessible name, text, or boolean state.

This complete local example creates a small snapshot:

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::documents::DocumentEpoch;
use ys::locators::AccessibilityStateName;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::accessibility_tree(
        "button.ax.json",
        DocumentEpoch::try_from(1)?,
        br#"{
            "schema":"yosoi.accessibility-tree.v1",
            "document_epoch":1,
            "root":"buy",
            "completeness":{"status":"complete"},
            "nodes":[{
                "id":"buy", "parent":null, "children":[],
                "ignored":false, "role":"button",
                "accessible_name":"Buy tea", "text":"Buy tea",
                "states":{"focused":true}
            }]
        }"#.to_vec(),
    )?;
    let plan = ys::Plan::new([
        ys::output("buttons", ys::role("button")?.name())?,
        ys::output("buy", ys::accessible_name("Buy tea")?.node())?,
        ys::output("text", ys::accessibility_text("Buy tea")?.text())?,
        ys::output(
            "focused",
            ys::accessibility_state(AccessibilityStateName::Focused, true).node(),
        )?,
    ])?;
    println!("{:?}", document.locate(&plan));
    Ok(())
}
```

In a live workflow, request `DocumentRequest::AccessibilityTree` through [Browser](browser.md) and use the returned document directly.

## Query and projection

Use `.name()` with `role(...)` or `accessible_name(...)`. Use `.text()` with `accessibility_text(...)`. All four query families can return `.node()` references; state queries support only that projection.

Role, name, and text queries use exact string equality and skip ignored nodes. The supported boolean states are `Expanded` and `Focused`. State matching uses the value actually recorded in the snapshot; an absent state is not the same as a recorded `false` value. Accessibility queries do not infer a new tree from HTML, and they do not act on browser elements.

## Incomplete trees

Findings inherit the snapshot's completeness. If a partial or unknown tree has no match, the outcome is `Indeterminate`, because omitted nodes might have matched. Inspect completeness before concluding that a control is absent.

Coordinates include the document epoch and node identity. Keep both with the snapshot. A later navigation may produce a different epoch even at the same URL.
