import time

from solders.keypair import Keypair

from iat.agent_buyer_runtime import (
    AgentBuyerRuntimeConfig,
    BoundedTransactionApproval,
    diagnose_agent_buyer_runtime,
)


WALLET = str(Keypair.from_seed(bytes([15]) * 32).pubkey())
PROGRAM = str(Keypair.from_seed(bytes([16]) * 32).pubkey())
VAULT = str(Keypair.from_seed(bytes([17]) * 32).pubkey())
DESTINATION = str(Keypair.from_seed(bytes([18]) * 32).pubkey())


def environment():
    return {
        "IAT_AGENT_WALLET_ADDRESS": WALLET,
        "IAT_AGENT_SIGNER_URL": "https://wallet-provider.example",
        "IAT_AGENT_SIGNER_TOKEN": "signer-token-long-enough",
        "IAT_WALLET_SIDECAR_TOKEN": "sidecar-token-long-enough",
        "IAT_AGENT_MAX_USDC_MINOR": "2000000",
        "IAT_AGENT_ALLOWED_PROGRAM_ID": PROGRAM,
        "IAT_AGENT_ALLOWED_TREASURY_VAULT": VAULT,
        "IAT_AGENT_ALLOWED_IAT_DESTINATION": DESTINATION,
    }


def approved_review(**overrides):
    value = {
        "cluster": "solana:devnet",
        "fee_payer": WALLET,
        "input": {"asset": "USDC", "amount_minor": 1_000_000},
        "simulation": {"status": "succeeded"},
        "expires_at": int(time.time()) + 120,
        "program_id": PROGRAM,
        "treasury_vault": VAULT,
        "iat_destination": DESTINATION,
    }
    value.update(overrides)
    return value


def test_runtime_config_assembles_sidecar_without_private_key():
    config = AgentBuyerRuntimeConfig.from_env(environment())
    app = config.create_sidecar_app()
    assert app.title == "IAT Local Wallet Sidecar"
    diagnostic = config.diagnostic()
    assert diagnostic["private_key_configured"] is False
    assert "signer-token-long-enough" not in str(diagnostic)
    assert "sidecar-token-long-enough" not in str(diagnostic)
    assert "signer-token-long-enough" not in repr(config)


def test_bounded_approval_accepts_only_exact_configured_payment():
    approval = AgentBuyerRuntimeConfig.from_env(environment()).approval()
    assert approval.approve(approved_review()) is True
    assert approval.approve(approved_review(input={"asset": "USDC", "amount_minor": 2_000_001})) is False
    assert approval.approve(approved_review(program_id=str(Keypair().pubkey()))) is False
    assert approval.approve(approved_review(treasury_vault=str(Keypair().pubkey()))) is False
    assert approval.approve(approved_review(iat_destination=str(Keypair().pubkey()))) is False
    assert approval.approve(approved_review(simulation={"status": "failed"})) is False


def test_readiness_lists_names_but_never_secret_values():
    env = environment()
    del env["IAT_AGENT_SIGNER_TOKEN"]
    result = diagnose_agent_buyer_runtime(env)
    assert result["status"] == "agent_buyer_sidecar_not_ready"
    assert result["missing_configuration"] == ["IAT_AGENT_SIGNER_TOKEN"]
    assert result["private_key_required"] is False
    assert "sidecar-token-long-enough" not in str(result)


def test_runtime_rejects_mainnet_and_unbounded_amount():
    mainnet = environment() | {"IAT_AGENT_SOLANA_CLUSTER": "solana:mainnet"}
    assert diagnose_agent_buyer_runtime(mainnet)["configuration_error"] == "only_solana_devnet_is_supported"
    invalid_limit = environment() | {"IAT_AGENT_MAX_USDC_MINOR": "0"}
    assert diagnose_agent_buyer_runtime(invalid_limit)["configuration_error"] == "maximum_usdc_minor_out_of_bounds"
