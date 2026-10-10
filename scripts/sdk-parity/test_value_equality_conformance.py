"""Keep projected-value equality evidence tied to Rust PartialEq inputs."""

import copy
import unittest

from run_value_equality_conformance import (
    observe_fixture,
    operation_passes,
    payload_checks,
    select_comparisons,
)


class ValueEqualityResultTests(unittest.TestCase):
    class ShapeAdapter:
        def validate_python(self, value):
            return value

        def dump_python(self, value, *, mode, exclude_none):
            del mode, exclude_none
            return value

    def setUp(self):
        self.comparison = {
            "rust": {
                "expected_eq": False,
                "expected_ne": True,
                "rust_eq": False,
                "rust_ne": True,
                "fixture_passed": True,
            },
            "python": {
                "helper_eq": False,
                "helper_ne": True,
                "json_operator_eq": False,
                "json_operator_ne": True,
            },
            "typed_values_equal": True,
        }

    def test_actual_eq_and_ne_must_both_match_the_expected_rust_case(self):
        self.assertTrue(operation_passes(self.comparison, "eq"))
        self.assertTrue(operation_passes(self.comparison, "ne"))
        self.assertFalse(operation_passes(self.comparison, "fmt"))

        mismatched = copy.deepcopy(self.comparison)
        mismatched["python"]["helper_eq"] = True
        self.assertFalse(operation_passes(mismatched, "eq"))
        mismatched = copy.deepcopy(self.comparison)
        mismatched["python"]["json_operator_ne"] = False
        self.assertFalse(operation_passes(mismatched, "ne"))
        mismatched = copy.deepcopy(self.comparison)
        mismatched["rust"]["rust_ne"] = False
        mismatched["rust"]["fixture_passed"] = False
        self.assertFalse(operation_passes(mismatched, "ne"))

    def test_non_json_values_do_not_require_json_model_operator_evidence(self):
        comparison = copy.deepcopy(self.comparison)
        comparison["python"]["json_operator_eq"] = None
        comparison["python"]["json_operator_ne"] = None
        self.assertTrue(operation_passes(comparison, "eq"))
        self.assertTrue(operation_passes(comparison, "ne"))

    def test_observer_uses_raw_rust_fixture_fields_and_typed_python_helper(self):
        left = {"kind": "text", "value": "first"}
        right = {"kind": "text", "value": "second"}
        fixture = {
            "name": "different-text",
            "left": left,
            "right": right,
            "expected_eq": False,
            "expected_ne": True,
            "rust_eq": False,
            "rust_ne": True,
            "fixture_passed": True,
        }
        observed = observe_fixture(
            fixture,
            self.ShapeAdapter(),
            {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b},
        )
        self.assertEqual(observed["rust"]["left"], left)
        self.assertEqual(observed["python"]["right"], right)
        self.assertEqual(observed["rustReceiver"], {"self": left})
        self.assertEqual(observed["rustArguments"], {"other": right})
        self.assertTrue(observed["eqPassed"])
        self.assertTrue(observed["nePassed"])
        self.assertTrue(observed["equal"])
        self.assertEqual(observed["rustSha256"], observed["pythonSha256"])

        fixture["rust_eq"] = True
        fixture["fixture_passed"] = False
        mismatched = observe_fixture(
            fixture,
            self.ShapeAdapter(),
            {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b},
        )
        self.assertFalse(mismatched["eqPassed"])

    def test_json_null_is_retained_as_a_value_in_evidence(self):
        from pydantic import TypeAdapter

        from yosoi.outcomes import ProjectedValue

        value = {"kind": "json", "value": None}
        fixture = {
            "name": "null",
            "left": value,
            "right": value,
            "expected_eq": True,
            "expected_ne": False,
            "rust_eq": True,
            "rust_ne": False,
            "fixture_passed": True,
        }
        observed = observe_fixture(
            fixture,
            TypeAdapter(ProjectedValue),
            {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b},
        )
        self.assertEqual(observed["python"]["left"], value)
        self.assertEqual(observed["rustSha256"], observed["pythonSha256"])
        self.assertTrue(observed["equal"])


