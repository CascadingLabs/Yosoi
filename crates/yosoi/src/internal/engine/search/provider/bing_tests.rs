#![expect(
    clippy::panic_in_result_fn,
    reason = "assertions intentionally report Bing parser test failures"
)]
use std::{env, error::Error, fs, io, num::NonZeroU16, path::PathBuf};

use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use serde_json::Value;
use sha2::{Digest, Sha256};

use super::destination::decode_unpadded_url_safe_base64;
use super::{
    BingDestinationError, BingParseError, decode_destination, parse, recovered_page_matches_query,
    recovery_query,
};
use crate::internal::engine::{
    Document, Policy,
    search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchHit, SearchHitMetadata,
        SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
    },
};

const ROW: &str =
    include_str!("../../tests/fixtures/search-providers/fixtures/bing-organic-row.html");
const MULTIROW: &str =
    include_str!("../../tests/fixtures/search-providers/fixtures/bing-multirow.html");
const SNIPPETLESS_ROWS: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/bing-safari26-snippetless-rows.html"
);
const SPONSORED_CONTROL: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/bing-synthetic-sponsored-control.html"
);
const MISSING_HREF_CONTROL: &str =
    include_str!("../../tests/fixtures/search-providers/fixtures/bing-synthetic-missing-href.html");
const HISTORY_GENERAL_OFF_QUERY: &str = include_str!(
    "../../tests/fixtures/search-providers/fixtures/bing-history-general-off-query.html"
);
const COTTON_ONLY_OFF_QUERY: &str =
    include_str!("../../tests/fixtures/search-providers/fixtures/bing-cotton-only-off-query.html");
const OBSERVATIONS: &str = include_str!("../../tests/fixtures/search-providers/observations.json");
const DECODER_VECTORS: &str =
    include_str!("../../tests/fixtures/search-providers/bing-ck-a-negative-vectors.json");

fn vectors() -> Result<Vec<Value>, Box<dyn Error>> {
    let value: Value = serde_json::from_str(DECODER_VECTORS)?;
    value
        .get("vectors")
        .and_then(Value::as_array)
        .cloned()
        .ok_or_else(|| io::Error::other("decoder vector list is missing").into())
}

fn positive_vectors() -> Result<Vec<(String, String)>, Box<dyn Error>> {
    vectors()?
        .into_iter()
        .filter(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
        .map(|value| {
            let encoded = value
                .get("u")
                .and_then(Value::as_str)
                .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
            let target = value
                .get("expected")
                .and_then(Value::as_str)
                .and_then(|value| value.strip_prefix("accept: "))
                .ok_or_else(|| io::Error::other("synthetic positive target is missing"))?;
            Ok((encoded.to_owned(), target.to_owned()))
        })
        .collect()
}

fn replace_two_redacted_wrappers(
    markup: &str,
    first_u: &str,
    second_u: &str,
) -> Result<String, Box<dyn Error>> {
    let mut parts = markup.split("u=REDACTED");
    let first = parts
        .next()
        .ok_or_else(|| io::Error::other("first redacted wrapper is missing"))?;
    let middle = parts
        .next()
        .ok_or_else(|| io::Error::other("second redacted wrapper is missing"))?;
    let last = parts
        .next()
        .ok_or_else(|| io::Error::other("row fixture has too few wrappers"))?;
    if parts.next().is_some() {
        return Err(io::Error::other("row fixture has more than two wrappers").into());
    }
    Ok(format!("{first}u={first_u}{middle}u={second_u}{last}"))
}

fn query_fidelity_destinations(name: &str) -> Result<Vec<String>, Box<dyn Error>> {
    let observations: Value = serde_json::from_str(OBSERVATIONS)?;
    let destinations = observations
        .get("provenance")
        .and_then(|value| value.get("bing_query_fidelity"))
        .and_then(|value| value.get("captures"))
        .and_then(|value| value.get(name))
        .and_then(|value| value.get("destination_urls"))
        .and_then(Value::as_array)
        .ok_or_else(|| io::Error::other("query-fidelity destination list is missing"))?;
    let mut output = Vec::with_capacity(destinations.len());
    for destination in destinations {
        let destination = destination
            .as_str()
            .ok_or_else(|| io::Error::other("query-fidelity destination is not text"))?;
        output.push(destination.to_owned());
    }
    Ok(output)
}

fn replace_redacted_destination_wrappers(
    markup: &str,
    destinations: &[String],
) -> Result<String, Box<dyn Error>> {
    let encoded_destinations = destinations
        .iter()
        .map(|destination| format!("a1{}", URL_SAFE_NO_PAD.encode(destination.as_bytes())))
        .collect::<Vec<_>>();
    let parts = markup.split("u=REDACTED").collect::<Vec<_>>();
    let placeholders = parts
        .len()
        .checked_sub(1)
        .ok_or_else(|| io::Error::other("query-fidelity fixture has no rows"))?;
    if placeholders != encoded_destinations.len() {
        return Err(
            io::Error::other("query-fidelity destination count does not match rows").into(),
        );
    }

    let mut output = String::new();
    for (index, part) in parts.iter().enumerate() {
        output.push_str(part);
        if let Some(encoded) = encoded_destinations.get(index) {
            output.push_str("u=");
            output.push_str(encoded);
        }
    }
    Ok(output)
}

fn require_query_relevance_unknown(outcome: ProviderOutcome) -> Result<SearchPage, Box<dyn Error>> {
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("uncertain relevance should retain result hits").into());
    };
    if page.coverage().web() != WebCoverage::Partial
        || !page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
    {
        return Err(io::Error::other("uncertain relevance must be explicit and partial").into());
    }
    Ok(page)
}

