//! Link discovery and cache expansion for acquired page documents.
use super::{
    CachedLinks, DiscoverySource, Document, Exploration, Runner, SourceOutcome, SourceStatus,
};
use crate::internal::documents::DocumentClass;
use tokio::time::Instant;
use url::Url;
impl Runner<'_> {
    pub(super) fn discover_document(
        &mut self,
        document: &Document,
        final_url: &Url,
        original: &Url,
        depth: u16,
    ) {
        let source = if document.class() == DocumentClass::SourceXml {
            DiscoverySource::XmlLink
        } else {
            DiscoverySource::HtmlLink
        };
        let links = if source == DiscoverySource::XmlLink {
            self.xml_links(document, final_url)
        } else {
            self.links(document, final_url)
        };
        if self.cancellation.is_cancelled() || Instant::now() >= self.deadline {
            self.active();
            for pending in [original, final_url] {
                if let Some(page) = self.pages.get_mut(pending) {
                    page.exploration = Exploration::Pending;
                }
            }
            self.source_outcomes.push(SourceOutcome {
                source,
                source_url: Some(final_url.clone()),
                status: SourceStatus::Truncated,
            });
            return;
        }
        match links {
            Ok(links) => {
                let bytes = links.iter().fold(0_usize, |total, url| {
                    total.saturating_add(url.as_str().len()).saturating_add(64)
                });
                if self.charge(bytes) {
                    self.cache.insert(
                        original.clone(),
                        CachedLinks {
                            source,
                            urls: links.clone(),
                        },
                    );
                    if final_url != original && self.charge(bytes) {
                        self.cache.insert(
                            final_url.clone(),
                            CachedLinks {
                                source,
                                urls: links.clone(),
                            },
                        );
                    }
                    self.expand(final_url, depth, links, source);
                }
                if source == DiscoverySource::XmlLink {
                    self.source_outcomes.push(SourceOutcome {
                        source,
                        source_url: Some(final_url.clone()),
                        status: if self.termination.is_some() {
                            SourceStatus::Truncated
                        } else {
                            SourceStatus::Completed
                        },
                    });
                }
            }
            Err(error) => {
                for failed in [original, final_url] {
                    if let Some(page) = self.pages.get_mut(failed) {
                        page.exploration = Exploration::Failed(error.clone());
                    }
                }
                self.source_outcomes.push(SourceOutcome {
                    source,
                    source_url: Some(final_url.clone()),
                    status: self.failure_status(error),
                });
            }
        }
    }
}
