use std::{error::Error, hint::black_box, time::Instant};
use url::Url;
use yosoi_dev_support::internal::map::{
    admission::{Scope, normalize},
    sources::parse_sitemap,
};
use yosoi_dev_support::internal::policy::policy::Map;

fn main() -> Result<(), Box<dyn Error>> {
    let seed = Url::parse("https://example.com/docs/")?;
    let policy = Map::default();
    let scope = Scope::new(&seed, &policy)?;
    let start = Instant::now();
    for _ in 0..10_000 {
        let url = normalize(black_box("/docs/page?x=1#fragment"), Some(&seed), 8192)?;
        scope.admit(black_box(&url))?;
    }
    println!("normalize_and_admit_10000={:?}", start.elapsed());
    let sitemap = b"<urlset><url><loc>https://example.com/docs/page</loc></url></urlset>";
    let start = Instant::now();
    for _ in 0..10_000 {
        black_box(parse_sitemap(black_box(sitemap), 500, 2_097_152)?);
    }
    println!("parse_sitemap_10000={:?}", start.elapsed());
    Ok(())
}
