use std::{error::Error, io::Error as IoError};

use yosoi::{LocateOutcome, prelude as ys};

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "products.html",
        br#"<article class='product'><span class='author'>Grace</span><span class='price'>12</span></article>"#.to_vec(),
    )?;

    let products = ys::css("article.product")?.each_as_region("product")?;
    let authors = products.find(ys::css(".author")?).text();
    let prices = products.find(ys::css(".price")?).text();

    let plan = ys::Plan::new([
        ys::output("product-author", authors)?,
        ys::output("product-price", prices)?,
    ])?;

    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err(IoError::other("expected product region findings").into());
    };
    for finding in result.findings() {
        println!("{}: {:?}", finding.output_id(), finding.value());
    }
    Ok(())
}
