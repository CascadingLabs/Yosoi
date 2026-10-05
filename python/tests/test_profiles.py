import pytest
from pydantic import ValidationError

import yosoi as ys


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (ys.documents.DocumentProfile.source_html(), "source_html"),
        (ys.documents.DocumentProfile.source_xml(), "source_xml"),
        (ys.documents.DocumentProfile.source_json(), "source_json"),
        (ys.documents.DocumentProfile.source_text(), "source_text"),
        (ys.documents.DocumentProfile.rendered_dom(7), "rendered_dom"),
        (ys.documents.DocumentProfile.accessibility_tree(7), "accessibility_tree"),
    ],
)
def test_profile_constructors_validate_and_report_document_class(
    profile: ys.documents.DocumentProfile, expected: str
) -> None:
    assert profile.document_class == expected


def test_document_from_profile_retains_the_exact_profile() -> None:
    profile = ys.documents.DocumentProfile.rendered_dom(19)
    document = ys.Document.from_profile("snapshot", profile, b"{}")
    assert document.profile == profile
    assert document.document_class == "rendered_dom"
    assert document.byte_len == 2


@pytest.mark.parametrize(
    "values",
    [
        {
            "representation": "rendered_dom",
            "source_format": "json",
            "schema": "yosoi_rendered_dom_v1",
        },
        {
            "representation": "source",
            "source_format": "html",
            "schema": "html5",
            "epoch": 1,
        },
        {
            "representation": "accessibility_tree",
            "source_format": "json",
            "schema": "yosoi_accessibility_tree_v1",
            "epoch": 0,
        },
        {
            "representation": "source",
            "source_format": "json",
            "schema": "html5",
        },
    ],
)
def test_profile_only_validation_rejects_invalid_axes_and_epochs(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ys.documents.DocumentProfile.model_validate(values)
