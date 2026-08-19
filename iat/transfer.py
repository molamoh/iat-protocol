import json
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from spl.token.instructions import transfer_checked, TransferCheckedParams, get_associated_token_address, create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID
from iat.config import IAT_DECIMALS, IAT_TOKEN_ADDRESS
from iat.settlement_transaction import (
    MEMO_PROGRAM_ID,
    build_atomic_settlement_instructions,
)

import os

RPC = (
    os.getenv("IAT_SOLANA_RPC_URL")
    or os.getenv("SOLANA_RPC_URL")
    or "https://api.mainnet-beta.solana.com"
)
IAT_MINT = IAT_TOKEN_ADDRESS

def load_keypair(keypair_input):
    from solders.keypair import Keypair

    if isinstance(keypair_input, str) and keypair_input.strip().startswith("["):
        return Keypair.from_bytes(bytes(json.loads(keypair_input)))

    with open(keypair_input, "r") as f:
        return Keypair.from_bytes(bytes(json.load(f)))


def send_iat(
    from_keypair_path,
    to_address,
    amount,
    order_id=None,
    memo_text=None,
):
    """
    Envoie un paiement IAT et ne retourne la signature qu'après confirmation
    effective sur Solana.

    Garanties :
    - validation stricte des entrées ;
    - création de l'ATA destinataire si nécessaire ;
    - simulation avec vérification des signatures ;
    - preflight RPC ;
    - rediffusion de la même transaction signée ;
    - aucune reconstruction pendant les retries ;
    - détection d'expiration du blockhash ;
    - rejet explicite des erreurs on-chain.
    """
    import time

    from solana.rpc.commitment import Confirmed
    from solana.rpc.types import TxOpts
    from solders.message import Message
    from solders.signature import Signature
    from solders.transaction import Transaction

    if not from_keypair_path:
        raise ValueError("from_keypair_path is required")

    if not to_address:
        raise ValueError("to_address is required")

    try:
        amount_value = float(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid IAT amount: {amount!r}") from exc

    if amount_value <= 0:
        raise ValueError("IAT amount must be greater than zero")

    try:
        destination_owner = Pubkey.from_string(str(to_address))
    except Exception as exc:
        raise ValueError(
            f"Invalid destination Solana wallet: {to_address!r}"
        ) from exc

    client = Client(RPC)
    keypair = load_keypair(from_keypair_path)

    mint = Pubkey.from_string(IAT_MINT)
    source = get_associated_token_address(keypair.pubkey(), mint)
    dest = get_associated_token_address(destination_owner, mint)

    # Évite les erreurs silencieuses dues aux flottants.
    amount_raw = int(round(amount_value * 10**8))

    if amount_raw <= 0:
        raise ValueError("IAT raw amount must be greater than zero")

    source_info = client.get_account_info(source, commitment=Confirmed)
    if source_info.value is None:
        raise RuntimeError(
            f"Source IAT token account does not exist: {source}"
        )

    instructions = []

    dest_info = client.get_account_info(dest, commitment=Confirmed)
    if dest_info.value is None:
        instructions.append(
            create_associated_token_account(
                payer=keypair.pubkey(),
                owner=destination_owner,
                mint=mint,
            )
        )

    instructions.append(
        transfer_checked(
            TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=source,
                mint=mint,
                dest=dest,
                owner=keypair.pubkey(),
                amount=amount_raw,
                decimals=8,
                signers=[],
            )
        )
    )

    if memo_text is not None:
        memo_data = str(memo_text).encode("utf-8")
    elif order_id is not None:
        memo_data = f"ORDER:{order_id}".encode("utf-8")
    else:
        memo_data = None

    if memo_data is not None:
        instructions.append(
            Instruction(
                program_id=MEMO_PROGRAM_ID,
                accounts=[],
                data=memo_data,
            )
        )

    latest = client.get_latest_blockhash(commitment=Confirmed).value
    blockhash = latest.blockhash
    last_valid_block_height = latest.last_valid_block_height

    message = Message(instructions, keypair.pubkey())
    transaction = Transaction([keypair], message, blockhash)

    signature = transaction.signatures[0]
    raw_transaction = bytes(transaction)

    # La simulation doit utiliser exactement la transaction qui sera envoyée.
    simulation = client.simulate_transaction(
        transaction,
        sig_verify=True,
        commitment=Confirmed,
    )

    simulation_error = simulation.value.err
    if simulation_error is not None:
        simulation_logs = simulation.value.logs or []
        raise RuntimeError(
            "Solana transaction simulation failed: "
            f"error={simulation_error!r}; logs={simulation_logs!r}"
        )

    send_options = TxOpts(
        skip_confirmation=True,
        skip_preflight=False,
        preflight_commitment=Confirmed,
        max_retries=5,
        last_valid_block_height=last_valid_block_height,
    )

    max_broadcast_attempts = 4
    polling_interval_seconds = 1.5
    last_send_error = None

    for attempt in range(1, max_broadcast_attempts + 1):
        current_height = client.get_block_height(
            commitment=Confirmed
        ).value

        if current_height > last_valid_block_height:
            raise RuntimeError(
                "Solana transaction expired before confirmation: "
                f"signature={signature}; "
                f"current_block_height={current_height}; "
                f"last_valid_block_height={last_valid_block_height}"
            )

        try:
            response = client.send_raw_transaction(
                raw_transaction,
                opts=send_options,
            )

            returned_signature = response.value

            if str(returned_signature) != str(signature):
                raise RuntimeError(
                    "RPC returned an unexpected transaction signature: "
                    f"expected={signature}; received={returned_signature}"
                )

            last_send_error = None

        except Exception as exc:
            # Une erreur RPC ne prouve pas que la transaction n'a pas été
            # reçue. On contrôle donc toujours son statut avant de conclure.
            last_send_error = exc

        confirmation_deadline = time.monotonic() + 12.0

        while time.monotonic() < confirmation_deadline:
            status_response = client.get_signature_statuses(
                [Signature.from_string(str(signature))],
                search_transaction_history=True,
            )

            status = status_response.value[0]

            if status is not None:
                if status.err is not None:
                    raise RuntimeError(
                        "Solana transaction failed on-chain: "
                        f"signature={signature}; error={status.err!r}"
                    )

                confirmation_status = str(
                    status.confirmation_status or ""
                ).lower()

                if (
                    "confirmed" in confirmation_status
                    or "finalized" in confirmation_status
                ):
                    return str(signature)

            current_height = client.get_block_height(
                commitment=Confirmed
            ).value

            if current_height > last_valid_block_height:
                raise RuntimeError(
                    "Solana transaction expired without confirmation: "
                    f"signature={signature}; "
                    f"last_send_error={last_send_error!r}"
                )

            time.sleep(polling_interval_seconds)

        # Rediffusion de raw_transaction : mêmes bytes, même blockhash,
        # même signature, donc aucun risque de double paiement.

    final_status_response = client.get_signature_statuses(
        [Signature.from_string(str(signature))],
        search_transaction_history=True,
    )
    final_status = final_status_response.value[0]

    if final_status is not None:
        if final_status.err is not None:
            raise RuntimeError(
                "Solana transaction failed on-chain after broadcasts: "
                f"signature={signature}; error={final_status.err!r}"
            )

        final_confirmation = str(
            final_status.confirmation_status or ""
        ).lower()

        if (
            "confirmed" in final_confirmation
            or "finalized" in final_confirmation
        ):
            return str(signature)

    raise RuntimeError(
        "Solana transaction was not confirmed after all broadcasts: "
        f"signature={signature}; "
        f"last_send_error={last_send_error!r}; "
        f"last_valid_block_height={last_valid_block_height}"
    )