fn require_supported_page(outcome: ProviderOutcome) -> Result<SearchPage, Box<dyn Error>> {
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("visible query evidence should retain result hits").into());
    };
    if page.coverage().web() != WebCoverage::Complete
        || page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
    {
        return Err(io::Error::other("visible query evidence should not be uncertain").into());
    }
    Ok(page)
}

fn retained_capture_record(name: &str) -> Result<(String, String, usize, u16), Box<dyn Error>> {
    let observations: Value = serde_json::from_str(OBSERVATIONS)?;
    let record = observations
        .get("provenance")
        .and_then(|value| value.get("captures"))
        .and_then(|value| value.get(name))
        .ok_or_else(|| io::Error::other("capture provenance entry is missing"))?;
    let artifact = record
        .get("artifact")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("capture artifact name is missing"))?;
    let hash = record
        .get("sha256")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("capture hash is missing"))?;
    let bytes = record
        .get("bytes")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| io::Error::other("capture byte count is missing"))?;
    let status = record
        .get("status")
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| io::Error::other("capture status is missing"))?;
    Ok((artifact.to_owned(), hash.to_owned(), bytes, status))
}

fn load_retained_capture(name: &str) -> Result<(Vec<u8>, u16), Box<dyn Error>> {
    let (artifact, expected_hash, expected_bytes, status) = retained_capture_record(name)?;
    let directory =
        env::var_os("YS_SEARCH_CAPTURE_DIR").map_or_else(|| PathBuf::from("/tmp"), PathBuf::from);
    let bytes = fs::read(directory.join(&artifact))?;
    let observed_hash = format!("{:x}", Sha256::digest(&bytes));
    if bytes.len() != expected_bytes || observed_hash != expected_hash {
        return Err(io::Error::other("retained capture does not match manifest provenance").into());
    }
    Ok((bytes, status))
}

#[test]
fn base64url_decoder_requires_unpadded_canonical_url_safe_encoding() {
    assert!(matches!(
        decode_unpadded_url_safe_base64("Zg"),
        Ok(bytes) if bytes.as_slice() == b"f"
    ));
    assert!(matches!(
        decode_unpadded_url_safe_base64("Zm8"),
        Ok(bytes) if bytes.as_slice() == b"fo"
    ));
    for value in ["Zg==", "Zh", "Zm9", "Zm+", "Zm/"] {
        assert_eq!(
            decode_unpadded_url_safe_base64(value),
            Err(BingDestinationError::InvalidBase64Url),
            "accepted noncanonical value {value}"
        );
    }
}

