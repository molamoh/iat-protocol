from iat.api import multi_exec


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
    assert results == [{
        "source": "google_news_rss",
        "title": "Bitcoin market risk rises - Example News",
        "snippet": "Example News",
        "link": "https://news.google.com/rss/articles/example",
        "display_link": "https://example.com",
        "date": "Sat, 01 Aug 2026 12:00:00 GMT",
        "position": 1,
    }]


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