def send_iat_split_atomic(
    from_keypair_path,
    treasury_address,
    winner_address,
    commission_amount,
    seller_payout_amount,
    memo_text=None,
):
    """
    Execute the protocol commission and seller payout in one atomic
    Solana transaction.

    Either every instruction succeeds or the complete transaction fails.
    """
    from solana.rpc.commitment import Confirmed

    client = Client(RPC)
    keypair = load_keypair(from_keypair_path)

    mint = Pubkey.from_string(IAT_MINT)
    treasury_owner = Pubkey.from_string(str(treasury_address))
    winner_owner = Pubkey.from_string(str(winner_address))

    treasury_ata = get_associated_token_address(treasury_owner, mint)
    winner_ata = get_associated_token_address(winner_owner, mint)

    commission_raw = int(round(float(commission_amount or 0) * 10**IAT_DECIMALS))
    seller_payout_raw = int(round(float(seller_payout_amount or 0) * 10**IAT_DECIMALS))
    treasury_info = client.get_account_info(treasury_ata, commitment=Confirmed)
    winner_info = client.get_account_info(winner_ata, commitment=Confirmed)
    instructions, _accounts = build_atomic_settlement_instructions(
        escrow_authority=keypair.pubkey(),
        mint=mint,
        treasury_owner=treasury_owner,
        winner_owner=winner_owner,
        commission_amount_minor=commission_raw,
        seller_payout_amount_minor=seller_payout_raw,
        create_treasury_account=treasury_info.value is None,
        create_winner_account=winner_info.value is None,
        memo_text=memo_text,
    )

    blockhash = client.get_latest_blockhash().value.blockhash

    from solders.message import Message
    from solders.transaction import Transaction

    message = Message(instructions, keypair.pubkey())
    transaction = Transaction([keypair], message, blockhash)

    simulation = client.simulate_transaction(
        transaction,
        sig_verify=True,
        commitment=Confirmed,
    )
    if simulation.value.err is not None:
        raise RuntimeError(
            "Solana atomic settlement simulation failed: "
            f"error={simulation.value.err!r}; "
            f"logs={(simulation.value.logs or [])!r}"
        )

    response = client.send_raw_transaction(bytes(transaction))
    return str(response.value)