#[test]
fn synthetic_positive_vector_decodes_and_populates_one_row() -> Result<(), Box<dyn Error>> {
    let values = vectors()?;
    let positive = values
        .iter()
        .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
        .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
    let encoded = positive
        .get("u")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
    let expected = positive
        .get("expected")
        .and_then(Value::as_str)
        .and_then(|value| value.strip_prefix("accept: "))
        .ok_or_else(|| io::Error::other("synthetic positive target is missing"))?;
    let wrapper = format!("https://www.bing.com/ck/a?u={encoded}");
    assert_eq!(decode_destination(&wrapper)?.as_str(), expected);

    let markup = ROW.replace("u=REDACTED", &format!("u={encoded}"));
    let document = Document::html("bing-fixture.html", markup.into_bytes())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=captured+title",
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected a parsed Bing result page").into());
    };
    let hit = page
        .hits()
        .first()
        .ok_or_else(|| io::Error::other("sanitized Bing row produced no hit"))?;
    assert_eq!(hit.url().as_str(), expected);
    assert_eq!(hit.title(), Some("[redacted captured title]"));
    assert_eq!(hit.snippet(), Some("[redacted captured snippet]"));
    assert_eq!(hit.organic_rank().get(), 1);
    assert_eq!(hit.placement_index().get(), 1);
    assert_eq!(page.issues().len(), 0);
    Ok(())
}

#[test]
fn synthetic_negative_vectors_are_rejected() -> Result<(), Box<dyn Error>> {
    for vector in vectors()?
        .iter()
        .filter(|value| value.get("kind").and_then(Value::as_str) == Some("negative"))
    {
        let name = vector
            .get("name")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("negative vector name is missing"))?;
        let encoded = vector
            .get("u")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("negative vector u value is missing"))?;
        let wrapper = format!("https://www.bing.com/ck/a?u={encoded}");
        assert!(
            decode_destination(&wrapper).is_err(),
            "vector {name} was accepted"
        );
    }
    Ok(())
}

#[test]
fn decoder_rejects_unknown_wrapper_shapes_and_destination_credentials() -> Result<(), Box<dyn Error>>
{
    let positive = vectors()?
        .into_iter()
        .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
        .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
    let encoded = positive
        .get("u")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
    let bad_wrappers = [
        format!("https://bing.com/ck/a?u={encoded}"),
        format!("https://www.bing.com/other?u={encoded}"),
        format!("http://www.bing.com/ck/a?u={encoded}"),
        format!("https://www.bing.com/ck/a?u={encoded}&u={encoded}"),
        format!("https://www.bing.com/ck/a?u={encoded}#fragment"),
    ];
    for wrapper in bad_wrappers {
        assert!(decode_destination(&wrapper).is_err());
    }
    let credentials =
        "https://www.bing.com/ck/a?u=a1aHR0cHM6Ly91c2VyOnBhc3NAZXhhbXBsZS5vcmcvcGF0aA";
    assert_eq!(
        decode_destination(credentials),
        Err(BingDestinationError::DestinationHasCredentials)
    );
    Ok(())
}

fn organic_row(destination: &str, title: &str, snippet: &str) -> String {
    let encoded = URL_SAFE_NO_PAD.encode(destination.as_bytes());
    format!(
        r#"<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1{encoded}">{title}</a></h2><div class="b_caption"><p class="b_lineclamp2">{snippet}</p></div></li>"#
    )
}

