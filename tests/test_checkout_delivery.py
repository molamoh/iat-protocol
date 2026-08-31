from iat.checkout_delivery import buyer_delivery_result


def test_buyer_delivery_result_includes_whitelisted_nested_report_fields():
    result = buyer_delivery_result(
        {
            "status": "foundation_supplier_pipeline_completed",
            "foundation_verdict": "foundation_verified_with_evidence",
            "result": {
                "status": "success",
                "summary": "Verified buyer report.",
                "confidence": 0.75,
                "sources": [{"url": "https://example.test/source"}],
            },
        }
    )

    assert result == {
        "status": "foundation_supplier_pipeline_completed",
        "summary": "Verified buyer report.",
        "confidence": 0.75,
        "sources": [{"url": "https://example.test/source"}],
        "foundation_verdict": "foundation_verified_with_evidence",
    }


def test_buyer_delivery_result_never_discloses_unlisted_nested_fields():
    result = buyer_delivery_result(
        {
            "status": "foundation_supplier_pipeline_completed",
            "internal_trace": "top-secret",
            "result": {
                "summary": "Safe summary.",
                "provider_credentials": "nested-secret",
                "supplier_execution": {"private": True},
            },
        }
    )

    assert result == {
        "status": "foundation_supplier_pipeline_completed",
        "summary": "Safe summary.",
    }


def test_buyer_delivery_result_uses_authoritative_top_level_value():
    result = buyer_delivery_result(
        {
            "status": "foundation_supplier_pipeline_completed",
            "result": {"status": "success", "summary": "Safe summary."},
        }
    )

    assert result["status"] == "foundation_supplier_pipeline_completed"
