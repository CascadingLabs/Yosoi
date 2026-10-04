#![allow(clippy::panic_in_result_fn)]
use super::support::*;

#[test]
fn caveman_shape_with_isolated_repair_foreign_content_and_tables_is_exactly_equivalent()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "catalog.html",
        concat!(
            "<!doctype html><html><head><title>Catalog</title></head><body><main>",
            "<article class='product-card' data-sku='sku-000000'>",
            "<header><h2>Distractor</h2></header><div class='meta'><span class='price'>USD 12.00</span></div>",
            "<table><tr><td>zero</td></tr></table>",
            "<svg viewBox='0 0 1 1'><title>icon</title><path d='M0 0L1 1'></path></svg>",
            "<p class='recovery'><b>alpha<i>beta</b>gamma</i></article>",
            "<article class='product-card' data-sku='sku-000073'>",
            "<header><h2>Target</h2></header><div class='meta'><span class='price'>USD 19.73</span></div>",
            "<table><tr><td>seventy-three</td></tr></table></article>",
            "</main></body></html>",
        ),
    )?;
    let outcome = assert_default_equivalent(&document, &caveman_plan()?)?;
    let findings = matched(&outcome)?;

    assert_eq!(findings.len(), 1);
    assert_eq!(
        findings.first().map(yosoi_documents::Finding::value),
        Some(&ProjectedValue::Text("USD 19.73".to_owned()))
    );
    assert_eq!(
        findings.first().map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1, 2, 2, 1],
            None,
        )?))
    );
    Ok(())
}

#[test]
fn ancestor_mutations_shift_only_the_final_repaired_tree_coordinate() -> Result<(), Box<dyn Error>>
{
    let plan = caveman_plan()?;
    let cases = [
        (
            "base",
            "<html><head></head><body><main><article class='product-card' data-sku='sku-000073'><header></header><div class='meta'><span class='price'>USD 19.73</span></div></article></main></body></html>",
            vec![1, 2, 1, 1, 2, 1],
        ),
        (
            "body-sibling",
            "<html><head></head><body><nav></nav><main><article class='product-card' data-sku='sku-000073'><header></header><div class='meta'><span class='price'>USD 19.73</span></div></article></main></body></html>",
            vec![1, 2, 2, 1, 2, 1],
        ),
        (
            "main-sibling",
            "<html><head></head><body><main><aside></aside><article class='product-card' data-sku='sku-000073'><header></header><div class='meta'><span class='price'>USD 19.73</span></div></article></main></body></html>",
            vec![1, 2, 1, 2, 2, 1],
        ),
        (
            "article-sibling",
            "<html><head></head><body><main><article class='product-card' data-sku='sku-000073'><header></header><div></div><div class='meta'><span class='price'>USD 19.73</span></div></article></main></body></html>",
            vec![1, 2, 1, 1, 3, 1],
        ),
        (
            "non-element-siblings",
            "<html><head></head><body>text<!--comment--><main><article class='product-card' data-sku='sku-000073'><header></header><div class='meta'><span class='price'>USD 19.73</span></div></article></main></body></html>",
            vec![1, 2, 1, 1, 2, 1],
        ),
    ];

    for (id, source, child_path) in cases {
        let outcome = assert_default_equivalent(&html(id, source)?, &plan)?;
        let finding = matched(&outcome)?
            .first()
            .ok_or_else(|| io::Error::other("coordinate fixture produced no finding"))?;
        assert_eq!(
            finding.coordinate(),
            &NativeCoordinate::SourceTree(TreeCoordinate::try_new(child_path, None)?)
        );
    }
    Ok(())
}

#[test]
fn every_repaired_element_sibling_shifts_coordinates_even_when_the_plan_ignores_it()
-> Result<(), Box<dyn Error>> {
    let plan = caveman_plan()?;
    let document = html(
        "all-ancestor-siblings.html",
        concat!(
            "<html><head></head><body>",
            "<header>body sibling</header><main>",
            "<nav>main sibling one</nav><aside>main sibling two</aside>",
            "<article class='product-card' data-sku='sku-000073'>",
            "<header>article sibling one</header><section>article sibling two</section><div class='meta'>",
            "<i>meta sibling one</i><b>meta sibling two</b><span class='price'>USD 19.73</span>",
            "</div></article><footer>after target</footer>",
            "</main><footer>after main</footer></body></html>",
        ),
    )?;
    let outcome = assert_default_equivalent(&document, &plan)?;
    let finding = matched(&outcome)?
        .first()
        .ok_or_else(|| io::Error::other("ancestor-sibling fixture produced no finding"))?;

    assert_eq!(
        finding.coordinate(),
        &NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 2, 3, 3, 3], None,)?)
    );
    Ok(())
}

#[test]
fn arbitrary_main_children_before_and_after_matching_articles_count_toward_ordinals()
-> Result<(), Box<dyn Error>> {
    let plan = caveman_plan()?;
    let document = html(
        "mixed-main-children.html",
        concat!(
            "<main>leading text<!--leading comment-->",
            "<nav>one</nav><section>two</section>",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>first</span></article>",
            "<aside>between</aside>",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>second</span></article>",
            "<footer>after</footer>trailing text<!--trailing comment-->",
            "</main>",
        ),
    )?;
    let outcome = assert_default_equivalent(&document, &plan)?;
    let findings = matched(&outcome)?;

    assert_eq!(
        findings
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::Text("first".to_owned()),
            ProjectedValue::Text("second".to_owned()),
        ]
    );
    assert_eq!(
        findings
            .iter()
            .map(|finding| finding.coordinate().clone())
            .collect::<Vec<_>>(),
        vec![
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 3, 1], None,)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 5, 1], None,)?),
        ]
    );
    Ok(())
}

#[test]
fn descendant_selector_tracks_extra_named_ancestors_in_the_final_coordinate()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "extra-ancestors.html",
        concat!(
            "<main><article class='product-card' data-sku='sku-000073'>",
            "<section><div><figure><span class='price'>USD 19.73</span></figure></div></section>",
            "</article></main>",
        ),
    )?;
    let outcome = assert_default_equivalent(&document, &caveman_plan()?)?;
    let finding = matched(&outcome)?
        .first()
        .ok_or_else(|| io::Error::other("extra-ancestor fixture produced no finding"))?;

    assert_eq!(
        finding.coordinate(),
        &NativeCoordinate::SourceTree(
            TreeCoordinate::try_new(vec![1, 2, 1, 1, 1, 1, 1, 1], None,)?
        )
    );
    Ok(())
}

#[test]
fn comments_and_text_at_each_ancestor_depth_never_increment_element_ordinals()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "non-element-siblings.html",
        concat!(
            "<!--document-adjacent--><html><head></head><body>",
            "body text<!--body--><main>",
            "main text<!--main--><article class='product-card' data-sku='sku-000073'>",
            "article text<!--article--><div class='meta'>",
            "meta text<!--meta--><span class='price'>USD 19.73</span>",
            "</div></article></main></body></html>",
        ),
    )?;
    let outcome = assert_default_equivalent(&document, &caveman_plan()?)?;
    let finding = matched(&outcome)?
        .first()
        .ok_or_else(|| io::Error::other("non-element sibling fixture produced no finding"))?;

    assert_eq!(
        finding.coordinate(),
        &NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1, 1, 1], None,)?)
    );
    Ok(())
}
