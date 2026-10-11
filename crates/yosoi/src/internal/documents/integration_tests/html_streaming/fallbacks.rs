#![allow(clippy::panic_in_result_fn)]
use super::support::*;
use crate::internal::documents as internal_documents;

#[test]
fn repair_hazards_before_inside_and_after_the_target_preserve_exact_public_results()
-> Result<(), Box<dyn Error>> {
    let plan = caveman_plan()?;
    let cases = [
        (
            "hazard-before-target",
            "<main><table><div>fostered before table</div></table><article class='product-card' data-sku='sku-000073'><span class='price'>before</span></article></main>",
            "before",
            vec![1, 2, 1, 3, 1],
        ),
        (
            "hazard-inside-nonmatch",
            "<main><article class='product-card' data-sku='sku-000001'><b><i>one</b>two</i><table><div>fostered</div></table></article><article class='product-card' data-sku='sku-000073'><span class='price'>nonmatch</span></article></main>",
            "nonmatch",
            vec![1, 2, 1, 2, 1],
        ),
        (
            "hazard-inside-target",
            "<main><article class='product-card' data-sku='sku-000073'><table><span class='price'>inside</span><tr><td>cell</td></tr></table></article></main>",
            "inside",
            vec![1, 2, 1, 1, 1],
        ),
        (
            "hazard-after-target",
            "<main><article class='product-card' data-sku='sku-000073'><span class='price'>after</span></article><table><div>fostered after target</div></table><b><i>one</b>two</i></main>",
            "after",
            vec![1, 2, 1, 1, 1],
        ),
    ];

    for (id, source, expected_value, child_path) in cases {
        let outcome = assert_default_equivalent(&html(id, source)?, &plan)?;
        let finding = matched(&outcome)?
            .first()
            .ok_or_else(|| io::Error::other("repair-hazard fixture produced no finding"))?;
        assert_eq!(
            finding.value(),
            &ProjectedValue::Text(expected_value.to_owned())
        );
        assert_eq!(
            finding.coordinate(),
            &NativeCoordinate::SourceTree(TreeCoordinate::try_new(child_path, None)?)
        );
    }
    Ok(())
}

#[test]
fn conservative_repair_fallback_cases_keep_clones_templates_and_reparenting_exact()
-> Result<(), Box<dyn Error>> {
    let plan = caveman_plan()?;

    let adoption = html(
        "adoption-fallback.html",
        "<main><article class='product-card' data-sku='sku-000073'><b><i><span class='price'>adopted</span></b>tail</i></article></main>",
    )?;
    let adoption_outcome = assert_default_equivalent(&adoption, &plan)?;
    assert_eq!(
        matched(&adoption_outcome)?
            .first()
            .map(internal_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1, 1, 1, 1, 1],
            None,
        )?))
    );

    let selectedcontent = html(
        "selectedcontent-fallback.html",
        "<main><article class='product-card' data-sku='sku-000073'><select><button><selectedcontent></selectedcontent></button><option selected><span class='price'>selected</span></option></select></article></main>",
    )?;
    let selectedcontent_outcome = assert_default_equivalent(&selectedcontent, &plan)?;
    assert_eq!(
        matched(&selectedcontent_outcome)?
            .iter()
            .map(|finding| finding.coordinate().clone())
            .collect::<Vec<_>>(),
        vec![
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(
                vec![1, 2, 1, 1, 1, 1, 1, 1],
                None,
            )?),
            NativeCoordinate::SourceTree(
                TreeCoordinate::try_new(vec![1, 2, 1, 1, 1, 2, 1], None,)?
            ),
        ]
    );

    let template = html(
        "template-fallback.html",
        "<main><article class='product-card' data-sku='sku-000073'><template><span class='price'>hidden</span></template><span class='price'>visible</span></article></main>",
    )?;
    let template_outcome = assert_default_equivalent(&template, &plan)?;
    let template_finding = matched(&template_outcome)?
        .first()
        .ok_or_else(|| io::Error::other("template fixture produced no visible finding"))?;
    assert_eq!(
        template_finding.value(),
        &ProjectedValue::Text("visible".to_owned())
    );
    assert_eq!(
        template_finding.coordinate(),
        &NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1, 2], None,)?)
    );
    Ok(())
}

