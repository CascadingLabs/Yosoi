use super::super::{
    controls::{Mutation, mutate},
    structure::Dom,
};
use super::*;

fn seed() -> Result<Document> {
    let bytes = include_bytes!(
        "../../../../../experiments/contract-fingerprints/fixtures/obj-002.dom.json"
    );
    let dom: Dom = serde_json::from_slice(bytes)?;
    dom.document("obj-002")
}

fn fixture() -> Result<(Document, Frozen, Expected)> {
    let document = seed()?;
    let recipe = Recipe::default();
    let plan = recipe.plan()?;
    let schema = Product::schema()?.clone();
    let located = recipe.locate(&document, &plan)?;
    let fingerprint = fingerprint::observe(&document, &located, &checksum(&schema)?)?;
    let reference = Reference {
        source: "document:v1:3ec6ae80-08f5-4377-a60d-80d2f96a2ae6".parse()?,
        fingerprint_checksum: checksum(&fingerprint)?,
        fingerprint,
    };
    let frozen = Frozen {
        version: 1,
        schema,
        recipe,
        plan_checksum: checksum(&plan)?,
        plan,
        references: vec![reference],
    };
    let expected = Expected {
        id: "obj-002".into(),
        name: "Loop ceramic mug".into(),
        price_cents: 2400,
        color: "Chalk".into(),
        material: "Glazed stoneware".into(),
        stock: Stock::Available(8),
    };
    Ok((document, frozen, expected))
}

#[test]
#[expect(
    clippy::float_cmp,
    reason = "Self-comparison of identical exact features must equal one."
)]
fn selected_evidence_extracts_and_matches_the_mug() -> Result {
    let (document, frozen, expected) = fixture()?;
    let case = evaluate_case(&frozen, &document, &expected)?;
    if !case.oracle_passed || case.comparisons.iter().any(|c| c.similarity != 1.0) {
        return fail("seed did not match itself");
    }
    Ok(())
}

#[test]
fn controls_expose_wrong_values_and_scope_cardinality_failures() -> Result {
    let (document, frozen, expected) = fixture()?;
    if run_controls(&frozen, &document, &expected)?.len() != 6 {
        return fail("control coverage missing");
    }
    Ok(())
}

#[test]
fn renamed_css_class_values_do_not_change_structure() -> Result {
    let (document, frozen, _) = fixture()?;
    let dom = Dom::read(&document)?;
    let located = frozen.recipe.locate(&document, &frozen.plan)?;
    let selected = super::super::structure::selected_nodes(&located, dom.document_epoch)?;
    let root = *selected
        .get("root")
        .ok_or_else(|| super::super::error("no root"))?;
    let field = *selected
        .get("name")
        .ok_or_else(|| super::super::error("no field"))?;
    let before = dom.signature(field, root)?;
    let mut changed = dom;
    for node in &mut changed.nodes {
        for attr in node
            .attributes
            .iter_mut()
            .flatten()
            .filter(|a| a.name == "class")
        {
            attr.value = "different framework classes".into();
        }
        if node.kind == "text" {
            node.value = Some("different content".into());
        }
    }
    if before != changed.signature(field, root)? {
        return fail("content leaked into structural features");
    }
    Ok(())
}

#[test]
fn profiles_and_contract_schemas_are_explicit_compatibility_boundaries() -> Result {
    let (_, frozen, _) = fixture()?;
    let original = &frozen
        .references
        .first()
        .ok_or_else(|| super::super::error("no reference"))?
        .fingerprint;
    let mut changed = original.clone();
    changed.profile = "future-version".into();
    if fingerprint::compare(original, &changed).is_ok() {
        return fail("profile mismatch accepted");
    }
    changed = original.clone();
    changed.schema_checksum = "different schema".into();
    if fingerprint::compare(original, &changed).is_ok() {
        return fail("schema mismatch accepted");
    }
    Ok(())
}

