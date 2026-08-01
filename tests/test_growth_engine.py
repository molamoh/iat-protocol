import sqlite3

import pytest

import iat.growth as growth


@pytest.fixture()
def growth_db(tmp_path, monkeypatch):
    database = tmp_path / "growth.db"

    def connect():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(growth, "get_conn", connect)
    monkeypatch.setattr(growth, "release_conn", lambda conn: conn.close())
    monkeypatch.setattr(growth, "qmark", lambda: "?")
    monkeypatch.delenv("IAT_GROWTH_OUTBOUND_ENABLED", raising=False)
    monkeypatch.setenv("IAT_GROWTH_RESPONSE_SECRET", "test-growth-response-secret")
    growth.init_growth_tables()
    return database


def _prospect(**metadata):
    return growth.upsert_prospect(
        url="https://agents.example.com/iat-hook",
        name="Autonomous AI commerce agent",
        segment="ai_agent",
        source="registry",
        metadata={
            "description": "AI agent API for buyer commerce and payments",
            "manifest_url": "https://agents.example.com/.well-known/agent.json",
            **metadata,
        },
    )


def _active_campaign(**policy):
    campaign = growth.create_campaign(
        name="AI agent adoption",
        target_segment="ai_agent",
        min_score=50,
        daily_action_limit=10,
        policy=policy,
    )
    growth.set_campaign_status(campaign["campaign_id"], "active")
    return campaign


def test_prospect_ingestion_is_canonical_and_idempotent(growth_db):
    first = growth.upsert_prospect(
        url="https://Agents.Example.com/path/",
        name="Agent",
        metadata={"one": 1},
    )
    second = growth.upsert_prospect(
        url="https://agents.example.com/path",
        name="Agent updated",
        metadata={"two": 2},
    )

    assert first["prospect_id"] == second["prospect_id"]
    stored = growth.get_prospect(first["prospect_id"])
    assert stored["canonical_url"] == "https://agents.example.com/path"
    assert stored["metadata"] == {"one": 1, "two": 2}


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com"],
)
def test_prospect_ingestion_rejects_unsafe_urls(growth_db, url):
    with pytest.raises(growth.GrowthValidationError):
        growth.upsert_prospect(url=url)


def test_qualification_produces_explainable_bounded_score(growth_db):
    prospect = _prospect(outreach_opt_in=True)

    result = growth.qualify_prospect(prospect["prospect_id"])

    assert result["status"] == "qualified"
    assert 50 <= result["score"] <= 100
    assert result["signals"]["explicit_opt_in"] is True
    assert result["signals"]["machine_interface"] is True


def test_discovery_feed_is_bounded_validated_and_deduplicated(growth_db, monkeypatch):
    monkeypatch.setenv("IAT_GROWTH_DISCOVERY_HOSTS", "registry.example.com")
    monkeypatch.setattr(
        growth,
        "validate_public_runtime_url",
        lambda url: {"hostname": "registry.example.com"},
    )

    class Response:
        headers = {"content-length": "500"}
        content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "url": "https://agents.example.com/iat-hook",
                        "name": "Agent",
                        "segment": "ai_agent",
                        "metadata": {"outreach_opt_in": True},
                    },
                    {
                        "url": "https://agents.example.com/iat-hook/",
                        "name": "Agent duplicate",
                        "segment": "ai_agent",
                    },
                    {"url": "file:///etc/passwd"},
                ]
            }

    calls = []
    monkeypatch.setattr(
        growth.requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Response(),
    )

    result = growth.discover_from_feed("https://registry.example.com/feed")

    assert result["imported"] == 2
    assert result["rejected"] == 1
    assert growth.list_prospects()["count"] == 1
    assert calls[0][1]["allow_redirects"] is False


def test_discovery_feed_allowlist_fails_closed(growth_db, monkeypatch):
    monkeypatch.setenv("IAT_GROWTH_DISCOVERY_HOSTS", "trusted.example.com")
    monkeypatch.setattr(
        growth,
        "validate_public_runtime_url",
        lambda url: {"hostname": "untrusted.example.com"},
    )

    with pytest.raises(growth.GrowthValidationError, match="not_allowed"):
        growth.discover_from_feed("https://untrusted.example.com/feed")


def test_do_not_contact_overrides_all_positive_signals(growth_db):
    prospect = _prospect(outreach_opt_in=True, do_not_contact=True)

    result = growth.qualify_prospect(prospect["prospect_id"])

    assert result["status"] == "rejected"
    assert result["score"] == 0


