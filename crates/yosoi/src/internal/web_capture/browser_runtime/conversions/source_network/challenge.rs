use crate::internal::browser as provider;
use crate::internal::web_capture as yosoi;

const MAX_ADMITTED_HEADERS: usize = 64;
const MAX_ADMITTED_HEADER_VALUE_CHARS: usize = 512;

fn bounded_header_value(value: &str) -> String {
    value
        .chars()
        .take(MAX_ADMITTED_HEADER_VALUE_CHARS)
        .collect()
}

fn admitted_cookie_name(value: &str) -> Option<String> {
    let name = value.split_once('=').map(|(name, _)| name.trim())?;
    if name.is_empty()
        || name.len() > 64
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        return None;
    }
    let normalized = name.to_ascii_lowercase();
    let known = normalized == "datadome"
        || normalized.starts_with("visid_incap")
        || normalized.starts_with("_px")
        || normalized.starts_with("bigipserver")
        || normalized.strip_prefix("ts").is_some_and(|suffix| {
            suffix.len() == 6 && suffix.bytes().all(|byte| byte.is_ascii_hexdigit())
        });
    known.then_some(normalized)
}

fn admitted_main_document_header(name: &str, value: &str) -> Option<(String, String)> {
    let name = name.trim().to_ascii_lowercase();
    let value = value.trim();
    let admitted = match name.as_str() {
        "content-type" | "content-language" | "content-length" | "last-modified" | "server" => {
            bounded_header_value(value)
        }
        "via" => {
            if value.to_ascii_lowercase().contains("cloudfront") {
                "cloudfront".to_owned()
            } else {
                "present".to_owned()
            }
        }
        "x-cdn" => {
            if value.to_ascii_lowercase().contains("incapsula") {
                "incapsula".to_owned()
            } else {
                "present".to_owned()
            }
        }
        "cf-mitigated" | "x-amzn-waf-action" => {
            let normalized = value.to_ascii_lowercase();
            if matches!(normalized.as_str(), "challenge" | "block") {
                normalized
            } else {
                "present".to_owned()
            }
        }
        "cf-ray"
        | "x-datadome"
        | "x-dd-b"
        | "x-akamai-transformed"
        | "x-iinfo"
        | "x-kpsdk-ct"
        | "x-kpsdk-cd"
        | "x-sucuri-id"
        | "x-sucuri-block"
        | "x-amz-cf-id" => "present".to_owned(),
        "set-cookie" => {
            return admitted_cookie_name(value).map(|name| ("set-cookie-name".into(), name));
        }
        _ => return None,
    };
    Some((name, admitted))
}

pub(super) fn admitted_main_document_headers(
    headers: &provider::ProtectedHeaders,
    admission: yosoi::BrowserHeaderAdmission,
) -> Option<Vec<(String, String)>> {
    if admission == yosoi::BrowserHeaderAdmission::Omit {
        return None;
    }
    Some(
        headers
            .as_slice()
            .iter()
            .filter_map(|(name, value)| admitted_main_document_header(name, value))
            .take(MAX_ADMITTED_HEADERS)
            .collect(),
    )
}

pub fn browser_challenge(
    report: Option<&provider::NavigationCaptureReport>,
    admission: yosoi::BrowserEvidenceAdmissionPolicy,
) -> yosoi::BrowserChallengeFact {
    let Some(report) = report else {
        return yosoi::BrowserChallengeFact::unavailable(
            yosoi::BrowserResponseSignalUnavailableReason::NavigationNotCollected,
        );
    };
    let Some(main) = report.main_document.as_ref() else {
        return yosoi::BrowserChallengeFact::unavailable(
            yosoi::BrowserResponseSignalUnavailableReason::MainDocumentNotObserved,
        );
    };
    let headers = admitted_main_document_headers(&main.headers, admission.headers());
    let body = admitted_body(main, admission.main_body());
    yosoi::classify_browser_challenge(yosoi::BrowserResponseSignals {
        scope: yosoi::BrowserResponseSignalScope::MainDocument,
        status: main.status,
        headers: headers.as_deref(),
        body,
    })
}

fn admitted_body(
    main: &provider::MainDocumentSource,
    admission: yosoi::BrowserMainBodyAdmission,
) -> yosoi::BrowserResponseBodySignals<'_> {
    if admission == yosoi::BrowserMainBodyAdmission::Omit {
        return yosoi::BrowserResponseBodySignals::Omitted;
    }
    match main.body_state {
        provider::ResponseBodyState::Available => {
            yosoi::BrowserResponseBodySignals::Complete(main.body())
        }
        provider::ResponseBodyState::Truncated => yosoi::BrowserResponseBodySignals::Truncated {
            retained: main.body(),
        },
        provider::ResponseBodyState::Unavailable => {
            yosoi::BrowserResponseBodySignals::Unavailable(match main.body_unavailable {
                Some(provider::SourceBodyUnavailableReason::RequestFailed) => {
                    yosoi::BrowserResponseSignalUnavailableReason::BodyRequestFailed
                }
                Some(provider::SourceBodyUnavailableReason::InvalidBase64) => {
                    yosoi::BrowserResponseSignalUnavailableReason::BodyInvalidEncoding
                }
                Some(provider::SourceBodyUnavailableReason::CaptureEndedBeforeBody) => {
                    yosoi::BrowserResponseSignalUnavailableReason::BodyCaptureEnded
                }
                Some(provider::SourceBodyUnavailableReason::CdpBodyUnavailable) | None => {
                    yosoi::BrowserResponseSignalUnavailableReason::BodyUnavailable
                }
            })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cookie_admission_keeps_only_the_bounded_cookie_name() {
        let admitted =
            admitted_main_document_header("Set-Cookie", "datadome=secret-token; Secure; HttpOnly");
        assert_eq!(
            admitted,
            Some(("set-cookie-name".to_owned(), "datadome".to_owned()))
        );
    }

    #[test]
    fn admitted_values_are_bounded() {
        let admitted = admitted_main_document_header(
            "server",
            &"x".repeat(MAX_ADMITTED_HEADER_VALUE_CHARS.saturating_add(100)),
        )
        .expect("server is admitted");
        assert_eq!(admitted.1.chars().count(), MAX_ADMITTED_HEADER_VALUE_CHARS);
    }

    #[test]
    fn ordinary_cookie_names_are_not_admitted() {
        assert!(admitted_main_document_header("set-cookie", "session=secret").is_none());
    }

    #[test]
    fn cloudflare_challenge_header_keeps_only_its_bounded_state() {
        assert_eq!(
            admitted_main_document_header("Cf-Mitigated", "challenge"),
            Some(("cf-mitigated".to_owned(), "challenge".to_owned()))
        );
    }
}
