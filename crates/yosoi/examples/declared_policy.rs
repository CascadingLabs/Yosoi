use std::{error::Error, io};

use yosoi::prelude as ys;
use ys::policy::prelude as policy_types;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = ys::Policy {
        page: policy_types::Page {
            acquisitions: vec![policy_types::DirectHttp],
        },
        ..ys::Policy::default()
    };
    let response = ys::request::new("https://example.com/")
        .bind(&policy)
        .send()
        .await?;
    let attempt = response
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("expected one acquisition attempt"))?;
    println!("HTTP status: {:?}", attempt.status());
    Ok(())
}
