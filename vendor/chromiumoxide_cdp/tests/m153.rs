use chromiumoxide_cdp::{
    CURRENT_REVISION,
    cdp::{CdpEvent, CdpEventMessage, browser_protocol::target::TargetInfo},
};
use chromiumoxide_types::Message;

#[test]
fn current_revision_matches_chrome_153() {
    assert_eq!(CURRENT_REVISION.to_string(), "v0.0.1681091");
}

#[test]
fn request_extra_info_deserializes_m153_fields() {
    let raw = r#"{
        "method":"Network.requestWillBeSentExtraInfo",
        "params":{
            "requestId":"request-1",
            "associatedCookies":[],
            "headers":{},
            "connectTiming":{"requestTime":1.0},
            "deviceBoundSessionUsages":[],
            "siteHasCookieInOtherPartition":false
        }
    }"#;

    let event = serde_json::from_str::<Message<CdpEventMessage>>(raw)
        .expect("M153 request extra info should deserialize");
    assert!(matches!(
        event,
        Message::Event(CdpEventMessage {
            params: CdpEvent::NetworkRequestWillBeSentExtraInfo(_),
            ..
        })
    ));
}

#[test]
fn target_info_accepts_m153_parent_and_embedder_metadata() {
    let raw = r#"{"targetId":"tab-1","type":"tab","title":"","url":"about:blank","attached":false,"parentId":"browser-1","canAccessOpener":false,"embedderData":{"tabActive":true}}"#;
    let target =
        serde_json::from_str::<TargetInfo>(raw).expect("M153 target info should deserialize");

    assert_eq!(
        target.parent_id.as_ref().map(AsRef::as_ref),
        Some("browser-1")
    );
    assert_eq!(
        target
            .embedder_data
            .as_ref()
            .and_then(|value| value.get("tabActive")),
        Some(&serde_json::Value::Bool(true))
    );
}
