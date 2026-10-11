#[test]
fn policy_prelude_supports_the_approved_concise_authoring_surface() {
    use crate::internal::engine::policy::prelude::{Browser, DirectHttp, Headful, Headless, Page};

    let page = Page::new(vec![DirectHttp, Browser(Headless), Browser(Headful)])
        .expect("valid mixed acquisition policy");
    assert_eq!(page.acquisitions.len(), 3);
}
