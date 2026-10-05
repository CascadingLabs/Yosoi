"""Rust-backed ordering for public Map SDK values."""

import unittest

from yosoi import map as map_sdk


class MapOrderingTests(unittest.TestCase):
    def test_rust_variant_order_is_used_for_tagged_models(self):
        seed = map_sdk.DiscoverySource(kind="seed")
        html_link = map_sdk.DiscoverySource(kind="html_link")

        self.assertLess(seed, html_link)
        self.assertLessEqual(seed, html_link)
        self.assertGreater(html_link, seed)
        self.assertGreaterEqual(html_link, seed)
        self.assertNotEqual(seed, html_link)
        self.assertEqual(seed, map_sdk.DiscoverySource(kind="seed"))

    def test_observation_uses_rust_source_then_option_url_order(self):
        source = map_sdk.DiscoverySource(kind="seed")
        no_url = map_sdk.Observation(source=source, source_url=None)
        with_url = map_sdk.Observation(
            source=source, source_url="https://example.test/source"
        )
        later_source = map_sdk.Observation(
            source=map_sdk.DiscoverySource(kind="html_link"), source_url=None
        )

        self.assertLess(no_url, with_url)
        self.assertLess(with_url, later_source)

    def test_omission_reason_order_comes_from_rust_enum_declaration(self):
        robots = map_sdk.OmissionReason(kind="robots")
        depth = map_sdk.OmissionReason(kind="depth")

        self.assertLess(robots, depth)
        self.assertGreater(depth, robots)

    def test_relationship_uses_url_fields_then_rust_kind_order(self):
        link = map_sdk.Relationship(
            from_url="https://example.test/from",
            to="https://example.test/to",
            kind="link",
        )
        canonical = map_sdk.Relationship(
            from_url="https://example.test/from",
            to="https://example.test/to",
            kind="canonical",
        )
        later_target = map_sdk.Relationship(
            from_url="https://example.test/from",
            to="https://example.test/z",
            kind="link",
        )

        self.assertLess(link, canonical)
        self.assertLess(link, later_target)

    def test_literal_aliases_use_the_typed_comparison_helper(self):
        self.assertEqual(
            map_sdk.compare_values("rejection", "unsupported_scheme", "credentials"),
            -1,
        )
        self.assertEqual(
            map_sdk.compare_values("relationship_kind", "link", "canonical"), -1
        )
        self.assertEqual(
            map_sdk.compare_values("relationship_kind", "redirect", "canonical"),
            -1,
        )

    def test_public_provider_remains_a_string_enum(self):
        provider = map_sdk.PublicProvider.crt_sh

        self.assertIsInstance(provider, str)
        self.assertEqual(provider, "crt_sh")
        self.assertLess(provider, "wayback_archive")
        self.assertEqual(
            map_sdk.compare_values("public_provider", "crt_sh", "wayback_archive"),
            -1,
        )


if __name__ == "__main__":
    unittest.main()
