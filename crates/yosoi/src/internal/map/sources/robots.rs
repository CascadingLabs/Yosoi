use super::ParseError;

mod pattern;
use self::pattern::{glob_matches, normalize_uri, parse_robots_rule, select_robot_rules};

const MAX_ROBOTS_BYTES: usize = 1024 * 1024;
const MAX_ROBOTS_ENTRIES: usize = 10_000;
const MAX_ROBOTS_MATCH_BYTES: usize = 64 * 1024;
const MAX_ROBOTS_MATCH_WORK: usize = 8 * 1024 * 1024;

/// A parsed robots policy after selecting the most specific matching group.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Robots {
    rules: Vec<RobotsRule>,
    sitemaps: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RobotsRule {
    pattern: Vec<PatternToken>,
    anchored: bool,
    specificity: usize,
    allow: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PatternToken {
    Literal(u8),
    Escaped(u8),
    Wildcard,
}

#[derive(Default)]
struct RobotsGroup {
    agents: Vec<String>,
    rules: Vec<RobotsRule>,
    has_directive: bool,
}

impl Robots {
    /// Parses robots.txt with a fixed limit of 10,000 recognized directives.
    pub fn parse(text: &str, agent: &str) -> Result<Self, ParseError> {
        Self::parse_bounded(text, agent, MAX_ROBOTS_ENTRIES)
    }

    /// Parses robots.txt and fails if it has more than max_entries recognized
    /// user-agent, rule, or sitemap directives.
    pub fn parse_bounded(text: &str, agent: &str, max_entries: usize) -> Result<Self, ParseError> {
        if text.len() > MAX_ROBOTS_BYTES {
            return Err(ParseError::ByteLimitExceeded {
                limit: MAX_ROBOTS_BYTES,
            });
        }

        let agent = agent.trim().to_ascii_lowercase();
        if agent.is_empty() {
            return Err(ParseError::EmptyUserAgent);
        }

        let mut groups = Vec::new();
        let mut current = RobotsGroup::default();
        let mut sitemaps = Vec::new();
        let mut entry_count = 0usize;

        for raw_line in text.lines() {
            let uncommented = raw_line.split_once('#').map_or(raw_line, |(line, _)| line);
            let line = uncommented.trim();
            if line.is_empty() {
                continue;
            }

            let Some((name, value)) = line.split_once(':') else {
                continue;
            };
            let name = name.trim();
            let value = value.trim();

            if name.eq_ignore_ascii_case("user-agent") {
                bump_entry_count(&mut entry_count, max_entries)?;
                if current.has_directive {
                    groups.push(current);
                    current = RobotsGroup::default();
                }
                if !value.is_empty() {
                    current.agents.push(value.to_ascii_lowercase());
                }
                continue;
            }

            if name.eq_ignore_ascii_case("sitemap") {
                bump_entry_count(&mut entry_count, max_entries)?;
                if !value.is_empty() {
                    sitemaps.push(value.to_owned());
                }
                continue;
            }

            if name.eq_ignore_ascii_case("allow") || name.eq_ignore_ascii_case("disallow") {
                bump_entry_count(&mut entry_count, max_entries)?;
                if !current.agents.is_empty() {
                    current.has_directive = true;
                    if !value.is_empty() {
                        current
                            .rules
                            .push(parse_robots_rule(value, name.eq_ignore_ascii_case("allow")));
                    }
                }
                continue;
            }

            // Unsupported directives still end a user-agent section, as they
            // separate its agent declarations from any following group.
            current.has_directive = true;
        }

        if !current.agents.is_empty() {
            groups.push(current);
        }

        let selected_rules = select_robot_rules(groups, &agent);
        Ok(Self {
            rules: selected_rules,
            sitemaps,
        })
    }

    /// Returns whether a path and query string are allowed by the selected
    /// robots group. The input should be the serialized URI path and query.
    /// Paths beyond the matcher bounds are conservatively disallowed.
    pub fn allowed(&self, path_and_query: &str) -> bool {
        if path_and_query.len() > MAX_ROBOTS_MATCH_BYTES {
            return false;
        }
        let path = normalize_uri(path_and_query.as_bytes());
        let mut best: Option<(usize, bool)> = None;
        let mut remaining_work = MAX_ROBOTS_MATCH_WORK;

        for rule in &self.rules {
            let Some(matches) =
                glob_matches(&rule.pattern, &path, rule.anchored, &mut remaining_work)
            else {
                return false;
            };
            if matches {
                match best {
                    None => best = Some((rule.specificity, rule.allow)),
                    Some((best_specificity, best_allow))
                        if rule.specificity > best_specificity
                            || (rule.specificity == best_specificity
                                && rule.allow
                                && !best_allow) =>
                    {
                        best = Some((rule.specificity, rule.allow));
                    }
                    Some(_) => {}
                }
            }
        }

        best.is_none_or(|(_, allow)| allow)
    }

    /// Returns the sitemap URLs declared in the document.
    pub fn sitemaps(&self) -> &[String] {
        &self.sitemaps
    }
}

const fn bump_entry_count(count: &mut usize, limit: usize) -> Result<(), ParseError> {
    if *count >= limit {
        return Err(ParseError::EntryLimitExceeded { limit });
    }
    *count = (*count).saturating_add(1);
    Ok(())
}
