---
title: 'Adding a product to the cart'
description: 'Read controls through accessibility evidence, click the lamp, and inspect its cart record.'
order: 6
---

# Adding a product to the cart

We can wait for a product and validate its data. Now we'll add the lamp to eShop's sample cart and read the resulting line.

A button has both a place in the DOM and a meaning in the interface. Before clicking, let's look at another representation of the page.

## Read the controls

The browser's **accessibility tree** describes controls through roles and accessible names. A button can have the role `button` and the name `Add to cart`. Its accessible name can come from visible text or an explicit label.

This evidence helps us understand what the interface offers. Request it explicitly, just as we requested rendered DOM. We'll use the static lamp page so its control is present in the initial markup.

## Example: inspect the button names

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Acquisition, BrowserMode, DocumentRequest, Page};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless)
            .documents([DocumentRequest::AccessibilityTree]),
    ])?;

    let plan = ys::Plan::new([ys::output("buttons", ys::role("button")?.name())?])?;
    let response = ys::request::new("https://qscrape.dev/eshop/html/product/obj-001/")
        .bind(&policy)
        .send()
        .await?;
    for document in response
        .attempts()
        .flat_map(|a| a.documents())
        .filter_map(|d| d.outcome().document())
    {
        println!("{:#?}", document.locate(&plan));
    }

    Ok(())
}
```

The Policy requests an accessibility tree. `role("button")` selects its button nodes, and `.name()` reads their accessible names. The findings include the lamp page's `Add to cart` control. The coordinates identify this captured tree and its generation.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.policy import Acquisition, Page, Policy


async def main():
    policy = Policy(
        page=Page(
            acquisitions=[
                Acquisition.browser("headless").with_documents(["accessibility_tree"]),
            ]
        )
    )

    plan = ys.Plan(outputs=[ys.output("buttons", ys.role("button").name())])
    response = (
        await ys.request.new("https://qscrape.dev/eshop/html/product/obj-001/")
        .bind(policy)
        .send()
    )
    for document in response.documents:
        print(document.locate(plan).values())


asyncio.run(main())
```

The Policy requests an accessibility tree. `role("button")` selects its button nodes, and `.name()` reads their accessible names. The printed values include the lamp page's `Add to cart` control. The findings retain the captured tree's coordinates and generation.

## Act, then inspect the result

The cart recipe uses the live browser's CSS selectors to act on the lamp's button. Reading an accessibility snapshot does not itself click a control.

We'll navigate to JavaScript eShop, wait for the lamp, click its button, open the cart, and wait for the lamp's cart line. The same invocation keeps browser state across those steps. The final Contract reads the product name, quantity, and total from that line.

## Example: add one lamp

These complete programs use the browser feature and async runtime from the previous lessons. They modify only eShop's sample cart.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Continuation, StopScope};