#[test]
fn normal_multiword_query_control_requires_one_topic_complete_row() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "bing-normal-query-control.html",
        [
            organic_row(
                "https://www.rust-lang.org/",
                "The Rust Programming Language",
                "A language empowering everyone to build reliable and efficient software.",
            ),
            organic_row(
                "https://doc.rust-lang.org/book/",
                "The Rust Programming Language Book",
                "Learn the Rust programming language.",
            ),
            organic_row(
                "https://doc.rust-lang.org/",
                "Rust Documentation",
                "Documentation for the Rust programming language.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    let page = require_supported_page(parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=rust+programming+language",
        5,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(page.hits().len(), 3);
    Ok(())
}

#[test]
fn destination_query_and_fragment_cannot_echo_query_relevance() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "bing-url-query-echo-control.html",
        [
            organic_row(
                "https://example.org/result-1?topic=cotton+candy#history",
                "Example report one",
                "A generic report summary.",
            ),
            organic_row(
                "https://example.org/result-2?topic=cotton+candy#history",
                "Example report two",
                "A second generic summary.",
            ),
            organic_row(
                "https://example.org/result-3?topic=cotton+candy#history",
                "Example report three",
                "A third generic summary.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    let page = require_query_relevance_unknown(parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=history+of+cotton+candy",
        5,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(page.hits().len(), 3);
    Ok(())
}

#[test]
fn captured_bing_pages_preserve_hits_and_report_unknown_relevance() -> Result<(), Box<dyn Error>> {
    let history_destinations = query_fidelity_destinations("history_original")?;
    let history_markup =
        replace_redacted_destination_wrappers(HISTORY_GENERAL_OFF_QUERY, &history_destinations)?;
    let history_document = Document::html(
        "bing-history-general-off-query.html",
        history_markup.into_bytes(),
    )?;
    let history_page = require_query_relevance_unknown(parse(
        &history_document,
        &Policy::default(),
        "https://www.bing.com/search?q=history+of+cotton+candy",
        5,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(history_page.hits().len(), 5);

    let cotton_destinations = query_fidelity_destinations("cotton_history_subject_first")?;
    let cotton_markup =
        replace_redacted_destination_wrappers(COTTON_ONLY_OFF_QUERY, &cotton_destinations)?;
    let cotton_document = Document::html(
        "bing-cotton-only-off-query.html",
        cotton_markup.into_bytes(),
    )?;
    let cotton_page = require_query_relevance_unknown(parse(
        &cotton_document,
        &Policy::default(),
        "https://www.bing.com/search?q=cotton+candy+history",
        10,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(cotton_page.hits().len(), 7);

    let quoted_page = require_query_relevance_unknown(parse(
        &cotton_document,
        &Policy::default(),
        "https://www.bing.com/search?q=%22cotton+candy%22+history",
        10,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(quoted_page.hits().len(), 7);
    let operator_page = require_query_relevance_unknown(parse(
        &cotton_document,
        &Policy::default(),
        "https://www.bing.com/search?q=intitle%3A%22cotton+candy%22+history",
        10,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(operator_page.hits().len(), 7);

    let split_topic = Document::html(
        "bing-split-topic.html",
        [
            organic_row(
                "https://example.org/cotton-fabric",
                "Cotton Fabric Guide",
                "Cotton is a natural fiber.",
            ),
            organic_row(
                "https://example.org/candy-guide",
                "Candy Guide",
                "Candy is made with sugar.",
            ),
            organic_row(
                "https://example.org/cotton-council",
                "Cotton Council",
                "Cotton is an agricultural crop.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    let split_page = require_query_relevance_unknown(parse(
        &split_topic,
        &Policy::default(),
        "https://www.bing.com/search?q=cotton+candy",
        5,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(split_page.hits().len(), 3);

    let topic_only = Document::html(
        "bing-topic-only-ambiguous.html",
        [
            organic_row(
                "https://example.org/cotton-candy-1",
                "Cotton Candy Inc.",
                "Cotton candy and spun sugar products.",
            ),
            organic_row(
                "https://example.org/cotton-candy-2",
                "Cotton Candy Recipes",
                "Learn about cotton candy treats.",
            ),
            organic_row(
                "https://example.org/cotton-candy-3",
                "Cotton Candy Store",
                "Cotton candy for parties and events.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    let topic_page = require_query_relevance_unknown(parse(
        &topic_only,
        &Policy::default(),
        "https://www.bing.com/search?q=history+of+cotton+candy",
        5,
        16 * 1024 * 1024,
    )?)?;
    assert!(!recovered_page_matches_query(
        &topic_page,
        "history of cotton candy"
    ));
    assert_eq!(recovery_query("\"cotton candy\" history"), None);
    assert_eq!(recovery_query("intitle:\"cotton candy\" history"), None);
    Ok(())
}

#[test]
fn history_scientific_name_and_how_to_intents_have_positive_controls() -> Result<(), Box<dyn Error>>
{
    let relevant_history = Document::html(
        "bing-cotton-candy-history.html",
        [
            organic_row(
                "https://example.org/cotton-candy-origins",
                "Cotton Candy Origins",
                "The origins of cotton candy and how it became popular.",
            ),
            organic_row(
                "https://example.org/cotton-candy-history",
                "Cotton Candy History",
                "A history of spun sugar and cotton candy.",
            ),
            organic_row(
                "https://example.org/cotton-candy-timeline",
                "Cotton Candy Timeline",
                "A timeline of cotton candy history.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    let recovered_url = "https://www.bing.com/search?q=cotton+candy+history";
    let recovered_page = require_supported_page(parse(
        &relevant_history,
        &Policy::default(),
        recovered_url,
        5,
        16 * 1024 * 1024,
    )?)?;
    assert!(recovered_page_matches_query(
        &recovered_page,
        "history of cotton candy"
    ));

    let relevant_scientific_name = Document::html(
        "bing-sunflower-scientific-name.html",
        [
            organic_row(
                "https://example.org/sunflower-name-1",
                "Sunflower Botanical Name",
                "The botanical name of the sunflower is Helianthus annuus.",
            ),
            organic_row(
                "https://example.org/sunflower-name-2",
                "Scientific Name of Sunflower",
                "Learn the sunflower's scientific name.",
            ),
            organic_row(
                "https://example.org/sunflower-name-3",
                "Binomial Name for Sunflower",
                "The binomial name of a sunflower.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    require_supported_page(parse(
        &relevant_scientific_name,
        &Policy::default(),
        "https://www.bing.com/search?q=sunflower+scientific+name",
        5,
        16 * 1024 * 1024,
    )?)?;

    let relevant_how_to = Document::html(
        "bing-sourdough-how-to.html",
        [
            organic_row(
                "https://example.org/sourdough-recipe-1",
                "Sourdough Bread Recipe",
                "Step-by-step instructions for making sourdough bread.",
            ),
            organic_row(
                "https://example.org/sourdough-recipe-2",
                "How to Make Sourdough Bread",
                "A practical guide to sourdough bread.",
            ),
            organic_row(
                "https://example.org/sourdough-recipe-3",
                "Sourdough Bread Tutorial",
                "Learn how to prepare sourdough bread.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    require_supported_page(parse(
        &relevant_how_to,
        &Policy::default(),
        "https://www.bing.com/search?q=sourdough+bread+how+to+make",
        5,
        16 * 1024 * 1024,
    )?)?;
    Ok(())
}

#[test]
fn paper_airplane_plural_and_plane_synonym_remain_supported() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "bing-paper-plane-history.html",
        [
            organic_row(
                "https://example.org/paper-plane-origins",
                "Paper Plane Origins",
                "The origins of paper planes and the history of the folded toy.",
            ),
            organic_row(
                "https://example.org/paper-airplane-history",
                "History of Paper Airplanes",
                "Paper airplanes have a long history.",
            ),
            organic_row(
                "https://example.org/paper-airplane-timeline",
                "Paper Airplane Timeline",
                "A timeline of paper airplane designs.",
            ),
        ]
        .concat()
        .into_bytes(),
    )?;
    require_supported_page(parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=history+of+paper+airplanes",
        5,
        16 * 1024 * 1024,
    )?)?;
    Ok(())
}

#[test]
#[ignore = "requires retained local HTTP-200 Bing captures; no network I/O"]
fn replay_retained_history_captures_keep_uncertain_rows_partial() -> Result<(), Box<dyn Error>> {
    let captures = [
        (
            "YS_BING_HISTORY_CAPTURE_PATH",
            "history of cotton candy",
            "c03c3da7bcee4eee24338be717263de8ab9d35fbc787821cf791393fabd0369a",
        ),
        (
            "YS_BING_HISTORY_REORDERED_CAPTURE_PATH",
            "history cotton candy",
            "661699944674f88096dcae4fd0a48c76956fcebb2db8d41c106053fddc984bb8",
        ),
        (
            "YS_BING_COTTON_ONLY_CAPTURE_PATH",
            "cotton candy history",
            "825049ad98372b08192c72d5baebb5b3e5927d9ac5bd057d0b9c1d44b10f8480",
        ),
        (
            "YS_BING_HISTORY_CHROME_CAPTURE_PATH",
            "history of cotton candy",
            "ceae4dcbd6903ea0971ee66625d6431e42fce8911af2b0f2b11a8cf365b42295",
        ),
    ];
    for (variable, query, expected_hash) in captures {
        let path = env::var_os(variable)
            .map(PathBuf::from)
            .ok_or_else(|| io::Error::other(format!("{variable} is required")))?;
        let bytes = fs::read(path)?;
        assert_eq!(format!("{:x}", Sha256::digest(&bytes)), expected_hash);
        let document = Document::html("bing-history-retained-capture.html", bytes)?;
        let page_url = format!("https://www.bing.com/search?q={}", query.replace(' ', "+"));
        require_query_relevance_unknown(parse(
            &document,
            &Policy::default(),
            &page_url,
            10,
            16 * 1024 * 1024,
        )?)?;
    }
    Ok(())
}

#[test]
fn make_only_rows_are_uncertain_but_a_topic_complete_recipe_is_supported()
-> Result<(), Box<dyn Error>> {
    fn row(encoded: &str, title: &str) -> String {
        format!(
            r#"<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u={encoded}">{title}</a></h2><div class="b_caption"><p class="b_lineclamp2">Automation platform</p></div></li>"#
        )
    }
    let first = row("a1aHR0cHM6Ly9leGFtcGxlLm9yZy9tYWtlLTE", "Make automation");
    let second = row("a1aHR0cHM6Ly9leGFtcGxlLm9yZy9tYWtlLTI", "Make workflows");
    let third = row("a1aHR0cHM6Ly9leGFtcGxlLm9yZy9tYWtlLTM", "Make software");
    let page_url = "https://www.bing.com/search?q=how+to+make+sourdough+bread";
    let unrelated = Document::html(
        "bing-off-query.html",
        format!("{first}{second}{third}").into_bytes(),
    )?;
    let unrelated_page = require_query_relevance_unknown(parse(
        &unrelated,
        &Policy::default(),
        page_url,
        5,
        16 * 1024 * 1024,
    )?)?;
    assert_eq!(unrelated_page.hits().len(), 3);

    let relevant = Document::html(
        "bing-relevant.html",
        format!(
            "{first}{second}{}",
            row(
                "a1aHR0cHM6Ly9leGFtcGxlLm9yZy9zb3VyZG91Z2gtMQ",
                "Sourdough bread recipe"
            )
        )
        .into_bytes(),
    )?;
    require_supported_page(parse(
        &relevant,
        &Policy::default(),
        page_url,
        5,
        16 * 1024 * 1024,
    )?)?;
    Ok(())
}

#[test]
fn recovery_query_preserves_distinctive_terms_and_refuses_operators() {
    assert_eq!(
        recovery_query("how to make sourdough bread"),
        Some("sourdough bread how to make".to_owned())
    );
    assert_eq!(
        recovery_query("history of paper airplanes"),
        Some("paper airplanes history".to_owned())
    );
    assert_eq!(
        recovery_query("scientific name for sunflower"),
        Some("sunflower scientific name".to_owned())
    );
    assert_eq!(
        recovery_query("history of cotton candy"),
        Some("cotton candy history".to_owned())
    );
    assert_eq!(
        recovery_query("history cotton candy"),
        Some("cotton candy history".to_owned())
    );
    assert_eq!(recovery_query("cotton candy history"), None);
    assert_eq!(
        recovery_query("what is a quokka"),
        Some("quokka".to_owned())
    );
    assert_eq!(recovery_query("site:example.com sourdough bread"), None);
    assert_eq!(recovery_query("\"history of paper airplanes\""), None);
    assert_eq!(recovery_query("sourdough bread"), None);
    assert_eq!(recovery_query("historia del algodón de azúcar"), None);
}

#[test]
fn recovered_single_word_page_must_match_the_original_query() -> Result<(), Box<dyn Error>> {
    let rank = NonZeroU16::MIN;
    let page_for = |url: &str, title: &str| -> Result<SearchPage, Box<dyn Error>> {
        let hit = SearchHit::new(SearchResultUrl::parse(url)?, rank, rank).with_metadata(
            SearchHitMetadata {
                title: Some(title.to_owned()),
                ..SearchHitMetadata::default()
            },
        );
        Ok(SearchPage::new(
            vec![hit],
            Vec::new(),
            SearchCoverage::new(WebCoverage::Complete, FeatureCoverage::NotCollected),
            Vec::new(),
        ))
    };
    let relevant = page_for("https://example.org/quokka", "Quokka facts")?;
    let unrelated = page_for("https://make.com/", "Make automation")?;
    assert!(recovered_page_matches_query(&relevant, "what is a quokka"));
    assert!(!recovered_page_matches_query(
        &unrelated,
        "what is a quokka"
    ));
    Ok(())
}

#[test]
#[ignore = "requires the retained local HTTP-200 Bing page; no network I/O"]
fn replay_retained_make_page_reports_unknown_relevance() -> Result<(), Box<dyn Error>> {
    let path = env::var_os("YS_BING_OFF_QUERY_CAPTURE_PATH")
        .map(PathBuf::from)
        .ok_or_else(|| io::Error::other("YS_BING_OFF_QUERY_CAPTURE_PATH is required"))?;
    let bytes = fs::read(path)?;
    assert_eq!(
        format!("{:x}", Sha256::digest(&bytes)),
        "8a9b6cdf7c7e1961d9649100582542b508ac106bd7353bed0ef7c4cce96a6154"
    );
    let document = Document::html("bing-retained-off-query.html", bytes)?;
    require_query_relevance_unknown(parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=how+to+make+sourdough+bread",
        5,
        16 * 1024 * 1024,
    )?)?;
    Ok(())
}

#[test]
fn zero_rows_are_unrecognized_not_empty() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "bing-empty-fixture.html",
        b"<html><body></body></html>".to_vec(),
    )?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        ),
        Err(BingParseError::UnrecognizedPage)
    ));
    Ok(())
}

#[test]
fn redacted_non_replayable_wrapper_is_not_a_result() -> Result<(), Box<dyn Error>> {
    let document = Document::html("bing-redacted-row.html", ROW.as_bytes().to_vec())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        ),
        Err(BingParseError::NoUsableHits)
    ));
    Ok(())
}

#[test]
fn first_hit_cannot_exceed_normalized_byte_budget() -> Result<(), Box<dyn Error>> {
    let values = vectors()?;
    let positive = values
        .iter()
        .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
        .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
    let encoded = positive
        .get("u")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
    let markup = ROW.replace("u=REDACTED", &format!("u={encoded}"));
    let document = Document::html("bing-byte-limit.html", markup.into_bytes())?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            1,
        ),
        Err(BingParseError::OutputLimit)
    ));
    Ok(())
}

#[test]
fn rejected_duplicate_keeps_later_rank_and_row_fields() -> Result<(), Box<dyn Error>> {
    let values = vectors()?;
    let positive = values
        .iter()
        .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
        .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
    let encoded = positive
        .get("u")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
    let first = ROW.replace("u=REDACTED", &format!("u={encoded}"));
    let duplicate = first.replace("[redacted captured title]", "synthetic duplicate title");
    // Synthetic URL-safe Base64 for https://example.org/other.
    let third = ROW
        .replace("u=REDACTED", "u=a1aHR0cHM6Ly9leGFtcGxlLm9yZy9vdGhlcg")
        .replace("[redacted captured title]", "synthetic third title")
        .replace("[redacted captured snippet]", "synthetic third snippet");
    let document = Document::html(
        "bing-three-rows.html",
        format!("{first}{duplicate}{third}").into_bytes(),
    )?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=captured+title",
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected Bing results").into());
    };
    assert_eq!(page.hits().len(), 2);
    let last = page
        .hits()
        .get(1)
        .ok_or_else(|| io::Error::other("missing third-ranked result"))?;
    assert_eq!(last.url().as_str(), "https://example.org/other");
    assert_eq!(last.title(), Some("synthetic third title"));
    assert_eq!(last.snippet(), Some("synthetic third snippet"));
    assert_eq!(last.organic_rank().get(), 3);
    assert!(page.issues().iter().any(|issue| {
        issue.placement_index.is_some_and(|index| index.get() == 2)
            && issue.kind == SearchIssueKind::DuplicateDestination
    }));
    assert_eq!(page.coverage().web(), WebCoverage::Partial);
    Ok(())
}

#[test]
fn captured_multirow_fixture_keeps_fields_with_their_source_row() -> Result<(), Box<dyn Error>> {
    let targets = positive_vectors()?;
    let first = targets
        .first()
        .ok_or_else(|| io::Error::other("first synthetic URL target is missing"))?;
    let second = targets
        .get(1)
        .ok_or_else(|| io::Error::other("second synthetic URL target is missing"))?;
    let markup = replace_two_redacted_wrappers(MULTIROW, &first.0, &second.0)?;
    let document = Document::html("bing-multirow.html", markup.into_bytes())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=captured+title",
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected captured Bing rows").into());
    };
    assert_eq!(page.hits().len(), 2);
    let first_hit = page
        .hits()
        .first()
        .ok_or_else(|| io::Error::other("missing first captured Bing row"))?;
    let second_hit = page
        .hits()
        .get(1)
        .ok_or_else(|| io::Error::other("missing second captured Bing row"))?;
    assert_eq!(first_hit.url().as_str(), first.1);
    assert_eq!(first_hit.title(), Some("[redacted captured title row 1]"));
    assert_eq!(
        first_hit.snippet(),
        Some("[redacted captured snippet row 1]")
    );
    assert_eq!(second_hit.url().as_str(), second.1);
    assert_eq!(second_hit.title(), Some("[redacted captured title row 2]"));
    assert_eq!(
        second_hit.snippet(),
        Some("[redacted captured snippet row 2]")
    );
    assert_eq!(first_hit.placement_index().get(), 1);
    assert_eq!(second_hit.placement_index().get(), 2);
    for result_limit in [1, 2] {
        let capped = parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=captured+title",
            result_limit,
            16 * 1024 * 1024,
        )?;
        let ProviderOutcome::Results(capped_page) = capped else {
            return Err(io::Error::other("expected capped organic results").into());
        };
        assert_eq!(capped_page.hits().len(), result_limit);
        assert_eq!(capped_page.coverage().web(), WebCoverage::Complete);
        assert_eq!(capped_page.issues().len(), 0);
    }
    Ok(())
}

#[test]
fn captured_snippetless_layout_keeps_valid_rows_with_optional_snippets()
-> Result<(), Box<dyn Error>> {
    let targets = positive_vectors()?;
    let first = targets
        .first()
        .ok_or_else(|| io::Error::other("first synthetic URL target is missing"))?;
    let second = targets
        .get(1)
        .ok_or_else(|| io::Error::other("second synthetic URL target is missing"))?;
    let markup = replace_two_redacted_wrappers(SNIPPETLESS_ROWS, &first.0, &second.0)?;
    let document = Document::html("bing-snippetless-rows.html", markup.into_bytes())?;
    let outcome = parse(
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=fixture",
        10,
        16 * 1024 * 1024,
    )?;
    let ProviderOutcome::Results(page) = outcome else {
        return Err(io::Error::other("expected captured snippetless Bing rows").into());
    };
    assert_eq!(page.hits().len(), 2);
    assert!(page.hits().iter().all(|hit| hit.snippet().is_none()));
    Ok(())
}

#[test]
fn synthetic_sponsored_control_is_not_selected_as_a_result_row() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "bing-synthetic-sponsored-control.html",
        SPONSORED_CONTROL.as_bytes().to_vec(),
    )?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        ),
        Err(BingParseError::UnrecognizedPage)
    ));
    Ok(())
}

