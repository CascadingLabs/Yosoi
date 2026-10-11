use super::super::{Flow, FlowValidationError, Step};
use crate::{action, expect};

#[test]
fn validates_triggered_and_standalone_expectations() {
    let triggered = action::click("button.checkout").until(
        expect::response("https://shop.example/api/cart")
            .method("POST")
            .status(201)
            .json("/cart/quantity", 1),
    );
    Flow::new([triggered])
        .validate()
        .expect("bounded response expectation should validate");

    let standalone = expect::all([
        expect::visible("#confirmation"),
        expect::ax("Order confirmed").role("status").into(),
    ])
    .until();
    Flow::new([standalone])
        .validate()
        .expect("bounded compound expectation should validate");
}

#[test]
fn rejects_navigation_as_an_until_trigger_before_execution() {
    let step =
        action::navigate("https://shop.example/checkout").until(expect::visible("#confirmation"));
    assert!(matches!(
        Flow::new([step]).validate(),
        Err(FlowValidationError::InvalidUntilTrigger { .. })
    ));
}

#[test]
fn rejects_empty_and_malformed_expectation_data() {
    let empty_url = expect::response("").until();
    assert!(matches!(
        Flow::new([empty_url]).validate(),
        Err(FlowValidationError::EmptyExpectation {
            field: "response URL",
            ..
        })
    ));

    let bad_pointer = expect::response("https://shop.example/api/cart")
        .json("/cart/~2quantity", 1)
        .until();
    assert!(matches!(
        Flow::new([bad_pointer]).validate(),
        Err(FlowValidationError::InvalidExpectation { .. })
    ));
}

#[test]
fn response_json_pointers_follow_rfc6901_escape_rules() {
    for pointer in ["", "/cart/quantity", "/a~0b/~1", "/雪/~01", "/~00", "/~10"] {
        Flow::new([expect::response("https://shop.example/api/cart")
            .json(pointer, 1)
            .until()])
        .validate()
        .expect("root, Unicode and escaped JSON Pointer tokens are valid");
    }
    for pointer in ["cart", "/x~", "/x~2", "/x~~0", "/x~é"] {
        assert!(
            matches!(
                Flow::new([expect::response("https://shop.example/api/cart")
                    .json(pointer, 1)
                    .until()])
                .validate(),
                Err(FlowValidationError::InvalidExpectation { .. })
            ),
            "invalid JSON Pointer: {pointer}"
        );
    }
}

#[test]
fn caps_nested_expectations() {
    let too_deep = (0..10).fold(expect::visible("#confirmation"), |inner, _| {
        expect::all([inner]).into()
    });
    let flow = Flow::new([Step::until_without_trigger(too_deep)]);
    assert!(matches!(
        flow.validate(),
        Err(FlowValidationError::ExpectationTooDeep { .. })
    ));
}
