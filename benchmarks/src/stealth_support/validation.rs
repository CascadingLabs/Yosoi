use serde_json::{Value, json};

pub fn validate_snapshot(
    stage: &str,
    value: &Value,
    expected_webdriver: bool,
    violations: &mut Vec<String>,
) {
    if value
        .pointer("/userAgent")
        .and_then(Value::as_str)
        .is_some_and(|ua| ua.contains("Headless"))
    {
        violations.push(format!("{stage}: user agent contains Headless"));
    }
    if value
        .pointer("/cspInlineScriptRan")
        .and_then(Value::as_bool)
        == Some(true)
    {
        violations.push(format!("{stage}: strict CSP inline script executed"));
    }
    if value.pointer("/webdriver").and_then(Value::as_bool) != Some(expected_webdriver) {
        violations.push(format!("{stage}: webdriver did not match policy"));
    }
    if value.pointer("/frame/webdriver").and_then(Value::as_bool) != Some(expected_webdriver) {
        violations.push(format!("{stage}: frame webdriver did not match policy"));
    }
    if value.pointer("/windowChrome").and_then(Value::as_bool) != Some(true) {
        violations.push(format!("{stage}: window.chrome is missing"));
    }
    if value
        .pointer("/automationGlobals")
        .and_then(Value::as_array)
        .is_some_and(|globals| !globals.is_empty())
    {
        violations.push(format!("{stage}: automation globals are present"));
    }
    if value
        .pointer("/languages")
        .and_then(Value::as_array)
        .is_some_and(|languages| {
            languages.iter().any(|language| {
                language
                    .as_str()
                    .is_some_and(|language| language.contains(";q="))
            })
        })
    {
        violations.push(format!(
            "{stage}: navigator.languages contains an HTTP quality weight"
        ));
    }
    validate_worker(stage, value, violations);
    validate_headers(stage, value, violations);
    for (screen, viewport) in [
        ("/viewport/screenWidth", "/viewport/innerWidth"),
        ("/viewport/screenHeight", "/viewport/innerHeight"),
    ] {
        if value.pointer(screen).and_then(Value::as_u64)
            != value.pointer(viewport).and_then(Value::as_u64)
        {
            violations.push(format!("{stage}: screen and viewport geometry disagree"));
        }
    }
    validate_client_hints(stage, value, violations);
}

fn validate_worker(stage: &str, value: &Value, violations: &mut Vec<String>) {
    if value.pointer("/worker/status").and_then(Value::as_str) != Some("ready") {
        violations.push(format!("{stage}: worker fingerprint was unavailable"));
    }
    for (top, worker) in [
        ("/userAgent", "/worker/userAgent"),
        ("/platform", "/worker/platform"),
        ("/languages", "/worker/languages"),
        ("/hardwareConcurrency", "/worker/hardwareConcurrency"),
        ("/deviceMemory", "/worker/deviceMemory"),
        ("/userAgentData/brands", "/worker/userAgentData/brands"),
        ("/userAgentData/platform", "/worker/userAgentData/platform"),
        (
            "/userAgentData/highEntropy/fullVersionList",
            "/worker/userAgentData/highEntropy/fullVersionList",
        ),
        (
            "/userAgentData/highEntropy/platformVersion",
            "/worker/userAgentData/highEntropy/platformVersion",
        ),
    ] {
        if value.pointer(top) != value.pointer(worker) {
            violations.push(format!("{stage}: main and worker fingerprints disagree"));
        }
    }
}

fn validate_headers(stage: &str, value: &Value, violations: &mut Vec<String>) {
    if value
        .pointer("/requestHeaders/user-agent")
        .and_then(Value::as_str)
        != value.pointer("/userAgent").and_then(Value::as_str)
    {
        violations.push(format!("{stage}: HTTP and JavaScript user agents disagree"));
    }
    if !value
        .pointer("/requestHeaders/accept-language")
        .and_then(Value::as_str)
        .is_some_and(|header| header.starts_with("en-US"))
    {
        violations.push(format!("{stage}: Accept-Language is missing or incoherent"));
    }
    if !value
        .pointer("/requestHeaders/sec-ch-ua-platform")
        .and_then(Value::as_str)
        .is_some_and(|header| header.contains("Linux"))
    {
        violations.push(format!(
            "{stage}: platform Client Hint header is incoherent"
        ));
    }
    let chrome_full_version = value
        .pointer("/userAgentData/highEntropy/fullVersionList")
        .and_then(Value::as_array)
        .and_then(|brands| {
            brands.iter().find_map(|brand| {
                if brand.pointer("/brand").and_then(Value::as_str) == Some("Google Chrome") {
                    brand.pointer("/version").and_then(Value::as_str)
                } else {
                    None
                }
            })
        });
    if !value
        .pointer("/requestHeaders/sec-ch-ua-full-version-list")
        .and_then(Value::as_str)
        .is_some_and(|header| chrome_full_version.is_some_and(|version| header.contains(version)))
    {
        violations.push(format!(
            "{stage}: full-version Client Hint header is incoherent"
        ));
    }
}

fn validate_client_hints(stage: &str, value: &Value, violations: &mut Vec<String>) {
    let ua_major = value
        .pointer("/userAgent")
        .and_then(Value::as_str)
        .and_then(|ua| ua.split("Chrome/").nth(1))
        .and_then(|version| version.split('.').next());
    let brands = value
        .pointer("/userAgentData/brands")
        .and_then(Value::as_array);
    if ua_major.is_none()
        || brands.is_none_or(|brands| {
            !brands.iter().any(|brand| {
                brand.pointer("/brand").and_then(Value::as_str) == Some("Google Chrome")
                    && brand.pointer("/version").and_then(Value::as_str) == ua_major
            })
        })
    {
        violations.push(format!(
            "{stage}: User-Agent and low-entropy Client Hints disagree"
        ));
    }
    let full_versions = value
        .pointer("/userAgentData/highEntropy/fullVersionList")
        .and_then(Value::as_array);
    if full_versions.is_none_or(|versions| {
        !versions.iter().any(|brand| {
            brand.pointer("/brand").and_then(Value::as_str) == Some("Google Chrome")
                && brand
                    .pointer("/version")
                    .and_then(Value::as_str)
                    .is_some_and(|version| ua_major.is_some_and(|major| version.starts_with(major)))
        })
    }) {
        violations.push(format!(
            "{stage}: full-version Client Hints are missing or incoherent"
        ));
    }
}

#[derive(Debug)]
pub struct LiveSummaryParts<'a> {
    pub signals: Value,
    pub statuses: Value,
    pub scores: Value,
    pub rows: Value,
    pub provider_resources: Value,
    pub challenge_markers: Value,
    pub body: &'a str,
}

pub fn live_summary_parts(summary: &Value) -> LiveSummaryParts<'_> {
    let signals = summary
        .pointer("/signals")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let rows = summary
        .pointer("/diagnosticRows")
        .cloned()
        .unwrap_or_else(|| json!([]));
    let statuses = summary
        .pointer("/statuses")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let scores = summary
        .pointer("/scores")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let provider_resources = summary
        .pointer("/providerResources")
        .cloned()
        .unwrap_or_else(|| json!([]));
    let challenge_markers = summary
        .pointer("/challengeMarkers")
        .cloned()
        .unwrap_or_else(|| json!([]));
    let body = summary
        .pointer("/bodyText")
        .and_then(Value::as_str)
        .map_or("", |value| value);
    LiveSummaryParts {
        signals,
        statuses,
        scores,
        rows,
        provider_resources,
        challenge_markers,
        body,
    }
}
