import base64
from decimal import Decimal

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.raydium import RaydiumClient, RaydiumError, RaydiumPolicy


def key():
    return str(Pubkey.new_unique())


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


class Session:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return Response(self.payloads.pop(0))


def quote_response(input_mint, output_mint, pool, **overrides):
    data = {
        "swapType": "BaseOut",
        "inputMint": input_mint,
        "inputAmount": "2500000",
        "outputMint": output_mint,
        "outputAmount": "1000000000",
        "otherAmountThreshold": "2525000",
        "slippageBps": 100,
        "priceImpactPct": "0.5",
        "routePlan": [
            {
                "poolId": pool,
                "inputMint": input_mint,
                "outputMint": output_mint,
                "feeAmount": "5000",
                "feeMint": input_mint,
            }
        ],
    }
    data.update(overrides)
    return {"id": "quote-1", "success": True, "version": "V1", "data": data}


def policy(pool, program, **overrides):
    values = {
        "allowed_pools": (pool,),
        "allowed_programs": (program,),
        "max_input_amount_minor": 3_000_000,
    }
    values.update(overrides)
    return RaydiumPolicy(**values)


def client(response, pool, program):
    return RaydiumClient(
        policy(pool, program),
        session=Session(response),
        clock=lambda: 2_000_000_000,
    )


def test_exact_output_quote_is_strictly_validated():
    input_mint, output_mint, pool, program = key(), key(), key(), key()
    adapter = client(
        quote_response(input_mint, output_mint, pool),
        pool,
        program,
    )
    result = adapter.quote_exact_output(
        input_mint=input_mint,
        output_mint=output_mint,
        output_amount_minor=1_000_000_000,
        input_decimals=6,
        output_decimals=8,
        pool_liquidity_usd=Decimal("25000"),
    )

    assert result.snapshot.input_amount == Decimal("2.525")
    assert result.snapshot.output_iat == Decimal("10")
    assert result.snapshot.price_impact_bps == 50
    assert result.snapshot.pool_id == pool
    assert adapter.session.calls[0][2]["params"]["txVersion"] == "LEGACY"


def test_pool_liquidity_is_verified_against_pool_program_and_mints():
    input_mint, output_mint, pool, program = key(), key(), key(), key()
    adapter = RaydiumClient(
        policy(pool, program),
        session=Session(
            {
                "success": True,
                "data": [
                    {
                        "id": pool,
                        "programId": program,
                        "mintA": {"address": output_mint},
                        "mintB": {"address": input_mint},
                        "tvl": 165.52,
                    }
                ],
            }
        ),
    )
    assert adapter.fetch_pool_liquidity_usd(
        input_mint=input_mint,
        output_mint=output_mint,
    ) == Decimal("165.52")


def test_pool_with_wrong_program_is_rejected():
    input_mint, output_mint, pool, program = key(), key(), key(), key()
    adapter = RaydiumClient(
        policy(pool, program),
        session=Session(
            {
                "success": True,
                "data": [
                    {
                        "id": pool,
                        "programId": key(),
                        "mintA": {"address": output_mint},
                        "mintB": {"address": input_mint},
                        "tvl": 100_000,
                    }
                ],
            }
        ),
    )
    with pytest.raises(RaydiumError, match="pool_program_not_allowlisted"):
        adapter.fetch_pool_liquidity_usd(
            input_mint=input_mint,
            output_mint=output_mint,
        )


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"outputAmount": "999999999"}, "raydium_exact_output_mismatch"),
        ({"otherAmountThreshold": "4000000"}, "raydium_input_cap_exceeded"),
        ({"priceImpactPct": "9"}, "raydium_price_impact_exceeded"),
        ({"routePlan": []}, "raydium_single_hop_required"),
        ({"routePlan": [{"poolId": "bad"}]}, "raydium_pool_not_allowlisted"),
    ],
)
def test_malicious_or_unsafe_quotes_fail_closed(override, reason):
    input_mint, output_mint, pool, program = key(), key(), key(), key()
    adapter = client(
        quote_response(input_mint, output_mint, pool, **override),
        pool,
        program,
    )
    with pytest.raises(RaydiumError, match=reason):
        adapter.quote_exact_output(
            input_mint=input_mint,
            output_mint=output_mint,
            output_amount_minor=1_000_000_000,
            input_decimals=6,
            output_decimals=8,
            pool_liquidity_usd=Decimal("25000"),
        )


