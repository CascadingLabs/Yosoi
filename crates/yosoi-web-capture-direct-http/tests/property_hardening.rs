#![allow(
    clippy::unwrap_used,
    reason = "bounded property generators and assertions"
)]

use proptest::{prelude::*, test_runner::Config};
use yosoi_web_capture_direct_http::{
    HttpContentCoding, MediaDeclaration, ObservedHeaderValue, SourceMediaType,
    parse_content_encoding, parse_media_declaration,
};

proptest! {
    #![proptest_config(Config::with_cases(128))]

    #[test]
    fn bounded_http_header_successes_have_canonical_round_trips(value in ".{0,2048}") {
        let observed = ObservedHeaderValue::from_text(value);
        if let Ok(codings) = parse_content_encoding(&observed) {
            prop_assert!(!codings.is_empty());
            prop_assert!(codings.len() <= 16);
            let canonical = codings.iter().map(|coding| match coding {
                HttpContentCoding::Identity => "identity",
                HttpContentCoding::Gzip => "gzip",
                HttpContentCoding::Brotli => "br",
                HttpContentCoding::Deflate => "deflate",
            }).collect::<Vec<_>>().join(", ");
            prop_assert_eq!(
                parse_content_encoding(&ObservedHeaderValue::from_text(canonical)),
                Ok(codings)
            );
        }
        if let MediaDeclaration::Parsed { essence, .. } =
            parse_media_declaration(&SourceMediaType::from(&observed))
        {
            prop_assert!(essence.is_ascii());
            prop_assert!(essence.len() <= 127);
            prop_assert_eq!(&essence, &essence.to_ascii_lowercase());
            prop_assert_eq!(essence.split('/').count(), 2);
        }
    }
}
