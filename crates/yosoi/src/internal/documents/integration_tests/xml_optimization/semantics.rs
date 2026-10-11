#![allow(clippy::panic_in_result_fn)]
use super::support::*;
use crate::internal::documents as internal_documents;

#[test]
fn public_xml_location_preserves_malformed_and_invalid_utf8_failure_mapping()
-> Result<(), Box<dyn Error>> {
    let plan = text_plan("//item")?;
    let malformed = Document::xml("malformed.xml", b"<root><item>unfinished</root>".to_vec())?;
    let invalid_utf8 = Document::xml(
        "invalid-utf8.xml",
        vec![
            b'<', b'r', b'o', b'o', b't', b'>', 0xff, b'<', b'/', b'r', b'o', b'o', b't', b'>',
        ],
    )?;

    assert_eq!(
        malformed.locate(&plan),
        LocateOutcome::Failed {
            failure: LocateFailure::ParseFailed {
                code: "xml_malformed".to_owned(),
            },
        }
    );
    assert_eq!(
        invalid_utf8.locate(&plan),
        LocateOutcome::Failed {
            failure: LocateFailure::ParseFailed {
                code: "xml_invalid_utf8".to_owned(),
            },
        }
    );
    Ok(())
}

#[test]
fn overlapping_descendant_contexts_are_deduplicated_in_document_order() -> Result<(), Box<dyn Error>>
{
    let document = xml(
        "overlap.xml",
        concat!(
            "<root><group id='outer'>",
            "<item>A</item><group id='inner'><item>B</item></group><item>C</item>",
            "</group></root>",
        ),
    )?;
    let plan = text_plan("//group//item")?;
    let outcome = assert_equivalent(&document, &plan)?;

    assert_eq!(text_values(&outcome)?, ["A", "B", "C"]);
    assert_eq!(
        matched(&outcome)?
            .iter()
            .map(internal_documents::Finding::order)
            .collect::<Vec<_>>(),
        [0, 1, 2]
    );
    Ok(())
}

#[test]
fn xpath_predicates_apply_left_to_right_and_positions_reset_per_parent()
-> Result<(), Box<dyn Error>> {
    let document = xml(
        "predicates.xml",
        concat!(
            "<root>",
            "<group><item kind='y'>g1-y</item><item kind='x'>g1-x</item><item kind='x'>g1-x2</item></group>",
            "<group><item kind='x'>g2-x1</item><item kind='x'>g2-x2</item></group>",
            "</root>",
        ),
    )?;
    let filtered_then_first = text_plan("//item[@kind='x'][1]")?;
    let first_then_filtered = text_plan("//item[1][@kind='x']")?;
    let second_per_parent = text_plan("//item[2]")?;

    assert_eq!(
        text_values(&assert_equivalent(&document, &filtered_then_first)?)?,
        ["g1-x", "g2-x1"]
    );
    assert_eq!(
        text_values(&assert_equivalent(&document, &first_then_filtered)?)?,
        ["g2-x1"]
    );
    assert_eq!(
        text_values(&assert_equivalent(&document, &second_per_parent)?)?,
        ["g1-x", "g2-x2"]
    );
    Ok(())
}

#[test]
fn namespace_aliases_share_expanded_name_positions_and_keep_exact_source_ranges()
-> Result<(), Box<dyn Error>> {
    let source = concat!(
        "<r:root xmlns:r='urn:root' xmlns:a='urn:item' xmlns:b='urn:item'>",
        "<a:item>A</a:item><b:item>B</b:item><item>C</item>",
        "</r:root>",
    );
    let document = xml("namespaces.xml", source)?;
    let query = xpath("//p:item")?.with_namespace("p", "urn:item")?;
    let plan = Plan::new([output("items", query.node())?])?;
    let outcome = assert_equivalent(&document, &plan)?;
    let findings = matched(&outcome)?;

    assert_eq!(findings.len(), 2);
    for (index, finding) in findings.iter().enumerate() {
        let NativeCoordinate::SourceTree(coordinate) = finding.coordinate() else {
            return Err(io::Error::other("XML finding used a non-tree coordinate").into());
        };
        let expected_ordinal = u32::try_from(index)?.saturating_add(1);
        assert_eq!(coordinate.child_path(), &[1, expected_ordinal]);
        assert_eq!(
            coordinate.expanded_name_path(),
            Some(
                [
                    ExpandedNamePathSegment::try_new(Some("urn:root".to_owned()), "root", 1,)?,
                    ExpandedNamePathSegment::try_new(
                        Some("urn:item".to_owned()),
                        "item",
                        expected_ordinal,
                    )?,
                ]
                .as_slice()
            )
        );
        let source_range = coordinate
            .source_bytes()
            .ok_or_else(|| io::Error::other("XML coordinate omitted its source range"))?;
        let element = if index == 0 {
            "<a:item>A</a:item>"
        } else {
            "<b:item>B</b:item>"
        };
        let start = source
            .find(element)
            .ok_or_else(|| io::Error::other("fixture element is missing"))?;
        assert_eq!(source_range.start(), u64::try_from(start)?);
        assert_eq!(source_range.end(), u64::try_from(start + element.len())?);
    }
    Ok(())
}

#[test]
fn mixed_text_normalization_is_stable_across_text_cdata_entities_and_elements()
-> Result<(), Box<dyn Error>> {
    let document = xml(
        "mixed-text.xml",
        "<root><item> \tA<![CDATA[\nB]]><em>\u{3000}C</em>&#xA0;D\r\n </item></root>",
    )?;
    let outcome = assert_equivalent(&document, &text_plan("//item")?)?;

    assert_eq!(text_values(&outcome)?, ["A B C D"]);
    Ok(())
}

#[test]
fn coordinates_distinguish_child_order_from_same_expanded_name_order() -> Result<(), Box<dyn Error>>
{
    let source = "<root><item>A</item><other/><item>B</item></root>";
    let document = xml("coordinates.xml", source)?;
    let outcome = assert_equivalent(&document, &text_plan("//item")?)?;
    let findings = matched(&outcome)?;

    assert_eq!(findings.len(), 2);
    let expected = [([1_u32, 1_u32], 1_u32), ([1_u32, 3_u32], 2_u32)];
    for (finding, (child_path, same_name_index)) in findings.iter().zip(expected) {
        let NativeCoordinate::SourceTree(coordinate) = finding.coordinate() else {
            return Err(io::Error::other("XML finding used a non-tree coordinate").into());
        };
        assert_eq!(coordinate.child_path(), child_path.as_slice());
        assert_eq!(
            coordinate
                .expanded_name_path()
                .and_then(|path| path.last())
                .map(ExpandedNamePathSegment::same_name_sibling_index),
            Some(same_name_index)
        );
        assert!(coordinate.source_bytes().is_some());
    }
    Ok(())
}
