#![allow(clippy::panic_in_result_fn)]
use super::support::*;

#[test]
fn stray_br_and_p_end_tags_before_a_candidate_use_repaired_element_ordinals()
-> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    for (id, stray) in [("stray-br.html", "</br>"), ("stray-p.html", "</p>")] {
        let body = format!(
            "{stray}<article class='product-card' data-sku='sku-000073'><span class='price'>{id}</span></article>"
        );
        assert_matches(
            &exact_outcome(&document(id, &body)?, &plan)?,
            &[(id.to_owned(), vec![1, 2, 1, 2, 1])],
        )?;
    }
    Ok(())
}

#[test]
fn implied_p_and_li_closures_with_nested_descendants_preserve_final_paths()
-> Result<(), Box<dyn Error>> {
    let plan = plan()?;
    let paragraph = document(
        "implied-p.html",
        concat!(
            "<article class='product-card' data-sku='sku-000073'>",
            "<p><span>nested paragraph text</span><div>new block</div>",
            "<span class='price'>paragraph</span></article>",
        ),
    )?;
    assert_matches(
        &exact_outcome(&paragraph, &plan)?,
        &[("paragraph".to_owned(), vec![1, 2, 1, 1, 3])],
    )?;

    let list = document(
        "implied-li.html",
        concat!(
            "<article class='product-card' data-sku='sku-000073'><ul>",
            "<li><div><span>first item</span></div>",
            "<li><span>second item</span><span class='price'>list</span>",
            "</ul></article>",
        ),
    )?;
    assert_matches(
        &exact_outcome(&list, &plan)?,
        &[("list".to_owned(), vec![1, 2, 1, 1, 1, 2, 2])],
    )?;
    Ok(())
}

#[test]
fn generic_two_step_grids_preserve_all_siblings_matches_and_coordinates()
-> Result<(), Box<dyn Error>> {
    let cases = [
        (
            "div-grid.html",
            "div.card span.price",
            concat!(
                "<nav>before</nav><section>",
                "<div class='card'><span class='price'>A</span></div>",
                "text<!--comment--><aside>between</aside>",
                "<div class='card'><div><span class='price'>B</span></div></div>",
                "</section><footer>after</footer>",
            ),
            vec![
                ("A".to_owned(), vec![1, 2, 1, 2, 1, 1]),
                ("B".to_owned(), vec![1, 2, 1, 2, 3, 1, 1]),
            ],
        ),
        (
            "list-grid.html",
            "li.product span.price",
            concat!(
                "<header>before</header><ul>",
                "<li>noise</li><li class='product'><span>name</span><span class='price'>C</span></li>",
                "<li class='product'><div><span class='price'>D</span></div></li>",
                "</ul><footer>after</footer>",
            ),
            vec![
                ("C".to_owned(), vec![1, 2, 1, 2, 2, 2]),
                ("D".to_owned(), vec![1, 2, 1, 2, 3, 1, 1]),
            ],
        ),
        (
            "section-grid.html",
            "section.item em.cost",
            concat!(
                "<div><p>before</p>",
                "<section class='item'><strong>label</strong><em class='cost'>E</em></section>",
                "<!--between--><article>noise</article>",
                "<section class='item'><div><em class='cost'>F</em></div></section>",
                "</div>",
            ),
            vec![
                ("E".to_owned(), vec![1, 2, 1, 1, 2, 2]),
                ("F".to_owned(), vec![1, 2, 1, 1, 4, 1, 1]),
            ],
        ),
    ];

    for (id, selector, body, expected) in cases {
        let plan = Plan::new([output("values", css(selector)?.text())?])?;
        assert_matches(&exact_outcome(&document(id, body)?, &plan)?, &expected)?;
    }
    Ok(())
}

#[test]
fn hard_shaped_thousand_record_catalog_preserves_sparse_multi_match_results()
-> Result<(), Box<dyn Error>> {
    const RECORDS: usize = 1_024;
    let targets = [0_usize, 73, 511, 1_023];
    let mut body = String::new();
    for index in 0..RECORDS {
        let sku = if targets.contains(&index) {
            "sku-000073".to_owned()
        } else {
            format!("other-{index:06}")
        };
        write!(
            &mut body,
            concat!(
                "<article class='product-card card-{index}' data-sku='{sku}' data-copy='{copy}'>",
                "<header><h2>Product {index}</h2></header>",
                "<div class='meta'><span class='price'>USD {index}.73</span><span class='availability'>stock</span></div>",
                "<div class='body'><p>description {index}</p></div>",
                "<ul><li>tag-a</li><li>tag-b</li></ul>",
                "<table><tr><td>{index}</td><td>{sku}</td></tr></table>",
                "</article>",
            ),
            index = index,
            sku = sku,
            copy = index % 29,
        )?;
    }
    let outcome = exact_outcome(&document("hard-shaped-1024.html", &body)?, &plan()?)?;
    let expected = targets
        .iter()
        .map(|index| {
            Ok((
                format!("USD {index}.73"),
                vec![1, 2, 1, u32::try_from(index.saturating_add(1))?, 2, 1],
            ))
        })
        .collect::<Result<Vec<_>, TryFromIntError>>()?;
    assert_matches(&outcome, &expected)?;
    Ok(())
}
