//! Bounded XML feed link discovery through the shared document locator.

use std::collections::{BTreeMap, BTreeSet};

use url::Url;
use yosoi_documents::{
    DocumentClass, Finding, LocateOutcome, NativeCoordinate, Plan, ProjectedValue, css, output,
};
use yosoi_map::admission::{Rejection, normalize};

use super::{Document, LimitReached, Runner, SourceFailure};

impl Runner<'_> {
    /// Extracts feed links with the shared bounded XML locator.
    ///
    /// Relative references are resolved with `Url::join`, including inherited
    /// `xml:base` values. URI references outside the URL parser's supported
    /// syntax are omitted through the ordinary admission rejection path.
    pub(super) fn xml_links(
        &mut self,
        document: &Document,
        url: &Url,
    ) -> Result<Vec<Url>, SourceFailure> {
        if document.class() != DocumentClass::SourceXml {
            return Err(SourceFailure::Parse);
        }

        let plan = Plan::new([
            output(
                "link_text",
                css("*|link").map_err(|_| SourceFailure::Parse)?.text(),
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "link_href",
                css("*[href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("href")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "xml_base",
                css("*[xml|base]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("xml:base")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
        ])
        .map_err(|_| SourceFailure::Parse)?;

        // The XML prefix has its fixed namespace URI in the XML data model;
        // QuerySpec rejects attempts to bind that reserved prefix explicitly.
        let result = match document.bind(self.policy()).locate(&plan) {
            LocateOutcome::Matched { result } => result,
            LocateOutcome::NoMatch { .. } => return Ok(Vec::new()),
            _ => return Err(SourceFailure::Parse),
        };

        let mut raw_bases = BTreeMap::<Vec<u32>, String>::new();
        for finding in result.findings() {
            if finding.output_id().as_str() != "xml_base" {
                continue;
            }
            let ProjectedValue::Attribute { value, .. } = finding.value() else {
                return Err(SourceFailure::Parse);
            };
            let path = source_path(finding)?;
            raw_bases.insert(path.to_vec(), value.clone());
        }
        let effective_bases = effective_xml_bases(url, raw_bases);

        let maximum_entries = u64::from(self.policy().map.limits.max_parser_entries.get());
        let mut links = BTreeSet::new();
        for finding in result.findings() {
            let output_id = finding.output_id().as_str();
            if !matches!(output_id, "link_text" | "link_href") {
                continue;
            }
            let raw = match finding.value() {
                ProjectedValue::Text(value) | ProjectedValue::Attribute { value, .. } => {
                    value.trim()
                }
                _ => return Err(SourceFailure::Parse),
            };
            if raw.is_empty() {
                continue;
            }

            let path = source_path(finding)?;
            let base = match base_for_path(url, path, &effective_bases) {
                Ok(base) => base,
                Err(reason) => {
                    self.reject(reason);
                    continue;
                }
            };
            match normalize(
                raw,
                Some(base),
                self.policy().map.limits.max_url_bytes.get(),
            ) {
                Ok(target) => match self.scope.admit(&target) {
                    Ok(()) => {
                        if links.contains(&target) {
                            continue;
                        }
                        let observed_entries =
                            u64::try_from(links.len()).map_err(|_| SourceFailure::Parse)?;
                        if observed_entries >= maximum_entries {
                            self.stop(LimitReached::ParserEntries);
                            break;
                        }
                        links.insert(target);
                    }
                    Err(reason) => self.reject(reason),
                },
                Err(reason) => self.reject(reason),
            }
        }

        Ok(links.into_iter().collect())
    }
}

fn source_path(finding: &Finding) -> Result<&[u32], SourceFailure> {
    match finding.coordinate() {
        NativeCoordinate::SourceTree(coordinate) => Ok(coordinate.child_path()),
        _ => Err(SourceFailure::Parse),
    }
}

fn effective_xml_bases(
    response_url: &Url,
    raw_bases: BTreeMap<Vec<u32>, String>,
) -> BTreeMap<Vec<u32>, Result<Url, Rejection>> {
    let mut effective_bases: BTreeMap<Vec<u32>, Result<Url, Rejection>> = BTreeMap::new();
    for (path, reference) in raw_bases {
        let mut parent_base = response_url.clone();
        let mut invalid_ancestor = false;
        for prefix_length in (1..path.len()).rev() {
            let Some(prefix) = path.get(..prefix_length) else {
                continue;
            };
            if let Some(ancestor) = effective_bases.get(prefix) {
                match ancestor {
                    Ok(base) => parent_base = base.clone(),
                    Err(_) => invalid_ancestor = true,
                }
                break;
            }
        }

        let base = if invalid_ancestor {
            Err(Rejection::InvalidUrl)
        } else {
            parent_base
                .join(&reference)
                .map_err(|_| Rejection::InvalidUrl)
        };
        effective_bases.insert(path, base);
    }
    effective_bases
}

fn base_for_path<'base>(
    response_url: &'base Url,
    path: &[u32],
    effective_bases: &'base BTreeMap<Vec<u32>, Result<Url, Rejection>>,
) -> Result<&'base Url, Rejection> {
    for prefix_length in (1..=path.len()).rev() {
        let Some(prefix) = path.get(..prefix_length) else {
            continue;
        };
        if let Some(base) = effective_bases.get(prefix) {
            return base.as_ref().map_err(|reason| *reason);
        }
    }
    Ok(response_url)
}
