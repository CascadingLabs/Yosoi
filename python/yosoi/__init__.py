"""Pydantic authoring and typed outcomes over the Yosoi Rust SDK."""

from __future__ import annotations

from importlib.metadata import version as _distribution_version

from . import _native as _native
from . import archive as archive
from . import browser as browser
from . import contracts as contracts
from . import documents as documents
from . import locators as locators
from . import map as map
from . import policy as policy
from . import request as request
from . import search as search
from . import surface as surface
from . import view as view
from .archive import Archive as Archive
from .archive import AutomationRecord as AutomationRecord
from .browser import (
    BoundFlow as BoundFlow,
)
from .browser import (
    BrowserCleanupError as BrowserCleanupError,
)
from .browser import (
    BrowserError as BrowserError,
)
from .browser import (
    Flow as Flow,
)
from .browser import (
    FlowExecutionError as FlowExecutionError,
)
from .browser import (
    FlowInvocationError as FlowInvocationError,
)
from .browser import (
    FlowOutcome as FlowOutcome,
)
from .browser import (
    Session as Session,
)
from .browser import (
    SessionPolicy as SessionPolicy,
)
from .browser import (
    Work as Work,
)
from .browser import (
    all_of as all_of,
)
from .browser import (
    assert_all as assert_all,
)
from .browser import (
    assert_that as assert_that,
)
from .browser import (
    ax as ax,
)
from .browser import (
    check as check,
)
from .browser import (
    click as click,
)
from .browser import (
    count_at_least as count_at_least,
)
from .browser import (
    enter_text as enter_text,
)
from .browser import (
    evaluate as evaluate,
)
from .browser import (
    evaluate_file as evaluate_file,
)
from .browser import (
    exists as exists,
)
from .browser import (
    flow as flow,
)
from .browser import (
    navigate as navigate,
)
from .browser import (
    response as response,
)
from .browser import (
    run_module as run_module,
)
from .browser import (
    run_module_with_export as run_module_with_export,
)
from .browser import (
    screenshot as screenshot,
)
from .browser import (
    session as session,
)
from .browser import (
    timed as timed,
)
from .browser import (
    until as until,
)
from .browser import (
    visible as visible,
)
from .browser import (
    wait as wait,
)
from .browser import (
    wait_until as wait_until,
)
from .cancellation import CancellationToken as CancellationToken
from .contracts import Contract as Contract
from .contracts import ExtractionPolicy as ExtractionPolicy
from .contracts import Field as Field
from .contracts import extract as extract
from .contracts import extract_report as extract_report
from .documents import Document as Document
from .locators import (
    Plan as Plan,
)
from .locators import (
    accessibility_state as accessibility_state,
)
from .locators import (
    accessibility_text as accessibility_text,
)
from .locators import (
    accessible_name as accessible_name,
)
from .locators import (
    css as css,
)
from .locators import (
    json_path as json_path,
)
from .locators import (
    json_pointer as json_pointer,
)
from .locators import (
    output as output,
)
from .locators import (
    regex as regex,
)
from .locators import (
    role as role,
)
from .locators import (
    text_literal as text_literal,
)
from .locators import (
    tree_text_contains as tree_text_contains,
)
from .locators import (
    xpath as xpath,
)
from .policy import Continuation as Continuation
from .policy import Continue as Continue
from .policy import FlowPolicy as FlowPolicy
from .policy import Policy as Policy
from .policy import Stop as Stop
from .policy import StopScope as StopScope
from .surface import (
    Budget as SurfaceBudget,
)
from .surface import (
    DecodedFrame as DecodedFrame,
)
from .surface import (
    Limits as SurfaceLimits,
)
from .surface import (
    PixelRect as PixelRect,
)
from .surface import (
    Session as SurfaceSession,
)
from .surface import (
    SessionPolicy as SurfaceSessionPolicy,
)
from .surface import (
    Surface as Surface,
)
from .surface import (
    SurfaceError as SurfaceError,
)
from .surface import (
    VideoError as VideoError,
)
from .surface import (
    VideoPolicy as VideoPolicy,
)
from .surface import (
    VideoSurface as VideoSurface,
)
from .surface import (
    WebSurface as WebSurface,
)
from .view import View as View

__version__ = _distribution_version("yosoi")

__all__ = [
    "BrowserSurface",
    "VideoSession",
    "SurfaceConnection",
    "SurfacePolicy",
    "ExecutionError",
    "Surface",
    "SurfaceError",
    "SurfaceBudget",
    "SurfaceLimits",
    "SurfaceSession",
    "SurfaceSessionPolicy",
    "WebSurface",
    "VideoSurface",
    "VideoPolicy",
    "VideoError",
    "DecodedFrame",
    "PixelRect",
    "archive",
    "view",
    "Archive",
    "AutomationRecord",
    "View",
    "__version__",
    "CancellationToken",
    "BoundFlow",
    "BrowserCleanupError",
    "BrowserError",
    "Flow",
    "FlowExecutionError",
    "FlowInvocationError",
    "FlowOutcome",
    "Session",
    "SessionPolicy",
    "Work",
    "assert_all",
    "assert_that",
    "all_of",
    "ax",
    "check",
    "click",
    "count_at_least",
    "enter_text",
    "evaluate",
    "evaluate_file",
    "exists",
    "flow",
    "navigate",
    "response",
    "run_module",
    "run_module_with_export",
    "screenshot",
    "session",
    "timed",
    "until",
    "visible",
    "wait",
    "wait_until",
    "Contract",
    "ExtractionPolicy",
    "Field",
    "extract",
    "extract_report",
    "contracts",
    "browser",
    "documents",
    "locators",
    "map",
    "policy",
    "request",
    "search",
    "surface",
    "Document",
    "Plan",
    "Policy",
    "Continuation",
    "Continue",
    "Stop",
    "StopScope",
    "FlowPolicy",
    "accessibility_state",
    "accessibility_text",
    "accessible_name",
    "css",
    "json_path",
    "json_pointer",
    "output",
    "regex",
    "role",
    "text_literal",
    "tree_text_contains",
    "xpath",
]

from .surface import BrowserSurface as BrowserSurface
from .surface import ExecutionError as ExecutionError
from .surface import SurfaceConnection as SurfaceConnection
from .surface import SurfacePolicy as SurfacePolicy
from .surface import VideoSession as VideoSession
