#![expect(
    clippy::panic_in_result_fn,
    reason = "assertions intentionally report Brave parser test failures"
)]
use std::{error::Error, io};

use super::{BraveParseError, parse};
use crate::internal::engine::{
    Document, Policy,
    search::{ProviderOutcome, WebCoverage},
};

const ROW: &str =
    include_str!("../../tests/fixtures/search-providers/fixtures/brave-organic-row.html");
const MULTIROW: &str =
    include_str!("../../tests/fixtures/search-providers/fixtures/brave-multirow.html");
const SPONSORED_CONTROL: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/brave-synthetic-sponsored-control.html"
);
const MISSING_HREF_CONTROL: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/brave-synthetic-missing-href.html"
);

#[test]
fn sanitized_row_keeps_url_title_and_snippet_together() -> Result<(), Box<dyn Error>> {
    let document = Document::html("brave-fixture.html", ROW.as_bytes().to_vec())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://search.brave.com/search?q=fixture",
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected a parsed Brave result page").into());
    };
    let hit = page
        .hits()
        .first()
        .ok_or_else(|| io::Error::other("sanitized Brave row produced no hit"))?;
    assert_eq!(hit.url().as_str(), "https://rust-lang.org/");
    assert_eq!(hit.title(), Some("[redacted captured title]"));
    assert_eq!(hit.snippet(), Some("[redacted captured snippet]"));
    assert_eq!(hit.organic_rank().get(), 1);
    assert_eq!(hit.placement_index().get(), 1);
    assert_eq!(page.issues().len(), 0);
    Ok(())
}

#[test]
fn zero_rows_are_unrecognized_not_empty() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "brave-empty-fixture.html",
        b"<html><body></body></html>".to_vec(),
    )?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://search.brave.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        ),
        Err(BraveParseError::UnrecognizedPage)
    ));
    Ok(())
}

#[test]
fn provider_navigation_is_not_an_organic_hit() -> Result<(), Box<dyn Error>> {
    let markup = ROW.replace(
        "https://rust-lang.org/",
        "https://search.brave.com/search?q=another-query",
    );
    let document = Document::html("brave-internal-link.html", markup.into_bytes())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://search.brave.com/search?q=fixture",
        10,
        16 * 1024 * 1024,
    );
    assert!(
        matches!(outcome, Err(BraveParseError::NoUsableHits)),
        "{outcome:?}"
    );
    Ok(())
}

#[test]
fn first_hit_cannot_exceed_normalized_byte_budget() -> Result<(), Box<dyn Error>> {
    let document = Document::html("brave-byte-limit.html", ROW.as_bytes().to_vec())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://search.brave.com/search?q=fixture",
            10,
            1,
        ),
        Err(BraveParseError::OutputLimit)
    ));
    Ok(())
}

#[test]
fn two_rows_keep_each_title_and_snippet_with_its_own_url() -> Result<(), Box<dyn Error>> {
    let second = ROW
        .replace("https://rust-lang.org/", "https://doc.rust-lang.org/book/")
        .replace("[redacted captured title]", "synthetic second title")
        .replace("[redacted captured snippet]", "synthetic second snippet");
    let document = Document::html("brave-two-rows.html", format!("{ROW}{second}").into_bytes())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://search.brave.com/search?q=fixture",
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected Brave results").into());
    };
    let first = page
        .hits()
        .first()
        .ok_or_else(|| io::Error::other("missing first result"))?;
    let second = page
        .hits()
        .get(1)
        .ok_or_else(|| io::Error::other("missing second result"))?;
    assert_eq!(first.url().as_str(), "https://rust-lang.org/");
    assert_eq!(first.title(), Some("[redacted captured title]"));
    assert_eq!(first.snippet(), Some("[redacted captured snippet]"));
    assert_eq!(second.url().as_str(), "https://doc.rust-lang.org/book/");
    assert_eq!(second.title(), Some("synthetic second title"));
    assert_eq!(second.snippet(), Some("synthetic second snippet"));
    assert_eq!(second.organic_rank().get(), 2);
    Ok(())
}

#[test]
fn captured_multirow_fixture_keeps_fields_with_their_source_row() -> Result<(), Box<dyn Error>> {
    let document = Document::html("brave-multirow.html", MULTIROW.as_bytes().to_vec())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://search.brave.com/search?q=fixture",
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected captured Brave rows").into());
    };
    assert_eq!(page.hits().len(), 2);
    let first = page
        .hits()
        .first()
        .ok_or_else(|| io::Error::other("missing first captured Brave row"))?;
    let second = page
        .hits()
        .get(1)
        .ok_or_else(|| io::Error::other("missing second captured Brave row"))?;
    assert_eq!(first.title(), Some("[redacted captured title row 1]"));
    assert_eq!(first.snippet(), Some("[redacted captured snippet row 1]"));
    assert_eq!(second.title(), Some("[redacted captured title row 2]"));
    assert_eq!(second.snippet(), Some("[redacted captured snippet row 2]"));
    assert_eq!(first.placement_index().get(), 1);
    assert_eq!(second.placement_index().get(), 2);
    let capped = parse(
        &document,
        &Policy::default(),
        "https://search.brave.com/search?q=fixture",
        1,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(capped_page) = capped else {
        return Err(io::Error::other("expected one capped organic result").into());
    };
    assert_eq!(capped_page.hits().len(), 1);
    assert_eq!(capped_page.coverage().web(), WebCoverage::Complete);
    assert_eq!(capped_page.issues().len(), 0);
    Ok(())
}

#[test]
fn synthetic_sponsored_control_is_not_selected_as_a_result_row() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "brave-synthetic-sponsored-control.html",
        SPONSORED_CONTROL.as_bytes().to_vec(),
    )?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://search.brave.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        ),
        Err(BraveParseError::UnrecognizedPage)
    ));
    Ok(())
}

#[test]
fn synthetic_missing_href_row_is_not_usable() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "brave-synthetic-missing-href.html",
        MISSING_HREF_CONTROL.as_bytes().to_vec(),
    )?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://search.brave.com/search?q=fixture",
        10,
        16 * 1024 * 1024,
    );
    assert!(
        matches!(outcome, Err(BraveParseError::NoUsableHits)),
        "{outcome:?}"
    );
    Ok(())
}
