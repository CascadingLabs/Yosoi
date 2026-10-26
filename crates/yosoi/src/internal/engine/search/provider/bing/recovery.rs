use std::{collections::HashSet, ops::Range};

use crate::internal::engine::search::{SearchHit, SearchPage};
use url::Url;

const CONNECTIVE_WORDS: &[&str] = &[
    "a", "an", "the", "of", "for", "in", "on", "at", "to", "is", "are", "was", "were", "what",
    "does", "do", "can",
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum QueryRelevance {
    Supported,
    Unknown,
}

#[derive(Clone, Copy)]
enum IntentKind {
    History,
    ScientificName,
    HowTo,
}

struct IntentLayout {
    kind: IntentKind,
    topic: Range<usize>,
    phrase: Range<usize>,
}

struct IntentQuery {
    kind: IntentKind,
    topic_terms: Vec<String>,
}

/// Classifies visible result titles, snippets, and destination host/path only.
/// URL query and fragment text can echo the authored query and is excluded.
/// Sparse samples, unsupported syntax, or incomplete topic/intent evidence
/// remain unknown instead of asserting that a result is irrelevant.
pub(super) fn query_relevance(hits: &[SearchHit], page_url: &Url) -> QueryRelevance {
    let Some(query) = page_url
        .query_pairs()
        .find(|(name, _)| name == "q")
        .map(|(_, value)| value)
    else {
        return QueryRelevance::Unknown;
    };
    query_relevance_for_query(hits, &query)
}

/// Returns whether sampled result metadata shows a complete absence of topic
/// terms for a supported intent query. Sparse, partial, or unsupported evidence
/// stays ambiguous and must not trigger an automatic rewrite.
pub fn has_clear_topic_loss(hits: &[SearchHit], query: &str) -> bool {
    if hits.len() < 3 {
        return false;
    }
    let Some(intent) = intent_query(query) else {
        return false;
    };
    !hits
        .iter()
        .take(5)
        .any(|hit| hit_mentions_any_topic_term(hit, &intent.topic_terms))
}

fn query_relevance_for_query(hits: &[SearchHit], query: &str) -> QueryRelevance {
    if let Some(intent) = intent_query(query) {
        if hits
            .iter()
            .take(5)
            .any(|hit| hit_supports_intent(hit, &intent))
        {
            return QueryRelevance::Supported;
        }
        // Missing visible topic terms cannot prove that the destination page is
        // irrelevant: titles and snippets may omit the matching content.
        return QueryRelevance::Unknown;
    }

    let Some(terms) = query_content_terms(query) else {
        return QueryRelevance::Unknown;
    };
    if terms.is_empty() {
        return QueryRelevance::Unknown;
    }
    if hits
        .iter()
        .take(5)
        .any(|hit| hit_contains_terms(hit, &terms))
    {
        QueryRelevance::Supported
    } else {
        QueryRelevance::Unknown
    }
}

fn hit_supports_intent(hit: &SearchHit, query: &IntentQuery) -> bool {
    let tokens = hit_tokens(hit);
    query
        .topic_terms
        .iter()
        .all(|term| tokens.iter().any(|token| topic_words_match(term, token)))
        && intent_is_visible(query.kind, &tokens)
}

fn hit_contains_terms(hit: &SearchHit, terms: &[String]) -> bool {
    let tokens = hit_tokens(hit);
    terms
        .iter()
        .all(|term| tokens.iter().any(|token| topic_words_match(term, token)))
}

fn hit_mentions_any_topic_term(hit: &SearchHit, terms: &[String]) -> bool {
    let tokens = hit_tokens(hit);
    terms
        .iter()
        .any(|term| tokens.iter().any(|token| topic_words_match(term, token)))
}

fn hit_tokens(hit: &SearchHit) -> HashSet<String> {
    let mut tokens = HashSet::new();
    for value in [hit.title(), hit.snippet()].into_iter().flatten() {
        add_text_tokens(&mut tokens, value);
    }
    if let Ok(url) = Url::parse(hit.url().as_str()) {
        if let Some(host) = url.host_str() {
            add_text_tokens(&mut tokens, host);
        }
        add_text_tokens(&mut tokens, url.path());
    }
    tokens
}

fn add_text_tokens(tokens: &mut HashSet<String>, value: &str) {
    for word in value.split(|character: char| !character.is_ascii_alphanumeric()) {
        if !word.is_empty() {
            tokens.insert(normalize_topic_word(word));
        }
    }
}

fn topic_words_match(query_word: &str, result_word: &str) -> bool {
    let query_word = normalize_topic_word(query_word);
    let result_word = normalize_topic_word(result_word);
    query_word == result_word
        || matches!(
            (query_word.as_str(), result_word.as_str()),
            ("airplane", "plane") | ("plane", "airplane")
        )
}

fn normalize_topic_word(word: &str) -> String {
    let normalized = word.to_ascii_lowercase();
    if let Some(stem) = normalized
        .strip_suffix("ies")
        .filter(|stem| stem.len() >= 3)
    {
        let mut singular = stem.to_owned();
        singular.push('y');
        return singular;
    }
    normalized
        .strip_suffix('s')
        .filter(|stem| stem.len() >= 4)
        .map(str::to_owned)
        .unwrap_or(normalized)
}

fn intent_is_visible(kind: IntentKind, tokens: &HashSet<String>) -> bool {
    match kind {
        IntentKind::History => ["history", "historical", "origin", "timeline"]
            .iter()
            .any(|term| tokens.contains(*term)),
        IntentKind::ScientificName => {
            tokens.contains("name")
                && ["scientific", "botanical", "binomial"]
                    .iter()
                    .any(|term| tokens.contains(*term))
        }
        IntentKind::HowTo => {
            (tokens.contains("how") && tokens.contains("make"))
                || [
                    "recipe",
                    "instruction",
                    "step",
                    "tutorial",
                    "guide",
                    "method",
                    "preparation",
                ]
                .iter()
                .any(|term| tokens.contains(*term))
        }
    }
}

/// A recovered page is verified only when one result shows every topic term
/// and an observable marker for the original intent.
pub fn recovered_page_matches_query(page: &SearchPage, original_query: &str) -> bool {
    if let Some(intent) = intent_query(original_query) {
        return page
            .hits()
            .iter()
            .take(5)
            .any(|hit| hit_supports_intent(hit, &intent));
    }
    let Some(terms) = query_content_terms(original_query) else {
        return false;
    };
    !terms.is_empty()
        && page
            .hits()
            .iter()
            .take(5)
            .any(|hit| hit_contains_terms(hit, &terms))
}

/// Produces one bounded Bing query rewrite after an off-query response.
/// Recognized intent phrases move after topic terms; quoted, operator,
/// non-ASCII, and already condensed queries do not produce another request.
pub fn recovery_query(query: &str) -> Option<String> {
    let words = query_words(query)?;
    if words.len() < 2 {
        return None;
    }
    if let Some(layout) = intent_layout(&words) {
        let mut output = words
            .get(layout.topic)?
            .iter()
            .copied()
            .filter(|word| !is_connective(word))
            .collect::<Vec<_>>();
        if output.is_empty() {
            return None;
        }
        output.extend(words.get(layout.phrase)?);
        let reordered = output.join(" ");
        return (reordered != query).then_some(reordered);
    }

    let content = words
        .iter()
        .copied()
        .filter(|word| !is_connective(word))
        .collect::<Vec<_>>();
    if content.is_empty() || content.len() == words.len() {
        return None;
    }
    Some(content.join(" "))
}

fn query_words(query: &str) -> Option<Vec<&str>> {
    if !query.is_ascii() || query.contains([':', '"']) {
        return None;
    }
    let words = query.split_ascii_whitespace().collect::<Vec<_>>();
    words
        .iter()
        .all(|word| word.bytes().all(|byte| byte.is_ascii_alphabetic()))
        .then_some(words)
}

fn intent_layout(words: &[&str]) -> Option<IntentLayout> {
    let length = words.len();
    if has_prefix(words, &["history", "of"]) {
        return Some(IntentLayout {
            kind: IntentKind::History,
            topic: 2..length,
            phrase: 0..1,
        });
    }
    if has_prefix(words, &["history"]) {
        return Some(IntentLayout {
            kind: IntentKind::History,
            topic: 1..length,
            phrase: 0..1,
        });
    }
    if has_prefix(words, &["scientific", "name", "for"]) {
        return Some(IntentLayout {
            kind: IntentKind::ScientificName,
            topic: 3..length,
            phrase: 0..2,
        });
    }
    if has_prefix(words, &["scientific", "name"]) {
        return Some(IntentLayout {
            kind: IntentKind::ScientificName,
            topic: 2..length,
            phrase: 0..2,
        });
    }
    if has_prefix(words, &["how", "to", "make"]) {
        return Some(IntentLayout {
            kind: IntentKind::HowTo,
            topic: 3..length,
            phrase: 0..3,
        });
    }
    if has_suffix(words, &["history"]) {
        let start = length.checked_sub(1)?;
        return Some(IntentLayout {
            kind: IntentKind::History,
            topic: 0..start,
            phrase: start..length,
        });
    }
    if has_suffix(words, &["scientific", "name"]) {
        let start = length.checked_sub(2)?;
        return Some(IntentLayout {
            kind: IntentKind::ScientificName,
            topic: 0..start,
            phrase: start..length,
        });
    }
    if has_suffix(words, &["how", "to", "make"]) {
        let start = length.checked_sub(3)?;
        return Some(IntentLayout {
            kind: IntentKind::HowTo,
            topic: 0..start,
            phrase: start..length,
        });
    }
    None
}

fn has_prefix(words: &[&str], prefix: &[&str]) -> bool {
    words.get(..prefix.len()).is_some_and(|candidate| {
        candidate
            .iter()
            .zip(prefix)
            .all(|(word, expected)| word.eq_ignore_ascii_case(expected))
    })
}

fn has_suffix(words: &[&str], suffix: &[&str]) -> bool {
    let Some(start) = words.len().checked_sub(suffix.len()) else {
        return false;
    };
    words.get(start..).is_some_and(|candidate| {
        candidate
            .iter()
            .zip(suffix)
            .all(|(word, expected)| word.eq_ignore_ascii_case(expected))
    })
}

fn intent_query(query: &str) -> Option<IntentQuery> {
    let words = query_words(query)?;
    let layout = intent_layout(&words)?;
    let topic_terms = words
        .get(layout.topic)?
        .iter()
        .copied()
        .filter(|word| !is_connective(word))
        .map(str::to_ascii_lowercase)
        .collect::<Vec<_>>();
    (!topic_terms.is_empty()).then_some(IntentQuery {
        kind: layout.kind,
        topic_terms,
    })
}

fn query_content_terms(query: &str) -> Option<Vec<String>> {
    Some(
        query_words(query)?
            .into_iter()
            .filter(|word| !is_connective(word))
            .map(str::to_ascii_lowercase)
            .collect(),
    )
}

fn is_connective(word: &str) -> bool {
    CONNECTIVE_WORDS
        .iter()
        .any(|connective| word.eq_ignore_ascii_case(connective))
}
