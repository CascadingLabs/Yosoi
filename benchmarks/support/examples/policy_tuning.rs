//! Offline user story for default tuning bound through one Policy.

use std::{error::Error, io};

use yosoi_dev_support::internal::engine::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let tuning = ys::policy::Tuning::default();
    let policy = ys::Policy {
        tuning,
        ..ys::Policy::default()
    };
    // Preparation snapshots the policy without making a network request.
    let request = ys::request::new("https://example.com/").bind(&policy);
    let prepared = request.prepare()?;
    if prepared.effective_policy().tuning != tuning {
        return Err(io::Error::other("prepared request lost its tuning").into());
    }

    let document = ys::Document::html("page", b"<h1>Hello</h1>".to_vec())?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    let one_shot = document.bind(&policy).locate(&plan);
    let parsed = document.bind(&policy).parse()?;
    let repeated = parsed.locate(&plan);
    if one_shot != repeated {
        return Err(io::Error::other("one-shot and reusable locations differ").into());
    }
    println!(
        "Selected tuning: {:?}",
        prepared.effective_policy().tuning.mode()
    );
    println!("Located result: {one_shot:#?}");
    Ok(())
}
