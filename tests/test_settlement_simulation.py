from solders.hash import Hash
from solders.keypair import Keypair
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address

from iat.settlement_simulation import (
    SettlementSimulationError,
    simulate_authorized_settlement,
)


def token_account(owner, mint, amount="0"):
    return {
        "owner": str(TOKEN_PROGRAM_ID),
        "data": {
            "parsed": {
                "info": {
                    "owner": str(owner),
                    "mint": str(mint),
                    "tokenAmount": {"amount": amount},
                }
            }
        },
    }


def test_unsigned_atomic_settlement_is_simulated_without_disclosing_transaction():
    escrow = Keypair().pubkey()
    winner = Keypair().pubkey()
    treasury = Keypair().pubkey()
    mint = Keypair().pubkey()
    source = get_associated_token_address(escrow, mint)
    treasury_ata = get_associated_token_address(treasury, mint)
    winner_ata = get_associated_token_address(winner, mint)
    observed_simulation = {}

    def rpc(method, params):
        if method == "getGenesisHash":
            return "EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
        if method == "getAccountInfo":
            address = params[0]
            if address == str(mint):
                return {
                    "value": {
                        "owner": str(TOKEN_PROGRAM_ID),
                        "data": {"parsed": {"info": {"decimals": 8}}},
                    }
                }
            accounts = {
                str(source): token_account(escrow, mint, "100000000"),
                str(treasury_ata): token_account(treasury, mint),
                str(winner_ata): token_account(winner, mint),
            }
            return {"value": accounts.get(address)}
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.default())}}
        if method == "simulateTransaction":
            observed_simulation["transaction_base64"] = params[0]
            observed_simulation["options"] = params[1]
            return {
                "context": {"slot": 123},
                "value": {"err": None, "logs": ["Program log: success"], "unitsConsumed": 9000},
            }
        raise AssertionError(method)

    result = simulate_authorized_settlement(
        authorization_id="psa_1",
        settlement_id="settlement_1",
        order_id="order_1",
        winner_wallet=str(winner),
        treasury_wallet=str(treasury),
        gross_amount_minor=100_000_000,
        commission_amount_minor=10_000_000,
        seller_payout_amount_minor=90_000_000,
        context={
            "cluster": "solana-devnet",
            "rpc_url": "https://api.devnet.solana.com",
            "escrow_authority": str(escrow),
            "mint": str(mint),
        },
        rpc=rpc,
    )
    assert result["simulation_status"] == "succeeded"
    assert result["cluster"] == "solana-devnet"
    assert result["genesis_hash"] == "EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
    assert result["token_program"] == str(TOKEN_PROGRAM_ID)
    assert result["instruction_count"] == 3
    assert result["required_signature_count"] == 1
    assert result["context_slot"] == 123
    assert result["serialized_transaction_disclosed"] is False
    assert "transaction_base64" not in result
    assert len(result["unsigned_transaction_sha256"]) == 64
    assert observed_simulation["transaction_base64"]
    assert observed_simulation["options"]["sigVerify"] is False


def test_mainnet_simulation_is_rejected_before_rpc():
    try:
        simulate_authorized_settlement(
            authorization_id="psa_1",
            settlement_id="settlement_1",
            order_id="order_1",
            winner_wallet=str(Keypair().pubkey()),
            treasury_wallet=str(Keypair().pubkey()),
            gross_amount_minor=1,
            commission_amount_minor=0,
            seller_payout_amount_minor=1,
            context={
                "cluster": "solana-devnet",
                "rpc_url": "https://api.mainnet-beta.solana.com",
                "escrow_authority": str(Keypair().pubkey()),
                "mint": str(Keypair().pubkey()),
            },
            rpc=lambda *_args: (_ for _ in ()).throw(AssertionError("rpc called")),
        )
    except SettlementSimulationError as exc:
        assert str(exc) == "mainnet_settlement_simulation_not_allowed"
    else:
        raise AssertionError("mainnet simulation should be rejected")
