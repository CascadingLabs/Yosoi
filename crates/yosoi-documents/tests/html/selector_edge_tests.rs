use std::{error::Error, io::Error as IoError};

use yosoi_documents::{LocateOutcome, Plan, ProjectedValue, css, output, xpath};

use super::html_document;

#[test]
fn relative_xpath_child_axis_starts_at_the_document_node() -> Result<(), Box<dyn Error>> {
    let document = html_document("<main><a>nested link</a></main>")?;

    let root_plan = Plan::new([output("root", xpath("html")?.node())?])?;
    let LocateOutcome::Matched { result } = document.locate(&root_plan) else {
        return Err(
            IoError::other("expected relative child axis to select document element").into(),
        );
    };
    assert_eq!(result.findings().len(), 1);

    let relative_plan = Plan::new([output("relative", xpath("a")?.text())?])?;
    assert!(matches!(
        document.locate(&relative_plan),
        LocateOutcome::NoMatch { .. }
    ));

    let descendant_plan = Plan::new([output("descendant", xpath("//a")?.text())?])?;
    let LocateOutcome::Matched { result } = document.locate(&descendant_plan) else {
        return Err(IoError::other("expected descendant axis to select nested link").into());
    };
    assert_eq!(result.findings().len(), 1);
    assert_eq!(
        result.findings().first().map(|finding| finding.value()),
        Some(&ProjectedValue::Text("nested link".to_owned()))
    );
    Ok(())
}

#[test]
fn css_and_xpath_exact_attribute_values_allow_quoted_closing_brackets() -> Result<(), Box<dyn Error>>
{
    let document = html_document("<a data-label=\"left]right\">bracket value</a>")?;
    let plan = Plan::new([
        output("css", css("a[data-label='left]right']")?.text())?,
        output("xpath", xpath("//a[@data-label='left]right']")?.text())?,
    ])?;

    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err(IoError::other("expected exact-value selectors with quoted brackets").into());
    };
    assert_eq!(result.findings().len(), 2);
    assert_eq!(
        result.findings().first().map(|finding| finding.value()),
        Some(&ProjectedValue::Text("bracket value".to_owned()))
    );
    assert_eq!(
        result.findings().get(1).map(|finding| finding.value()),
        Some(&ProjectedValue::Text("bracket value".to_owned()))
    );
    Ok(())
}
