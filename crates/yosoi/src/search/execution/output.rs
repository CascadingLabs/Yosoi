use crate::search::{
    FeatureCoverage, ProviderOutcome, ProviderResult, SearchCoverage, SearchFailure, SearchFeature,
    SearchHit, SearchIssue, SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
};

pub(super) fn cap_global_output(
    providers: &mut [ProviderResult],
    total_result_limit: usize,
    total_output_limit: usize,
) {
    let mut retained_results = 0_usize;
    let mut retained_bytes = 0_usize;
    for provider in providers {
        let ProviderOutcome::Results(page) = &provider.outcome else {
            continue;
        };

        let page_fits_results =
            page.hits().len() <= total_result_limit.saturating_sub(retained_results);
        let page_bytes = page.retained_string_bytes();
        let page_fits_bytes = page_bytes
            .and_then(|bytes| retained_bytes.checked_add(bytes))
            .is_some_and(|bytes| bytes <= total_output_limit);
        if page_fits_results && page_fits_bytes {
            retained_results = retained_results
                .checked_add(page.hits().len())
                .unwrap_or(total_result_limit);
            retained_bytes = page_bytes
                .and_then(|bytes| retained_bytes.checked_add(bytes))
                .unwrap_or(total_output_limit);
            continue;
        }

        let mut hits = Vec::with_capacity(page.hits().len());
        let mut web_limited = false;
        let mut feature_limited = false;
        for hit in page.hits() {
            if retained_results >= total_result_limit {
                web_limited = true;
                break;
            }
            let Some(hit_bytes) = hit_retained_string_bytes(hit) else {
                web_limited = true;
                break;
            };
            let Some(next_bytes) = retained_bytes.checked_add(hit_bytes) else {
                web_limited = true;
                break;
            };
            if next_bytes > total_output_limit {
                web_limited = true;
                break;
            }
            let Some(next_results) = retained_results.checked_add(1) else {
                web_limited = true;
                break;
            };
            retained_results = next_results;
            retained_bytes = next_bytes;
            hits.push(hit.clone());
        }

        let mut features = Vec::with_capacity(page.features().len());
        for feature in page.features() {
            let Some(feature_bytes) = feature_retained_string_bytes(feature) else {
                feature_limited = true;
                break;
            };
            let Some(next_bytes) = retained_bytes.checked_add(feature_bytes) else {
                feature_limited = true;
                break;
            };
            if next_bytes > total_output_limit {
                feature_limited = true;
                break;
            }
            retained_bytes = next_bytes;
            features.push(feature.clone());
        }

        let mut issues = page.issues().to_vec();
        let limited = web_limited || feature_limited;
        if limited
            && !issues
                .iter()
                .any(|issue| issue.kind == SearchIssueKind::OutputLimit)
        {
            issues.push(SearchIssue {
                placement_index: None,
                kind: SearchIssueKind::OutputLimit,
            });
        }
        let coverage = SearchCoverage::new(
            if web_limited {
                WebCoverage::Partial
            } else {
                page.coverage().web()
            },
            if feature_limited {
                FeatureCoverage::Partial
            } else {
                page.coverage().rich_features()
            },
        );
        if hits.is_empty() && features.is_empty() && limited {
            provider.outcome = ProviderOutcome::Failed(SearchFailure::BudgetExhausted);
            continue;
        }
        provider.outcome =
            ProviderOutcome::Results(SearchPage::new(hits, features, coverage, issues));
    }
}

fn hit_retained_string_bytes(hit: &SearchHit) -> Option<usize> {
    let metadata = hit.metadata();
    let mut bytes = hit.url().as_str().len();
    for value in [
        metadata.title.as_deref(),
        metadata.snippet.as_deref(),
        metadata.display_url.as_deref(),
        metadata.publisher.as_deref(),
        metadata.published_at.as_deref(),
        metadata.thumbnail_url.as_ref().map(SearchResultUrl::as_str),
    ]
    .into_iter()
    .flatten()
    {
        bytes = bytes.checked_add(value.len())?;
    }
    Some(bytes)
}

fn feature_retained_string_bytes(feature: &SearchFeature) -> Option<usize> {
    match feature {
        SearchFeature::Sponsored {
            destination, label, ..
        } => destination
            .as_str()
            .len()
            .checked_add(label.as_deref().map_or(0, str::len)),
        SearchFeature::Answer {
            text, citations, ..
        } => citations.iter().try_fold(text.len(), |total, url| {
            total.checked_add(url.as_str().len())
        }),
        SearchFeature::ImageGallery { images, .. } => {
            images.iter().try_fold(0_usize, |total, image| {
                total
                    .checked_add(image.image_url.as_str().len())
                    .and_then(|value| value.checked_add(image.source_page_url.as_str().len()))
            })
        }
        SearchFeature::LocalPack {
            places, map_url, ..
        } => places.iter().try_fold(
            map_url.as_ref().map_or(0, |url| url.as_str().len()),
            |total, place| {
                total
                    .checked_add(place.name.len())
                    .and_then(|value| value.checked_add(place.place_url.as_str().len()))
            },
        ),
    }
}
