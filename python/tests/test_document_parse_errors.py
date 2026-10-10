"""Document and parse errors retain public Rust identity through Python."""

import pytest
from pydantic import ValidationError

from yosoi.documents import Document, DocumentProfile
from yosoi.errors import DocumentError, ParseError, rust_error_details
from yosoi.policy import Documents, Policy
from yosoi.scalars import AddressableByteLimit, DocumentEpoch, DocumentId


def test_empty_document_id_keeps_document_error_variant():
    with pytest.raises(DocumentError) as caught:
        DocumentId("")

    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "yosoi_documents::DocumentError"
    assert detail.variant == "EmptyId"
    assert detail.details == {}


def test_empty_non_text_document_keeps_document_error_variant():
    with pytest.raises(DocumentError) as caught:
        Document.from_json("empty-json", b"")

    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "yosoi_documents::DocumentError"
    assert detail.variant == "EmptyPayload"
    assert detail.details == {}


def test_zero_document_epoch_keeps_profile_error_variant():
    with pytest.raises(DocumentError) as caught:
        DocumentEpoch(0)

    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "yosoi_documents::DocumentProfileError"
    assert detail.variant == "ZeroEpoch"
    assert detail.details == {}


def test_incompatible_profile_axes_keep_serde_error_metadata():
    with pytest.raises(ValidationError) as caught:
        DocumentProfile(
            representation="source",
            source_format="html",
            schema_profile="xml10",
        )

    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "serde_json::Error"
    assert detail.variant == "Data"
    assert detail.details["category"] == "data"


@pytest.mark.parametrize(
    ("payload", "display_fragment"),
    [
        ('{"title":"first","title":"second"}', "duplicate member name"),
        ('{"title":', "ended before a complete value"),
    ],
)
def test_json_parse_errors_keep_public_parse_variant_and_source(
    payload: str, display_fragment: str
):
    document = Document.from_json("bad-json", payload)

    with pytest.raises(ParseError) as caught:
        document.parse()

    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "yosoi_engine::ParseError"
    assert detail.variant == "Document"
    assert detail.details["source"]["rust_type"] == (
        "yosoi_documents::DocumentParseError"
    )
    assert detail.source_chain == ()
    assert display_fragment in detail.details["source"]["message"]
    assert display_fragment in str(caught.value)


def test_html_parse_limit_keeps_parse_error_and_source_chain():
    document = Document.html("limited-html", "<main>content</main>")
    policy = Policy(documents=Documents(max_input_bytes=AddressableByteLimit(1)))

    with pytest.raises(ParseError) as caught:
        document.bind(policy).parse()

    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "yosoi_engine::ParseError"
    assert detail.variant == "Document"
    assert detail.details["source"]["rust_type"] == (
        "yosoi_documents::DocumentParseError"
    )
    assert detail.source_chain == ()
    assert "above the 1-byte limit" in detail.details["source"]["message"]
    assert "above the 1-byte limit" in str(caught.value)
