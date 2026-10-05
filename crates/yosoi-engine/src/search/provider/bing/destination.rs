use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use url::Url;

use crate::search::SearchResultUrl;

use super::common::has_user_information;
use super::{BingDestinationError, MAX_PROVIDER_PAGE_URL_BYTES, PAGE_HOST};

const WRAPPER_PATH: &str = "/ck/a";
const TRACKING_PREFIX: &str = "a1";
const MAX_TRACKING_VALUE_BYTES: usize = 4_098;
const MAX_ENCODED_DESTINATION_BYTES: usize = 4_096;
const MAX_DECODED_DESTINATION_BYTES: usize = 3_072;

/// Decodes only the `www.bing.com/ck/a?u=a1...` shape observed in the saved pages.
pub fn decode_destination(value: &str) -> Result<SearchResultUrl, BingDestinationError> {
    if value.len() > MAX_PROVIDER_PAGE_URL_BYTES {
        return Err(BingDestinationError::TrackingUrlTooLong);
    }
    let url = Url::parse(value).map_err(|_| BingDestinationError::InvalidWrapperUrl)?;
    if url.scheme() != "https"
        || url.host_str() != Some(PAGE_HOST)
        || url.path() != WRAPPER_PATH
        || url.port().is_some()
        || has_user_information(&url)
        || url.fragment().is_some()
    {
        return Err(BingDestinationError::UnsupportedWrapper);
    }

    let mut destination_value = None;
    for (name, parameter_value) in url.query_pairs() {
        if name == "u" {
            if destination_value.is_some() {
                return Err(BingDestinationError::DestinationParameterCount);
            }
            destination_value = Some(parameter_value.into_owned());
        }
    }
    let destination_value =
        destination_value.ok_or(BingDestinationError::DestinationParameterCount)?;
    if destination_value.len() > MAX_TRACKING_VALUE_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let encoded = destination_value
        .strip_prefix(TRACKING_PREFIX)
        .ok_or(BingDestinationError::UnsupportedPrefix)?;
    if encoded.is_empty() {
        return Err(BingDestinationError::InvalidBase64Url);
    }
    if encoded.len() > MAX_ENCODED_DESTINATION_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let decoded = decode_unpadded_url_safe_base64(encoded)?;
    if decoded.len() > MAX_DECODED_DESTINATION_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let destination_text =
        String::from_utf8(decoded).map_err(|_| BingDestinationError::InvalidUtf8)?;
    if destination_text.trim() != destination_text
        || destination_text
            .bytes()
            .any(|byte| byte.is_ascii_whitespace() || byte.is_ascii_control())
    {
        return Err(BingDestinationError::InvalidDestination);
    }
    let destination =
        Url::parse(&destination_text).map_err(|_| BingDestinationError::InvalidDestination)?;
    if !matches!(destination.scheme(), "http" | "https") || destination.host_str().is_none() {
        return Err(BingDestinationError::InvalidDestination);
    }
    if has_user_information(&destination) {
        return Err(BingDestinationError::DestinationHasCredentials);
    }
    SearchResultUrl::parse(destination.as_str())
        .map_err(|_| BingDestinationError::InvalidDestination)
}

pub(super) fn decode_unpadded_url_safe_base64(
    value: &str,
) -> Result<Vec<u8>, BingDestinationError> {
    let bytes = value.as_bytes();
    if bytes.is_empty() || bytes.len() > MAX_ENCODED_DESTINATION_BYTES || bytes.len() % 4 == 1 {
        return Err(BingDestinationError::InvalidBase64Url);
    }
    let output_capacity = bytes
        .len()
        .checked_mul(3)
        .map(|length| length / 4)
        .ok_or(BingDestinationError::DestinationTooLong)?;
    if output_capacity > MAX_DECODED_DESTINATION_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let decoded = URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| BingDestinationError::InvalidBase64Url)?;
    if decoded.len() > MAX_DECODED_DESTINATION_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    Ok(decoded)
}
