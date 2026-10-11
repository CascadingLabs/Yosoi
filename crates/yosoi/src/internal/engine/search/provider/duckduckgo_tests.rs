#![expect(
    clippy::panic_in_result_fn,
    reason = "assertions intentionally report DuckDuckGo parser test failures"
)]
use std::{env, error::Error, fs, io, num::NonZeroU16, path::PathBuf};

use crate::internal::documents::DocumentEpoch;
use sha2::{Digest as _, Sha256};

use super::{DuckDuckGoParseError, parse};
use crate::internal::engine::{
    Document, Policy,
    search::{ProviderOutcome, SearchFailure, WebCoverage},
};

const ROWS: &str = include_str!("tests/fixtures/duckduckgo/duckduckgo-rendered-dom.json");
const EMPTY: &str = include_str!("tests/fixtures/duckduckgo/duckduckgo-empty-rendered-dom.json");
const CHALLENGE: &str =
    include_str!("tests/fixtures/duckduckgo/duckduckgo-synthetic-challenge-rendered-dom.json");
const PAGE_URL: &str = "https://duckduckgo.com/?q=fixture";
const RESULT_LIMIT: usize = 10;
const OUTPUT_LIMIT: usize = 16 * 1024 * 1024;

fn rendered_document(id: &str, bytes: impl Into<Vec<u8>>) -> Result<Document, Box<dyn Error>> {
    Ok(Document::rendered_dom(
        id,
        DocumentEpoch::try_from(1_u64)?,
        bytes,
    )?)
}

#[test]
fn sanitized_rows_keep_fields_together_skip_ads_and_preserve_placement()
-> Result<(), Box<dyn Error>> {
    let document = rendered_document("duckduckgo-results.json", ROWS.as_bytes().to_vec())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        PAGE_URL,
        RESULT_LIMIT,
        OUTPUT_LIMIT,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected parsed DuckDuckGo results").into());
    };
    let first = page
        .hits()
        .first()
        .ok_or_else(|| io::Error::other("missing first organic result"))?;
    let second = page
        .hits()
        .get(1)
        .ok_or_else(|| io::Error::other("missing second organic result"))?;

    assert_eq!(page.hits().len(), 2);
    assert_eq!(first.url().as_str(), "https://rust-lang.org/");
    assert_eq!(first.title(), Some("[redacted first title]"));
    assert_eq!(first.snippet(), Some("[redacted first snippet]"));
    assert_eq!(first.organic_rank().get(), 1);
    assert_eq!(first.placement_index().get(), 2);
    assert_eq!(second.url().as_str(), "https://doc.rust-lang.org/book/");
    assert_eq!(second.title(), Some("[redacted second title]"));
    assert_eq!(second.snippet(), Some("[redacted second snippet]"));
    assert_eq!(second.organic_rank().get(), 2);
    assert_eq!(second.placement_index().get(), 3);
    assert_eq!(page.coverage().web(), WebCoverage::Complete);
    assert_eq!(page.issues().len(), 0);
    let capped = parse(
        &document,
        &Policy::default(),
        "https://duckduckgo.com/?q=fixture",
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
fn observed_mainline_empty_marker_is_empty() -> Result<(), Box<dyn Error>> {
    let document = rendered_document("duckduckgo-empty.json", EMPTY.as_bytes().to_vec())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            PAGE_URL,
            RESULT_LIMIT,
            OUTPUT_LIMIT
        ),
        Ok(ProviderOutcome::Empty)
    ));
    Ok(())
}

#[test]
fn known_provider_challenge_marker_is_failed_challenge() -> Result<(), Box<dyn Error>> {
    let document = rendered_document("duckduckgo-challenge.json", CHALLENGE.as_bytes())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            PAGE_URL,
            RESULT_LIMIT,
            OUTPUT_LIMIT
        ),
        Ok(ProviderOutcome::Failed(SearchFailure::Challenge))
    ));
    Ok(())
}

