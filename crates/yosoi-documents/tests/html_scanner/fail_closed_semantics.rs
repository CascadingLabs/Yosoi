#![allow(clippy::panic_in_result_fn)]
use super::support::*;

#[test]
fn repair_and_unsupported_hazards_at_every_candidate_boundary_fall_back_exactly()
-> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    let cases = [
        (
            "hazard-before-article",
            "<template><div>hidden</div></template><article class='product-card' data-sku='sku-000073'><span class='price'>before</span></article>",
            Some(("before", vec![1, 2, 1, 2, 1])),
        ),
        (
            "hazard-in-nonmatch",
            "<article class='product-card' data-sku='wrong'><b><i>one</b>two</i><table><div>fostered</div></table></article><article class='product-card' data-sku='sku-000073'><span class='price'>nonmatch</span></article>",
            Some(("nonmatch", vec![1, 2, 1, 2, 1])),
        ),
        (
            "table-before-match",
            "<article class='product-card' data-sku='sku-000073'><table><tr><td>cell</td></tr></table><span class='price'>table</span></article>",
            Some(("table", vec![1, 2, 1, 1, 2])),
        ),
        (
            "foreign-before-match",
            "<article class='product-card' data-sku='sku-000073'><svg><title>icon</title></svg><span class='price'>foreign</span></article>",
            Some(("foreign", vec![1, 2, 1, 1, 2])),
        ),
        (
            "implicit-close-before-match",
            "<article class='product-card' data-sku='sku-000073'><p>paragraph<div>block</div><span class='price'>implicit</span></article>",
            Some(("implicit", vec![1, 2, 1, 1, 3])),
        ),
        (
            "formatting-around-match",
            "<article class='product-card' data-sku='sku-000073'><b><i><span class='price'>formatting</span></i></b></article>",
            Some(("formatting", vec![1, 2, 1, 1, 1, 1, 1])),
        ),
        (
            "hazard-after-match",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>after</span><table><div>fostered</div></table><svg></svg></article>",
            Some(("after", vec![1, 2, 1, 1, 1])),
        ),
        (
            "hazard-after-article",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>after-article</span></article><template><div>hidden</div></template>",
            Some(("after-article", vec![1, 2, 1, 1, 1])),
        ),
        (
            "plaintext-swallows-candidate",
            "<article class='product-card' data-sku='wrong'><plaintext>text</article><article class='product-card' data-sku='sku-000073'><span class='price'>swallowed</span></article>",
            None,
        ),
    ];

    for (id, body, expected) in cases {
        let outcome = exact_outcome(&document(id, body)?, &plan)?;
        match expected {
            Some((value, child_path)) => {
                assert_matches(&outcome, &[(value.to_owned(), child_path)])?;
            }
            None => assert!(matches!(outcome, LocateOutcome::NoMatch { .. })),
        }
    }
    Ok(())
}

#[test]
fn every_explicitly_unsupported_tag_preserves_retained_semantics() -> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    let paired_tags = [
        "iframe",
        "noembed",
        "noscript",
        "script",
        "select",
        "selectedcontent",
        "style",
        "template",
        "textarea",
        "xmp",
    ];
    for tag in paired_tags {
        let body = format!(
            "<article class='product-card' data-sku='sku-000073'><{tag}>hazard</{tag}><span class='price'>{tag}</span></article>"
        );
        let outcome = exact_outcome(&document(&format!("unsupported-{tag}.html"), &body)?, &plan)?;
        assert_eq!(
            outcome,
            document(&format!("unsupported-{tag}.html"), &body)?
                .parse()?
                .locate(&plan)
        );
    }

    for (tag, body) in [
        (
            "frameset",
            "<article class='product-card' data-sku='sku-000073'><frameset><frame></frameset><span class='price'>frameset</span></article>",
        ),
        (
            "plaintext",
            "<article class='product-card' data-sku='sku-000073'><plaintext><span class='price'>plaintext</span></article>",
        ),
    ] {
        let outcome = exact_outcome(&document(&format!("unsupported-{tag}.html"), body)?, &plan)?;
        let retained = document(&format!("unsupported-{tag}.html"), body)?
            .parse()?
            .locate(&plan);
        assert_eq!(outcome, retained);
    }
    Ok(())
}

#[test]
fn malicious_quote_comment_tag_boundaries_and_malformed_eof_fail_over_safely()
-> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    let cases = [
        (
            "comment-fake-target",
            "<article class='product-card' data-sku='sku-000073'><!-- </article><article class='product-card' data-sku='sku-000073'><span class='price'>fake</span> --><span class='price'>comment</span></article>",
            Some(("comment", vec![1, 2, 1, 1, 1])),
        ),
        (
            "less-than-text",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>one < two</span></article>",
            Some(("one < two", vec![1, 2, 1, 1, 1])),
        ),
        (
            "unterminated-comment-after",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>comment-eof</span><!-- unterminated",
            Some(("comment-eof", vec![1, 2, 1, 1, 1])),
        ),
        (
            "unterminated-attribute-after",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>quote-eof</span><div title='unterminated",
            Some(("quote-eof", vec![1, 2, 1, 1, 1])),
        ),
        (
            "unclosed-target-eof",
            "<article class='product-card' data-sku='sku-000073'><section><span class='price'>open-eof",
            Some(("open-eof", vec![1, 2, 1, 1, 1, 1])),
        ),
        (
            "entity-forces-fallback",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>USD&nbsp;19.73</span></article>",
            Some(("USD\u{a0}19.73", vec![1, 2, 1, 1, 1])),
        ),
        (
            "null-forces-fallback",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>before\0after</span></article>",
            Some(("beforeafter", vec![1, 2, 1, 1, 1])),
        ),
    ];

    for (id, body, expected) in cases {
        let outcome = exact_outcome(&document(id, body)?, &plan)?;
        if let Some((value, child_path)) = expected {
            assert_matches(&outcome, &[(value.to_owned(), child_path)])?;
        }
    }
    Ok(())
}

#[test]
fn eligible_catalog_rejects_one_byte_over_the_input_limit_before_candidate_evaluation()
-> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    let document = document(
        "input-limit.html",
        "<article class='product-card' data-sku='sku-000073'><span class='price'>limited</span></article>",
    )?;
    let maximum = document
        .byte_len()
        .checked_sub(1)
        .ok_or_else(|| io::Error::other("HTML fixture cannot be empty"))?;
    let limits = input_budget(maximum)?;

    assert!(matches!(
        document.parse_with_budget(limits),
        Err(DocumentParseError::Html(HtmlParseError::InputLimitExceeded {
            maximum: retained_maximum,
            observed,
        })) if retained_maximum == maximum && observed == document.byte_len()
    ));
    assert_eq!(
        document.locate_with_budget(&plan, limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum,
                observed: document.byte_len(),
            }
        }
    );
    Ok(())
}
