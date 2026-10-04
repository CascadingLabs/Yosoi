// This public SDK example intentionally shows the approved namespace spelling.
#![allow(clippy::absolute_paths)]

use yosoi_policy as ys;

fn main() -> Result<(), ys::PolicyError> {
    let page_policy = ys::policy::Page {
        acquisitions: vec![
            ys::policy::Acquisition::DirectHttp,
            ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless).documents([
                ys::policy::DocumentRequest::RenderedDom,
                ys::policy::DocumentRequest::AccessibilityTree,
            ]),
        ],
    };
    let request_policy = ys::policy::Request {
        direct_http_redirects: ys::policy::DirectHttpRedirects::Disabled,
        ..Default::default()
    };
    let policy = ys::Policy {
        page: page_policy,
        request: request_policy,
        ..Default::default()
    };

    // Keep the authored declaration while making an immutable resolved snapshot.
    let snapshot = ys::PolicySnapshot::from_policy(&policy)?;
    // Canonical JSON is the direct Policy value with no schema envelope.
    println!("{}", policy.to_canonical_json()?);
    println!("{:?}", snapshot.effective_policy());
    println!("{}", snapshot.identity().digest());
    Ok(())
}