def test_action_is_blocked_without_explicit_opt_in(growth_db):
    prospect = _prospect()
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()

    result = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])

    assert result["status"] == "blocked"
    assert result["reason"] == "authorization_required"
    with pytest.raises(growth.GrowthValidationError, match="blocked_action"):
        growth.approve_action(
            result["action_id"],
            approved_by="admin",
            reason="attempt to bypass consent",
        )


def test_verified_public_manifest_permission_authorizes_outreach(growth_db):
    prospect = _prospect(
        outreach_permission={
            "allowed": True,
            "source": "agent_manifest",
            "evidence_url": "https://agents.example.com/.well-known/agent.json",
            "observed_at": growth._now(),
        }
    )
    qualified = growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()

    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])

    assert qualified["signals"]["public_outreach_permission"] is True
    assert qualified["signals"]["outreach_authorized"] is True
    assert proposed["status"] == "proposed"


@pytest.mark.parametrize(
    "permission",
    [
        {"allowed": True, "source": "scraped_page", "evidence_url": "https://agents.example.com/a", "observed_at": 1},
        {"allowed": True, "source": "agent_manifest", "evidence_url": "https://other.example/a", "observed_at": 1},
        {"allowed": True, "source": "agent_manifest", "evidence_url": "https://agents.example.com/a"},
    ],
)
def test_unverifiable_public_permission_fails_closed(growth_db, permission):
    prospect = _prospect(outreach_permission=permission)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()

    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])

    assert proposed["status"] == "blocked"


def test_approved_action_stays_disabled_until_global_outbound_enabled(growth_db):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()
    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])
    growth.approve_action(
        proposed["action_id"],
        approved_by="growth-admin",
        reason="verified machine endpoint opt-in",
    )

    result = growth.execute_action(proposed["action_id"])

    assert result["status"] == "disabled"
    assert result["reason"] == "outbound_disabled_by_default"


def test_same_prospect_cannot_be_proposed_twice_within_24_hours(growth_db):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    first_campaign = _active_campaign()
    second_campaign = _active_campaign()

    first = growth.propose_action(prospect["prospect_id"], first_campaign["campaign_id"])
    second = growth.propose_action(prospect["prospect_id"], second_campaign["campaign_id"])

    assert first["status"] == "proposed"
    assert second["status"] == "skipped"
    assert second["reason"] == "prospect_24h_cooldown"
    assert second["next_eligible_at"] > growth._now()


def test_failed_outreach_attempt_also_reserves_24h_cooldown(growth_db, monkeypatch):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()
    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])
    growth.approve_action(
        proposed["action_id"],
        approved_by="growth-admin",
        reason="verified machine endpoint opt-in",
    )
    monkeypatch.setenv("IAT_GROWTH_OUTBOUND_ENABLED", "true")
    monkeypatch.setattr(
        growth,
        "validate_public_runtime_url",
        lambda url: {"hostname": "agents.example.com"},
    )
    monkeypatch.setattr(
        growth.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            growth.requests.ConnectionError("offline")
        ),
    )

    result = growth.execute_action(proposed["action_id"])
    eligibility = growth.prospect_outreach_eligibility(prospect["prospect_id"])

    assert result["status"] == "failed"
    assert eligibility["eligible"] is False
    assert eligibility["reason"] == "prospect_24h_cooldown"
    assert growth.get_prospect(prospect["prospect_id"])["contact_count"] == 1


def test_execution_is_ssrf_checked_and_idempotent(growth_db, monkeypatch):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()
    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])
    growth.approve_action(
        proposed["action_id"],
        approved_by="growth-admin",
        reason="verified machine endpoint opt-in",
    )
    monkeypatch.setenv("IAT_GROWTH_OUTBOUND_ENABLED", "true")
    monkeypatch.setattr(
        growth,
        "validate_public_runtime_url",
        lambda url: {"hostname": "agents.example.com"},
    )

    class Response:
        status_code = 202
        text = "accepted"

    calls = []
    monkeypatch.setattr(
        growth.requests,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Response(),
    )

    first = growth.execute_action(proposed["action_id"])
    second = growth.execute_action(proposed["action_id"])

    assert first["status"] == "executed"
    assert second["status"] == "already_executed"
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False


