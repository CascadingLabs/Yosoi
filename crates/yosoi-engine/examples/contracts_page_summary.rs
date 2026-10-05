//! Page-scoped Contract using referenced pinned locator constants.

#![allow(dead_code)] // Public SDK example.

use std::error::Error;
use yosoi_engine::prelude as ys;

const TITLE_LOCATOR: ys::PinnedOutputLocator = ys::locator::css("title").text();
const DESCRIPTION_LOCATOR: ys::PinnedOutputLocator =
    ys::locator::css("meta[name=description]").text();

#[derive(ys::Contract)]
#[ys(id = "page_summary", description = "Summary metadata for one document")]
struct PageSummary {
    #[ys(
        description = "The page title shown to a reader",
        locator = TITLE_LOCATOR
    )]
    title: String,

    #[ys(
        description = "Optional page summary text",
        locator = DESCRIPTION_LOCATOR
    )]
    description: Option<String>,
}

fn evaluate_summary(
    document: &ys::Document,
) -> Result<ys::ContractOutcome<PageSummary>, ys::ContractLocatorError> {
    Ok(PageSummary::extract(&PageSummary::locate(document)?).validate())
}

fn main() -> Result<(), Box<dyn Error>> {
    let schema = PageSummary::schema()?;
    let _ = schema.scope();
    let _ = PageSummary::plan()?;
    Ok(())
}
