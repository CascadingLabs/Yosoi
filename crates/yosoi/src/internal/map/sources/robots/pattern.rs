use super::{PatternToken, RobotsGroup, RobotsRule};

pub(super) fn parse_robots_rule(value: &str, allow: bool) -> RobotsRule {
    let bytes = value.as_bytes();
    let anchored = bytes.last() == Some(&b'$');
    let pattern_end = if anchored {
        bytes.len().saturating_sub(1)
    } else {
        bytes.len()
    };
    let pattern = parse_pattern(bytes.get(..pattern_end).unwrap_or_default());
    let specificity = pattern
        .iter()
        .filter(|token| !matches!(token, PatternToken::Wildcard))
        .count();
    RobotsRule {
        pattern,
        anchored,
        specificity,
        allow,
    }
}

fn parse_pattern(bytes: &[u8]) -> Vec<PatternToken> {
    let mut pattern = Vec::with_capacity(bytes.len());
    let mut index = 0usize;
    while index < bytes.len() {
        let byte = bytes.get(index).copied().unwrap_or_default();
        if byte == b'*' {
            pattern.push(PatternToken::Wildcard);
            index = index.saturating_add(1);
            continue;
        }

        if byte == b'%' {
            let escaped = bytes
                .get(index.saturating_add(1)..index.saturating_add(3))
                .and_then(decode_hex_pair);
            if let Some(octet) = escaped {
                if is_unreserved(octet) {
                    pattern.push(PatternToken::Literal(octet));
                } else {
                    pattern.push(PatternToken::Escaped(octet));
                }
                index = index.saturating_add(3);
                continue;
            }
        }

        pattern.push(normalize_raw_octet(byte));
        index = index.saturating_add(1);
    }
    pattern
}

pub(super) fn normalize_uri(bytes: &[u8]) -> Vec<PatternToken> {
    let mut normalized = Vec::with_capacity(bytes.len());
    let mut index = 0usize;
    while index < bytes.len() {
        let byte = bytes.get(index).copied().unwrap_or_default();
        if byte == b'%' {
            let escaped = bytes
                .get(index.saturating_add(1)..index.saturating_add(3))
                .and_then(decode_hex_pair);
            if let Some(octet) = escaped {
                if is_unreserved(octet) {
                    normalized.push(PatternToken::Literal(octet));
                } else {
                    normalized.push(PatternToken::Escaped(octet));
                }
                index = index.saturating_add(3);
                continue;
            }
        }
        normalized.push(normalize_raw_octet(byte));
        index = index.saturating_add(1);
    }
    normalized
}

const fn normalize_raw_octet(byte: u8) -> PatternToken {
    if byte >= 0x80 || is_reserved(byte) {
        PatternToken::Escaped(byte)
    } else {
        PatternToken::Literal(byte)
    }
}

fn decode_hex_pair(digits: &[u8]) -> Option<u8> {
    let mut values = digits.iter().copied();
    let high = hex_value(values.next()?)?;
    let low = hex_value(values.next()?)?;
    if values.next().is_some() {
        return None;
    }
    Some((high << 4) | low)
}

const fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => byte.checked_sub(b'0'),
        b'a'..=b'f' => match byte.checked_sub(b'a') {
            Some(value) => value.checked_add(10),
            None => None,
        },
        b'A'..=b'F' => match byte.checked_sub(b'A') {
            Some(value) => value.checked_add(10),
            None => None,
        },
        _ => None,
    }
}

const fn is_unreserved(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~')
}

const fn is_reserved(byte: u8) -> bool {
    matches!(
        byte,
        b':' | b'/'
            | b'?'
            | b'#'
            | b'['
            | b']'
            | b'@'
            | b'!'
            | b'$'
            | b'&'
            | b'\''
            | b'('
            | b')'
            | b'*'
            | b'+'
            | b','
            | b';'
            | b'='
    )
}

pub(super) fn glob_matches(
    pattern: &[PatternToken],
    path: &[PatternToken],
    anchored: bool,
    remaining_work: &mut usize,
) -> Option<bool> {
    let mut pattern_index = 0usize;
    let mut path_index = 0usize;
    let mut last_wildcard: Option<(usize, usize)> = None;

    while path_index < path.len() {
        if *remaining_work == 0 {
            return None;
        }
        *remaining_work = (*remaining_work).saturating_sub(1);
        if pattern_index == pattern.len() {
            if !anchored {
                return Some(true);
            }
            if let Some((wildcard_index, matched_path_index)) = last_wildcard {
                let next_path_index = matched_path_index.saturating_add(1);
                last_wildcard = Some((wildcard_index, next_path_index));
                pattern_index = wildcard_index.saturating_add(1);
                path_index = next_path_index;
                continue;
            }
            return Some(false);
        }

        let expected = pattern.get(pattern_index).copied();
        let actual = path.get(path_index).copied();
        match (expected, actual) {
            (Some(PatternToken::Wildcard), _) => {
                last_wildcard = Some((pattern_index, path_index));
                pattern_index = pattern_index.saturating_add(1);
            }
            (Some(expected), Some(actual)) if expected == actual => {
                pattern_index = pattern_index.saturating_add(1);
                path_index = path_index.saturating_add(1);
            }
            _ => {
                if let Some((wildcard_index, matched_path_index)) = last_wildcard {
                    let next_path_index = matched_path_index.saturating_add(1);
                    last_wildcard = Some((wildcard_index, next_path_index));
                    pattern_index = wildcard_index.saturating_add(1);
                    path_index = next_path_index;
                } else {
                    return Some(false);
                }
            }
        }
    }

    while matches!(pattern.get(pattern_index), Some(PatternToken::Wildcard)) {
        if *remaining_work == 0 {
            return None;
        }
        *remaining_work = (*remaining_work).saturating_sub(1);
        pattern_index = pattern_index.saturating_add(1);
    }

    Some(pattern_index == pattern.len())
}

pub(super) fn select_robot_rules(groups: Vec<RobotsGroup>, agent: &str) -> Vec<RobotsRule> {
    let mut specific_groups: Vec<(usize, RobotsGroup)> = Vec::new();
    let mut wildcard_groups = Vec::new();
    let mut best_specificity = 0usize;

    for group in groups {
        let mut group_specificity = 0usize;
        let mut wildcard_match = false;
        for group_agent in &group.agents {
            if group_agent == "*" {
                wildcard_match = true;
            } else if agent.contains(group_agent) {
                group_specificity = group_specificity.max(group_agent.len());
            }
        }

        if group_specificity > 0 {
            best_specificity = best_specificity.max(group_specificity);
            specific_groups.push((group_specificity, group));
        } else if wildcard_match {
            wildcard_groups.push(group);
        }
    }

    let matching_groups = if best_specificity > 0 {
        specific_groups
            .into_iter()
            .filter_map(|(specificity, group)| (specificity == best_specificity).then_some(group))
            .collect()
    } else {
        wildcard_groups
    };

    matching_groups
        .into_iter()
        .flat_map(|group| group.rules)
        .collect()
}
