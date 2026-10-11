#![allow(clippy::panic_in_result_fn)]
use super::support::*;

#[test]
fn generated_article_counts_target_positions_multiplicity_and_absence_are_exact()
-> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    let cases = [
        (1_usize, vec![0_usize]),
        (2, vec![1]),
        (7, vec![0]),
        (7, vec![3]),
        (7, vec![6]),
        (17, vec![0, 8, 16]),
        (17, Vec::new()),
    ];

    for (records, targets) in cases {
        let id = format!("generated-{records}-{targets:?}.html");
        let document = document(&id, &generated_catalog(records, &targets)?)?;
        let outcome = exact_outcome(&document, &plan)?;
        if targets.is_empty() {
            assert!(matches!(outcome, LocateOutcome::NoMatch { .. }));
            continue;
        }
        let expected = targets
            .iter()
            .map(|index| {
                Ok((
                    format!("value-{index}"),
                    vec![1, 2, 1, u32::try_from(index.saturating_add(1))?, 1],
                ))
            })
            .collect::<Result<Vec<_>, TryFromIntError>>()?;
        assert_matches(&outcome, &expected)?;
    }
    Ok(())
}

#[test]
fn unrelated_attributes_tags_nested_safe_elements_comments_text_and_voids_are_exact()
-> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    for attribute_count in [0_usize, 1, 4, 16, 64] {
        let mut unrelated = String::new();
        for index in 0..attribute_count {
            write!(&mut unrelated, " data-noise-{index}='value-{index}'")?;
        }
        let body = format!(
            "<article class='product-card' data-sku='sku-000073'{unrelated}><span class='price'>attrs-{attribute_count}</span></article>"
        );
        let outcome = exact_outcome(
            &document(&format!("attributes-{attribute_count}.html"), &body)?,
            &plan,
        )?;
        assert_matches(
            &outcome,
            &[(format!("attrs-{attribute_count}"), vec![1, 2, 1, 1, 1])],
        )?;
    }

    for sibling_count in [0_usize, 1, 5, 19] {
        let mut siblings = String::new();
        for index in 0..sibling_count {
            write!(
                &mut siblings,
                "<section data-index='{index}'>noise-{index}</section>"
            )?;
        }
        let body = format!(
            "<article class='product-card' data-sku='sku-000073'>{siblings}<span class='price'>siblings-{sibling_count}</span></article>"
        );
        let outcome = exact_outcome(
            &document(&format!("siblings-{sibling_count}.html"), &body)?,
            &plan,
        )?;
        assert_matches(
            &outcome,
            &[(
                format!("siblings-{sibling_count}"),
                vec![1, 2, 1, 1, u32::try_from(sibling_count.saturating_add(1))?],
            )],
        )?;
    }

    let nested = document(
        "nested-safe.html",
        concat!(
            "text<!--fake <span class='price'>bad</span> -->",
            "<article class='product-card' data-sku='sku-000073'>",
            "article text<!--article comment--><img alt='x'><br><input disabled>",
            "<section><div><figure><span class='price'>nested</span></figure></div></section>",
            "</article>trailing text<!--trailing comment-->",
        ),
    )?;
    assert_matches(
        &exact_outcome(&nested, &plan)?,
        &[("nested".to_owned(), vec![1, 2, 1, 1, 4, 1, 1, 1])],
    )?;
    Ok(())
}

#[test]
fn attribute_grammar_and_duplicate_first_value_semantics_are_exact() -> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    let cases = [
        (
            "double-single-boolean",
            "<article hidden class=\"product-card extra\" data-sku='sku-000073'><span inert class=price>quoted</span></article>",
            Some("quoted"),
        ),
        (
            "uppercase",
            "<ARTICLE CLASS='product-card' DATA-SKU='sku-000073'><SPAN CLASS='price'>upper</SPAN></ARTICLE>",
            Some("upper"),
        ),
        (
            "quoted-tag-boundary",
            "<article data-note=\"x>y </article><article>\" class='product-card' data-sku='sku-000073'><span class='price' title='</span><b>'>boundary</span></article>",
            Some("boundary"),
        ),
        (
            "first-class-wins",
            "<article class='product-card' class='wrong' data-sku='sku-000073'><span class='price'>first-class</span></article>",
            Some("first-class"),
        ),
        (
            "wrong-first-class-wins",
            "<article class='wrong' class='product-card' data-sku='sku-000073'><span class='price'>wrong-class</span></article>",
            None,
        ),
        (
            "first-sku-wins",
            "<article class='product-card' data-sku='sku-000073' data-sku='wrong'><span class='price'>first-sku</span></article>",
            Some("first-sku"),
        ),
        (
            "wrong-first-sku-wins",
            "<article class='product-card' data-sku='wrong' data-sku='sku-000073'><span class='price'>wrong-sku</span></article>",
            None,
        ),
        (
            "first-span-class-wins",
            "<article class='product-card' data-sku='sku-000073'><span class='price' class='wrong'>first-span</span></article>",
            Some("first-span"),
        ),
        (
            "wrong-first-span-class-wins",
            "<article class='product-card' data-sku='sku-000073'><span class='wrong' class='price'>wrong-span</span></article>",
            None,
        ),
    ];

    for (id, body, expected) in cases {
        let outcome = exact_outcome(&document(id, body)?, &plan)?;
        match expected {
            Some(value) => assert_matches(&outcome, &[(value.to_owned(), vec![1, 2, 1, 1, 1])])?,
            None => assert!(matches!(outcome, LocateOutcome::NoMatch { .. })),
        }
    }
    Ok(())
}
