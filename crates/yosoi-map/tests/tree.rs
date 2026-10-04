use url::Url;
use yosoi_map::{
    DiscoverySource, Exploration, Observation, PageEntry, Relationship, RelationshipKind,
    TreeEntry, tree,
};

fn url(value: &str) -> Url {
    Url::parse(value).expect("test URL is valid")
}

fn page(value: &str, minimum_link_depth: Option<u16>) -> PageEntry {
    PageEntry {
        url: url(value),
        minimum_link_depth,
        observations: if minimum_link_depth == Some(0) {
            vec![Observation {
                source: DiscoverySource::Seed,
                source_url: None,
            }]
        } else {
            Vec::new()
        },
        exploration: Exploration::Inventoried,
    }
}

fn sitemap_page(value: &str) -> PageEntry {
    PageEntry {
        url: url(value),
        minimum_link_depth: None,
        observations: vec![Observation {
            source: DiscoverySource::Sitemap,
            source_url: Some(url("https://example.com/sitemap.xml")),
        }],
        exploration: Exploration::Inventoried,
    }
}

fn relationship(from: &str, to: &str, kind: RelationshipKind) -> Relationship {
    Relationship {
        from: url(from),
        to: url(to),
        kind,
    }
}

fn entry<'a>(tree: &'a [TreeEntry], value: &str) -> &'a TreeEntry {
    let page = url(value);
    tree.iter()
        .find(|entry| entry.page == page)
        .expect("tree contains every inventoried page")
}

#[test]
fn zero_cost_redirect_and_multiple_parents_keep_the_minimum_link_depth() {
    let root = "https://example.com/";
    let link_parent = "https://example.com/a";
    let redirect_parent = "https://example.com/b";
    let child = "https://example.com/x";
    let pages = vec![
        page(root, Some(0)),
        page(link_parent, None),
        page(redirect_parent, None),
        page(child, None),
    ];
    let edges = vec![
        relationship(root, link_parent, RelationshipKind::Link),
        relationship(root, redirect_parent, RelationshipKind::Redirect),
        relationship(link_parent, child, RelationshipKind::Link),
        relationship(redirect_parent, child, RelationshipKind::Link),
    ];

    let result = tree(&pages, &edges);

    assert_eq!(entry(&result, redirect_parent).parent, Some(url(root)));
    assert_eq!(entry(&result, redirect_parent).depth, Some(0));
    assert_eq!(entry(&result, child).parent, Some(url(redirect_parent)));
    assert_eq!(entry(&result, child).depth, Some(1));
}

#[test]
fn equal_depth_multiple_parents_have_a_stable_url_ordered_parent() {
    let first_root = "https://example.com/a-root";
    let second_root = "https://example.com/b-root";
    let child = "https://example.com/child";
    let pages = vec![
        page(second_root, Some(0)),
        page(first_root, Some(0)),
        page(child, None),
    ];
    let edges = vec![
        relationship(second_root, child, RelationshipKind::Link),
        relationship(first_root, child, RelationshipKind::Link),
    ];

    let result = tree(&pages, &edges);

    assert_eq!(entry(&result, child).parent, Some(url(first_root)));
    assert_eq!(entry(&result, child).depth, Some(1));
}

#[test]
fn redirect_cycles_terminate_and_unattached_sitemap_pages_keep_unknown_depth() {
    let root = "https://example.com/";
    let redirected = "https://example.com/redirected";
    let child = "https://example.com/child";
    let sitemap_one = "https://example.com/from-sitemap-one";
    let sitemap_two = "https://example.com/from-sitemap-two";
    let pages = vec![
        page(root, Some(0)),
        page(redirected, None),
        page(child, None),
        sitemap_page(sitemap_one),
        sitemap_page(sitemap_two),
    ];
    let edges = vec![
        relationship(root, redirected, RelationshipKind::Redirect),
        relationship(redirected, root, RelationshipKind::Redirect),
        relationship(redirected, child, RelationshipKind::Link),
        relationship(child, redirected, RelationshipKind::Redirect),
    ];

    let result = tree(&pages, &edges);

    assert_eq!(result.len(), pages.len());
    assert_eq!(entry(&result, root).parent, None);
    assert_eq!(entry(&result, root).depth, Some(0));
    assert_eq!(entry(&result, redirected).parent, Some(url(root)));
    assert_eq!(entry(&result, redirected).depth, Some(0));
    assert_eq!(entry(&result, child).parent, Some(url(redirected)));
    assert_eq!(entry(&result, child).depth, Some(1));
    for sitemap_page in [sitemap_one, sitemap_two] {
        assert_eq!(entry(&result, sitemap_page).parent, None);
        assert_eq!(entry(&result, sitemap_page).depth, None);
    }
}

#[test]
fn redirect_target_at_depth_zero_keeps_the_authored_seed_as_parent() {
    let seed = page("https://example.com/about", Some(0));
    let mut target = page("https://example.com/about/", Some(0));
    target.observations = vec![Observation {
        source: DiscoverySource::Redirect,
        source_url: Some(seed.url.clone()),
    }];
    let edges = vec![relationship(
        seed.url.as_str(),
        target.url.as_str(),
        RelationshipKind::Redirect,
    )];
    let result = tree(&[seed.clone(), target.clone()], &edges);
    let redirected = result
        .iter()
        .find(|entry| entry.page == target.url)
        .expect("redirect target retained");
    assert_eq!(redirected.parent, Some(seed.url));
    assert_eq!(redirected.depth, Some(0));
}
