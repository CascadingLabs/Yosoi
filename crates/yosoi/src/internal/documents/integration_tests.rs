#[path = "integration_tests/support/html_fast_modes.rs"]
mod html_fast_modes;
#[path = "integration_tests/support/html_scanner.rs"]
mod html_scanner;
#[path = "integration_tests/support/html_streaming.rs"]
mod html_streaming;
#[path = "integration_tests/support/xml_optimization.rs"]
mod xml_optimization;

mod accessibility;
mod compact_html_semantics;
mod decoded_text;
mod decoded_text_optimization_semantics;
mod document_class_routing_adversarial;
mod document_reconstruction;
mod dom;
mod html;
mod html_fast_api_and_budget_semantics;
mod html_fast_projection_semantics;
mod html_scanner_fail_closed_semantics;
mod html_scanner_positive_semantics;
mod html_scanner_repaired_tree_semantics;
mod html_selector_visit_budgets;
mod html_streaming_budget_semantics;
mod html_streaming_coordinate_semantics;
mod html_streaming_fallback_semantics;
mod json_locators;
mod kernel;
mod tree_text_streaming_regressions;
mod xml;
mod xml_reuse_and_limits;
mod xml_semantic_equivalence;
