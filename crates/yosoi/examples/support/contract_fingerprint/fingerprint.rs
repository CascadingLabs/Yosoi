//! Exact sparse features and hierarchical comparison, deliberately without sketches.
use super::{
    Result, fail,
    structure::{Dom, selected_nodes},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use yosoi::{documents::Document, locators::LocateOutcome};

pub(super) const PROFILE: &str = "selected-dom-paths-v1-depth3";
pub(super) const THRESHOLD: f64 = 0.85;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct Fingerprint {
    pub profile: String,
    pub schema_checksum: String,
    pub components: BTreeMap<String, BTreeSet<String>>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub(super) struct Comparison {
    pub similarity: f64,
    pub coverage: f64,
    pub components: BTreeMap<String, f64>,
    pub eligible: bool,
}

pub(super) fn checksum<T: Serialize>(value: &T) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(value)?)))
}

pub(super) fn observe(
    document: &Document,
    located: &LocateOutcome,
    schema_checksum: &str,
) -> Result<Fingerprint> {
    let LocateOutcome::Matched { result } = located else {
        return fail("no matched contract evidence");
    };
    if result.document_id() != document.id() {
        return fail("evidence belongs to a different Document");
    }
    let dom = Dom::read(document)?;
    let selected = selected_nodes(located, dom.document_epoch)?;
    let root = selected
        .get("root")
        .copied()
        .ok_or_else(|| super::error("exactly one contract root required"))?;
    let mut components = BTreeMap::new();
    for (field, node) in selected {
        components.insert(field, dom.signature(node, root)?);
    }
    Ok(Fingerprint {
        profile: PROFILE.into(),
        schema_checksum: schema_checksum.into(),
        components,
    })
}

// Weighted Jaccard over binary structural features. Relation features have weight 2,
// descendant-path features weight 1. Separate hierarchy weights give root weight 2
// and each required field weight 1, preventing feature-rich roots from dominating.
fn weight(feature: &str) -> f64 {
    if feature.starts_with("relation:") {
        2.0
    } else {
        1.0
    }
}
fn jaccard(a: &BTreeSet<String>, b: &BTreeSet<String>) -> f64 {
    let union: f64 = a.union(b).map(|f| weight(f)).sum();
    if union == 0.0 {
        return 0.0;
    }
    a.intersection(b).map(|f| weight(f)).sum::<f64>() / union
}

#[expect(
    clippy::float_cmp,
    clippy::suboptimal_flops,
    reason = "Preserve frozen v1 arithmetic and exact coverage over small integer weights."
)]
pub(super) fn compare(a: &Fingerprint, b: &Fingerprint) -> Result<Comparison> {
    if a.profile != PROFILE || b.profile != PROFILE || a.schema_checksum != b.schema_checksum {
        return fail("incompatible fingerprint profile or contract schema");
    }
    if [a, b].iter().any(|fingerprint| {
        fingerprint
            .components
            .get("root")
            .is_none_or(BTreeSet::is_empty)
    }) {
        return fail("fingerprint requires nonempty contract-root evidence");
    }
    let keys: BTreeSet<&String> = a.components.keys().chain(b.components.keys()).collect();
    if keys.is_empty() {
        return fail("empty fingerprint has no comparison evidence");
    }
    let mut components = BTreeMap::new();
    let mut total = 0.0;
    let mut matched = 0.0;
    let mut score = 0.0;
    for key in keys {
        let hierarchy_weight = if key == "root" { 2.0 } else { 1.0 };
        total += hierarchy_weight;
        let similarity = match (a.components.get(key), b.components.get(key)) {
            (Some(x), Some(y)) if !x.is_empty() && !y.is_empty() => {
                matched += hierarchy_weight;
                jaccard(x, y)
            }
            _ => 0.0,
        };
        score += hierarchy_weight * similarity;
        components.insert(key.clone(), similarity);
    }
    let similarity = score / total;
    let coverage = matched / total;
    let eligible = coverage == 1.0
        && similarity >= THRESHOLD
        && components.values().all(|score| *score >= THRESHOLD);
    Ok(Comparison {
        similarity,
        coverage,
        components,
        eligible,
    })
}
