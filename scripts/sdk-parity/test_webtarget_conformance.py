"""Focused checks for WebTarget raw conversion parity and attribution."""

import unittest

from run_webtarget_conformance import (
    AS_REF_PATH,
    AS_STR_PATH,
    EXPECTED_CONVERSIONS,
    EXPECTED_VALUES,
    NEW_PATH,
    OPERATION_PATH,
    _conversion_item,
    _mapping_check,
    compare_fixture,
    evidence_cases,
    validate_fixture_set,
)

import parity


def _fixture_set():
    cases = []
    for value_name, input_value in EXPECTED_VALUES.items():
        for conversion, rust_type in EXPECTED_CONVERSIONS.items():
            cases.append(
                {
                    "name": f"{value_name}/{conversion}",
                    "valueName": value_name,
                    "conversion": conversion,
                    "rustArgumentType": rust_type,
                    "operationPath": OPERATION_PATH,
                    "operationTrait": "From",
                    "asRefPath": AS_REF_PATH,
                    "asRefTrait": "AsRef",
                    "newPath": NEW_PATH,
                    "asStrPath": AS_STR_PATH,
                    "input": input_value,
                    "raw": input_value,
                    "asRefRaw": input_value,
                    "newRaw": input_value,
                    "asStrRaw": input_value,
                    "fixturePassed": True,
                }
            )
    return {
        "schemaVersion": 1,
        "kind": "yosoi-web-target-conversion-fixtures",
        "cases": cases,
    }


def _rust_item(path, trait, key, argument_type=None):
    arguments = []
    if argument_type is not None:
        arguments.append({"name": "value", "type": argument_type, "receiver": False})
    return {
        "rustPath": path,
        "trait": trait,
        "symbolKey": key,
        "kind": "function",
        "rustArguments": arguments,
    }


class WebTargetConformanceTests(unittest.TestCase):
    def test_fixture_contract_requires_four_values_and_all_six_conversions(self):
        fixture_set = _fixture_set()
        self.assertEqual(len(validate_fixture_set(fixture_set)), 24)
        self.assertIn("https://例え.テスト/道?q=雪", EXPECTED_VALUES.values())
        self.assertIn("", EXPECTED_VALUES.values())

        fixture_set["cases"].pop()
        with self.assertRaises(ValueError):
            validate_fixture_set(fixture_set)

    def test_invalid_authored_text_is_compared_without_url_normalization(self):
        fixture = next(
            item
            for item in _fixture_set()["cases"]
            if item["name"] == "invalid-authored-text/from-str"
        )
        observed = {
            "input": fixture["input"],
            "raw": "not a URL/雪",
            "targetType": "yosoi.request.WebTarget",
        }
        comparison = compare_fixture(
            fixture,
            observed,
            None,
            None,
            None,
            None,
            parity,
        )
        self.assertFalse(comparison["equal"])
        self.assertNotEqual(comparison["rustSha256"], comparison["pythonSha256"])

    def test_cow_ownership_modes_resolve_to_the_same_exact_from_impl(self):
        cow_item = _rust_item(
            OPERATION_PATH, "From", "from-cow-symbol", "std::borrow::Cow<'value, str>"
        )
        rust = {"items": [cow_item]}
        cases = [
            item
            for item in _fixture_set()["cases"]
            if item["conversion"] in {"from-cow-borrowed", "from-cow-owned"}
        ]
        for fixture in cases:
            self.assertIs(_conversion_item(rust, fixture), cow_item)

    def test_evidence_requires_exact_mapped_inventory_symbol(self):
        fixture = _fixture_set()["cases"][0]
        from_item = _rust_item(OPERATION_PATH, "From", "from-symbol", "&str")
        as_ref_item = _rust_item(AS_REF_PATH, "AsRef", "as-ref-inventory-symbol")
        new_item = _rust_item(NEW_PATH, None, "new-symbol", "impl Into<String>")
        as_str_item = _rust_item(AS_STR_PATH, None, "as-str-symbol")
        rust = {"items": [from_item, as_ref_item, new_item, as_str_item]}
        comparison = compare_fixture(
            fixture,
            {
                "input": fixture["input"],
                "raw": fixture["input"],
                "targetType": "WebTarget",
            },
            from_item,
            as_ref_item,
            new_item,
            as_str_item,
            parity,
        )
        ledger = {
            "entries": [
                {
                    "rustPath": OPERATION_PATH,
                    "symbolKey": "from-symbol",
                    "trait": "From",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.request.WebTarget.new",
                    "argumentMappings": [
                        {
                            "rustArgument": "value",
                            "pythonArgument": "value",
                            "conversion": "String to str",
                        }
                    ],
                },
                {
                    "rustPath": AS_REF_PATH,
                    "symbolKey": "out-of-date-key",
                    "trait": "AsRef",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.request.WebTarget.as_str",
                    "argumentMappings": [],
                },
            ]
        }

        cases = evidence_cases(ledger, [comparison], rust)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["rustPath"], OPERATION_PATH)
        self.assertEqual(cases[0]["symbolKey"], "from-symbol")
        self.assertEqual(cases[0]["outcome"], "passed")


class ArgumentEvidenceTests(unittest.TestCase):
    def test_different_python_argument_cannot_verify_the_mapping(self):
        entry = {
            "argumentMappings": [{"rustArgument": "value", "pythonArgument": "value"}]
        }
        checks = _mapping_check(entry, "https://example.com", "different")
        self.assertFalse(checks[0]["equal"])
        self.assertNotEqual(checks[0]["rustSha256"], checks[0]["pythonSha256"])


if __name__ == "__main__":
    unittest.main()
