use std::{error::Error, io};

use yosoi::{policy, prelude as ys};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = ys::Policy {
        page: policy::Page {
            acquisitions: vec![policy::Acquisition::DirectHttp],
        },
        ..ys::Policy::default()
    };
    let response = ys::request::new("https://example.com/")
        .bind(&policy)
        .send()
        .await?;
    let mut attempts = response.attempts();
    let attempt = attempts
        .next()
        .ok_or_else(|| io::Error::other("expected one acquisition attempt"))?;
    println!("HTTP status: {:?}", attempt.status());
    Ok(())
}
