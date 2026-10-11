use crate::internal::engine::search::{SearchHit, SearchPage};
use url::Url;

/// Detects the observed Bing degradation where a full query is echoed but
/// organic rows are about a different, single term. A short result sample,
/// one-word query, operator query, or non-ASCII query remains unclassified.
pub(super) fn hits_match_query(hits: &[SearchHit], page_url: &Url) -> bool {
    if hits.len() < 3 {
        return true;
    }
    let Some(query) = page_url
        .query_pairs()
        .find(|(name, _)| name == "q")
        .map(|(_, value)| value)
    else {
        return true;
    };
    let Some(anchor) = query_anchor(&query) else {
        return true;
    };
    let singular = anchor.strip_suffix('s').filter(|value| value.len() >= 5);
    hits_contain_anchor(hits, &anchor, singular)
}

fn hits_contain_anchor(hits: &[SearchHit], anchor: &str, singular: Option<&str>) -> bool {
    hits.iter().take(5).any(|hit| {
        [hit.title(), hit.snippet(), Some(hit.url().as_str())]
            .into_iter()
            .flatten()
            .any(|value| {
                let normalized = value.to_ascii_lowercase();
                normalized.contains(anchor)
                    || singular.is_some_and(|word| normalized.contains(word))
            })
    })
}

/// A recovered page must still mention a distinctive term from the caller's
/// original query; a one-word recovery query cannot skip this check.
pub fn recovered_page_matches_query(page: &SearchPage, original_query: &str) -> bool {
    let Some(anchor) = query_anchor(original_query) else {
        return false;
    };
    let singular = anchor.strip_suffix('s').filter(|value| value.len() >= 5);
    hits_contain_anchor(page.hits(), &anchor, singular)
}

/// Produces one shorter Bing query after a detected off-query response. This
/// preserves distinctive ASCII words and refuses operators and quoted terms.
pub fn recovery_query(query: &str) -> Option<String> {
    let words = query.split_ascii_whitespace().collect::<Vec<_>>();
    if words.len() < 2
        || words
            .iter()
            .any(|word| !word.bytes().all(|byte| byte.is_ascii_alphabetic()))
    {
        return None;
    }
    let content = words
        .iter()
        .copied()
        .filter(|word| {
            !matches!(
                word.to_ascii_lowercase().as_str(),
                "a" | "an"
                    | "the"
                    | "of"
                    | "for"
                    | "in"
                    | "on"
                    | "at"
                    | "to"
                    | "is"
                    | "are"
                    | "was"
                    | "were"
                    | "what"
                    | "how"
                    | "who"
                    | "when"
                    | "where"
                    | "why"
                    | "does"
                    | "do"
                    | "can"
                    | "make"
                    | "history"
                    | "scientific"
                    | "name"
            )
        })
        .collect::<Vec<_>>();
    if content.is_empty() || content.len() == words.len() {
        return None;
    }
    Some(content.join(" "))
}

pub(super) fn query_anchor(query: &str) -> Option<String> {
    if !query.is_ascii() || query.contains([':', '"']) {
        return None;
    }
    let words = query
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>();
    if words.len() < 2 {
        return None;
    }
    words
        .iter()
        .rev()
        .take(2)
        .filter(|word| word.len() >= 6)
        .max_by_key(|word| word.len())
        .map(|word| word.to_ascii_lowercase())
}
