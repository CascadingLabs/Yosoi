//! Scoped redirect facts and alias inventory; acquired hops are never fetched twice.
use super::{
    DiscoverySource, Exploration, FetchResult, Purpose, RelationshipKind, Runner, SkipReason,
    SourceFailure,
};
use crate::internal::map::admission::normalize;
use crate::internal::policy::policy::{DirectHttpRedirectTargets, DirectHttpRedirects};
use std::collections::BTreeSet;
use url::Url;

impl Runner<'_> {
    pub(super) async fn fetch(
        &mut self,
        start: &Url,
        purpose: Purpose,
    ) -> Result<FetchResult, SourceFailure> {
        let mut aliases = Vec::new();
        let result = self.follow_redirects(start, purpose, &mut aliases).await;
        match result {
            Ok(FetchResult::Acquired(mut fetched)) => {
                fetched.aliases = aliases;
                Ok(FetchResult::Acquired(fetched))
            }
            Ok(FetchResult::Reused {
                url, exploration, ..
            }) => Ok(FetchResult::Reused {
                url,
                exploration,
                aliases,
            }),
            Err(error) => {
                if self.termination.is_none() && matches!(purpose, Purpose::Page { .. }) {
                    self.mark_aliases(&aliases, &Exploration::Failed(error.clone()));
                }
                Err(error)
            }
        }
    }

    async fn follow_redirects(
        &mut self,
        start: &Url,
        purpose: Purpose,
        aliases: &mut Vec<Url>,
    ) -> Result<FetchResult, SourceFailure> {
        let mut current = start.clone();
        let mut seen = BTreeSet::new();
        let mut hops = 0_u32;
        loop {
            if !self.active() {
                return Err(SourceFailure::Transport);
            }
            if matches!(purpose, Purpose::Page { .. }) {
                self.scope
                    .admit(&current)
                    .map_err(|_| SourceFailure::RedirectRejected)?;
            }
            if !seen.insert(current.clone()) {
                return Err(SourceFailure::RedirectLimit);
            }
            aliases.push(current.clone());
            if matches!(purpose, Purpose::Page { .. }) {
                Box::pin(self.ensure_origin(&current)).await;
                if !self.allowed(&current) {
                    return Err(SourceFailure::RedirectRejected);
                }
                if current != *start
                    && !self.redirects.contains_key(&current)
                    && let Some(exploration) = self.completed_page_state(&current)
                {
                    return Ok(FetchResult::Reused {
                        url: current,
                        exploration,
                        aliases: Vec::new(),
                    });
                }
            }
            let cached = if matches!(purpose, Purpose::Page { .. }) {
                self.redirects.get(&current).cloned()
            } else {
                None
            };
            let reused_redirect = cached.is_some();
            let next = if let Some(next) = cached {
                next
            } else {
                let fetched = self.once(&current).await?;
                if !matches!(fetched.status, 301 | 302 | 303 | 307 | 308)
                    || self.policy().request.direct_http_redirects == DirectHttpRedirects::Disabled
                {
                    return Ok(FetchResult::Acquired(Box::new(fetched)));
                }
                normalize(
                    fetched
                        .location
                        .as_deref()
                        .ok_or(SourceFailure::RedirectRejected)?,
                    Some(&current),
                    self.policy().map.limits.max_url_bytes.get(),
                )
                .map_err(|_| SourceFailure::RedirectRejected)?
            };
            let (maximum, targets) = match self.policy().request.direct_http_redirects {
                DirectHttpRedirects::Disabled => return Err(SourceFailure::RedirectRejected),
                DirectHttpRedirects::Follow { max_hops, targets } => (max_hops.get(), targets),
            };
            if hops >= maximum {
                return Err(SourceFailure::RedirectLimit);
            }
            if targets == DirectHttpRedirectTargets::SameOrigin && next.origin() != current.origin()
            {
                return Err(SourceFailure::RedirectRejected);
            }
            match purpose {
                Purpose::Page { depth } => {
                    self.scope
                        .admit(&next)
                        .map_err(|_| SourceFailure::RedirectRejected)?;
                    self.edge(&current, &next, RelationshipKind::Redirect);
                    if !reused_redirect {
                        if !self.charge(
                            current
                                .as_str()
                                .len()
                                .saturating_add(next.as_str().len())
                                .saturating_add(96),
                        ) {
                            return Err(SourceFailure::Transport);
                        }
                        self.redirects.insert(current.clone(), next.clone());
                    }
                    if !self.page(
                        next.clone(),
                        None,
                        DiscoverySource::Redirect,
                        Some(&current),
                    ) {
                        return Err(SourceFailure::Transport);
                    }
                    if let Some(page) = self.pages.get_mut(&next) {
                        if page
                            .minimum_link_depth
                            .is_none_or(|previous| depth < previous)
                        {
                            page.minimum_link_depth = Some(depth);
                        }
                        if matches!(
                            page.exploration,
                            Exploration::Inventoried | Exploration::Skipped(SkipReason::Depth)
                        ) {
                            page.exploration = Exploration::Pending;
                        }
                    }
                }
                Purpose::Support => {
                    if next.origin() != start.origin() {
                        return Err(SourceFailure::RedirectRejected);
                    }
                }
            }
            hops = hops.saturating_add(1);
            current = next;
        }
    }

    pub(super) fn mark_aliases(&mut self, aliases: &[Url], exploration: &Exploration) {
        for url in aliases {
            if let Some(page) = self.pages.get_mut(url) {
                page.exploration = exploration.clone();
            }
        }
    }
}
