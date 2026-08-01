from iat.api import db, multi_exec


RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item>
    <title>Bitcoin market risk rises - Example News</title>
    <link>https://news.google.com/rss/articles/example</link>
    <pubDate>Sat, 01 Aug 2026 12:00:00 GMT</pubDate>
    <source url="https://example.com">Example News</source>
  </item>
</channel></rss>"""


class Response:
    status_code = 200
    content = RSS


def test_google_news_rss_is_bounded_and_normalized(monkeypatch):
    observed = {}

    def fake_get(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return Response()

    monkeypatch.setattr(multi_exec.requests, "get", fake_get)

    results = multi_exec.foundation_google_news_rss_search("Bitcoin risk", limit=50)

    assert observed["url"] == "https://news.google.com/rss/search"
    assert observed["timeout"] == 15
    assert observed["params"]["q"] == "Bitcoin risk"
    assert results == [{
        "source": "google_news_rss",
        "title": "Bitcoin market risk rises - Example News",
        "snippet": "Example News",
        "link": "https://news.google.com/rss/articles/example",
        "display_link": "https://example.com",
        "date": "Sat, 01 Aug 2026 12:00:00 GMT",
        "position": 1,
    }]


def test_search_query_removes_format_instructions():
    assert multi_exec.foundation_search_query(
        "Analyse courte du risque Bitcoin aujourd'hui, avec sources, résumé structuré et recommandation finale."
    ) == "risque Bitcoin aujourd'hui"


def test_web_evidence_uses_keyless_news_before_html_fallback(monkeypatch):
    monkeypatch.setattr(multi_exec, "foundation_serper_search", lambda *a, **k: [])
    monkeypatch.setattr(multi_exec, "foundation_tavily_search", lambda *a, **k: [])
    monkeypatch.setattr(multi_exec, "foundation_google_search", lambda *a, **k: [])
    monkeypatch.setattr(
        multi_exec,
        "foundation_google_news_rss_search",
        lambda *a, **k: [{"title": "evidence"}],
    )
    monkeypatch.setattr(
        multi_exec,
        "foundation_duckduckgo_search",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected fallback")),
    )

    result = multi_exec.foundation_web_evidence_search("Bitcoin risk")

    assert result["provider"] == "google_news_rss"
    assert result["result_count"] == 1


def test_consensus_reads_normalized_web_evidence_results():
    evidence = [
        {
            "title": "Bitcoin market risk and volatility today",
            "snippet": "Bitcoin volatility remains elevated",
            "link": "https://example.com/bitcoin-risk",
        },
        {
            "title": "Bitcoin market analysis today",
            "snippet": "Risk indicators for Bitcoin markets",
            "link": "https://second.example/bitcoin-analysis",
        },
        {
            "title": "Bitcoin volatility report",
            "snippet": "Market risk report for Bitcoin",
            "link": "https://third.example/bitcoin-report",
        },
    ]
    results = []
    for agent_id in ("foundation-a", "foundation-b"):
        results.append({
            "success": True,
            "agent_id": agent_id,
            "wallet": agent_id,
            "reputation": 0.95,
            "data": {
                "summary": "Bitcoin market risk analysis",
                "final_recommendation": "Monitor Bitcoin volatility and risk",
                "claims": ["Bitcoin volatility remains elevated"],
                "structured_signals": {"provider": "google_news_rss"},
                "metrics": {"external_evidence_count": 3},
                "raw": {
                    "query": "Bitcoin risk today",
                    "web_evidence": {"results": evidence},
                },
            },
        })

    consensus = multi_exec.compute_consensus(results)

    assert consensus["valid_agents"] == 2
    assert consensus["status"] == "passed"
    assert consensus["consensus_gates"]["usable_agents"] == 2


def test_evidence_can_be_ready_when_cross_source_claims_override_weak_research_wording():
    result = db.evaluate_foundation_evidence_package_db({
        "foundation_ready_for_decision": True,
        "research_consensus": {"status": "failed", "valid_agents": 2, "score": 0.05},
        "verification_consensus": {"status": "passed", "valid_agents": 2, "score": 0.8},
        "best_verification_result": {
            "data": {
                "verified_claim_count": 2,
                "rejected_claim_count": 0,
            }
        },
    })

    evaluation = result["evaluation"]
    assert evaluation["foundation_decision_ready"] is True
    assert evaluation["foundation_evidence_status"] == (
        "decision_ready_with_cross_source_verification"
    )
