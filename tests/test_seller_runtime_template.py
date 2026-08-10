import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException


MODULE_PATH = Path(__file__).parents[1] / "examples" / "seller_runtime" / "app.py"
SPEC = importlib.util.spec_from_file_location("seller_runtime_template", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
def test_verification_document_requires_configuration(monkeypatch):
    monkeypatch.delenv("IAT_SELLER_ID", raising=False)
    monkeypatch.delenv("IAT_SELLER_VERIFICATION_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        MODULE.seller_verification()
    assert exc.value.status_code == 503


def test_execution_requires_distinct_runtime_secret(monkeypatch):
    monkeypatch.setenv("IAT_RUNTIME_EXECUTION_SECRET", "runtime-secret")
    payload = MODULE.ExecutionRequest(request="bounded work")
    with pytest.raises(HTTPException) as exc:
        MODULE.execute(payload, authorization=None)
    authorized = MODULE.execute(payload, authorization="Bearer runtime-secret")
    assert exc.value.status_code == 401
    assert authorized["status"] == "success"
