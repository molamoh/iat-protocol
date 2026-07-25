from iat.api.agent_b_api import make_buyer_order_response


def test_buyer_order_response_preserves_checkout_credential():
    response = make_buyer_order_response(
        {
            "order_id": "order-checkout",
            "buyer_secret": "buyer-secret-long-enough",
            "price": 1,
            "seller_wallet": "seller-wallet",
        }
    )

    assert response["status"] == "order_created"
    assert response["order_id"] == "order-checkout"
    assert response["buyer_secret"] == "buyer-secret-long-enough"
