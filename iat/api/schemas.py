"""Request models shared by the public buyer and payment routes."""

from pydantic import BaseModel


class OrderRequest(BaseModel):
    service: str
    query: str | None = None
    buyer_wallet: str | None = None
    buyer_intent: dict | None = None
    requirements: dict | None = None
    buyer_context: dict | None = None
    locked_agent_id: str | None = None
    locked_unit_price: str | None = None
    intent_decision_id: str | None = None
    locked_order_id: str | None = None


class BuyerPreviewRequest(BaseModel):
    buyer_wallet: str
    prompt: str
    max_price: float | None = None
    session_id: str | None = None
    debug: bool = False


class BuyerConfirmRequest(BaseModel):
    buyer_wallet: str
    session_id: str
    max_price: float | None = None
    debug: bool = False


class VerifyPaymentRequest(BaseModel):
    order_id: str
    tx_signature: str
