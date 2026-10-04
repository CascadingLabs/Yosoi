use std::sync::OnceLock;

use regex::{RegexSet, RegexSetBuilder};
use serde::Deserialize;

use super::{
    BROWSER_CHALLENGE_BODY_PREFIX_LIMIT, BrowserChallengeSignalSource, BrowserResponseBodySignals,
    BrowserResponseSignals,
};

const CORPUS_JSON: &str = include_str!("corpus.json");

#[derive(Debug, Deserialize)]
struct VendorSignature {
    vendor: String,
    signals: Vec<String>,
    #[serde(default)]
    challenge: Vec<String>,
}

struct CompiledCorpus {
    patterns: RegexSet,
    metadata: Vec<SignalMetadata>,
}

struct SignalMetadata {
    vendor: String,
    source: BrowserChallengeSignalSource,
    active_challenge: bool,
}

pub(super) struct MatchedSignal {
    pub vendor: String,
    pub source: BrowserChallengeSignalSource,
    pub active_challenge: bool,
}

pub(super) fn classify(signals: &BrowserResponseSignals<'_>) -> Option<Vec<MatchedSignal>> {
    let corpus = compiled()?;
    let mut normalized = normalize_head(signals.status, signals.headers.unwrap_or(&[]));
    let head_matches = scan(corpus, &normalized);
    if head_matches.iter().any(|matched| matched.active_challenge) {
        return Some(head_matches);
    }
    let body = match signals.body {
        BrowserResponseBodySignals::Complete(body)
        | BrowserResponseBodySignals::Truncated { retained: body } => body,
        BrowserResponseBodySignals::Omitted | BrowserResponseBodySignals::Unavailable(_) => &[],
    };
    if body.is_empty() {
        return Some(head_matches);
    }
    normalized.push_str("\nB:");
    let prefix_end = body_prefix_end(body);
    let prefix = body.get(..prefix_end).unwrap_or(body);
    normalized.push_str(&flatten(&String::from_utf8_lossy(prefix).to_lowercase()));
    Some(scan(corpus, &normalized))
}

fn scan(corpus: &CompiledCorpus, normalized: &str) -> Vec<MatchedSignal> {
    corpus
        .patterns
        .matches(normalized)
        .into_iter()
        .filter_map(|index| corpus.metadata.get(index))
        .map(|metadata| MatchedSignal {
            vendor: metadata.vendor.clone(),
            source: metadata.source,
            active_challenge: metadata.active_challenge,
        })
        .collect()
}

fn compiled() -> Option<&'static CompiledCorpus> {
    static COMPILED: OnceLock<Option<CompiledCorpus>> = OnceLock::new();
    COMPILED.get_or_init(compile).as_ref()
}

fn compile() -> Option<CompiledCorpus> {
    let vendors: Vec<VendorSignature> = serde_json::from_str(CORPUS_JSON).ok()?;
    let mut patterns = Vec::new();
    let mut metadata = Vec::new();
    for vendor in vendors {
        for pattern in vendor.signals {
            let source = signal_source(&pattern)?;
            patterns.push(section_anchor(&pattern));
            metadata.push(SignalMetadata {
                vendor: vendor.vendor.clone(),
                source,
                active_challenge: false,
            });
        }
        for pattern in vendor.challenge {
            let source = signal_source(&pattern)?;
            patterns.push(section_anchor(&pattern));
            metadata.push(SignalMetadata {
                vendor: vendor.vendor.clone(),
                source,
                active_challenge: true,
            });
        }
    }
    let patterns = RegexSetBuilder::new(patterns)
        .case_insensitive(true)
        .size_limit(8 * 1024 * 1024)
        .build()
        .ok()?;
    Some(CompiledCorpus { patterns, metadata })
}

fn signal_source(pattern: &str) -> Option<BrowserChallengeSignalSource> {
    if pattern.starts_with("h:") {
        Some(BrowserChallengeSignalSource::Headers)
    } else if pattern.starts_with("b:") {
        Some(BrowserChallengeSignalSource::Body)
    } else {
        None
    }
}

fn section_anchor(pattern: &str) -> String {
    pattern.strip_prefix("b:").map_or_else(
        || format!("(?m)^{pattern}"),
        |rest| format!("(?m)^b:.*{rest}"),
    )
}

fn flatten(value: &str) -> String {
    value.replace(['\n', '\r'], " ")
}

fn normalize_head(status: Option<u16>, headers: &[(String, String)]) -> String {
    let capacity = 64_usize.saturating_add(headers.len().saturating_mul(48));
    let mut normalized = String::with_capacity(capacity);
    if let Some(status) = status {
        normalized.push_str("S:");
        normalized.push_str(&status.to_string());
    }
    for (name, value) in headers {
        normalized.push_str("\nH:");
        normalized.push_str(&flatten(&name.to_lowercase()));
        normalized.push_str(": ");
        normalized.push_str(&flatten(&value.to_lowercase()));
    }
    normalized
}

fn body_prefix_end(body: &[u8]) -> usize {
    body.len().min(BROWSER_CHALLENGE_BODY_PREFIX_LIMIT)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn corpus_compiles_with_expected_signal_volume() {
        assert!(
            compiled().is_some_and(|corpus| corpus.patterns.len() > 10),
            "challenge corpus must compile"
        );
    }
}