#[test]
fn repair_sensitive_documents_remain_exactly_equivalent() -> Result<(), Box<dyn Error>> {
    let plan = caveman_plan()?;
    let cases = [
        (
            "implied-nodes-and-tbody",
            "<main><article class='product-card' data-sku='sku-000073'><table><tr><td><span class='price'>USD 19.73</span></td></tr></table></article></main>",
        ),
        (
            "foster-parenting",
            "<main><article class='product-card' data-sku='sku-000073'><table><span class='price'>USD 19.73</span><tr><td>cell</td></tr></table></article></main>",
        ),
        (
            "adoption-agency",
            "<main><article class='product-card' data-sku='sku-000073'><b>before<i><span class='price'>USD 19.73</span></b>after</i></article></main>",
        ),
        (
            "selectedcontent-clone",
            "<main><article class='product-card' data-sku='sku-000073'><select><button><selectedcontent></selectedcontent></button><option selected><span class='price'>USD 19.73</span></option></select></article></main>",
        ),
        (
            "template-and-visible-sibling",
            "<main><article class='product-card' data-sku='sku-000073'><template><span class='price'>hidden</span></template><span class='price'>USD 19.73</span></article></main>",
        ),
        (
            "foreign-content",
            "<main><article class='product-card' data-sku='sku-000073'><svg viewBox='0 0 1 1'><title>icon</title><path d='M0 0L1 1'></path></svg><math><mtext><b>formula</b></mtext></math><span class='price'>USD 19.73</span></article></main>",
        ),
    ];

    for (id, source) in cases {
        assert_default_equivalent(&html(id, source)?, &plan)?;
    }
    Ok(())
}

#[test]
fn duplicate_late_and_absent_targets_preserve_complete_terminal_outcomes()
-> Result<(), Box<dyn Error>> {
    let plan = caveman_plan()?;
    let duplicate = html(
        "duplicate.html",
        concat!(
            "<main>",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>first</span></article>",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>second</span></article>",
            "</main>",
        ),
    )?;
    let duplicate_outcome = assert_default_equivalent(&duplicate, &plan)?;
    assert_eq!(
        matched(&duplicate_outcome)?
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::Text("first".to_owned()),
            ProjectedValue::Text("second".to_owned()),
        ]
    );

    let late = html(
        "late.html",
        concat!(
            "<main>",
            "<article class='product-card' data-sku='sku-000001'><span class='price'>d1</span></article>",
            "<article class='product-card' data-sku='sku-000002'><span class='price'>d2</span></article>",
            "<article class='product-card' data-sku='sku-000003'><span class='price'>d3</span></article>",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>late</span></article>",
            "</main>",
        ),
    )?;
    assert_eq!(
        matched(&assert_default_equivalent(&late, &plan)?)?
            .first()
            .map(internal_documents::Finding::value),
        Some(&ProjectedValue::Text("late".to_owned()))
    );

    let absent = html(
        "absent.html",
        "<main><article class='product-card' data-sku='sku-000001'><span class='price'>d1</span></article></main>",
    )?;
    assert!(matches!(
        assert_default_equivalent(&absent, &plan)?,
        LocateOutcome::NoMatch { .. }
    ));
    Ok(())
}

#[test]
fn descendant_text_normalization_matches_ascii_unicode_and_entity_semantics()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "normalization.html",
        "<article class='product-card' data-sku='sku-000073'><span class='price'> \tUSD&nbsp;<b>19</b>.73\u{3000}X\r\n </span></article>",
    )?;
    let outcome = assert_default_equivalent(&document, &caveman_plan()?)?;
    assert_eq!(
        matched(&outcome)?
            .first()
            .map(internal_documents::Finding::value),
        Some(&ProjectedValue::Text("USD\u{a0}19.73\u{3000}X".to_owned()))
    );
    Ok(())
}