#[test]
fn synthetic_missing_href_row_is_not_usable() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "bing-synthetic-missing-href.html",
        MISSING_HREF_CONTROL.as_bytes().to_vec(),
    )?;
    assert!(matches!(
        parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        ),
        Err(BingParseError::NoUsableHits)
    ));
    Ok(())
}

#[test]
#[ignore = "requires retained local CAS-502 pages; this replay performs no network I/O"]
fn replay_retained_brave_bing_captures_serially() -> Result<(), Box<dyn Error>> {
    use crate::internal::engine::search::provider::brave;

    let captures = [
        ("brave_standard_http", "brave", 20_usize),
        ("bing_standard_http", "bing", 10_usize),
        ("bing_safari26_http", "bing", 10_usize),
        ("brave_safari26_http", "rate_limited", 0_usize),
    ];
    for (capture_name, provider, expected_hits) in captures {
        let (bytes, status) = load_retained_capture(capture_name)?;
        if provider == "rate_limited" {
            assert_eq!(status, 429);
            eprintln!(
                "local_search_replay capture={capture_name} bytes={} status={status} classification=rate_limited source=status_manifest parsed=false sha256_verified=true",
                bytes.len()
            );
            continue;
        }
        assert_eq!(status, 200);
        let document = Document::html(capture_name, bytes.clone())?;
        let outcome = match provider {
            "brave" => brave::parse(
                &document,
                &Policy::default(),
                "https://search.brave.com/search",
                32,
                16 * 1024 * 1024,
            )?,
            "bing" => parse(
                &document,
                &Policy::default(),
                "https://www.bing.com/search",
                32,
                16 * 1024 * 1024,
            )?,
            _ => return Err(io::Error::other("unknown local replay provider").into()),
        };
        let ProviderOutcome::Results(page) = outcome else {
            return Err(
                io::Error::other("local successful capture did not parse as results").into(),
            );
        };
        let validated_urls = page
            .hits()
            .iter()
            .filter(|hit| SearchResultUrl::parse(hit.url().as_str()).is_ok())
            .count();
        let invalid_destinations = page
            .issues()
            .iter()
            .filter(|issue| issue.kind == SearchIssueKind::InvalidDestination)
            .count();
        assert_eq!(page.hits().len(), expected_hits);
        assert_eq!(validated_urls, expected_hits);
        assert_eq!(invalid_destinations, 0);
        eprintln!(
            "local_search_replay capture={capture_name} bytes={} status={status} classification=results expected_rows={expected_hits} hits={} validated_http_urls={validated_urls} invalid_destination_issues={invalid_destinations} issue_count={} coverage={:?} sha256_verified=true",
            bytes.len(),
            page.hits().len(),
            page.issues().len(),
            page.coverage().web(),
        );
    }
    Ok(())
}
