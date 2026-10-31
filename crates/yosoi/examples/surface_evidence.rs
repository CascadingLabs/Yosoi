//! Inspect native accessibility and network evidence through one bounded browser.
use std::{env, error::Error};
use yosoi::surface::{
    Budget, SurfaceConnection, SurfacePolicy,
    browser::{BrowserRepresentation, BrowserSurface},
    model::{ReadOperation, ReadRequest},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error + Send + Sync>> {
    let url = env::args()
        .nth(1)
        .unwrap_or_else(|| "https://cascadinglabs.com/yosoi/getting-started/what-is-yosoi/".into());
    let depth = env::args()
        .nth(2)
        .map(|value| value.parse::<usize>())
        .transpose()?
        .unwrap_or(8);
    let mut policy = SurfacePolicy::default();
    policy.documents.ax.max_depth = depth;
    policy.documents.ax.max_bytes = 524_288;
    policy.documents.ax.response_bytes = 8192;
    policy.documents.network.max_bytes = 262_144;
    policy.documents.network.response_bytes = 8192;
    let mut browser = BrowserSurface::open(&url, policy, true).await?;
    let read = async {
        for representation in [BrowserRepresentation::Ax, BrowserRepresentation::Network] {
            let observation = browser.observe(representation).await?;
            let result = browser
                .read(
                    representation,
                    ReadRequest {
                        operation: ReadOperation::Overview,
                        budget: Budget {
                            bytes: 8192,
                            items: 20,
                        },
                        continuation: None,
                    },
                )
                .await?;
            println!(
                "{}",
                serde_json::to_string(
                    &serde_json::json!({"observation":observation,"result":result})
                )?
            );
        }
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    }
    .await;
    let closed = browser.close().await;
    read?;
    closed?;
    Ok(())
}
