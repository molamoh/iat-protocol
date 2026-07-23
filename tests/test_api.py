from unittest.mock import Mock

from iat import sdk


def _response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = str(payload)
    return response


def test_create_order_is_local_and_does_not_call_production(monkeypatch):
    response = _response(
        {
            "order_id": "order-test",
            "seller_id": "seller-test",
            "seller_wallet": "wallet-test",
            "price": 1.0,
        }
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(sdk.requests, "post", post)
    monkeypatch.setattr(sdk, "API", "http://iat.test")

    data = sdk.create_order("risk_report", query="test query")

    assert data["order_id"] == "order-test"
    post.assert_called_once()
    assert post.call_args.args[0] == "http://iat.test/create-order"


def test_list_services_is_local_and_does_not_call_production(monkeypatch):
    response = _response({"services": ["risk_report"]})
    get = Mock(return_value=response)
    monkeypatch.setattr(sdk.requests, "get", get)
    monkeypatch.setattr(sdk, "API", "http://iat.test")

    data = sdk.list_services()

    assert data == {"services": ["risk_report"]}
    get.assert_called_once_with(
        "http://iat.test/services",
        headers={},
        timeout=30,
    )


def test_verify_order_uses_canonical_buyer_endpoint(monkeypatch):
    response = _response({"status": "delivered", "result": {"ok": True}})
    post = Mock(return_value=response)
    monkeypatch.setattr(sdk.requests, "post", post)
    monkeypatch.setattr(sdk, "API", "http://iat.test")
    monkeypatch.delenv("IAT_VERIFY_PAYMENT_PATH", raising=False)

    data = sdk.verify_order("order-test", "signature-test")

    assert data["status"] == "delivered"
    assert post.call_args.args[0] == "http://iat.test/buyer/verify-payment"
