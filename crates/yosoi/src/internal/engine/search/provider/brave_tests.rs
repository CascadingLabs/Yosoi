#![expect(
    clippy::panic_in_result_fn,
    reason = "assertions intentionally report Brave parser test failures"
)]
use std::{
    env,
    error::Error,
    fs, io,
    path::{Path, PathBuf},
};

use crate::internal::documents::DocumentEpoch;

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
const BROWSER_POSITIVE_SOURCE: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/brave-browser-positive-response.html"
);
const BROWSER_POSITIVE_DOM: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/brave-browser-positive-rendered-dom.json"
);
const BROWSER_OFF_QUERY_SOURCE: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/brave-browser-off-query-response.html"
);
const BROWSER_OFF_QUERY_DOM: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/brave-browser-off-query-rendered-dom.json"
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
fn unsupported_document_classes_are_rejected_explicitly() -> Result<(), Box<dyn Error>> {
    let document = Document::text("brave-text-document.txt", b"not an HTML document".to_vec())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://search.brave.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        ),
        Err(BraveParseError::UnsupportedDocumentClass)
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
fn paired_browser_documents_keep_the_observed_brave_rows_in_sync() -> Result<(), Box<dyn Error>> {
    let response_document = Document::html(
        "brave-browser-response.html",
        BROWSER_POSITIVE_SOURCE.as_bytes().to_vec(),
    )?;
    let rendered_dom = Document::rendered_dom(
        "brave-browser-rendered-dom.json",
        DocumentEpoch::try_from(1_u64)?,
        BROWSER_POSITIVE_DOM.as_bytes().to_vec(),
    )?;
    let provider_page_url = "https://search.brave.com/search?q=rust+programming+language";
    let source_outcome = parse(
        &response_document,
        &Policy::default(),
        provider_page_url,
        10,
        16 * 1024 * 1024,
    )?;
    let dom_outcome = parse(
        &rendered_dom,
        &Policy::default(),
        provider_page_url,
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(source_page) = source_outcome else {
        return Err(io::Error::other("expected Brave response-document results").into());
    };
    let ProviderOutcome::Results(dom_page) = dom_outcome else {
        return Err(io::Error::other("expected Brave rendered-DOM results").into());
    };

    assert_eq!(source_page.hits().len(), 3);
    assert_eq!(source_page.hits().len(), dom_page.hits().len());
    for (source_hit, dom_hit) in source_page.hits().iter().zip(dom_page.hits()) {
        assert_eq!(source_hit.url(), dom_hit.url());
        assert_eq!(source_hit.title(), dom_hit.title());
        assert_eq!(source_hit.snippet(), dom_hit.snippet());
        assert_eq!(source_hit.organic_rank(), dom_hit.organic_rank());
        assert_eq!(source_hit.placement_index(), dom_hit.placement_index());
    }

    let first = source_page
        .hits()
        .first()
        .ok_or_else(|| io::Error::other("missing first browser-captured Brave hit"))?;
    let second = source_page
        .hits()
        .get(1)
        .ok_or_else(|| io::Error::other("missing second browser-captured Brave hit"))?;
    let third = source_page
        .hits()
        .get(2)
        .ok_or_else(|| io::Error::other("missing third browser-captured Brave hit"))?;
    assert_eq!(first.title(), Some("Rust Programming Language"));
    assert_eq!(first.snippet(), Some("[redacted captured snippet 1]"));
    assert_eq!(
        second.title(),
        Some("Rust (programming language) - Wikipedia")
    );
    assert_eq!(second.snippet(), Some("[redacted captured snippet 2]"));
    assert_eq!(
        third.title(),
        Some(
            "r/learnrust on Reddit: Rust - A Living Hell - The Perspective From A Programmer Of 30 Years"
        )
    );
    assert_eq!(third.snippet(), None);
    Ok(())
}

#[test]
fn paired_browser_off_query_documents_have_the_same_parser_interpretation()
-> Result<(), Box<dyn Error>> {
    let response_document = Document::html(
        "brave-browser-off-query-response.html",
        BROWSER_OFF_QUERY_SOURCE.as_bytes().to_vec(),
    )?;
    let rendered_dom = Document::rendered_dom(
        "brave-browser-off-query-rendered-dom.json",
        DocumentEpoch::try_from(1_u64)?,
        BROWSER_OFF_QUERY_DOM.as_bytes().to_vec(),
    )?;
    let provider_page_url =
        "https://search.brave.com/search?q=%22brave-cas630-no-match-probe-20261026-xqjv%22";
    let source_outcome = parse(
        &response_document,
        &Policy::default(),
        provider_page_url,
        10,
        16 * 1024 * 1024,
    );
    let dom_outcome = parse(
        &rendered_dom,
        &Policy::default(),
        provider_page_url,
        10,
        16 * 1024 * 1024,
    );

    assert_eq!(source_outcome, dom_outcome);
    Ok(())
}

#[derive(Debug, Eq, PartialEq)]
struct ParserSummary {
    classification: String,
    hits: usize,
    titles: Vec<String>,
    snippets: usize,
    issues: usize,
    web_coverage: Option<WebCoverage>,
}

fn parser_summary(outcome: Result<ProviderOutcome, BraveParseError>) -> ParserSummary {
    match outcome {
        Ok(ProviderOutcome::Results(page)) => ParserSummary {
            classification: "results".to_owned(),
            hits: page.hits().len(),
            titles: page
                .hits()
                .iter()
                .take(3)
                .filter_map(|hit| hit.title())
                .map(str::to_owned)
                .collect(),
            snippets: page
                .hits()
                .iter()
                .filter(|hit| hit.snippet().is_some())
                .count(),
            issues: page.issues().len(),
            web_coverage: Some(page.coverage().web()),
        },
        Ok(ProviderOutcome::Empty) => ParserSummary {
            classification: "empty".to_owned(),
            hits: 0,
            titles: Vec::new(),
            snippets: 0,
            issues: 0,
            web_coverage: None,
        },
        Ok(ProviderOutcome::Failed(failure)) => ParserSummary {
            classification: format!("failed:{failure:?}"),
            hits: 0,
            titles: Vec::new(),
            snippets: 0,
            issues: 0,
            web_coverage: None,
        },
        Ok(ProviderOutcome::Cancelled) => ParserSummary {
            classification: "cancelled".to_owned(),
            hits: 0,
            titles: Vec::new(),
            snippets: 0,
            issues: 0,
            web_coverage: None,
        },
        Ok(ProviderOutcome::NotStarted(reason)) => ParserSummary {
            classification: format!("not_started:{reason:?}"),
            hits: 0,
            titles: Vec::new(),
            snippets: 0,
            issues: 0,
            web_coverage: None,
        },
        Err(error) => ParserSummary {
            classification: format!("parse_error:{error:?}"),
            hits: 0,
            titles: Vec::new(),
            snippets: 0,
            issues: 0,
            web_coverage: None,
        },
    }
}

fn read_capture_target_and_status(capture_dir: &Path) -> Result<(String, u16), Box<dyn Error>> {
    let manifest_bytes = fs::read(capture_dir.join("manifest.json"))?;
    let manifest: serde_json::Value = serde_json::from_slice(&manifest_bytes)?;
    let target = manifest
        .get("target")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| io::Error::other("capture manifest has no target"))?
        .to_owned();
    let attempt = manifest
        .get("attempts")
        .and_then(serde_json::Value::as_array)
        .and_then(|attempts| attempts.first())
        .ok_or_else(|| io::Error::other("capture manifest has no attempt"))?;
    let status = attempt
        .get("status")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| io::Error::other("capture attempt has no HTTP status"))?;
    Ok((target, u16::try_from(status)?))
}

