use std::{
    collections::{BTreeSet, VecDeque},
    str,
};

use crate::internal::documents::DocumentClass;
use crate::internal::map::{
    admission::{Rejection, normalize},
    sources::{self, Robots, SitemapKind},
};
use crate::internal::policy::policy::{PageDiscovery, Robots as RobotsPolicy};
use url::Url;

use super::{
    DiscoverySource, Fetch, FetchResult, LimitReached, OmissionReason, Purpose, RobotsState,
    Runner, SourceFailure, SourceOutcome, SourceSkipReason, SourceStatus, SupportDocument,
    SupportDocumentKind,
};
use crate::internal::engine::Document;

impl Runner<'_> {
    pub(super) async fn run(&mut self) {
        self.host(&self.seed.clone(), DiscoverySource::Seed, None);
        if self.policy().map.pages == PageDiscovery::Explore {
            self.page(self.seed.clone(), Some(0), DiscoverySource::Seed, None);
        }
        self.passive().await;
        self.explore_pages().await;
        self.source_outcomes.push(SourceOutcome {
            source: DiscoverySource::HtmlLink,
            source_url: None,
            status: if self.policy().map.pages == PageDiscovery::Disabled {
                SourceStatus::Disabled
            } else if self.termination.is_some() {
                SourceStatus::Truncated
            } else {
                SourceStatus::Completed
            },
        });
    }

    pub(super) async fn fetch_support(&mut self, start: &Url) -> Result<Fetch, SourceFailure> {
        match self.fetch(start, Purpose::Support).await? {
            FetchResult::Acquired(fetched) => Ok(*fetched),
            FetchResult::Reused { .. } => Err(SourceFailure::Transport),
        }
    }

    pub(super) fn allowed(&self, url: &Url) -> bool {
        if self.policy().map.robots == RobotsPolicy::Ignore {
            return true;
        }
        let origin = url.origin().ascii_serialization();
        match self.robots.get(&origin) {
            Some(RobotsState::Rules(rules)) => {
                let mut path = url.path().to_owned();
                if let Some(query) = url.query() {
                    path.push('?');
                    path.push_str(query);
                }
                rules.allowed(&path)
            }
            _ => false,
        }
    }
    pub(super) fn support_record(
        &mut self,
        url: Url,
        kind: SupportDocumentKind,
        status: SourceStatus,
    ) {
        if !self.charge(url.as_str().len().saturating_add(192)) {
            return;
        }
        self.support.push(SupportDocument {
            url: url.clone(),
            kind,
            status: status.clone(),
        });
        self.source_outcomes.push(SourceOutcome {
            source: if kind == SupportDocumentKind::Robots {
                DiscoverySource::Robots
            } else {
                DiscoverySource::Sitemap
            },
            source_url: Some(url),
            status,
        });
    }

    pub(super) async fn ensure_origin(&mut self, page: &Url) {
        let origin = page.origin().ascii_serialization();
        if self.robots.contains_key(&origin) || !self.active() {
            return;
        }
        self.robots.insert(origin.clone(), RobotsState::Blocked);
        let Ok(root) = Url::parse(&origin) else {
            return;
        };
        let Ok(robot_url) = root.join("/robots.txt") else {
            return;
        };
        let fetched = self.fetch_support(&robot_url).await;
        let mut sitemap_urls = Vec::new();
        let max_entries = usize::try_from(self.policy().map.limits.max_parser_entries.get())
            .unwrap_or(usize::MAX);
        match fetched {
            Ok(fetched) if fetched.status == 404 || fetched.status == 410 => {
                if let Ok(rules) = Robots::parse_bounded("", "YosoiMap", max_entries) {
                    self.robots
                        .insert(origin.clone(), RobotsState::Rules(rules));
                }
                self.support_record(
                    robot_url,
                    SupportDocumentKind::Robots,
                    SourceStatus::Completed,
                );
            }
            Ok(fetched) if (200..300).contains(&fetched.status) => {
                let rules = fetched
                    .document
                    .as_ref()
                    .map(Document::bytes)
                    .or(fetched.raw_response.as_deref())
                    .or({
                        if fetched.status == 204 {
                            Some(&[])
                        } else {
                            None
                        }
                    })
                    .and_then(|bytes| str::from_utf8(bytes).ok())
                    .and_then(|text| Robots::parse_bounded(text, "YosoiMap", max_entries).ok());
                if let Some(rules) = rules {
                    sitemap_urls.extend(rules.sitemaps().iter().cloned());
                    self.robots
                        .insert(origin.clone(), RobotsState::Rules(rules));
                    self.support_record(
                        robot_url,
                        SupportDocumentKind::Robots,
                        SourceStatus::Completed,
                    );
                } else {
                    self.support_record(
                        robot_url,
                        SupportDocumentKind::Robots,
                        SourceStatus::Failed(SourceFailure::Parse),
                    );
                }
            }
            Ok(fetched) => self.support_record(
                robot_url,
                SupportDocumentKind::Robots,
                SourceStatus::Failed(SourceFailure::HttpStatus(fetched.status)),
            ),
            Err(error) => self.support_record(
                robot_url,
                SupportDocumentKind::Robots,
                self.failure_status(error),
            ),
        }
        let mut candidates: Vec<_> = sitemap_urls.into_iter().map(|url| (url, false)).collect();
        candidates.extend([
            ("/sitemap.xml".to_owned(), true),
            ("/sitemap_index.xml".to_owned(), true),
        ]);
        self.sitemaps(&root, candidates).await;
    }

    pub(super) async fn sitemaps(&mut self, origin: &Url, urls: Vec<(String, bool)>) {
        let mut pending = VecDeque::new();
        // Source declarations are admitted one at a time, rather than copied
        // into a potentially oversized work queue. Nested index tasks are bounded.
        let mut declarations = urls.into_iter();
        let mut seen = BTreeSet::new();
        while self.active() {
            let Some((raw, depth, optional)) = pending.pop_front().or_else(|| {
                declarations
                    .next()
                    .map(|(url, optional)| (url, 0_u16, optional))
            }) else {
                break;
            };
            let Ok(url) = normalize(
                &raw,
                Some(origin),
                self.policy().map.limits.max_url_bytes.get(),
            ) else {
                self.omit();
                continue;
            };
            if url.origin() != origin.origin() {
                self.reject(Rejection::OriginScope);
                continue;
            }
            if !seen.insert(url.clone()) {
                continue;
            }
            if self.sitemap_count >= self.policy().map.limits.max_sitemaps.get() {
                self.stop(LimitReached::Sitemaps);
                break;
            }
            self.sitemap_count = self.sitemap_count.saturating_add(1);
            let fetched = match self.fetch_support(&url).await {
                Ok(fetched) => fetched,
                Err(error) => {
                    self.support_record(
                        url,
                        SupportDocumentKind::Sitemap,
                        self.failure_status(error),
                    );
                    continue;
                }
            };
            if fetched.status != 200 {
                self.support_record(
                    url,
                    SupportDocumentKind::Sitemap,
                    SourceStatus::Failed(SourceFailure::HttpStatus(fetched.status)),
                );
                continue;
            }
            let remaining = u64::from(self.policy().map.limits.max_total_response_bytes.get())
                .saturating_sub(self.summary.response_bytes);
            let already_charged = fetched
                .raw_response
                .as_ref()
                .map_or(0, |bytes| u64::try_from(bytes.len()).unwrap_or(u64::MAX));
            let parse_cap = remaining
                .saturating_add(already_charged)
                .min(u64::from(self.policy().map.limits.max_response_bytes.get()));
            let parsed = fetched
                .document
                .as_ref()
                .map(Document::bytes)
                .or(fetched.raw_response.as_deref())
                .ok_or(SourceFailure::IncompleteDocument)
                .and_then(|bytes| {
                    sources::parse_sitemap(
                        bytes,
                        usize::try_from(self.policy().map.limits.max_parser_entries.get())
                            .unwrap_or(usize::MAX),
                        usize::try_from(if fetched.raw_response.is_some() {
                            parse_cap
                        } else {
                            u64::from(self.policy().map.limits.max_response_bytes.get())
                        })
                        .unwrap_or(usize::MAX),
                    )
                    .map_err(|error| {
                        if matches!(error, sources::ParseError::ByteLimitExceeded { .. }) {
                            let additional = parse_cap.saturating_sub(already_charged);
                            self.summary.response_bytes =
                                self.summary.response_bytes.saturating_add(additional);
                            if let Some(trace) = self.request_trace.last_mut() {
                                trace.charged_response_bytes =
                                    trace.charged_response_bytes.saturating_add(additional);
                            }
                            self.stop(
                                if parse_cap
                                    < u64::from(self.policy().map.limits.max_response_bytes.get())
                                {
                                    LimitReached::TotalResponseBytes
                                } else {
                                    LimitReached::ResponseBytes
                                },
                            );
                        }
                        SourceFailure::Parse
                    })
                });
            let sitemap = match parsed {
                Ok(sitemap) => sitemap,
                Err(error) => {
                    let html = fetched
                        .document
                        .as_ref()
                        .is_some_and(|document| document.class() == DocumentClass::SourceHtml);
                    let status = if html && self.termination.is_none() {
                        if optional {
                            SourceStatus::Skipped(SourceSkipReason::NotSitemap)
                        } else {
                            SourceStatus::Failed(SourceFailure::UnexpectedSitemapContent)
                        }
                    } else {
                        self.failure_status(error)
                    };
                    self.support_record(url, SupportDocumentKind::Sitemap, status);
                    continue;
                }
            };
            if fetched.raw_response.is_some() {
                let additional = u64::try_from(sitemap.decoded_bytes)
                    .unwrap_or(u64::MAX)
                    .saturating_sub(already_charged);
                self.summary.response_bytes =
                    self.summary.response_bytes.saturating_add(additional);
                if let Some(trace) = self.request_trace.last_mut() {
                    trace.charged_response_bytes =
                        trace.charged_response_bytes.saturating_add(additional);
                }
            }
            let kind = if sitemap.kind == SitemapKind::Index {
                SupportDocumentKind::SitemapIndex
            } else {
                SupportDocumentKind::Sitemap
            };
            self.support_record(
                url.clone(),
                kind,
                if sitemap.truncated {
                    SourceStatus::Truncated
                } else {
                    SourceStatus::Completed
                },
            );
            if sitemap.truncated {
                self.stop(LimitReached::ParserEntries);
            }
            for location in sitemap.locations {
                if kind == SupportDocumentKind::SitemapIndex {
                    if depth >= self.policy().map.limits.max_sitemap_depth {
                        self.omit_reason(OmissionReason::SitemapDepth);
                        continue;
                    }
                    if pending.len().saturating_add(self.queue.len())
                        >= usize::try_from(self.policy().map.limits.max_pending.get())
                            .unwrap_or(usize::MAX)
                    {
                        self.stop(LimitReached::Pending);
                        break;
                    }
                    let location = match normalize(
                        &location,
                        Some(&fetched.url),
                        self.policy().map.limits.max_url_bytes.get(),
                    ) {
                        Ok(value) => value.to_string(),
                        Err(reason) => {
                            self.reject(reason);
                            continue;
                        }
                    };
                    if !self.charge(location.len().saturating_add(64)) {
                        break;
                    }
                    pending.push_back((location, depth.saturating_add(1), false));
                } else {
                    match normalize(
                        &location,
                        Some(&fetched.url),
                        self.policy().map.limits.max_url_bytes.get(),
                    ) {
                        Ok(page) => {
                            self.page(page, None, DiscoverySource::Sitemap, Some(&url));
                        }
                        Err(reason) => self.reject(reason),
                    }
                }
                if self.termination.is_some() {
                    break;
                }
            }
        }
        let unfinished = pending.len().saturating_add(declarations.count());
        if unfinished > 0 {
            self.summary.omitted = self
                .summary
                .omitted
                .saturating_add(u64::try_from(unfinished).unwrap_or(u64::MAX));
            self.source_outcomes.push(SourceOutcome {
                source: DiscoverySource::Sitemap,
                source_url: None,
                status: SourceStatus::NotStarted,
            });
        }
    }
}
