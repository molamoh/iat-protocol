import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="IAT Seller Runtime", version="1.0.0")


class ExecutionRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail=f"{name.lower()}_not_configured")
    return value


@app.get("/")
def manifest():
    return {
        "status": "ok",
        "protocol": "iat-seller-runtime/1",
        "seller_id": os.getenv("IAT_SELLER_ID", "unconfigured"),
        "service": os.getenv("IAT_SELLER_SERVICE", "bounded_ai_service"),
        "execution": "/execute",
        "verification": "/.well-known/iat-seller-verification.json",
    }


@app.get("/.well-known/iat-seller-verification.json")
def seller_verification():
    return {
        "seller_id": required_env("IAT_SELLER_ID"),
        "iat_seller_verification": required_env("IAT_SELLER_VERIFICATION_TOKEN"),
    }


@app.post("/execute")
def execute(payload: ExecutionRequest, authorization: str | None = Header(default=None)):
    expected = required_env("IAT_RUNTIME_EXECUTION_SECRET")
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="runtime_auth_required")
    return {
        "status": "success",
        "service": os.getenv("IAT_SELLER_SERVICE", "bounded_ai_service"),
        "summary": payload.request[:500],
        "evidence": {"runtime": "seller_controlled", "bounded": True},
    }