def test_authenticated_response_is_idempotent_and_visible(growth_db, monkeypatch):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()
    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])
    action = growth.list_actions()["actions"][0]
    growth.approve_action(
        proposed["action_id"],
        approved_by="growth-admin",
        reason="verified response-enabled endpoint",
    )
    monkeypatch.setenv("IAT_GROWTH_OUTBOUND_ENABLED", "true")
    monkeypatch.setattr(
        growth,
        "validate_public_runtime_url",
        lambda url: {"hostname": "agents.example.com"},
    )

    class Response:
        status_code = 202
        text = "accepted"

    monkeypatch.setattr(growth.requests, "post", lambda *args, **kwargs: Response())
    growth.execute_action(proposed["action_id"])

    payload = {
        "action_id": proposed["action_id"],
        "response_token": action["payload"]["response_token"],
        "idempotency_key": "response-key-0001",
        "response_type": "interested",
        "message": "Send machine integration details.",
    }
    first = growth.record_prospect_response(**payload)
    duplicate = growth.record_prospect_response(**payload)

    assert first["status"] == "recorded"
    assert duplicate["status"] == "already_recorded"
    assert growth.list_responses()["count"] == 1
    assert growth.campaign_analytics(campaign["campaign_id"])["rates"]["response_rate"] == 1.0
    assert "message" not in duplicate


def test_opt_out_response_creates_global_suppression(growth_db, monkeypatch):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()
    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])
    action = growth.list_actions()["actions"][0]
    growth.approve_action(
        proposed["action_id"],
        approved_by="growth-admin",
        reason="verified response-enabled endpoint",
    )
    monkeypatch.setenv("IAT_GROWTH_OUTBOUND_ENABLED", "true")
    monkeypatch.setattr(
        growth,
        "validate_public_runtime_url",
        lambda url: {"hostname": "agents.example.com"},
    )

    class Response:
        status_code = 200
        text = "ok"

    monkeypatch.setattr(growth.requests, "post", lambda *args, **kwargs: Response())
    growth.execute_action(proposed["action_id"])

    result = growth.record_prospect_response(
        action_id=proposed["action_id"],
        response_token=action["payload"]["response_token"],
        idempotency_key="response-opt-out-0001",
        response_type="opt_out",
    )

    assert result["response_type"] == "opt_out"
    assert growth.list_suppressions()["count"] == 1
    assert growth.get_prospect(prospect["prospect_id"])["status"] == "rejected"


def test_invalid_response_token_fails_closed(growth_db):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()
    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])

    with pytest.raises(growth.GrowthValidationError, match="executed_action"):
        growth.record_prospect_response(
            action_id=proposed["action_id"],
            response_token="0" * 64,
            idempotency_key="response-invalid-0001",
            response_type="interested",
        )


def test_ab_learning_requires_evidence_approval_and_supports_rollback(growth_db):
    campaign = growth.create_campaign(
        name="Bounded A/B",
        target_segment="ai_agent",
        min_score=50,
        policy={
            "variants": [
                {"id": "a", "message": "Try IAT sandbox"},
                {"id": "b", "message": "Discover IAT commerce"},
            ]
        },
    )
    campaign_id = campaign["campaign_id"]
    conn = growth.get_conn()
    cur = conn.cursor()
    now = growth._now()
    for variant in ("a", "b"):
        for index in range(5):
            action_id = f"action-{variant}-{index}"
            prospect_id = f"prospect-{variant}-{index}"
            cur.execute(
                """INSERT INTO growth_actions
                (action_id, idempotency_key, prospect_id, campaign_id, action_type,
                 channel, status, risk_level, payload, reason, attempts,
                 scheduled_at, executed_at, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    action_id, f"idem-{variant}-{index}", prospect_id, campaign_id,
                    "protocol_invitation", "machine_webhook", "executed", "low",
                    growth._json({"variant_id": variant}), "test", 1,
                    now, now, now, now,
                ),
            )
            if variant == "a" or index == 0:
                cur.execute(
                    """INSERT INTO growth_responses
                    (response_id, idempotency_key, action_id, prospect_id, campaign_id,
                     response_type, message, metadata, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        f"response-{variant}-{index}", f"response-idem-{variant}-{index}",
                        action_id, prospect_id, campaign_id,
                        "interested" if variant == "a" else "not_interested",
                        "", "{}", now,
                    ),
                )
    conn.commit()
    growth.release_conn(conn)

    proposed = growth.generate_campaign_recommendation(campaign_id, min_samples=5)
    assert proposed["status"] == "proposed"
    assert proposed["winner_variant"] == "a"

    growth.apply_recommendation(proposed["recommendation_id"])
    applied = next(
        item for item in growth.list_campaigns()["campaigns"]
        if item["campaign_id"] == campaign_id
    )
    assert applied["policy"]["preferred_variant"] == "a"

    growth.rollback_recommendation(proposed["recommendation_id"])
    rolled_back = next(
        item for item in growth.list_campaigns()["campaigns"]
        if item["campaign_id"] == campaign_id
    )
    assert "preferred_variant" not in rolled_back["policy"]


