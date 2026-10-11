#![allow(clippy::absolute_paths, clippy::arithmetic_side_effects)]

use crate::internal::direct_http as yosoi_web_capture_direct_http;

use crate::internal::direct_http::ObservedHeaderValue;
use crate::internal::types::Sha256Digest;

use super::*;

fn value(text: &str) -> ObservedHeaderValue {
    ObservedHeaderValue::from_text(text)
}

#[test]
fn absent_encoding_is_an_empty_identity_chain() {
    assert_eq!(
        parse_content_encoding(&ObservedHeaderValue::Absent),
        Ok(Vec::new())
    );
}
#[test]
fn supported_names_are_case_insensitive_and_ordered() {
    assert_eq!(
        parse_content_encoding(&value("GZip, identity, BR, deflate, x-gzip")),
        Ok(vec![
            HttpContentCoding::Gzip,
            HttpContentCoding::Identity,
            HttpContentCoding::Brotli,
            HttpContentCoding::Deflate,
            HttpContentCoding::Gzip
        ])
    );
}
#[test]
fn empty_list_members_are_malformed() {
    assert_eq!(
        parse_content_encoding(&value("gzip,,br")),
        Err(ContentEncodingError::Malformed)
    );
}
#[test]
fn invalid_token_bytes_are_malformed() {
    assert_eq!(
        parse_content_encoding(&value("gzip;level=1")),
        Err(ContentEncodingError::Malformed)
    );
}
#[test]
fn unknown_tokens_are_unsupported_not_malformed() {
    assert_eq!(
        parse_content_encoding(&value("zstd")),
        Err(ContentEncodingError::Unsupported)
    );
}
#[test]
fn unsafe_header_observations_are_malformed() {
    assert_eq!(
        parse_content_encoding(&ObservedHeaderValue::TooLong),
        Err(ContentEncodingError::Malformed)
    );
    assert_eq!(
        parse_content_encoding(&ObservedHeaderValue::InvalidEncoding),
        Err(ContentEncodingError::Malformed)
    );
}
#[test]
fn coding_count_is_bounded() {
    let text = std::iter::repeat_n("identity", 17)
        .collect::<Vec<_>>()
        .join(",");
    assert_eq!(
        parse_content_encoding(&value(&text)),
        Err(ContentEncodingError::Malformed)
    );
}

#[test]
fn publication_hashes_exact_retained_prefix() {
    let mut sink = BoundedMemorySink::new(3);
    sink.write(b"abc").unwrap();
    let bytes = Box::new(sink).commit().unwrap();
    let outcome = publish(bytes, 3, 7, BodyTerminal::RepresentationLimit).unwrap();
    let source = outcome.payload().retained_source().unwrap();
    assert_eq!(source.bytes(), b"abc");
    assert_eq!(source.digest(), Sha256Digest::digest(b"abc"));
    assert_eq!(
        source.extent(),
        yosoi_web_capture_direct_http::RetainedSourceExtent::Truncated
    );
    assert_eq!(outcome.content_coded_bytes(), 7);
}

#[test]
fn incomplete_empty_output_is_unavailable() {
    let outcome = publish(Vec::new(), 0, 1, BodyTerminal::Disconnect).unwrap();
    assert!(matches!(
        outcome.payload().state(),
        yosoi_web_capture_direct_http::AcquiredPayloadState::Unavailable { .. }
    ));
    assert_eq!(outcome.content_coded_bytes(), 1);
    assert_eq!(outcome.terminal(), BodyTerminal::Disconnect);
}

#[test]
fn normally_completed_empty_output_is_retained() {
    let outcome = publish(Vec::new(), 0, 0, BodyTerminal::Complete).unwrap();
    let source = outcome.payload().retained_source().unwrap();
    assert_eq!(source.bytes(), b"");
    assert_eq!(source.digest(), Sha256Digest::digest(b""));
    assert_eq!(
        source.extent(),
        yosoi_web_capture_direct_http::RetainedSourceExtent::Complete
    );
}
