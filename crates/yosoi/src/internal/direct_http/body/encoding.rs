use super::super::ObservedHeaderValue;
use super::{ContentEncodingError, HttpContentCoding};

const MAX_CODINGS: usize = 16;

/// Parses a bounded list without retaining untrusted values.
pub fn parse_content_encoding(
    value: &ObservedHeaderValue,
) -> Result<Vec<HttpContentCoding>, ContentEncodingError> {
    let text = match value {
        ObservedHeaderValue::Absent => return Ok(Vec::new()),
        ObservedHeaderValue::Value(text) => text.as_str(),
        ObservedHeaderValue::InvalidEncoding
        | ObservedHeaderValue::TooLong
        | ObservedHeaderValue::Duplicate => {
            return Err(ContentEncodingError::Malformed);
        }
    };
    let mut codings = Vec::new();
    for element in text.split(',') {
        if codings.len() == MAX_CODINGS {
            return Err(ContentEncodingError::Malformed);
        }
        let token = element.trim();
        if token.is_empty() || !token.bytes().all(is_token_byte) {
            return Err(ContentEncodingError::Malformed);
        }
        let coding = if token.eq_ignore_ascii_case("identity") {
            HttpContentCoding::Identity
        } else if token.eq_ignore_ascii_case("gzip") || token.eq_ignore_ascii_case("x-gzip") {
            HttpContentCoding::Gzip
        } else if token.eq_ignore_ascii_case("br") {
            HttpContentCoding::Brotli
        } else if token.eq_ignore_ascii_case("deflate") {
            HttpContentCoding::Deflate
        } else {
            return Err(ContentEncodingError::Unsupported);
        };
        codings.push(coding);
    }
    Ok(codings)
}

const fn is_token_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric()
        || matches!(
            byte,
            b'!' | b'#'
                | b'$'
                | b'%'
                | b'&'
                | b'\''
                | b'*'
                | b'+'
                | b'-'
                | b'.'
                | b'^'
                | b'_'
                | b'`'
                | b'|'
                | b'~'
        )
}