#[test]
fn root_relative_features_reject_outside_nodes_and_wrong_epochs() -> Result {
    let (document, frozen, _) = fixture()?;
    let dom = Dom::read(&document)?;
    let located = frozen.recipe.locate(&document, &frozen.plan)?;
    let selected = super::super::structure::selected_nodes(&located, dom.document_epoch)?;
    let field = *selected
        .get("name")
        .ok_or_else(|| super::super::error("no name"))?;
    if dom.signature(dom.root, field).is_ok() {
        return fail("outside relation accepted");
    }
    if super::super::structure::selected_nodes(&located, dom.document_epoch.saturating_add(1))
        .is_ok()
    {
        return fail("wrong epoch accepted");
    }
    Ok(())
}

#[test]
fn missing_required_component_reduces_coverage() -> Result {
    let (document, frozen, _) = fixture()?;
    let changed = mutate(&document, &frozen.recipe, Mutation::MissingPrice)?;
    let located = frozen.recipe.locate(&changed, &frozen.plan)?;
    if recipe::extract(&located).is_ok() {
        return fail("Contract accepted missing price");
    }
    let fingerprint = fingerprint::observe(&changed, &located, &checksum(&frozen.schema)?)?;
    let comparison = fingerprint::compare(
        &frozen
            .references
            .first()
            .ok_or_else(|| super::super::error("no reference"))?
            .fingerprint,
        &fingerprint,
    )?;
    if comparison.coverage >= 1.0 || comparison.eligible {
        return fail("missing field retained full coverage");
    }
    Ok(())
}

#[test]
fn runtime_checks_distinguish_unavailable_zero_and_invalid_prices() -> Result {
    let (document, frozen, _) = fixture()?;
    let located = frozen.recipe.locate(&document, &frozen.plan)?;
    let mut product = recipe::extract(&located)?;
    product.stock = "Currently unavailable.".into();
    if recipe::runtime_validate(&product, "obj-002")? != Stock::Unavailable {
        return fail("unavailability lost");
    }
    product.stock = "0 in stock and ready to find a home.".into();
    if recipe::runtime_validate(&product, "obj-002").is_ok() {
        return fail("zero available accepted");
    }
    for invalid in [
        "$1.2",
        "$-1.00",
        "1.00",
        "$18446744073709551615.99",
        "$1.001",
    ] {
        if recipe::price_cents(invalid).is_ok() {
            return fail("invalid or overflowing price accepted");
        }
    }
    Ok(())
}

#[tokio::test]
async fn checked_in_archive_replays_baseline_and_seed_sensitivity() -> Result {
    replay(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../experiments/contract-fingerprints/fixtures/evidence")
            .as_path(),
    )
    .await
}

#[test]
fn snapshot_local_ids_cannot_substitute_a_different_document() -> Result {
    let (document, frozen, _) = fixture()?;
    let located = frozen.recipe.locate(&document, &frozen.plan)?;
    let other = Dom::read(&document)?.document("other-product")?;
    if fingerprint::observe(&other, &located, &checksum(&frozen.schema)?).is_ok() {
        return fail("cross-document evidence accepted");
    }
    Ok(())
}

#[test]
fn fingerprints_without_a_root_cannot_match() -> Result {
    let (_, frozen, _) = fixture()?;
    let mut fingerprint = frozen.references[0].fingerprint.clone();
    fingerprint.components.remove("root");
    assert!(fingerprint::compare(&fingerprint, &fingerprint).is_err());
    Ok(())
}

#[test]
fn weighted_jaccard_has_an_inclusive_component_threshold() -> Result {
    use std::collections::BTreeMap;
    let features = |count: usize| (0..count).map(|n| format!("path:{n}")).collect();
    let make = |count| fingerprint::Fingerprint {
        profile: fingerprint::PROFILE.into(),
        schema_checksum: "same-schema".into(),
        components: BTreeMap::from([("root".into(), features(count))]),
    };
    let reference = make(20);
    let at = fingerprint::compare(&reference, &make(17))?;
    assert!((at.similarity - 0.85).abs() < f64::EPSILON);
    assert!(at.eligible);
    assert!(!fingerprint::compare(&reference, &make(16))?.eligible);
    Ok(())
}

