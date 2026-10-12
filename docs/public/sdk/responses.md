---
title: Responses
description: Distinguish acquisition failures, partial documents, and usable evidence.
order: 3
---

# Responses

A response contains acquisition attempts in Policy order. Each attempt contains an outcome for each document requested from that acquisition.

| Acquisition attempt | Requested representation | Example outcome |
| ------------------- | ------------------------ | --------------- |
| Direct HTTP         | Response document        | Produced        |
| Browser             | Rendered DOM             | Produced        |
| Browser             | Accessibility tree       | Partial         |

This structure lets you use a successful document while keeping the reasons another document was unavailable.

## Acquisition state

| `AttemptState`       | Meaning                                                                  |
| -------------------- | ------------------------------------------------------------------------ |
| `Completed`          | The acquisition completed; inspect its document outcomes and HTTP status |
| `Failed(kind)`       | The acquisition failed; `diagnostic()` may explain why                   |
| `NotStarted(reason)` | The acquisition did not start                                            |

`status()` returns `Option<u16>` because an HTTP response may never have been observed. A completed attempt is not a promise of a successful HTTP status or usable document.

## Document state

| `DocumentOutcome`               | Meaning                                                   |
| ------------------------------- | --------------------------------------------------------- |
| `Produced(document)`            | The requested representation was materialized             |
| `Partial { document, reasons }` | Evidence is incomplete; a usable document may be present  |
| `Unavailable(reason)`           | The requested evidence is unavailable                     |
| `Unprojectable(reason)`         | Captured evidence could not become the requested document |

Use `document()` when you intentionally accept both produced and usable partial documents. Match the enum when completeness affects your result.

## Locate complete documents

This function accepts a response and prints titles from fully produced HTML documents:

## Example: responses

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::documents::DocumentClass;
use ys::request::{DocumentOutcome, ResponseRef};

fn print_titles(response: ResponseRef<'_>) -> Result<(), Box<dyn Error>> {
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;

    for attempt in response.attempts() {
        for selected in attempt.documents() {
            match selected.outcome() {
                DocumentOutcome::Produced(document)
                    if document.class() == DocumentClass::SourceHtml =>
                {
                    println!("{:?}", document.locate(&plan));
                }
                DocumentOutcome::Partial { reasons, .. } => {
                    eprintln!("Partial document: {reasons:?}");
                }
                other => eprintln!("Other document outcome: {other:?}"),
            }
        }
    }
    Ok(())
}
```

This helper accepts an acquired Response and inspects each requested representation. Partial documents remain distinct from produced HTML.

### Python

```python
import yosoi as ys

def print_titles(response):
    plan = ys.Plan(outputs=[ys.output("title", ys.css("h1").text())])
    for attempt in response.attempts:
        for selected in attempt.documents:
            outcome = selected.outcome
            if outcome.status == "produced" and outcome.document.document_class == "source_html":
                print(outcome.document.locate(plan))
            elif outcome.status == "partial":
                print("Partial document:", outcome.reasons)
            else:
                print("Other document outcome:", outcome)
```

Pass a Response returned by `send` to this helper. The fields expose the same per-attempt document outcomes.

## Walk through the result

Pass `response.as_ref()` for a normal request or `capture.response()` for a [Map capture](map.md).

## Ownership

`Response` owns the result. `ResponseRef`, `Attempt`, `AttemptDocument`, and `DocumentRef` borrow from it. Reading a document's bytes does not copy them.

Call `DocumentRef::to_owned()` when a document must outlive the response. This retains an owned copy; use it deliberately for larger documents. An owned document can also be passed to a Contract's generated `locate()` method. To avoid the copy, call `document.locate(MyContract::plan()?)` on the borrowed document.

## Correlation and configuration

`request_id()` identifies the request. Each attempt has a `capture_id()`, `requested_target()`, `acquisition()`, and `authored_selection()`. Each selected document reports `requested()`.

`policy_snapshot()` preserves the validated Policy used for execution. `termination()` distinguishes normal completion from cancellation. Keep these facts alongside the data you use when you need to explain an outcome.
