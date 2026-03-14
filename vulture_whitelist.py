"""Vulture whitelist — false positives from required protocol signatures."""

# __aexit__ parameters are required by the async context manager protocol
exc_type  # noqa
exc_val  # noqa
exc_tb  # noqa
