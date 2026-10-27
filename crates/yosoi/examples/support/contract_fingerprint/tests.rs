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
