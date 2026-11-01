//! Shared SurfaceRead behavior across all immutable web Document classes.
use serde::Deserialize;
use std::{error::Error, io};
use yosoi::{
    documents::{Document, DocumentEpoch},
    surface::{
        Budget, Surface,
        browser::WebSurface,
        model::{Access, ReadOperation, ReadRequest, ReadResult, SourceId, SurfaceRead},
    },
};

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

#[derive(Deserialize)]
struct Cases {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    format: String,
    content: String,
    query: String,
}

fn document(case: &Case) -> Result<Document, Box<dyn Error + Send + Sync>> {
    let bytes = case.content.as_bytes().to_vec();
    let epoch = DocumentEpoch::try_from(7)?;
    match case.format.as_str() {
        "html" => Ok(Document::html(&case.name, bytes)?),
        "xml" => Ok(Document::xml(&case.name, bytes)?),
        "json" => Ok(Document::json(&case.name, bytes)?),
        "text" => Ok(Document::text(&case.name, bytes)?),
        "rendered_dom" => Ok(Document::rendered_dom(&case.name, epoch, bytes)?),
        "accessibility_tree" => Ok(Document::accessibility_tree(&case.name, epoch, bytes)?),
        _ => Err(io::Error::other("unknown Surface parity fixture").into()),
    }
}

fn request(operation: ReadOperation) -> ReadRequest {
    ReadRequest {
        operation,
        budget: Budget::default(),
        continuation: None,
    }
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions intentionally fail when a supported document class loses shared-read parity."
)]
fn all_six_document_classes_share_the_immutable_read_protocol() -> TestResult {
    let cases: Cases =
        serde_json::from_str(include_str!("../../../python/parity/surface-vectors.json"))?;
    for case in cases.cases {
        let document = document(&case)?;
        let index = Surface::new(&document)?;
        let reader = WebSurface::new(index, SourceId::new(format!("fixture:{}", case.name))?)?;
        let descriptor = reader.descriptor();
        assert!(!descriptor.controllable, "{}", case.format);
        for operation in ["overview", "expand", "inspect", "search", "parent"] {
            let capability = descriptor
                .capabilities
                .iter()
                .find(|capability| capability.id == format!("web.{operation}@1"))
                .ok_or_else(|| io::Error::other(format!("missing {operation} capability")))?;
            assert_eq!(
                capability.access,
                Access::Read,
                "{} {operation}",
                case.format
            );
            assert!(
                capability.control_domain.is_none(),
                "{} {operation}",
                case.format
            );
        }

        let overview = reader.read(&request(ReadOperation::Overview))?;
        assert!(matches!(overview, ReadResult::Page(_)), "{}", case.format);
        let expanded = reader.read(&request(ReadOperation::Expand {
            reference: reader.root_reference(),
        }))?;
        assert!(matches!(expanded, ReadResult::Page(_)), "{}", case.format);

        let found = reader.read(&request(ReadOperation::Search { query: case.query }))?;
        let ReadResult::Page(found) = found else {
            return Err(io::Error::other("search did not return a page").into());
        };
        let reference = found
            .entries
            .first()
            .map(|entry| entry.reference.clone())
            .ok_or_else(|| io::Error::other(format!("{} search found no evidence", case.format)))?;
        let inspected = reader.read(&request(ReadOperation::Inspect {
            reference: reference.clone(),
        }))?;
        let ReadResult::Inspection(inspected) = inspected else {
            return Err(io::Error::other("inspect did not return a fragment").into());
        };
        assert!(inspected.content.contains("lamp"), "{}", case.format);
        assert_eq!(inspected.reference, reference);

        let parent = reader.read(&request(ReadOperation::Parent { reference }))?;
        assert!(matches!(parent, ReadResult::Parent(_)), "{}", case.format);
        assert!(reader.native_reference(&reader.root_reference()).is_ok());
    }
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions intentionally fail if incomplete native coverage is lost or granted control."
)]
fn partial_ax_and_network_coverage_remain_read_only() -> TestResult {
    let cases: Cases =
        serde_json::from_str(include_str!("../../../python/parity/surface-vectors.json"))?;
    let ax = cases
        .cases
        .iter()
        .find(|case| case.format == "accessibility_tree")
        .ok_or_else(|| io::Error::other("AX fixture missing"))?;
    let ax_reader = WebSurface::new(Surface::new(&document(ax)?)?, SourceId::new("fixture:ax")?)?;
    assert!(!ax_reader.observation().coverage.complete);
    assert!(!ax_reader.descriptor().controllable);

    let network = Document::json(
        "network",
        br#"{"schema":"yosoi.network.v1","events":[{"url":"/items"}]}"#.to_vec(),
    )?;
    let network_reader =
        WebSurface::new(Surface::new(&network)?, SourceId::new("fixture:network")?)?;
    assert_eq!(
        network_reader.descriptor().representation,
        "yosoi.web.network.v1"
    );
    assert!(!network_reader.observation().coverage.complete);
    assert!(!network_reader.descriptor().controllable);
    Ok(())
}
