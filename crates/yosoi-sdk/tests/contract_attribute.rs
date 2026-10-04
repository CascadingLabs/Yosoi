use yosoi_sdk::prelude as ys;

#[derive(ys::Contract)]
#[ys(id = "search_hit", description = "One search result", root = ys::locator::css("li.result"))]
struct SearchHit {
    #[ys(description = "Result link", locator = ys::locator::css("a[href]").attribute("href"))]
    href: String,
    #[ys(description = "Result title", locator = ys::locator::css("a[href]").text())]
    title: String,
}

#[test]
fn public_contract_sdk_validates_result_links_per_row() -> Result<(), Box<dyn std::error::Error>> {
    let document = ys::Document::html(
        "search.html",
        b"<ul><li class='result'><a href='https://a.example/'>A</a></li><li class='result'><a href='https://b.example/'>B</a></li></ul>".to_vec(),
    )?;
    let results = SearchHit::extract(&SearchHit::locate(&document)?)
        .validate()
        .require_all()?;
    assert_eq!(results.len(), 2);
    assert_eq!(
        results.first().map(|row| row.href.as_str()),
        Some("https://a.example/")
    );
    assert_eq!(results.get(1).map(|row| row.title.as_str()), Some("B"));
    Ok(())
}