class ValueEqualityAttributionTests(unittest.TestCase):
    def setUp(self):
        self.comparisons = [{"name": "one-pair"}]
        self.entry = {
            "decision": "mapped",
            "rustPath": "yosoi::locators::ProjectedValue::eq",
            "symbolKey": (
                "member:function:yosoi::locators::ProjectedValue::eq"
                "@signature:abc@trait:PartialEq@source:def"
            ),
            "trait": "PartialEq",
            "pythonTarget": "yosoi.outcomes.projected_values_equal",
            "receiverMapping": {"rustArgument": "self", "pythonArgument": "left"},
            "argumentMappings": [{"rustArgument": "other", "pythonArgument": "right"}],
        }

    def test_selector_requires_exact_projected_value_partial_eq_operation(self):
        self.assertEqual(
            select_comparisons(self.entry, self.comparisons), self.comparisons
        )

        unsupported = copy.deepcopy(self.entry)
        unsupported["rustPath"] = "yosoi::locators::Document::eq"
        self.assertEqual(select_comparisons(unsupported, self.comparisons), [])
        unsupported = copy.deepcopy(self.entry)
        unsupported["trait"] = "Clone"
        self.assertEqual(select_comparisons(unsupported, self.comparisons), [])
        unsupported = copy.deepcopy(self.entry)
        unsupported["decision"] = "language-specific"
        self.assertEqual(select_comparisons(unsupported, self.comparisons), [])
        unsupported = copy.deepcopy(self.entry)
        unsupported["receiverMapping"]["pythonArgument"] = "missing"
        self.assertEqual(select_comparisons(unsupported, self.comparisons), [])
        unsupported = copy.deepcopy(self.entry)
        unsupported["argumentMappings"] = []
        self.assertEqual(select_comparisons(unsupported, self.comparisons), [])

    def test_ne_requires_its_own_python_target_and_symbol_key(self):
        not_equal = copy.deepcopy(self.entry)
        not_equal["rustPath"] = "yosoi::locators::ProjectedValue::ne"
        not_equal["symbolKey"] = (
            "member:function:yosoi::locators::ProjectedValue::ne@signature:ghi@trait:PartialEq@source:jkl"
        )
        not_equal["pythonTarget"] = "yosoi.outcomes.projected_values_not_equal"
        self.assertEqual(
            select_comparisons(not_equal, self.comparisons), self.comparisons
        )

        wrong_mapping = copy.deepcopy(not_equal)
        wrong_mapping["pythonTarget"] = "yosoi.outcomes.projected_values_equal"
        self.assertEqual(select_comparisons(wrong_mapping, self.comparisons), [])
        wrong_mapping = copy.deepcopy(not_equal)
        wrong_mapping["symbolKey"] = self.entry["symbolKey"]
        self.assertEqual(select_comparisons(wrong_mapping, self.comparisons), [])

    def test_both_receiver_and_other_operands_are_checked_including_json_null(self):
        left = {"kind": "json", "value": {"active": True}}
        right = {"kind": "json", "value": None}
        selected = [
            {
                "rustReceiver": {"self": left},
                "rustArguments": {"other": right},
                "pythonArguments": {"left": left, "right": right},
            }
        ]
        entry = {
            "receiverMapping": {
                "rustArgument": "self",
                "pythonArgument": "left",
            },
            "argumentMappings": [{"rustArgument": "other", "pythonArgument": "right"}],
        }
        checks = payload_checks(entry, selected)
        self.assertEqual([check["kind"] for check in checks], ["receiver", "argument"])
        self.assertTrue(all(check["equal"] for check in checks))

        selected[0]["pythonArguments"].pop("right")
        self.assertFalse(payload_checks(entry, selected)[1]["equal"])


if __name__ == "__main__":
    unittest.main()
