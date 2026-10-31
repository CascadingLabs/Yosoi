"""Focused forwarding checks with mocked native handles and no browser build."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
import types
import unittest
from typing import Literal, get_args
from unittest.mock import patch


PYTHON_ROOT = Path(__file__).resolve().parents[1]
SURFACE_PATH = PYTHON_ROOT / "yosoi" / "surface.py"
BROWSER_PATH = PYTHON_ROOT / "yosoi" / "browser.py"


class FakeBrowserError(Exception):
    pass


class FakeSurfacePolicy:
    def model_dump_json(self) -> str:
        return '{"archive":"off"}'


class FakeNativeHandle:
    def __init__(self) -> None:
        self.released = False


class FakeSession:
    def __init__(self, handle=None) -> None:
        self._handle = handle
        self._cancellation = None


class FakeSessionHandle:
    def __init__(self, work_handle: FakeNativeHandle) -> None:
        self.work_handle = work_handle

    async def work(self, _cancellation=None):
        return self.work_handle


class FakeWork:
    def __init__(self, session: FakeSession) -> None:
        self._session = session
        self._handle = None
        self._released = False
        self._release_task = None
        self._operation_lock = asyncio.Lock()

    @property
    def released(self) -> bool:
        return self._released

    async def _acquire(self) -> None:
        if self._released:
            raise FakeBrowserError("Work is released")
        if self._handle is None:
            self._handle = await self._session._handle.work()


class FakeBrowserSurfaceHandle:
    pass


def load_surface_api() -> types.SimpleNamespace:
    """Execute the public forwarding classes without importing the native wheel."""
    tree = ast.parse(SURFACE_PATH.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if (isinstance(node, ast.ClassDef) and node.name in {"SurfaceConnection", "BrowserSurface"})
        or (isinstance(node, ast.AsyncFunctionDef) and node.name == "consume_session")
    ]
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    module_ast = ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[]))
    native = types.SimpleNamespace(
        BrowserSurface=object,
        VideoSession=object,
        surface_browser_consume_session=None,
        surface_browser_consume_work=None,
    )
    browser_module = types.SimpleNamespace(
        Session=FakeSession,
        Work=FakeWork,
        BrowserError=FakeBrowserError,
    )
    namespace = {
        "__name__": "surface_forwarding_under_test",
        "asyncio": asyncio,
        "json": json,
        "Mapping": dict,
        "Self": object,
        "_native": native,
        "_browser": browser_module,
        "SurfacePolicy": FakeSurfacePolicy,
        "BrowserError": FakeBrowserError,
        "Outcome": object,
        "BrowserObservation": object,
        "BrowserRepresentation": object,
        "ReadRequest": object,
        "ReadResult": object,
        "_RESULT": object(),
        "_require_browser": lambda: None,
    }
    exec(compile(module_ast, str(SURFACE_PATH), "exec"), namespace)
    return types.SimpleNamespace(**namespace)


class SurfaceConsumptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load_surface_api()

    def test_session_path_forwards_the_existing_native_session_and_policy(self):
        native_session = object()
        session = FakeSession(native_session)
        native_surface = FakeBrowserSurfaceHandle()
        received = []

        async def consume(handle, policy_json):
            received.append((handle, json.loads(policy_json)))
            return native_surface

        with patch.object(self.api._native, "surface_browser_consume_session", consume):
            result = asyncio.run(self.api.BrowserSurface.consume_session(session))

        self.assertIs(result._handle, native_surface)
        self.assertIs(session._handle, native_session)
        self.assertIs(received[0][0], native_session)
        self.assertEqual(received[0][1], {"archive": "off"})

    def test_module_function_forwards_to_browser_surface_classmethod(self):
        session = FakeSession(object())
        expected = object()
        calls = []

        async def consume(cls, actual_session, policy):
            calls.append((cls, actual_session, policy))
            return expected

        with patch.object(self.api.BrowserSurface, "consume_session", classmethod(consume)):
            result = asyncio.run(self.api.consume_session(session))

        self.assertIs(result, expected)
        self.assertEqual(calls, [(self.api.BrowserSurface, session, None)])

    def test_work_transfer_marks_only_a_taken_native_handle_released(self):
        native_work = FakeNativeHandle()
        session = FakeSession(FakeSessionHandle(native_work))
        work = FakeWork(session)
        native_surface = FakeBrowserSurfaceHandle()
        received = []

        async def consume(handle, policy_json):
            received.append((handle, json.loads(policy_json)))
            handle.released = True
            return native_surface

        with patch.object(self.api._native, "surface_browser_consume_work", consume):
            result = asyncio.run(self.api.BrowserSurface.consume_work(work))

        self.assertIs(result._handle, native_surface)
        self.assertIs(received[0][0], native_work)
        self.assertEqual(received[0][1], {"archive": "off"})
        self.assertTrue(work.released)
        self.assertIsNone(work._handle)
        self.assertIsNotNone(session._handle)

    def test_pre_take_failure_keeps_work_but_post_take_failure_consumes_it(self):
        for consume_and_fail in (False, True):
            native_work = FakeNativeHandle()
            work = FakeWork(FakeSession(FakeSessionHandle(native_work)))

            async def fail(handle, _policy_json):
                if consume_and_fail:
                    handle.released = True
                raise RuntimeError("native binding failed")

            with patch.object(self.api._native, "surface_browser_consume_work", fail):
                with self.assertRaisesRegex(RuntimeError, "native binding failed"):
                    asyncio.run(self.api.BrowserSurface.consume_work(work))

            self.assertEqual(work.released, consume_and_fail)
            self.assertEqual(work._handle is None, consume_and_fail)

    def test_scroll_is_a_supported_python_action_kind(self):
        tree = ast.parse(BROWSER_PATH.read_text(encoding="utf-8"))
        declaration = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "ActionKind" for target in node.targets)
        )
        namespace = {"Literal": Literal}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[declaration], type_ignores=[])),
                     str(BROWSER_PATH), "exec"), namespace)
        self.assertIn("scroll", get_args(namespace["ActionKind"]))


if __name__ == "__main__":
    unittest.main()
