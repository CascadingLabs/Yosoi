use super::{
    Result, fail,
    fingerprint::{self, Comparison, Fingerprint, checksum},
    recipe::{self, Product, Recipe, Stock},
    storage::{read_json, read_ref, save_json, stage_archive, write_ref},
};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeSet, fs, path::Path, time::Instant};
use yosoi::{
    Archive, archive::DocumentArchiveRef, contracts::ContractSchema, documents::Document,
    locators::Plan,
};

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Reference {
    source: DocumentArchiveRef,
    fingerprint: Fingerprint,
    fingerprint_checksum: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Frozen {
    version: u32,
    schema: ContractSchema,
    recipe: Recipe,
    plan: Plan,
    plan_checksum: String,
    references: Vec<Reference>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Expected {
    id: String,
    name: String,
    price_cents: u64,
    color: String,
    material: String,
    stock: Stock,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
struct Case {
    id: String,
    product: Option<Product>,
    comparisons: Vec<Comparison>,
    fingerprint_checksum: String,
    fingerprint_bytes: usize,
    runtime_validated: bool,
    oracle_passed: bool,
    error: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Report {
    version: u32,
    frozen: DocumentArchiveRef,
    oracle: DocumentArchiveRef,
    sources: Vec<DocumentArchiveRef>,
    cases: Vec<Case>,
    controls: Vec<Case>,
    evaluation_us: u128,
}

pub async fn freeze(output: &Path) -> Result {
    if output.join("frozen.ref.json").exists()
        || ["obj-003", "obj-004", "obj-005", "obj-006"]
            .iter()
            .any(|id| output.join(format!("{id}.ref.json")).exists())
    {
        return fail(
            "freeze must precede held-out capture and cannot overwrite an existing freeze",
        );
    }
    let archive = Archive::open(output.join("archive")).await?;
    let schema = Product::schema()?.clone();
    let schema_checksum = checksum(&schema)?;
    let recipe = Recipe::default();
    let plan = recipe.plan()?;
    let mut references = Vec::new();
    for id in ["obj-001", "obj-002"] {
        let source = read_ref(&output.join(format!("{id}.ref.json")))?;
        let document = archive.read_document(&source).await?;
        let located = recipe.locate(&document, &plan)?;
        let product = recipe::extract(&located)?;
        recipe::runtime_validate(&product, id)?;
        let fingerprint = fingerprint::observe(&document, &located, &schema_checksum)?;
        let fingerprint_checksum = checksum(&fingerprint)?;
        references.push(Reference {
            source,
            fingerprint,
            fingerprint_checksum,
        });
    }
    let frozen = Frozen {
        version: 1,
        schema,
        recipe,
        plan_checksum: checksum(&plan)?,
        plan,
        references,
    };
    let reference = save_json(&archive, "contract-fingerprint-frozen-v1", &frozen).await?;
    // Archive stores the authoritative plan/schema/reference attachment; this is its locator.
    write_ref(&output.join("frozen.ref.json"), &reference)?;
    fs::write(
        output.join("frozen.json"),
        serde_json::to_vec_pretty(&frozen)?,
    )?;
    println!(
        "Frozen two references; plan checksum {}",
        frozen.plan_checksum
    );
    Ok(())
}

async fn load_frozen(archive: &Archive, reference: &DocumentArchiveRef) -> Result<Frozen> {
    let frozen: Frozen = read_json(archive, reference).await?;
    if frozen.version != 1
        || frozen.schema != *Product::schema()?
        || checksum(&frozen.plan)? != frozen.plan_checksum
        || frozen.plan != frozen.recipe.plan()?
        || frozen.references.len() != 2
    {
        return fail("incompatible or inconsistent frozen reference");
    }
    for reference in &frozen.references {
        if checksum(&reference.fingerprint)? != reference.fingerprint_checksum {
            return fail("fingerprint checksum mismatch");
        }
        let document = archive.read_document(&reference.source).await?;
        let located = frozen.recipe.locate(&document, &frozen.plan)?;
        let actual = fingerprint::observe(&document, &located, &checksum(&frozen.schema)?)?;
        if actual != reference.fingerprint {
            return fail("fingerprint does not reproduce from archived seed");
        }
    }
    Ok(frozen)
}

fn evaluate_case(frozen: &Frozen, document: &Document, expected: &Expected) -> Result<Case> {
    let located = frozen.recipe.locate(document, &frozen.plan)?;
    let fingerprint = fingerprint::observe(document, &located, &checksum(&frozen.schema)?)?;
    let comparisons = frozen
        .references
        .iter()
        .map(|reference| fingerprint::compare(&reference.fingerprint, &fingerprint))
        .collect::<Result<Vec<_>>>()?;
    let mut case = Case {
        id: expected.id.clone(),
        product: None,
        comparisons,
        fingerprint_checksum: checksum(&fingerprint)?,
        fingerprint_bytes: serde_json::to_vec(&fingerprint)?.len(),
        runtime_validated: false,
        oracle_passed: false,
        error: None,
    };
    if !case
        .comparisons
        .iter()
        .any(|comparison| comparison.eligible)
    {
        case.error = Some("no eligible structural reference; rediscovery required".into());
        return Ok(case);
    }
    let product = match recipe::extract(&located) {
        Ok(value) => value,
        Err(error) => {
            case.error = Some(error.to_string());
            return Ok(case);
        }
    };
    let stock = match recipe::runtime_validate(&product, document.id().as_str()) {
        Ok(value) => value,
        Err(error) => {
            case.error = Some(error.to_string());
            case.product = Some(product);
            return Ok(case);
        }
    };
    case.runtime_validated = true;
    case.oracle_passed = product.id == expected.id
        && product.name == expected.name
        && recipe::price_cents(&product.price)? == expected.price_cents
        && product.color == expected.color
        && product.material == expected.material
        && stock == expected.stock;
    case.product = Some(product);
    Ok(case)
}

fn verify_collection(cases: &[Case]) -> Result {
    let expected: BTreeSet<&str> = [
        "obj-001", "obj-002", "obj-003", "obj-004", "obj-005", "obj-006",
    ]
    .into_iter()
    .collect();
    let actual: BTreeSet<&str> = cases.iter().map(|case| case.id.as_str()).collect();
    if cases.len() != expected.len() || actual != expected {
        return fail("collection coverage or uniqueness failed");
    }
    Ok(())
}

pub async fn evaluate(output: &Path, oracle_path: &Path) -> Result {
    let archive = Archive::open(output.join("archive")).await?;
    let frozen_ref = read_ref(&output.join("frozen.ref.json"))?;
    let frozen = load_frozen(&archive, &frozen_ref).await?;
    let expected: Vec<Expected> = serde_json::from_slice(&fs::read(oracle_path)?)?;
    let oracle = save_json(&archive, "qscrape-oracle-v1", &expected).await?;
    let started = Instant::now();
    let mut cases = Vec::new();
    let mut sources = Vec::new();
    for item in &expected {
        let source = read_ref(&output.join(format!("{}.ref.json", item.id)))?;
        let document = archive.read_document(&source).await?;
        cases.push(evaluate_case(&frozen, &document, item)?);
        sources.push(source);
    }
    let controls = run_controls(
        &frozen,
        &archive
            .read_document(
                &sources
                    .get(1)
                    .ok_or_else(|| super::error("mug source missing"))?
                    .clone(),
            )
            .await?,
        expected
            .get(1)
            .ok_or_else(|| super::error("mug oracle missing"))?,
    )?;
    let report = Report {
        version: 1,
        frozen: frozen_ref,
        oracle,
        sources,
        cases,
        controls,
        evaluation_us: started.elapsed().as_micros(),
    };
    let report_ref = save_json(&archive, "contract-fingerprint-report-v1", &report).await?;
    write_ref(&output.join("report.ref.json"), &report_ref)?;
    fs::write(
        output.join("report.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    verify_collection(&report.cases)?;
    println!(
        "{} of four held-out products verified; zero additional AI discovery calls; {} us including Archive reads and controls",
        report
            .cases
            .iter()
            .filter(|case| case.id != "obj-001" && case.id != "obj-002" && case.oracle_passed)
            .count(),
        report.evaluation_us
    );
    Ok(())
}

pub async fn replay(output: &Path) -> Result {
    let staged = stage_archive(output)?;
    let archive = Archive::open(staged.path().join("store")).await?;
    let report: Report = read_json(&archive, &read_ref(&output.join("report.ref.json"))?).await?;
    if report.version != 1 {
        return fail("unsupported report version");
    }
    let frozen = load_frozen(&archive, &report.frozen).await?;
    let oracle: Vec<Expected> = read_json(&archive, &report.oracle).await?;
    if report.sources.len() != oracle.len() {
        return fail("source/oracle count mismatch");
    }
    let mut cases = Vec::new();
    for (source, expected) in report.sources.iter().zip(&oracle) {
        let document = archive.read_document(source).await?;
        cases.push(evaluate_case(&frozen, &document, expected)?);
    }
    verify_collection(&cases)?;
    let controls = run_controls(
        &frozen,
        &archive
            .read_document(
                report
                    .sources
                    .get(1)
                    .ok_or_else(|| super::error("mug source missing"))?,
            )
            .await?,
        oracle
            .get(1)
            .ok_or_else(|| super::error("mug oracle missing"))?,
    )?;
    if cases != report.cases || controls != report.controls {
        return fail("archived results did not reproduce");
    }
    if output.join("sensitivity.ref.json").exists() {
        let saved: Sensitivity =
            read_json(&archive, &read_ref(&output.join("sensitivity.ref.json"))?).await?;
        if saved != sensitivity_result(&archive, &saved.baseline).await? {
            return fail("seed-sensitivity replay mismatch");
        }
    }
    println!(
        "Archive-only replay reproduced all decisions, comparisons, controls and optional seed sensitivity"
    );
    Ok(())
}

#[expect(
    clippy::float_cmp,
    reason = "The wrong-value control must preserve exact structural identity."
)]
fn run_controls(frozen: &Frozen, document: &Document, expected: &Expected) -> Result<Vec<Case>> {
    use super::controls::{Mutation, mutate};
    let mut controls = Vec::new();
    for mutation in [
        Mutation::MissingPrice,
        Mutation::WrongPrice,
        Mutation::ReorderedFacts,
        Mutation::DuplicatePrice,
        Mutation::ChangedWrapper,
        Mutation::OutsideDecoy,
    ] {
        let mutated = mutate(document, &frozen.recipe, mutation)?;
        let case = evaluate_case(frozen, &mutated, expected);
        let mut case = match case {
            Ok(case) => case,
            Err(error) => Case {
                id: expected.id.clone(),
                product: None,
                comparisons: Vec::new(),
                fingerprint_checksum: String::new(),
                fingerprint_bytes: 0,
                runtime_validated: false,
                oracle_passed: false,
                error: Some(error.to_string()),
            },
        };
        let correct = match mutation {
            Mutation::WrongPrice => {
                case.runtime_validated
                    && !case.oracle_passed
                    && case.comparisons.iter().all(|c| c.similarity == 1.0)
            }
            Mutation::ReorderedFacts | Mutation::OutsideDecoy => {
                case.runtime_validated && case.oracle_passed
            }
            Mutation::MissingPrice | Mutation::DuplicatePrice | Mutation::ChangedWrapper => {
                !case.runtime_validated && !case.oracle_passed
            }
        };
        if !correct {
            return fail(&format!(
                "control {mutation:?} contradicted its expected behavior: {case:?}"
            ));
        }
        case.id = format!("{mutation:?}");
        controls.push(case);
    }
    Ok(controls)
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
struct SeedScenario {
    seeds: Vec<String>,
    cases: Vec<Case>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
struct Sensitivity {
    version: u32,
    baseline: DocumentArchiveRef,
    scenarios: Vec<SeedScenario>,
}

async fn sensitivity_result(
    archive: &Archive,
    baseline: &DocumentArchiveRef,
) -> Result<Sensitivity> {
    let report: Report = read_json(archive, baseline).await?;
    let frozen = load_frozen(archive, &report.frozen).await?;
    let oracle: Vec<Expected> = read_json(archive, &report.oracle).await?;
    let mut documents = Vec::new();
    for source in &report.sources {
        documents.push(archive.read_document(source).await?);
    }
    let mut scenarios = Vec::new();
    for seeds in [
        vec!["obj-001", "obj-002"],
        vec!["obj-002", "obj-005"],
        vec!["obj-005"],
    ] {
        let mut variant = frozen.clone();
        variant.references.clear();
        for id in &seeds {
            let index = documents
                .iter()
                .position(|document| document.id().as_str() == *id)
                .ok_or_else(|| super::error("sensitivity seed missing"))?;
            let document = documents
                .get(index)
                .ok_or_else(|| super::error("sensitivity document missing"))?;
            let located = variant.recipe.locate(document, &variant.plan)?;
            let product = recipe::extract(&located)?;
            recipe::runtime_validate(&product, id)?;
            let fingerprint =
                fingerprint::observe(document, &located, &checksum(&variant.schema)?)?;
            variant.references.push(Reference {
                source: report
                    .sources
                    .get(index)
                    .ok_or_else(|| super::error("sensitivity source missing"))?
                    .clone(),
                fingerprint_checksum: checksum(&fingerprint)?,
                fingerprint,
            });
        }
        let cases = documents
            .iter()
            .zip(&oracle)
            .map(|(document, expected)| evaluate_case(&variant, document, expected))
            .collect::<Result<Vec<_>>>()?;
        scenarios.push(SeedScenario {
            seeds: seeds.into_iter().map(str::to_owned).collect(),
            cases,
        });
    }
    Ok(Sensitivity {
        version: 1,
        baseline: baseline.clone(),
        scenarios,
    })
}

pub async fn sensitivity(output: &Path) -> Result {
    let archive = Archive::open(output.join("archive")).await?;
    let result = sensitivity_result(&archive, &read_ref(&output.join("report.ref.json"))?).await?;
    let reference = save_json(
        &archive,
        "contract-fingerprint-seed-sensitivity-v1",
        &result,
    )
    .await?;
    write_ref(&output.join("sensitivity.ref.json"), &reference)?;
    fs::write(
        output.join("sensitivity.json"),
        serde_json::to_vec_pretty(&result)?,
    )?;
    for scenario in &result.scenarios {
        println!(
            "seeds {:?}: {}/6 products verified (post-hoc exploration)",
            scenario.seeds,
            scenario
                .cases
                .iter()
                .filter(|case| case.oracle_passed)
                .count()
        );
    }
    Ok(())
}