fn read_source_document(capture_dir: &Path) -> Result<Document, Box<dyn Error>> {
    Ok(Document::html(
        "retained-brave-response.html",
        fs::read(capture_dir.join("attempt-0-ResponseDocument.data"))?,
    )?)
}

fn read_rendered_dom_document(capture_dir: &Path) -> Result<Document, Box<dyn Error>> {
    let bytes = fs::read(capture_dir.join("attempt-0-RenderedDom.data"))?;
    let metadata: serde_json::Value = serde_json::from_slice(&bytes)?;
    let epoch = metadata
        .get("document_epoch")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| io::Error::other("retained rendered DOM has no epoch"))?;
    Ok(Document::rendered_dom(
        "retained-brave-rendered-dom.json",
        DocumentEpoch::try_from(epoch)?,
        bytes,
    )?)
}

#[test]
#[ignore = "local-only; replays retained Brave Request documents without network or browser I/O"]
fn replay_retained_brave_browser_and_http_captures_serially() -> Result<(), Box<dyn Error>> {
    let root = env::var_os("YS_BRAVE_CAPTURE_DIR")
        .map(PathBuf::from)
        .ok_or_else(|| {
            io::Error::other("set YS_BRAVE_CAPTURE_DIR to the retained capture directory")
        })?;
    for capture_name in ["brave-1", "brave-2"] {
        let capture_dir = root.join(capture_name);
        let (target, status) = read_capture_target_and_status(&capture_dir)?;
        assert_eq!(
            status, 200,
            "{capture_name} was not a completed success capture"
        );
        let response_document = read_source_document(&capture_dir)?;
        let rendered_dom = read_rendered_dom_document(&capture_dir)?;
        let source_summary = parser_summary(parse(
            &response_document,
            &Policy::default(),
            &target,
            10,
            16 * 1024 * 1024,
        ));
        let dom_summary = parser_summary(parse(
            &rendered_dom,
            &Policy::default(),
            &target,
            10,
            16 * 1024 * 1024,
        ));
        eprintln!(
            "capture={capture_name} status={status} source={source_summary:?} rendered_dom={dom_summary:?}"
        );
        assert_eq!(
            source_summary, dom_summary,
            "{capture_name} document classes differ"
        );
    }

    let http_dir = root.join("brave-http-quoted-1");
    let (target, status) = read_capture_target_and_status(&http_dir)?;
    assert_eq!(
        status, 200,
        "direct-HTTP comparison was not a completed success capture"
    );
    let response_document = read_source_document(&http_dir)?;
    let summary = parser_summary(parse(
        &response_document,
        &Policy::default(),
        &target,
        10,
        16 * 1024 * 1024,
    ));
    eprintln!("capture=brave-http-quoted-1 status={status} source={summary:?}");
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