def test_stale_execution_is_recovered_for_operator_visibility(growth_db):
    prospect = _prospect(outreach_opt_in=True)
    growth.qualify_prospect(prospect["prospect_id"])
    campaign = _active_campaign()
    proposed = growth.propose_action(prospect["prospect_id"], campaign["campaign_id"])
    conn = growth.get_conn()
    conn.execute(
        "UPDATE growth_actions SET status=?, updated_at=? WHERE action_id=?",
        ("executing", growth._now() - 1_000, proposed["action_id"]),
    )
    conn.commit()
    growth.release_conn(conn)

    result = growth.recover_stale_actions(stale_after_seconds=300)
    action = growth.list_actions()["actions"][0]

    assert result["recovered"] == 1
    assert action["status"] == "failed"
    assert action["reason"] == "stale_execution_recovered"


def test_domain_circuit_opens_after_three_consecutive_failures(growth_db):
    prospect = _prospect(outreach_opt_in=True)
    conn = growth.get_conn()
    now = growth._now()
    for index in range(3):
        conn.execute(
            """INSERT INTO growth_actions
            (action_id, idempotency_key, prospect_id, campaign_id, action_type,
             channel, status, risk_level, payload, reason, attempts,
             scheduled_at, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"failed-{index}", f"failed-idem-{index}", prospect["prospect_id"],
                "campaign", "protocol_invitation", "machine_webhook", "failed",
                "low", "{}", "delivery failed", 1, now, now, now + index,
            ),
        )
    conn.commit()
    growth.release_conn(conn)

    health = growth.domain_delivery_health("agents.example.com")

    assert health["allowed"] is False
    assert health["circuit"] == "open"


def test_growth_cycle_is_idempotent(growth_db):
    prospect = _prospect(outreach_opt_in=True)
    campaign = _active_campaign()

    first = growth.run_growth_cycle()
    second = growth.run_growth_cycle()

    assert first["qualified"] == 1
    assert first["proposed"] == 1
    assert second["proposed"] == 0
    assert growth.list_actions()["count"] == 1
    assert growth.get_prospect(prospect["prospect_id"])["status"] == "qualified"
    assert campaign["campaign_id"]


def test_conversion_and_dashboard_metrics(growth_db):
    prospect = _prospect(outreach_opt_in=True)

    conversion = growth.record_conversion(
        prospect["prospect_id"],
        conversion_type="sandbox_order",
        value=4.5,
    )
    dashboard = growth.growth_dashboard()

    assert conversion["status"] == "converted"
    assert dashboard["prospects"]["converted"] == 1
    assert dashboard["conversion_value"] == 4.5
    assert dashboard["safety"]["outbound_disabled_by_default"] is True


def test_inbound_pilot_registration_is_qualified_and_idempotent(growth_db):
    payload = {
        "url": "https://pilot-agent.example.com/iat",
        "name": "Pilot buyer agent",
        "segment": "ai_agent",
        "use_case": "Autonomous purchasing of verified digital services via USDC.",
        "source": "github",
        "referral": "readme",
        "outreach_opt_in": True,
    }

    first = growth.register_inbound_pilot(**payload)
    second = growth.register_inbound_pilot(**payload)

    assert first["status"] == "accepted"
    assert second["status"] == "already_registered"
    assert first["pilot_id"] == second["pilot_id"]
    assert first["qualification"]["status"] == "qualified"
    events = growth.list_growth_events(
        event_type="conversion_pilot_application"
    )
    assert events["count"] == 1
    stored = growth.get_prospect(first["pilot_id"])
    assert stored["metadata"]["outreach_opt_in"] is True
    assert stored["metadata"]["acquisition_source"] == "github"


def test_inbound_pilot_requires_explicit_consent(growth_db):
    with pytest.raises(growth.GrowthValidationError, match="consent_required"):
        growth.register_inbound_pilot(
            url="https://pilot-agent.example.com",
            name="Pilot agent",
            segment="ai_agent",
            use_case="Autonomous purchasing of digital services.",
            outreach_opt_in=False,
        )
