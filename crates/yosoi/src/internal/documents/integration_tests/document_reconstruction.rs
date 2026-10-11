use std::error::Error;

use crate::internal::documents::{
    Document, DocumentClass, DocumentEpoch, DocumentError, DocumentId, DocumentProfile,
};

#[test]
fn durable_profiles_reconstruct_every_document_class_exactly() -> Result<(), Box<dyn Error>> {
    let epoch = DocumentEpoch::try_from(7_u64)?;
    let cases = [
        (
            "source-html",
            DocumentProfile::source_html(),
            DocumentClass::SourceHtml,
            b"<main>Example</main>".as_slice(),
        ),
        (
            "source-xml",
            DocumentProfile::source_xml(),
            DocumentClass::SourceXml,
            b"<root>Example</root>".as_slice(),
        ),
        (
            "source-json",
            DocumentProfile::source_json(),
            DocumentClass::SourceJson,
            br#"{"title":"Example"}"#.as_slice(),
        ),
        (
            "decoded-text",
            DocumentProfile::source_text(),
            DocumentClass::SourceText,
            b"Example".as_slice(),
        ),
        (
            "rendered-dom",
            DocumentProfile::rendered_dom(epoch),
            DocumentClass::RenderedDom,
            b"{\"nodes\":[]}".as_slice(),
        ),
        (
            "accessibility-tree",
            DocumentProfile::accessibility_tree_v1(epoch),
            DocumentClass::AccessibilityTree,
            b"{\"nodes\":[]}".as_slice(),
        ),
    ];

    for (id, profile, class, bytes) in cases {
        let document = Document::from_profile(DocumentId::try_new(id)?, profile, bytes.to_vec())?;
        if document.id().as_str() != id
            || document.profile() != profile
            || document.class() != class
            || document.bytes() != bytes
        {
            return Err(format!("{id} did not retain its exact reconstruction inputs").into());
        }
    }
    Ok(())
}

#[test]
fn reconstruction_retains_existing_payload_validation() -> Result<(), Box<dyn Error>> {
    let empty_html = Document::from_profile(
        DocumentId::try_new("empty-html")?,
        DocumentProfile::source_html(),
        Vec::new(),
    );
    if empty_html != Err(DocumentError::EmptyPayload) {
        return Err("empty non-text payload bypassed Document validation".into());
    }

    let empty_text = Document::from_profile(
        DocumentId::try_new("empty-text")?,
        DocumentProfile::source_text(),
        Vec::new(),
    )?;
    if !empty_text.bytes().is_empty() || empty_text.class() != DocumentClass::SourceText {
        return Err("empty decoded text did not preserve its existing semantics".into());
    }
    Ok(())
}
