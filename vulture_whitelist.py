"""Vulture whitelist — false positives from required protocol signatures."""

# __aexit__ parameters are required by the async context manager protocol
exc_type  # noqa
exc_val  # noqa
exc_tb  # noqa

# TYPE_CHECKING imports used in string annotations (invisible to vulture)
TaskiqResult  # noqa
AsyncTaskiqTask  # noqa
