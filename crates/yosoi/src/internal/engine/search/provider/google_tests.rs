#![expect(
    clippy::panic_in_result_fn,
    reason = "assertions report parser regressions"
)]

use super::{
    GoogleParseError, GoogleParsedDocument, GoogleResultTarget, is_google_challenge_redirect,
    is_opaque_redirect, parse, parse_rows, redirect_destination, response_is_challenge,
    result_destination, result_target,
};
use crate::internal::{
    documents::DocumentEpoch,
    engine::{
        Document, Policy,
        search::{ProviderOutcome, SearchFailure, SearchIssueKind, SearchResultUrl, WebCoverage},
    },
};
use std::{collections::HashMap, error::Error, num::NonZeroU16};

const ROW: &str = include_str!("tests/fixtures/google/google-rendered-row.json");
const CHALLENGE: &str = include_str!("tests/fixtures/google/google-challenge-dom.json");

fn document_from_html(html: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::observed_dom(
        "google-result-rows",
        1,
        html.as_bytes().to_vec(),
        &Policy::default(),
    )?)
}

#[test]
fn captured_challenge_marker_is_not_an_empty_result() -> Result<(), Box<dyn Error>> {
    let document = Document::rendered_dom(
        "google-challenge",
        DocumentEpoch::try_from(1_u64)?,
        CHALLENGE.as_bytes().to_vec(),
    )?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://www.google.com/search?q=rust",
            5,
            16_384
        )?,
        ProviderOutcome::Failed(SearchFailure::Challenge)
    ));
    Ok(())
}

#[test]
fn captured_rendered_row_keeps_result_fields_together() -> Result<(), Box<dyn Error>> {
    let document = Document::rendered_dom(
        "google-row",
        DocumentEpoch::try_from(1_u64)?,
        ROW.as_bytes().to_vec(),
    )?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://www.google.com/search?q=rust",
        5,
        16_384,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err("expected results".into());
    };
    assert_eq!(page.hits().len(), 1);
    assert_eq!(
        page.hits().first().map(|hit| hit.url().as_str()),
        Some("https://example.com/rust")
    );
    assert!(
        page.issues().is_empty(),
        "unexpected issues: {:?}",
        page.issues()
    );
    Ok(())
}

#[test]
fn opaque_google_row_is_resolved_by_placement_and_unresolved_rows_are_partial()
-> Result<(), Box<dyn Error>> {
    let document = document_from_html(
        "<html><body>\
         <div class=\"tF2Cxc\"><div class=\"yuRUbf\"><a class=\"zReHs\" href=\"https://example.org/direct\"><h3>Direct title</h3></a></div><div class=\"VwiC3b\">Direct snippet</div></div>\
         <div class=\"tF2Cxc\"><div class=\"yuRUbf\"><a class=\"zReHs\" href=\"/goto?url=opaque\"><h3>Wrapped title</h3></a></div><div class=\"VwiC3b\">Wrapped snippet</div></div>\
         </body></html>",
    )?;
    let GoogleParsedDocument::Results(page) = parse_rows(
        &document,
        &Policy::default(),
        "https://www.google.com/search?q=rust",
        5,
    )?
    else {
        return Err("expected Google result rows".into());
    };
    let placement = page
        .opaque_redirects()
        .map(|(placement, _)| placement)
        .next()
        .ok_or("opaque result row was not retained")?;
    assert_eq!(placement, NonZeroU16::new(2).ok_or("invalid placement")?);

    let unresolved = page.finish(&HashMap::new(), &HashMap::new(), 5, 16_384)?;
    let ProviderOutcome::Results(partial) = unresolved else {
        return Err("expected direct result to survive an unresolved wrapper".into());
    };
    assert_eq!(partial.hits().len(), 1);
    assert_eq!(partial.coverage().web(), WebCoverage::Partial);
    assert!(partial.issues().iter().any(|issue| {
        issue.placement_index == Some(placement)
            && issue.kind == SearchIssueKind::RedirectResolutionFailed
    }));

    let GoogleParsedDocument::Results(page) = parse_rows(
        &document,
        &Policy::default(),
        "https://www.google.com/search?q=rust",
        5,
    )?
    else {
        return Err("expected Google result rows".into());
    };
    let mut failed_redirects = HashMap::new();
    failed_redirects.insert(placement, SearchIssueKind::RedirectChallenge);
    let ProviderOutcome::Results(challenged) =
        page.finish(&HashMap::new(), &failed_redirects, 5, 16_384)?
    else {
        return Err("expected direct result beside a challenged wrapper".into());
    };
    assert!(challenged.issues().iter().any(|issue| {
        issue.placement_index == Some(placement) && issue.kind == SearchIssueKind::RedirectChallenge
    }));

    let GoogleParsedDocument::Results(page) = parse_rows(
        &document,
        &Policy::default(),
        "https://www.google.com/search?q=rust",
        5,
    )?
    else {
        return Err("expected Google result rows".into());
    };
    let destination = SearchResultUrl::parse("https://example.org/wrapped")?;
    let mut resolved = HashMap::new();
    resolved.insert(placement, destination);
    let ProviderOutcome::Results(results) = page.finish(&resolved, &HashMap::new(), 5, 16_384)?
    else {
        return Err("expected resolved Google rows".into());
    };
    assert_eq!(results.hits().len(), 2);
    let wrapped = results
        .hits()
        .get(1)
        .ok_or("wrapped hit was not retained")?;
    assert_eq!(wrapped.url().as_str(), "https://example.org/wrapped");
    assert_eq!(wrapped.organic_rank().get(), 2);
    assert_eq!(wrapped.placement_index().get(), 2);
    assert_eq!(wrapped.title(), Some("Wrapped title"));
    assert_eq!(wrapped.snippet(), Some("Wrapped snippet"));
    assert!(
        results.issues().is_empty(),
        "unexpected issues: {:?}",
        results.issues()
    );
    Ok(())
}

