use super::*;

fn missing() -> MediaDeclaration {
    MediaDeclaration::Missing
}

#[test]
fn multiple_candidates_are_sorted_and_deduplicated_at_decision_boundary() {
    assert_eq!(
        classify_detected(
            &missing(),
            false,
            vec![SourceFormat::Json, SourceFormat::Html, SourceFormat::Json],
            ClassificationExtent::Complete
        ),
        SourceClassificationOutcome::Ambiguous {
            candidates: vec![SourceFormat::Html, SourceFormat::Json],
            disagreement: DeclarationDisagreement::Inconclusive,
            extent: ClassificationExtent::Complete,
        }
    );
}

#[test]
fn ambiguity_preserves_retained_prefix_extent() {
    let outcome = classify_detected(
        &missing(),
        false,
        vec![SourceFormat::Html, SourceFormat::Json],
        ClassificationExtent::RetainedPrefix,
    );
    assert!(matches!(
        outcome,
        SourceClassificationOutcome::Ambiguous {
            extent: ClassificationExtent::RetainedPrefix,
            ..
        }
    ));
}

#[test]
fn declaration_disagreement_uses_whole_candidate_set() {
    let declaration = MediaDeclaration::Parsed {
        essence: "application/json".to_owned(),
        charset: CharsetDeclaration::Missing,
    };
    let outcome = classify_detected(
        &declaration,
        false,
        vec![SourceFormat::Html, SourceFormat::Json],
        ClassificationExtent::Complete,
    );
    assert!(
        matches!(outcome, SourceClassificationOutcome::Classified(value) if value.disagreement() == DeclarationDisagreement::Supports)
    );
}

#[test]
fn public_detector_outputs_are_canonical_even_though_v1_signatures_are_disjoint() {
    let outcome = classify(&missing(), b"<html>", ClassificationExtent::Complete);
    assert!(matches!(
        outcome,
        SourceClassificationOutcome::Classified(_)
    ));
}
