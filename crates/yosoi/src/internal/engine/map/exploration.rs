use std::collections::{BTreeSet, HashSet};

use crate::internal::documents::{
    DocumentClass, Finding, LocateOutcome, Plan, ProjectedValue, css, output,
};
use crate::internal::map::admission::normalize;
use crate::internal::policy::policy::DiscoveryDocuments;
use url::Url;

use super::{
    DiscoverySource, Exploration, FetchResult, HostVerification, LimitReached, MapTermination,
    OmissionReason, PageTask, Purpose, RelationshipKind, RetainedCapture, Runner, SkipReason,
    SourceFailure, SourceOutcome, SourceStatus,
};
use crate::internal::engine::Document;

impl Runner<'_> {
    pub(super) async fn explore(&mut self, task: PageTask) {
        if task.probe && self.reuse_completed_probe(&task.url, task.depth) {
            return;
        }
        let url = task.url;
        if !self.redirects.contains_key(&url)
            && let Some(links) = self.cache.get(&url).cloned()
        {
            self.expand(&url, task.depth, links.urls, links.source);
            return;
        }
        if !task.probe
            && !self.redirects.contains_key(&url)
            && self
                .pages
                .get(&url)
                .is_some_and(|page| page.exploration != Exploration::Pending)
        {
            return;
        }
        self.ensure_origin(&url).await;
        if !self.active() {
            return;
        }
        if !self.allowed(&url) {
            self.probes.remove(&url);
            self.omit_reason(OmissionReason::Robots);
            if let Some(page) = self.pages.get_mut(&url) {
                page.exploration = Exploration::Skipped(SkipReason::Robots);
            }
            return;
        }
        let fetched = match self.fetch(&url, Purpose::Page { depth: task.depth }).await {
            Ok(FetchResult::Acquired(fetched)) => *fetched,
            Ok(FetchResult::Reused {
                url: final_url,
                exploration,
                aliases,
            }) => {
                self.probes.remove(&url);
                if task.probe {
                    self.page(
                        url.clone(),
                        Some(task.depth),
                        DiscoverySource::PassiveCertificate,
                        None,
                    );
                }
                self.page(
                    final_url.clone(),
                    Some(task.depth),
                    DiscoverySource::Redirect,
                    Some(&url),
                );
                self.mark_aliases(&aliases, &exploration);
                for page_url in [&url, &final_url] {
                    if let Some(page) = self.pages.get_mut(page_url) {
                        page.exploration = exploration.clone();
                    }
                }
                if let Some(links) = self.cache.get(&final_url).cloned() {
                    self.expand(&final_url, task.depth, links.urls, links.source);
                }
                return;
            }
            Err(error) => {
                if self.termination.is_none() {
                    self.probes.remove(&url);
                    if let Some(page) = self.pages.get_mut(&url) {
                        page.exploration = Exploration::Failed(error.clone());
                    }
                    self.source_outcomes.push(SourceOutcome {
                        source: DiscoverySource::HtmlLink,
                        source_url: Some(url),
                        status: SourceStatus::Failed(error),
                    });
                }
                return;
            }
        };
        self.probes.remove(&url);
        if task.probe {
            self.page(
                url.clone(),
                Some(task.depth),
                DiscoverySource::PassiveCertificate,
                None,
            );
        }
        if fetched.url != url {
            self.page(
                fetched.url.clone(),
                Some(task.depth),
                DiscoverySource::Redirect,
                Some(&url),
            );
        }
        if let Some(host) = fetched
            .url
            .host_str()
            .and_then(|host| self.hosts.get_mut(host))
        {
            host.verification = HostVerification::HttpObserved;
        }
        let state = if !(200..300).contains(&fetched.status) {
            Exploration::Failed(SourceFailure::HttpStatus(fetched.status))
        } else if fetched.document.as_ref().is_none_or(|doc| {
            !matches!(
                doc.class(),
                DocumentClass::SourceHtml | DocumentClass::SourceXml
            )
        }) {
            Exploration::Skipped(SkipReason::NonHtml)
        } else {
            Exploration::Inspected
        };
        if let Some(page) = self.pages.get_mut(&url) {
            page.exploration = state.clone();
        }
        if let Some(page) = self.pages.get_mut(&fetched.url) {
            page.exploration = state.clone();
        }
        if state == Exploration::Inspected
            && let Some(document) = &fetched.document
        {
            self.discover_document(document, &fetched.url, &url, task.depth);
        }
        let final_state = self
            .pages
            .get(&fetched.url)
            .map_or(state, |page| page.exploration.clone());
        self.mark_aliases(&fetched.aliases, &final_state);
        if self.policy().map.documents == DiscoveryDocuments::RetainWithinBudget {
            let bytes = fetched
                .document
                .as_ref()
                .map_or(0, Document::byte_len)
                .saturating_add(
                    fetched
                        .raw_response
                        .as_ref()
                        .map_or(0, |bytes| u64::try_from(bytes.len()).unwrap_or(u64::MAX)),
                );
            let next = self.summary.retained_document_bytes.saturating_add(bytes);
            if next <= u64::from(self.policy().map.limits.max_retained_document_bytes.get())
                && self.charge(128)
            {
                self.summary.retained_document_bytes = next;
                self.captures.push(RetainedCapture {
                    url: fetched.url,
                    response: fetched.response,
                });
            } else {
                self.omit();
                self.source_outcomes.push(SourceOutcome {
                    source: DiscoverySource::HtmlLink,
                    source_url: Some(fetched.url),
                    status: SourceStatus::Failed(SourceFailure::RetentionLimit),
                });
            }
        }
    }

    pub(super) fn links(
        &mut self,
        document: &Document,
        url: &Url,
    ) -> Result<Vec<Url>, SourceFailure> {
        let plan = Plan::new([
            output(
                "canonical",
                css("link[rel][href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("href")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "link_rel",
                css("link[rel][href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("rel")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "base",
                css("base[href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("href")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "links",
                css("a[href],area[href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("href")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
        ])
        .map_err(|_| SourceFailure::Parse)?;
        let result = match document.bind(self.policy()).locate(&plan) {
            LocateOutcome::Matched { result } => result,
            LocateOutcome::NoMatch { .. } => return Ok(Vec::new()),
            _ => return Err(SourceFailure::Parse),
        };
        let mut base = url.clone();
        for finding in result.findings() {
            if finding.output_id().as_str() == "base"
                && let ProjectedValue::Attribute { value, .. } = finding.value()
                && let Ok(value) = normalize(
                    value,
                    Some(url),
                    self.policy().map.limits.max_url_bytes.get(),
                )
            {
                base = value;
                break;
            }
        }
        let canonical_nodes: HashSet<_> = result
            .findings()
            .iter()
            .filter(|finding| finding.output_id().as_str() == "link_rel")
            .filter(|finding| {
                matches!(finding.value(), ProjectedValue::Attribute { value, .. }
                    if value.split_ascii_whitespace().any(|token| token.eq_ignore_ascii_case("canonical")))
            })
            .map(Finding::coordinate)
            .collect();
        for finding in result
            .findings()
            .iter()
            .filter(|finding| finding.output_id().as_str() == "canonical")
            .filter(|finding| canonical_nodes.contains(finding.coordinate()))
        {
            if let ProjectedValue::Attribute { value, .. } = finding.value() {
                match normalize(
                    value,
                    Some(&base),
                    self.policy().map.limits.max_url_bytes.get(),
                ) {
                    Ok(target) => self.edge(url, &target, RelationshipKind::Canonical),
                    Err(reason) => self.reject(reason),
                }
            }
        }
        let mut links = BTreeSet::new();
        for finding in result
            .findings()
            .iter()
            .filter(|finding| finding.output_id().as_str() == "links")
        {
            if links.len()
                >= usize::try_from(self.policy().map.limits.max_parser_entries.get())
                    .unwrap_or(usize::MAX)
            {
                self.stop(LimitReached::ParserEntries);
                break;
            }
            if let ProjectedValue::Attribute { value, .. } = finding.value() {
                match normalize(
                    value,
                    Some(&base),
                    self.policy().map.limits.max_url_bytes.get(),
                ) {
                    Ok(url) => match self.scope.admit(&url) {
                        Ok(()) => {
                            links.insert(url);
                        }
                        Err(reason) => self.reject(reason),
                    },
                    Err(reason) => self.reject(reason),
                }
            }
        }
        Ok(links.into_iter().collect())
    }
    pub(super) fn expand(
        &mut self,
        from: &Url,
        depth: u16,
        links: Vec<Url>,
        source: DiscoverySource,
    ) {
        for url in links {
            let Some(next) = depth.checked_add(1) else {
                self.omit();
                continue;
            };
            self.page(url.clone(), Some(next), source, Some(from));
            self.edge(from, &url, RelationshipKind::Link);
            if self.termination.is_some()
                && self.termination != Some(MapTermination::Limit(LimitReached::Pending))
            {
                break;
            }
        }
    }
}