#[test]
fn bounded_challenge_marker_requires_both_google_signals() {
    assert!(response_is_challenge(
        b"Our systems have detected unusual traffic <form id=\"captcha-form\">"
    ));
    assert!(!response_is_challenge(b"unusual traffic only"));
    assert!(!response_is_challenge(b"captcha-form only"));
}

#[test]
fn only_observed_google_challenge_paths_stop_wrapper_resolution() -> Result<(), Box<dyn Error>> {
    let source = url::Url::parse("https://www.google.com/goto?url=opaque")?;
    assert!(is_google_challenge_redirect(
        &source,
        "https://www.google.com/sorry/index?q=opaque"
    ));
    assert!(is_google_challenge_redirect(
        &source,
        "https://www.google.com/recaptcha/api2/anchor"
    ));
    assert!(!is_google_challenge_redirect(
        &source,
        "https://www.google.com/search?q=rust"
    ));
    assert!(!is_google_challenge_redirect(
        &source,
        "https://www.google.com.evil.test/sorry/index"
    ));
    assert!(!is_google_challenge_redirect(
        &source,
        "https://example.org/sorry/index"
    ));
    Ok(())
}

#[test]
fn known_google_intermediaries_are_rejected_but_play_and_lookalikes_are_kept()
-> Result<(), Box<dyn Error>> {
    let page = url::Url::parse("https://www.google.com/search?q=android")?;
    assert!(matches!(
        result_target(
            &page,
            "https://play.google.com/store/apps/details?id=com.example"
        ),
        Some(GoogleResultTarget::Direct(url))
            if url.as_str() == "https://play.google.com/store/apps/details?id=com.example"
    ));

    let wrapper = url::Url::parse("https://www.google.com/goto?url=opaque")?;
    for location in [
        "https://www.google.com/search?q=other",
        "https://www.google.com/goto?url=opaque",
        "https://www.google.com/sorry/index",
        "https://g.co/short-link",
        "https://www.googleadservices.com/pagead/aclk?ad=opaque",
    ] {
        assert!(redirect_destination(&wrapper, location).is_none());
    }
    for lookalike in [
        "https://googleadservices.com.evil.test/pagead/aclk",
        "https://evilg.co.test/path",
    ] {
        assert_eq!(
            redirect_destination(&wrapper, lookalike).map(|url| url.to_string()),
            Some(lookalike.to_owned())
        );
    }
    Ok(())
}

#[test]
fn response_shell_is_not_a_result_document() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "shell",
        b"<html><a href='/httpservice/retry/enablejs'>here</a></html>".to_vec(),
    )?;
    assert_eq!(
        parse(
            &document,
            &Policy::default(),
            "https://www.google.com/search?q=rust",
            5,
            16_384
        ),
        Err(GoogleParseError::UnsupportedDocumentClass)
    );
    Ok(())
}

#[test]
fn destinations_decode_only_explicit_unambiguous_targets() -> Result<(), Box<dyn Error>> {
    let page = url::Url::parse("https://www.google.com/search?q=rust")?;
    assert_eq!(
        result_destination(&page, "/url?q=https%3A%2F%2Fexample.com%2Frust")
            .map(|url| url.to_string()),
        Some("https://example.com/rust".to_owned())
    );
    assert!(result_destination(&page, "/goto?url=opaque").is_none());
    assert!(
        result_destination(
            &page,
            "/url?q=https://example.com&url=https://other.example"
        )
        .is_none()
    );
    assert!(result_destination(&page, "/search?q=navigation").is_none());
    Ok(())
}

#[test]
fn opaque_redirect_resolution_never_accepts_ambiguous_or_unsafe_destinations()
-> Result<(), Box<dyn Error>> {
    let source = url::Url::parse("https://www.google.com/goto?url=opaque")?;
    assert!(is_opaque_redirect(&source));
    assert_eq!(
        redirect_destination(&source, "https://example.org/article").map(|url| url.to_string()),
        Some("https://example.org/article".to_owned())
    );
    assert!(redirect_destination(&source, "https://user:secret@example.org/").is_none());
    assert!(redirect_destination(&source, "javascript:alert(1)").is_none());
    assert!(redirect_destination(&source, "/search?q=elsewhere").is_none());
    assert!(!is_opaque_redirect(&url::Url::parse(
        "https://google.com.evil.test/goto?url=x"
    )?));
    assert!(!is_opaque_redirect(&url::Url::parse(
        "https://www.google.com/goto?url=x&url=y"
    )?));
    Ok(())
}