#[test]
fn a_weak_field_is_not_hidden_by_a_strong_root() -> Result {
    use std::collections::{BTreeMap, BTreeSet};
    let features = |values: &[&str]| {
        values
            .iter()
            .map(|v| (*v).to_owned())
            .collect::<BTreeSet<_>>()
    };
    let a = fingerprint::Fingerprint {
        profile: fingerprint::PROFILE.into(),
        schema_checksum: "same-schema".into(),
        components: BTreeMap::from([
            ("root".into(), features(&["path:root"])),
            (
                "field".into(),
                features(&["relation:root/field", "path:field"]),
            ),
        ]),
    };
    let mut b = a.clone();
    b.components.insert(
        "field".into(),
        features(&["relation:root/field", "path:field", "path:extra"]),
    );
    let comparison = fingerprint::compare(&a, &b)?;
    // Relation weight 2 yields field Jaccard 3/4; root hierarchy weight 2
    // yields aggregate (2 + 3/4)/3, above the threshold.
    assert!((comparison.components["field"] - 0.75).abs() < f64::EPSILON);
    assert!(comparison.similarity > fingerprint::THRESHOLD);
    assert!(!comparison.eligible);
    assert_eq!(comparison, fingerprint::compare(&b, &a)?);
    Ok(())
}

#[test]
fn empty_and_one_sided_components_abstain() -> Result {
    let (_, frozen, _) = fixture()?;
    let original = &frozen.references[0].fingerprint;
    for missing in [true, false] {
        let mut changed = original.clone();
        if missing {
            changed.components.remove("price");
        } else {
            changed
                .components
                .insert("price".into(), Default::default());
        }
        let comparison = fingerprint::compare(original, &changed)?;
        assert!(comparison.coverage < 1.0);
        assert!(!comparison.eligible);
        assert_eq!(comparison, fingerprint::compare(&changed, original)?);
    }
    let mut empty = original.clone();
    empty.components.clear();
    assert!(fingerprint::compare(&empty, &empty).is_err());
    Ok(())
}

#[tokio::test]
async fn evaluation_is_independent_of_oracle_order() -> Result {
    let evidence = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../experiments/contract-fingerprints/fixtures/evidence");
    let staged = stage_archive(&evidence)?;
    let output = staged.path();
    fs::rename(output.join("store"), output.join("archive"))?;
    for entry in fs::read_dir(&evidence)? {
        let entry = entry?;
        if entry
            .path()
            .extension()
            .is_some_and(|extension| extension == "json")
        {
            fs::copy(entry.path(), output.join(entry.file_name()))?;
        }
    }
    let oracle_path = output.join("oracle.json");
    let mut oracle: Vec<Expected> = serde_json::from_slice(&fs::read(&oracle_path)?)?;
    oracle.reverse();
    fs::write(&oracle_path, serde_json::to_vec(&oracle)?)?;
    evaluate(output, &oracle_path).await?;
    replay(output).await?;
    Ok(())
}

#[test]
fn root_ancestry_limit_includes_the_root_in_its_64_nodes() -> Result {
    let document = seed()?;
    let mut dom = Dom::read(&document)?;
    let template = dom
        .nodes
        .iter()
        .find(|node| node.kind == "element")
        .ok_or_else(|| super::super::error("element missing"))?
        .clone();
    dom.nodes.clear();
    dom.root = 1;
    for id in 1_u64..=65 {
        let mut node = template.clone();
        node.id = id;
        node.parent = id.checked_sub(1).filter(|parent| *parent != 0);
        node.children.clear();
        node.tag_name = Some(if id == 1 { "main" } else { "div" }.into());
        dom.nodes.push(node);
    }
    for depth in [63, 64] {
        let signature = dom.signature(depth, 1)?;
        assert!(
            signature
                .iter()
                .any(|feature| feature.starts_with("relation:main["))
        );
    }
    // Previously the loop advanced to root #1 after visiting #2 and returned
    // success without ever adding the root symbol to the relation.
    assert!(dom.signature(65, 1).is_err());
    Ok(())
}

#[test]
fn invalid_oracle_ids_are_rejected_before_evaluation() {
    let ids = [
        "obj-001", "obj-002", "obj-003", "obj-004", "obj-005", "obj-006",
    ];
    assert!(verify_ids(ids.into_iter()).is_ok());
    assert!(verify_ids(ids.into_iter().take(5)).is_err());
    assert!(verify_ids(ids.into_iter().chain(["obj-002"])).is_err());
    assert!(verify_ids(["../obj-002"].into_iter()).is_err());
}