#[derive(ys::Contract)]
#[ys(id = "cart-line", description = "The lamp in our cart",
    root = ys::locator::css(r#"[data-shop-part="cart-line"][data-product-id="obj-001"]"#))]
struct CartLine {
    #[ys(description = "Product name", locator = ys::locator::css(".shop-cart-item-name").text())]
    name: String,
    #[ys(description = "Quantity text", locator = ys::locator::css(".shop-quantity span").text())]
    quantity: String,
    #[ys(description = "Line total", locator = ys::locator::css(".shop-line-total").text())]
    total: ys::Money,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let card = r#"article[data-product-id="obj-001"]"#;
    let cart_line = r#"[data-shop-part="cart-line"][data-product-id="obj-001"]"#;

    let recipe = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/javascript/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: card.into(),
            },
            5_000,
        ),
        // callout: The card scopes this click to the lamp's button.
        ys::action::click(format!("{card} button")),
        ys::action::navigate("https://qscrape.dev/eshop/javascript/cart/"),
        // callout: Wait for the resulting cart line, then inspect its values.
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: cart_line.into(),
            },
            5_000,
        ),
        // callout: These task checks make completion require the intended lamp, quantity, and total.
        ys::action::assert_all::<CartLine>(
            CartLine::plan()?,
            [
                ys::action::check(|line: &CartLine| line.name == "Arc desk lamp")
                    .named("lamp"),
                ys::action::check(|line: &CartLine| line.quantity == "1")
                    .named("one unit"),
                ys::action::check(|line: &CartLine| line.total.minor_units() == 6800)
                    .named("expected total"),
            ],
        )
        .into(),
    ])
    .on_failure(Continuation::Stop(StopScope::Invocation));

    let outcome = recipe.invoke().await?;
    outcome.require_completed()?;

    let html = outcome
        .steps
        .last()
        .and_then(|step| step.receipt.observation.as_ref())
        .and_then(|observation| observation.html.as_ref());
    if let Some(html) = html {
        let document = ys::Document::html("cart", html.as_bytes().to_vec())?;
        let lines = CartLine::extract(&CartLine::locate(&document)?)
            .validate()
            .require_all()?;
        for line in lines {
            println!("{} x{}: {}", line.name, line.quantity, line.total);
        }
    }

    Ok(())
}
```

The product ID scopes both the click and the cart record to the lamp. `on_failure` stops dependent work when a prerequisite fails. The wait establishes that its cart line exists. The final Contract assertion validates exactly one record and checks the intended name, quantity, and total. We then print values from its retained HTML.

Rust's native Contract fields support String and Money here, so quantity is retained as text. The total becomes Money. Run `cargo run`: the record prints `Arc desk lamp x1: $68.00`.

### Python

```python
import asyncio
import yosoi as ys


class CartLine(ys.Contract):
    """The lamp in our cart."""

    root = ys.css('[data-shop-part="cart-line"][data-product-id="obj-001"]')
    name: str = ys.Field("Product name", locator=ys.css(".shop-cart-item-name"))
    quantity: int = ys.Field("Quantity", locator=ys.css(".shop-quantity span"), ge=1)
    total: ys.Money = ys.Field("Line total", locator=ys.css(".shop-line-total"))


async def main():
    card = 'article[data-product-id="obj-001"]'
    cart_line = '[data-shop-part="cart-line"][data-product-id="obj-001"]'

    recipe = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/javascript/"),
            ys.wait_until(ys.exists(card), timeout_ms=5_000),
            # callout: The card scopes this click to the lamp's button.
            ys.click(f"{card} button"),
            ys.navigate("https://qscrape.dev/eshop/javascript/cart/"),
            # callout: Wait for the resulting cart line, then inspect its values.
            ys.wait_until(ys.exists(cart_line), timeout_ms=5_000),
            # callout: These task checks make completion require the intended lamp, quantity, and total.
            ys.assert_all(
                CartLine,
                checks=[
                    ys.check("lamp", lambda line: line.name == "Arc desk lamp"),
                    ys.check("one unit", lambda line: line.quantity == 1),
                    ys.check(
                        "expected total", lambda line: line.total.minor_units == 6800
                    ),
                ],
            ),
        ],
        on_failure=ys.policy.Stop(scope="invocation"),
    )

    outcome = await recipe.invoke()
    outcome.require_completed()

    observation = outcome.steps[-1].receipt.observation
    if observation is not None and observation.html is not None:
        document = ys.Document.html("cart", observation.html)
        for line in CartLine.extract(document):
            print(f"{line.name} x{line.quantity}: {line.total}")


asyncio.run(main())
```

The product ID scopes both the click and the cart record to the lamp. `on_failure` stops dependent work when a prerequisite fails. The wait establishes that its cart line exists. The final Contract assertion validates exactly one record and checks the intended name, quantity, and total. We then print values from its retained HTML.

Pydantic constructs quantity as an integer and applies the minimum of one. The total becomes Money. Run `uv run python main.py`: the record prints `Arc desk lamp x1: $68.00`.

## Keep the effect and its evidence together

The click is one operation. The cart line is evidence of the resulting state. A successful click receipt alone would not establish that the correct product reached the cart.

The example checks the name, quantity, and total so successful completion requires the intended cart state. These assertions are part of the browser task: they establish the result before dependent work continues. If an action times out after dispatch, preserve its receipts and inspect the cart before deciding to repeat it.

## Next

[Following the data](following-the-data.md) looks at the JSON that supplies the shop and introduces other document formats.
