//! Inspect local Flow continuation settings without acquiring a browser.

use std::error::Error;

use yosoi::{Policy, action, prelude as ys};

fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = Policy::default();
    policy.flow.on_failure = ys::Stop(ys::Invocation);

    let account_flow = ys::Flow::new([
        action::navigate("https://shop.example/account"),
        action::assert(ys::Condition::Exists {
            selector: "[data-account]".to_owned(),
        })
        .into(),
    ])
    .on_failure(ys::Stop(ys::CurrentFlow));

    let checkout_flow = ys::Flow::new([
        account_flow.into(),
        action::screenshot().on_failure(ys::Continue),
    ])
    .on_cancellation(ys::Stop(ys::Invocation));

    checkout_flow.validate()?;
    println!("Policy: {}", policy.to_canonical_json()?);
    println!("Flow: {}", serde_json::to_string_pretty(&checkout_flow)?);
    Ok(())
}