#[test]
fn unknown_zero_row_document_is_not_empty() -> Result<(), Box<dyn Error>> {
    let empty_tree = r#"{"schema":"yosoi.rendered-dom.v1","document_epoch":1,"tree_model":"document_light_dom","root":1,"nodes":[{"kind":"document","id":1,"parent":null,"children":[2]},{"kind":"element","id":2,"parent":1,"children":[3],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"html","attributes":[]},{"kind":"element","id":3,"parent":2,"children":[],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"body","attributes":[]}] }"#;
    let document = rendered_document("duckduckgo-unrecognized.json", empty_tree.as_bytes())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            PAGE_URL,
            RESULT_LIMIT,
            OUTPUT_LIMIT
        ),
        Err(DuckDuckGoParseError::UnrecognizedPage)
    ));
    Ok(())
}

#[test]
fn first_hit_cannot_exceed_normalized_byte_budget() -> Result<(), Box<dyn Error>> {
    let document = rendered_document("duckduckgo-byte-limit.json", ROWS.as_bytes().to_vec())?;
    assert!(matches!(
        parse(&document, &Policy::default(), PAGE_URL, RESULT_LIMIT, 1),
        Err(DuckDuckGoParseError::OutputLimit)
    ));
    Ok(())
}

#[test]
#[ignore = "requires the retained local CAS-502 rendered DOM; no network I/O"]
fn replay_retained_headful_dom_reports_bounded_row_issues() -> Result<(), Box<dyn Error>> {
    let path = env::var_os("YS_DDG_CAPTURE_PATH")
        .map(PathBuf::from)
        .ok_or_else(|| io::Error::other("YS_DDG_CAPTURE_PATH is required"))?;
    let bytes = fs::read(path)?;
    let digest = format!("{:x}", Sha256::digest(&bytes));
    assert_eq!(
        digest,
        "14b522250b20df13ffb2aaf7831f0ca67da070350bb20def6845892fef652293"
    );
    let document = rendered_document("duckduckgo-retained-dom.json", bytes)?;
    let outcome = parse(&document, &Policy::default(), PAGE_URL, 10, OUTPUT_LIMIT)?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("retained DDG page did not yield results").into());
    };
    println!(
        "ddg_replay hits={} issue_count={} coverage={:?}",
        page.hits().len(),
        page.issues().len(),
        page.coverage().web()
    );
    for issue in page.issues() {
        println!(
            "ddg_replay issue_kind={:?} placement_index={:?}",
            issue.kind,
            issue.placement_index.map(NonZeroU16::get)
        );
    }
    assert_eq!(page.hits().len(), 10);
    assert_eq!(page.issues().len(), 0);
    assert_eq!(page.coverage().web(), WebCoverage::Complete);
    Ok(())
}

#[test]
#[ignore = "requires the retained local HTTP-200 empty DDG DOM; no network I/O"]
fn replay_retained_empty_dom_reports_empty() -> Result<(), Box<dyn Error>> {
    let path = env::var_os("YS_DDG_EMPTY_CAPTURE_PATH")
        .map(PathBuf::from)
        .ok_or_else(|| io::Error::other("YS_DDG_EMPTY_CAPTURE_PATH is required"))?;
    let bytes = fs::read(path)?;
    assert_eq!(
        format!("{:x}", Sha256::digest(&bytes)),
        "0f8051c4fad514aa55841fbd12c7e9a15f71ccb6c0c786e8e999b91c132e8b59"
    );
    let document = rendered_document("duckduckgo-retained-empty.json", bytes)?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            PAGE_URL,
            RESULT_LIMIT,
            OUTPUT_LIMIT
        ),
        Ok(ProviderOutcome::Empty)
    ));
    println!("ddg_empty_replay=recognized sha256_verified=true");
    Ok(())
}

#[test]
fn rejects_non_rendered_documents() -> Result<(), Box<dyn Error>> {
    let document = Document::html("duckduckgo-source.html", ROWS.as_bytes().to_vec())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            PAGE_URL,
            RESULT_LIMIT,
            OUTPUT_LIMIT
        ),
        Err(DuckDuckGoParseError::UnsupportedDocumentClass)
    ));
    Ok(())
}