def serialized_transaction(
    *,
    buyer,
    buyer_input,
    escrow,
    input_mint,
    output_mint,
    program,
    extra_program=None,
):
    metas = [
        AccountMeta(buyer_input, False, True),
        AccountMeta(escrow, False, True),
        AccountMeta(input_mint, False, False),
        AccountMeta(output_mint, False, False),
    ]
    instructions = [Instruction(program, b"swap", metas)]
    if extra_program:
        instructions.append(Instruction(extra_program, b"attack", []))
    message = Message.new_with_blockhash(instructions, buyer, Hash.default())
    transaction = VersionedTransaction.populate(message, [Signature.default()])
    return base64.b64encode(bytes(transaction)).decode()


def test_built_transaction_is_legacy_single_swap_and_escrow_bound():
    buyer, buyer_input, escrow = Pubkey.new_unique(), Pubkey.new_unique(), Pubkey.new_unique()
    input_mint, output_mint = Pubkey.new_unique(), Pubkey.new_unique()
    pool, program = key(), Pubkey.new_unique()
    quote = quote_response(str(input_mint), str(output_mint), pool)
    encoded = serialized_transaction(
        buyer=buyer,
        buyer_input=buyer_input,
        escrow=escrow,
        input_mint=input_mint,
        output_mint=output_mint,
        program=program,
    )
    adapter = RaydiumClient(
        policy(pool, str(program)),
        session=Session({"success": True, "data": [{"transaction": encoded}]}),
    )
    result = adapter.build_exact_output_transaction(
        quote_response=quote,
        buyer_wallet=str(buyer),
        input_account=str(buyer_input),
        settlement_escrow=str(escrow),
        expected_input_mint=str(input_mint),
        expected_output_mint=str(output_mint),
        expected_output_amount_minor=1_000_000_000,
    )

    assert result["transaction_base64"] == encoded
    assert result["output_account"] == str(escrow)
    assert result["output_to_buyer_wallet"] is False
    assert result["buyer_signature_required"] is True


def test_transaction_with_unknown_program_is_rejected():
    buyer, buyer_input, escrow = Pubkey.new_unique(), Pubkey.new_unique(), Pubkey.new_unique()
    input_mint, output_mint = Pubkey.new_unique(), Pubkey.new_unique()
    pool, program, attacker = key(), Pubkey.new_unique(), Pubkey.new_unique()
    encoded = serialized_transaction(
        buyer=buyer,
        buyer_input=buyer_input,
        escrow=escrow,
        input_mint=input_mint,
        output_mint=output_mint,
        program=program,
        extra_program=attacker,
    )
    adapter = RaydiumClient(
        policy(pool, str(program)),
        session=Session({"success": True, "data": [{"transaction": encoded}]}),
    )
    with pytest.raises(RaydiumError, match="program_not_allowlisted"):
        adapter.build_exact_output_transaction(
            quote_response=quote_response(str(input_mint), str(output_mint), pool),
            buyer_wallet=str(buyer),
            input_account=str(buyer_input),
            settlement_escrow=str(escrow),
            expected_input_mint=str(input_mint),
            expected_output_mint=str(output_mint),
            expected_output_amount_minor=1_000_000_000,
        )


def test_non_official_api_host_is_rejected():
    with pytest.raises(RaydiumError, match="api_url_not_allowlisted"):
        RaydiumPolicy(
            api_url="https://attacker.invalid",
            allowed_pools=(key(),),
            allowed_programs=(key(),),
            max_input_amount_minor=1,
        ).validate()
