"""Ensure native imports and the model stack preserve a disabled GIL."""

import os
import subprocess
import sys
import sysconfig

import pytest


@pytest.mark.skipif(
    not sysconfig.get_config_var("Py_GIL_DISABLED"),
    reason="requires a free-threaded interpreter",
)
def test_imports_and_models_preserve_free_threading() -> None:
    # Use a fresh interpreter so pytest plugins cannot hide a GIL transition.
    # Do not force PYTHON_GIL=0: that would mask incompatible native imports.
    environment = os.environ.copy()
    environment.pop("PYTHON_GIL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            """
import sys
assert not sys._is_gil_enabled(), "GIL enabled before imports"
import yosoi
assert not sys._is_gil_enabled(), "Yosoi import enabled the GIL"
from pydantic import BaseModel
assert not sys._is_gil_enabled(), "Pydantic import enabled the GIL"
from concurrent.futures import ThreadPoolExecutor

class Record(BaseModel):
    value: int

class ContractRecord(yosoi.Contract):
    value: str = yosoi.Field("Value", locator=yosoi.css("h1"))

def validate(value):
    document = yosoi.Document.html(str(value), f"<h1>{value}</h1>")
    plan = yosoi.Plan(outputs=[yosoi.output("value", yosoi.css("h1").text())])
    located = document.locate(plan)
    with document.parse() as parsed:
        assert parsed.locate(plan) == located
    contract_records = yosoi.extract(document, ContractRecord).validate().require_all()
    assert contract_records[0].value == str(value)
    return Record.model_validate({"value": located.values()[0]}).value

with ThreadPoolExecutor(max_workers=2) as pool:
    assert list(pool.map(validate, range(32))) == list(range(32))
assert not sys._is_gil_enabled(), "model validation enabled the GIL"
""",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
