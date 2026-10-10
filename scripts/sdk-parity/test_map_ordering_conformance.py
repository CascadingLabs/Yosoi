"""Focused checks for Map ordering machine-proof attribution."""

import copy
import unittest

from run_map_ordering_conformance import (
    _ord_symbol,
    argument_checks,
    comparison_passes,
)


class MapOrderingConformanceTests(unittest.TestCase):
    def test_payload_checks_compare_rust_self_and_other_with_python_left_right(self):
        selected = [
            {
                "kind": "discovery_source",
                "rustReceiver": {"self": {"kind": "seed"}},
                "rustArguments": {"other": {"kind": "html_link"}},
                "pythonArguments": {
                    "kind": "discovery_source",
                    "left": {"kind": "seed"},
                    "right": {"kind": "html_link"},
                },
            }
        ]

        checks = argument_checks(selected)

        self.assertEqual([check["key"] for check in checks], ["self", "other", "kind"])
        self.assertEqual(
            [check["kind"] for check in checks], ["receiver", "argument", "fixed"]
        )
        self.assertTrue(all(check["equal"] for check in checks))
        self.assertEqual(checks[0]["rustSha256"], checks[0]["pythonSha256"])
        self.assertEqual(checks[1]["rustSha256"], checks[1]["pythonSha256"])

        selected[0]["pythonArguments"]["left"] = {"kind": "robots"}
        self.assertFalse(argument_checks(selected)[0]["equal"])
        selected[0]["pythonArguments"]["kind"] = "relationship"
        self.assertFalse(argument_checks(selected)[2]["equal"])

    def test_comparison_requires_both_rust_orders_and_python_order(self):
        comparison = {
            "passed": True,
            "rust": {
                "expected_cmp": -1,
                "rust_cmp": -1,
                "rust_partial_cmp": -1,
                "fixture_passed": True,
            },
            "python": {"cmp": -1, "operators": {"lt": True}},
        }
        self.assertTrue(comparison_passes(comparison))
        comparison["passed"] = False
        self.assertFalse(comparison_passes(comparison))

    def test_rust_reference_selection_requires_the_public_ord_cmp(self):
        valid = {
            "rustPath": "yosoi::map::Relationship::cmp",
            "trait": "Ord",
            "kind": "function",
            "symbolKey": "member:function:yosoi::map::Relationship::cmp@trait:Ord",
        }
        inventory = {"items": [valid]}

        self.assertEqual(_ord_symbol(inventory, valid["rustPath"]), valid)
        for field, value in (("trait", "PartialOrd"), ("kind", "struct_field")):
            unsupported = copy.deepcopy(valid)
            unsupported[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                _ord_symbol({"items": [unsupported]}, valid["rustPath"])


if __name__ == "__main__":
    unittest.main()
