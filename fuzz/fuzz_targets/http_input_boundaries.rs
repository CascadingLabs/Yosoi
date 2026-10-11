#![no_main]

use libfuzzer_sys::fuzz_target;
use yosoi_dev_support::internal::direct_http::{
    CharsetDeclaration, CharsetIssue, ContentEncodingError, HttpContentCoding, MediaDeclaration,
    MediaDeclarationIssue, ObservedHeaderValue, RequestedWebTarget, SourceMediaType,
    parse_content_encoding, parse_media_declaration,
};

fuzz_target!(|data: &[u8]| {
    let value = String::from_utf8_lossy(data).into_owned();
    let observed = match data.first().copied().unwrap_or_default() % 5 {
        0 => ObservedHeaderValue::Absent,
        1 => ObservedHeaderValue::InvalidEncoding,
        2 => ObservedHeaderValue::Duplicate,
        3 => ObservedHeaderValue::TooLong,
        _ => ObservedHeaderValue::from_text(value.clone()),
    };

    validate_content_encoding(&observed, parse_content_encoding(&observed));
    validate_media_declaration(
        &observed,
        parse_media_declaration(&SourceMediaType::from(&observed)),
    );
    validate_url(&value);
});

fn validate_content_encoding(
    observed: &ObservedHeaderValue,
    result: Result<Vec<HttpContentCoding>, ContentEncodingError>,
) {
    match (observed, result) {
        (ObservedHeaderValue::Absent, Ok(codings)) => assert!(codings.is_empty()),
        (
            ObservedHeaderValue::InvalidEncoding
            | ObservedHeaderValue::TooLong
            | ObservedHeaderValue::Duplicate,
            Err(ContentEncodingError::Malformed),
        ) => {}
        (ObservedHeaderValue::Value(_), Ok(codings)) => {
            assert!(!codings.is_empty());
            assert!(codings.len() <= 16);
            let canonical = codings
                .iter()
                .map(|coding| match coding {
                    HttpContentCoding::Identity => "identity",
                    HttpContentCoding::Gzip => "gzip",
                    HttpContentCoding::Brotli => "br",
                    HttpContentCoding::Deflate => "deflate",
                })
                .collect::<Vec<_>>()
                .join(", ");
            assert_eq!(
                parse_content_encoding(&ObservedHeaderValue::from_text(canonical.clone())),
                Ok(codings.clone())
            );
            assert_eq!(
                parse_content_encoding(&ObservedHeaderValue::from_text(
                    canonical.to_ascii_uppercase()
                )),
                Ok(codings)
            );
        }
        (ObservedHeaderValue::Value(_), Err(error)) => {
            let display = error.to_string();
            assert!(!display.is_empty());
            assert!(display.len() <= 128);
        }
        _ => panic!("header observation and Content-Encoding outcome disagree"),
    }
}

fn validate_media_declaration(observed: &ObservedHeaderValue, declaration: MediaDeclaration) {
    match (observed, declaration) {
        (ObservedHeaderValue::Absent, MediaDeclaration::Missing) => {}
        (
            ObservedHeaderValue::InvalidEncoding,
            MediaDeclaration::Malformed(MediaDeclarationIssue::InvalidEncoding),
        )
        | (
            ObservedHeaderValue::TooLong,
            MediaDeclaration::Malformed(MediaDeclarationIssue::TooLong),
        )
        | (
            ObservedHeaderValue::Duplicate,
            MediaDeclaration::Malformed(MediaDeclarationIssue::DuplicateField),
        ) => {}
        (ObservedHeaderValue::Value(_), MediaDeclaration::Parsed { essence, charset }) => {
            assert!(essence.is_ascii());
            assert!(essence.len() <= 127);
            assert_eq!(essence, essence.to_ascii_lowercase());
            let mut parts = essence.split('/');
            assert!(parts.next().is_some_and(|part| !part.is_empty()));
            assert!(parts.next().is_some_and(|part| !part.is_empty()));
            assert!(parts.next().is_none());
            match charset {
                CharsetDeclaration::Missing => {}
                CharsetDeclaration::Label { canonical, .. } => {
                    assert!(canonical.is_ascii());
                    assert!(canonical.len() <= 63);
                    let reparsed = parse_media_declaration(&SourceMediaType::from_text(format!(
                        "{essence}; charset={canonical}"
                    )));
                    assert!(matches!(
                        reparsed,
                        MediaDeclaration::Parsed {
                            charset: CharsetDeclaration::Label { canonical: value, .. },
                            ..
                        } if value == canonical
                    ));
                }
                CharsetDeclaration::Issue(CharsetIssue::Unsupported { normalized }) => {
                    assert!(normalized.is_ascii());
                    assert!(normalized.len() <= 63);
                }
                CharsetDeclaration::Issue(CharsetIssue::Invalid | CharsetIssue::Conflicting) => {}
            }
        }
        (ObservedHeaderValue::Value(_), MediaDeclaration::Malformed(_)) => {}
        _ => panic!("header observation and media declaration outcome disagree"),
    }
}

fn validate_url(value: &str) {
    match RequestedWebTarget::parse(value) {
        Ok(target) => {
            assert!(
                target.as_str().starts_with("http://") || target.as_str().starts_with("https://")
            );
            assert_eq!(RequestedWebTarget::parse(target.as_str()), Ok(target));
        }
        Err(error) => {
            let display = error.to_string();
            assert!(!display.is_empty());
            assert!(display.len() <= 256);
        }
    }
}
